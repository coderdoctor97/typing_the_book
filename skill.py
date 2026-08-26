#!/usr/bin/env python3
"""
skill.py — Skill Discovery + Skill Routing + Command Resolution engine.

Part of the typing_the_book agent skill system. This module:

  * discovers skills dynamically from `skills/` (each skill folder has a
    SKILL.md doc and a manifest.json of structured metadata),
  * indexes them and can (re)generate `skill-registry/registry.json`,
  * routes a user request to the most relevant skill + command,
  * validates that every returned command actually exists in a manifest,
  * returns machine-readable, deterministic structured results.

It NEVER executes commands. The agent reads the result and decides whether to
execute. Skill manifests are the source of truth; registry.json is a
generated index.

CLI:
    python3 skill.py discover                rebuild skill-registry/registry.json
    python3 skill.py list                    print the skill index
    python3 skill.py route "<request>"       route a request, print JSON
    python3 skill.py validate                validate manifests + registry (exit 0/1)

Library:
    from skill import route, discover_skills, build_registry, validate_all, is_known_command

Design notes (deterministic, stdlib only — no LLM, no embeddings):
  * Scoring is a weighted sum of matched signals: name, alias, keyword,
    capability, intent, description. A signal "matches" only when every token
    of its phrase appears in the request (strict, inspectable). Scores are
    rounded and normalized to 0..1.
  * Name-prefix disambiguation: when the request contains a longer skill name
    (e.g. "ponytail-review"), the shorter prefix skill ("ponytail") does not
    get name/alias credit — the more specific skill wins.
  * Confidence bands: >=0.90 very strong, >=0.75 strong, >=0.50 possible,
    <0.50 weak. A command is only ever returned if it is registered in the
    manifest of a discovered skill. Unknown/invalid commands are never
    invented.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SKILLS_DIR = ROOT / "skills"
REGISTRY_DIR = ROOT / "skill-registry"
REGISTRY_PATH = REGISTRY_DIR / "registry.json"
REGISTRY_SCHEMA_VERSION = 1

MANIFEST_FILENAME = "manifest.json"
SKILL_FILENAME = "SKILL.md"

# --------------------------------------------------------------------------
# Scoring configuration (deterministic)
# --------------------------------------------------------------------------
MIN_MATCH_CONFIDENCE = 0.50   # below this: no_match
AMBIGUITY_DELTA = 0.10        # top gap < delta and second >= floor => ambiguous

# Weight of each matched signal toward a skill's total score.
WEIGHTS = {
    "name": 0.50,        # the request names the skill (all name tokens present)
    "alias": 0.40,       # an alias / trigger phrase from the manifest
    "keyword": 0.25,     # any keyword from the manifest matched
    "capability": 0.20,  # any capability phrase matched
    "intent": 0.15,      # any intent trigger phrase matched
    "description": 0.05, # the request's words all appear in the skill description
}

# Command-resolution weights within the selected skill.
CMD_NAME_WEIGHT = 0.55        # the command name appears in the request
CMD_KEYWORD_WEIGHT = 0.30     # a command-level keyword appears in the request
CMD_DESC_WEIGHT = 0.15        # the request's words all appear in the command description

CONFIDENCE_BANDS = (
    (0.90, "very strong"),
    (0.75, "strong"),
    (0.50, "possible"),
    (0.00, "weak"),
)

STOPWORDS = frozenset(
    "a an the this that these those with for on of to in at by my your me us is are "
    "was were do does did it its and or but not please can could would should help i "
    "we they he she something some any using use used me up out over under from about "
    "into than then there here what which who whom".split()
)

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def normalize(text: str) -> str:
    """Lowercase, tokenize, drop stopwords; return a canonical phrase string."""
    if not text:
        return ""
    tokens = [t for t in _TOKEN_RE.findall(text.lower()) if t not in STOPWORDS]
    return " ".join(tokens)


def tokens(text: str) -> set[str]:
    """Token set of a (raw or normalized) string, stopwords removed."""
    if not text:
        return set()
    return set(t for t in _TOKEN_RE.findall(text.lower()) if t not in STOPWORDS)


def phrase_matches(text_tokens: set[str], phrase: str) -> bool:
    """True if every token of the phrase appears in the request token set."""
    pt = tokens(phrase)
    if not pt:
        return False
    return pt <= text_tokens


def matched_phrases(text_tokens: set[str], phrases: list[str]) -> list[str]:
    return [p for p in phrases if phrase_matches(text_tokens, p)]


def round3(x: float) -> float:
    return round(x, 3)


# --------------------------------------------------------------------------
# Skill model + manifest loading
# --------------------------------------------------------------------------
REQUIRED_MANIFEST_FIELDS = ("name", "description", "keywords", "aliases",
                            "capabilities", "intents", "commands")


@dataclass
class Skill:
    name: str
    description: str
    keywords: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    intents: dict[str, list[str]] = field(default_factory=dict)
    commands: list[dict] = field(default_factory=list)
    manifest_path: str = ""
    skill_dir: str = ""

    @property
    def command_names(self) -> list[str]:
        return [c["name"] for c in self.commands]


def load_manifest(path: Path) -> Skill:
    """Load and structurally validate one manifest.json into a Skill."""
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    missing = [k for k in REQUIRED_MANIFEST_FIELDS if k not in data]
    if missing:
        raise ValueError(f"{path}: missing required fields {missing}")
    for key, types in (("description", str), ("keywords", list), ("aliases", list),
                       ("capabilities", list), ("intents", dict), ("commands", list)):
        if not isinstance(data.get(key), types):
            raise ValueError(f"{path}: field '{key}' must be {types.__name__}")

    commands = []
    for cmd in data["commands"]:
        if isinstance(cmd, str):            # tolerate a bare command name
            cmd = {"name": cmd}
        if not isinstance(cmd, dict) or not cmd.get("name"):
            raise ValueError(f"{path}: command entries need a 'name'")
        commands.append({
            "name": str(cmd["name"]),
            "syntax": str(cmd.get("syntax", "")),
            "description": str(cmd.get("description", "")),
            "keywords": list(cmd.get("keywords", []) or []),
        })
    if not commands:
        raise ValueError(f"{path}: at least one command is required")

    names = [c["name"] for c in commands]
    if len(names) != len(set(names)):
        raise ValueError(f"{path}: duplicate command names {names}")

    return Skill(
        name=str(data["name"]),
        description=str(data["description"]),
        keywords=[str(k) for k in data["keywords"]],
        aliases=[str(a) for a in data["aliases"]],
        capabilities=[str(c) for c in data["capabilities"]],
        intents={str(k): [str(p) for p in v] for k, v in data["intents"].items()},
        commands=commands,
        manifest_path=str(path),
        skill_dir=str(path.parent),
    )


def discover_skills(root: str | Path | None = None) -> list[Skill]:
    """Dynamically discover every routable skill under <root>/skills.

    A skill is routable iff its folder contains both SKILL.md and a valid
    manifest.json. Folders without a manifest (or with a broken one) are
    skipped — validate_all() reports them. New skills are picked up without
    any change to this module.
    """
    skills_dir = Path(root or ROOT) / "skills"
    found: list[Skill] = []
    if not skills_dir.is_dir():
        return found
    for entry in sorted(skills_dir.iterdir()):
        if not entry.is_dir():
            continue
        manifest = entry / MANIFEST_FILENAME
        if not manifest.is_file():
            continue
        try:
            found.append(load_manifest(manifest))
        except (ValueError, json.JSONDecodeError):
            continue  # invalid manifest: not routable; validate_all() flags it
    return found


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------
def _desc_hit(text_tokens: set[str], skill: Skill) -> bool:
    dt = tokens(skill.description)
    return bool(dt) and text_tokens <= dt


def score_skill(text_tokens: set[str], skill: Skill,
                suppress_name_alias: bool = False) -> tuple[float, list[str]]:
    """Score one skill against the request. Returns (score, matched_signals).

    `suppress_name_alias` is set for skills whose name is a token-prefix of a
    longer skill name that the request also contains (e.g. "ponytail" when
    "ponytail-review" was mentioned) — the more specific skill should win.
    """
    score = 0.0
    reasons: list[str] = []

    if not suppress_name_alias:
        name_tokens = tokens(skill.name)
        if name_tokens and name_tokens <= text_tokens:
            score += WEIGHTS["name"]
            reasons.append(f"name:{skill.name}")
        for alias in skill.aliases:
            if phrase_matches(text_tokens, alias):
                score += WEIGHTS["alias"]
                reasons.append(f"alias:{alias}")
                break

    if matched_phrases(text_tokens, skill.keywords):
        score += WEIGHTS["keyword"]
        reasons.append("keywords")

    if matched_phrases(text_tokens, skill.capabilities):
        score += WEIGHTS["capability"]
        reasons.append("capabilities")

    for intent_id, phrases in skill.intents.items():
        if matched_phrases(text_tokens, phrases):
            score += WEIGHTS["intent"]
            reasons.append(f"intent:{intent_id}")
            break

    if _desc_hit(text_tokens, skill):
        score += WEIGHTS["description"]
        reasons.append("description")

    return round3(min(1.0, score)), reasons


def resolve_command(text_tokens: set[str], skill: Skill) -> tuple[str | None, float, list[str]]:
    """Pick the best command within a skill. Returns (name, score, reasons).

    A command matches when its name, keyword, or description appears in the
    request. Single-command skills always resolve to that command (the skill
    match implies it). Returns None when a multi-command skill has no
    command-level signal — the agent then decides.
    """
    commands = skill.commands
    if not commands:
        return None, 0.0, []
    if len(commands) == 1:
        return commands[0]["name"], 0.0, ["single-command skill"]

    best_name, best_score, best_reasons = None, 0.0, []
    for cmd in commands:
        score = 0.0
        reasons = []
        if tokens(cmd["name"]) & text_tokens:
            score += CMD_NAME_WEIGHT
            reasons.append(f"name:{cmd['name']}")
        for kw in cmd.get("keywords", []):
            if phrase_matches(text_tokens, kw):
                score += CMD_KEYWORD_WEIGHT
                reasons.append(f"keyword:{kw}")
                break
        dt = tokens(cmd.get("description", ""))
        if dt and text_tokens <= dt:
            score += CMD_DESC_WEIGHT
            reasons.append("description")
        if score > best_score:
            best_name, best_score, best_reasons = cmd["name"], round3(score), reasons
    return best_name, best_score, best_reasons


def confidence_label(score: float) -> str:
    for floor, label in CONFIDENCE_BANDS:
        if score >= floor:
            return label
    return "weak"


def detect_intent(text_tokens: set[str], skill: Skill | None) -> str | None:
    """Return the id of the first matched intent trigger, if any."""
    if skill is None:
        return None
    for intent_id, phrases in skill.intents.items():
        if matched_phrases(text_tokens, phrases):
            return intent_id
    return None


def _name_suppressed(skills: list[Skill], text_tokens: set[str]) -> set[str]:
    """Skills whose name is a token-prefix of a longer name also in the request."""
    occurring = {
        s.name for s in skills
        if tokens(s.name) and tokens(s.name) <= text_tokens
    }
    suppressed: set[str] = set()
    for a in skills:
        if a.name not in occurring:
            continue
        ta = tokens(a.name)
        for b in skills:
            if b.name == a.name or b.name not in occurring:
                continue
            if ta < tokens(b.name):
                suppressed.add(a.name)
                break
    return suppressed


# --------------------------------------------------------------------------
# Routing
# --------------------------------------------------------------------------
def route(request: str, root: str | Path | None = None) -> dict:
    """Route a user request to the most relevant skill + command.

    Returns a machine-readable dict with status one of:
      "matched"   — confident skill (+ command) recommendation
      "ambiguous" — several skills are equally plausible; ask the user
      "no_match"  — nothing scored above the confidence floor
    """
    text = normalize(request)
    text_tokens = tokens(text)
    skills = discover_skills(root)

    result: dict = {"request": request, "status": "no_match", "intent": "unknown",
                    "skill": None, "command": None, "confidence": 0.0,
                    "reason": "no skill scored at least "
                              f"{MIN_MATCH_CONFIDENCE:g}", "validated": False}

    if not text_tokens or not skills:
        return result

    suppressed = _name_suppressed(skills, text_tokens)
    scored = []
    for skill in skills:
        score, reasons = score_skill(text_tokens, skill,
                                     suppress_name_alias=skill.name in suppressed)
        cmd, cmd_score, cmd_reasons = resolve_command(text_tokens, skill)
        scored.append((score, reasons, cmd, cmd_score, cmd_reasons, skill))

    scored.sort(key=lambda t: (-t[0], -len(t[1]), t[5].name))
    best_score, best_reasons, best_cmd, _, best_cmd_reasons, best_skill = scored[0]

    if best_score < MIN_MATCH_CONFIDENCE:
        return result

    second_score = round3(scored[1][0]) if len(scored) > 1 else 0.0

    if (second_score >= MIN_MATCH_CONFIDENCE
            and best_score - second_score < AMBIGUITY_DELTA):
        cmds_by_skill = {s.name: set(s.command_names) for s in skills}
        candidates = []
        for score, reasons, cmd, _, _, skill in scored:
            if score < MIN_MATCH_CONFIDENCE:
                break
            candidates.append({
                "skill": skill.name,
                "command": cmd,
                "confidence": round3(score),
                "reason": "; ".join(reasons),
            })
        validated = all(
            c["command"] is None or c["command"] in cmds_by_skill.get(c["skill"], set())
            for c in candidates
        )
        result.update({
            "status": "ambiguous",
            "intent": detect_intent(text_tokens, best_skill) or "ambiguous",
            "candidates": candidates,
            "selected": None,
            "confidence": round3(best_score),
            "reason": f"top candidates within {AMBIGUITY_DELTA:g} of each other; "
                      "ask the user which skill to use",
            "validated": validated,
        })
        return result

    command_valid = best_cmd is None or best_cmd in best_skill.command_names
    alternatives = []
    for score, reasons, cmd, _, _, skill in scored[1:4]:
        if score < 0.25:
            break
        alternatives.append({
            "skill": skill.name,
            "command": cmd,
            "confidence": round3(score),
        })

    reason = "matched signals: " + "; ".join(best_reasons)
    if best_cmd_reasons:
        reason += f"; command '{best_cmd}' resolved via " + ", ".join(best_cmd_reasons)

    intent = detect_intent(text_tokens, best_skill)
    if not intent:
        intent = f"{best_skill.name}.{best_cmd}" if best_cmd else best_skill.name

    result.update({
        "status": "matched",
        "intent": intent,
        "skill": best_skill.name,
        "command": best_cmd,
        "confidence": round3(best_score),
        "confidence_label": confidence_label(best_score),
        "reason": reason,
        "validated": bool(command_valid),
        "alternatives": alternatives,
        "available_commands": best_skill.command_names,
    })
    return result


# --------------------------------------------------------------------------
# Registry (generated index; manifests remain the source of truth)
# --------------------------------------------------------------------------
def build_registry(root: str | Path | None = None) -> dict:
    """Scan skills/ and write <root>/skill-registry/registry.json. Returns it."""
    root_path = Path(root or ROOT)
    skills = discover_skills(root_path)
    registry = {
        "schema_version": REGISTRY_SCHEMA_VERSION,
        "skills_dir": "skills",
        "note": "Generated index. Source of truth: each skill's manifest.json.",
        "skill_count": len(skills),
        "skills": [
            {
                "name": s.name,
                "description": s.description,
                "commands": s.command_names,
                "manifest": str(Path(s.manifest_path).relative_to(root_path)),
            }
            for s in skills
        ],
    }
    reg_dir = root_path / "skill-registry"
    reg_dir.mkdir(parents=True, exist_ok=True)
    (reg_dir / "registry.json").write_text(
        json.dumps(registry, indent=2) + "\n", encoding="utf-8")
    return registry


def load_registry(root: str | Path | None = None) -> dict | None:
    reg_path = Path(root or ROOT) / "skill-registry" / "registry.json"
    if not reg_path.is_file():
        return None
    try:
        return json.loads(reg_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def known_commands(root: str | Path | None = None) -> list[str]:
    cmds: set[str] = set()
    for skill in discover_skills(root):
        cmds.update(skill.command_names)
    return sorted(cmds)


def is_known_command(name: str, root: str | Path | None = None) -> bool:
    return name in known_commands(root)


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------
def validate_all(root: str | Path | None = None) -> dict:
    """Check every skill folder + manifest + registry. Returns a report dict."""
    root_path = Path(root or ROOT)
    skills_dir = root_path / "skills"
    errors: list[str] = []
    warnings: list[str] = []
    checked = 0

    if not skills_dir.is_dir():
        errors.append(f"skills directory missing: {skills_dir}")
        return {"ok": False, "errors": errors, "warnings": warnings,
                "skills_checked": 0, "commands_registered": []}

    for entry in sorted(skills_dir.iterdir()):
        if not entry.is_dir():
            continue
        manifest = entry / MANIFEST_FILENAME
        doc = entry / SKILL_FILENAME
        has_doc = doc.is_file()
        has_manifest = manifest.is_file()
        if not has_doc and not has_manifest:
            continue  # not a skill folder
        if not has_doc:
            errors.append(f"{entry.name}: has manifest.json but no SKILL.md")
            continue
        if not has_manifest:
            errors.append(f"{entry.name}: skill has SKILL.md but no manifest.json "
                          "(not routable — create one)")
            continue
        checked += 1
        try:
            skill = load_manifest(manifest)
        except (ValueError, json.JSONDecodeError) as e:
            errors.append(f"{entry.name}: invalid manifest — {e}")
            continue
        if skill.name != entry.name:
            errors.append(f"{entry.name}: manifest name '{skill.name}' does not "
                          f"match folder name")

    registry = load_registry(root_path)
    if registry is None:
        warnings.append("skill-registry/registry.json missing — run "
                        "'python3 skill.py discover'")
    elif registry.get("schema_version") != REGISTRY_SCHEMA_VERSION:
        warnings.append("registry schema_version differs — regenerate with "
                        "'python3 skill.py discover'")

    commands = known_commands(root_path)
    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "skills_checked": checked,
        "commands_registered": commands,
    }


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def _usage() -> str:
    return (
        "skill.py — Skill Discovery + Routing + Command Resolution\n\n"
        "usage:\n"
        "  python3 skill.py discover                rebuild skill-registry/registry.json\n"
        "  python3 skill.py list                    print the skill index\n"
        "  python3 skill.py route \"<request>\"       route a request, print JSON\n"
        "  python3 skill.py validate                validate manifests + registry (exit 0/1)\n"
    )


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(_usage())
        return 0

    cmd = argv[0]
    if cmd == "discover":
        registry = build_registry()
        print(json.dumps(registry, indent=2))
        print(f"\nregistry written: {REGISTRY_PATH}")
        return 0

    if cmd == "list":
        skills = discover_skills()
        if not skills:
            print("no routable skills found")
            return 1
        for s in skills:
            cmds = ", ".join(s.command_names) or "(none)"
            print(f"{s.name:32} commands: {cmds}")
        print(f"\n{len(skills)} skills, {len(known_commands())} commands")
        return 0

    if cmd == "route":
        request = " ".join(argv[1:])
        if not request:
            print('missing request — try: python3 skill.py route "audit this ui"')
            return 1
        print(json.dumps(route(request), indent=2))
        return 0

    if cmd == "validate":
        report = validate_all()
        print(json.dumps(report, indent=2))
        for err in report["errors"]:
            print(f"ERROR: {err}")
        for warn in report["warnings"]:
            print(f"WARN: {warn}")
        print("OK" if report["ok"] else "FAILED")
        return 0 if report["ok"] else 1

    print(f"unknown command: {cmd}\n")
    print(_usage())
    return 1


if __name__ == "__main__":
    sys.exit(main())
