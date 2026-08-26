#!/usr/bin/env python3
"""
skill.py — Portable Skill Router (Skill_by_Satya)

A generalized, self-bootstrapping skill-routing engine. Copy this file (or the
whole Skill_by_Satya folder) into another agent repository and it will:

  * bootstrap a routing environment where none exists (skills/, manifests,
    registry, agent.md contract, and this router),
  * synchronize an existing skill environment (discover existing skills,
    generate candidate manifests for ones that lack them, rebuild the
    registry),
  * route user requests to the best skill + command with deterministic
    confidence scoring,
  * validate that every returned command actually exists (never invents
    commands),
  * return machine-readable structured results the agent decides on.

It NEVER executes commands. It only recommends.

CLI:
    python3 skill.py bootstrap [--root DIR]   establish the routing environment
    python3 skill.py sync [--root DIR]        idempotent discover+rebuild+validate
    python3 skill.py discover [--root DIR]    rebuild skill-registry/registry.json
    python3 skill.py list [--root DIR]        print the skill index
    python3 skill.py route "<request>" [--root DIR]
    python3 skill.py validate [--root DIR]    validate manifests + registry (exit 0/1)

Default ROOT is the directory containing this file (the target repository
root). Override with --root, useful for testing and for bootstrap-from-a-copy.

Bootstrap is conservative:
  * never overwrites an existing manifest, registry, skill.py, or agent.md
    contract section (idempotent),
  * existing skills are preserved; only *missing* candidate manifests are
    generated and flagged `"needs_review": true` for the agent to polish.

Source of truth: skills/<skill>/manifest.json. skill-registry/registry.json
is a generated index (rebuilt, never hand-edited).
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parent

SKILLS_DIR_NAME = "skills"
REGISTRY_DIR_NAME = "skill-registry"
REGISTRY_FILENAME = "registry.json"
MANIFEST_FILENAME = "manifest.json"
SKILL_FILENAME = "SKILL.md"
AGENT_MD_FILENAME = "agent.md"
ROUTER_FILENAME = "skill.py"

REGISTRY_SCHEMA_VERSION = 1

CONTRACT_MARKER = "<!-- Skill_by_Satya:routing-contract -->"

# --------------------------------------------------------------------------
# Scoring configuration (deterministic; tune freely)
# --------------------------------------------------------------------------
MIN_MATCH_CONFIDENCE = 0.50   # below this: no_match
AMBIGUITY_DELTA = 0.10        # top gap < delta and second >= floor => ambiguous

WEIGHTS = {
    "name": 0.50,
    "alias": 0.40,
    "keyword": 0.25,
    "capability": 0.20,
    "intent": 0.15,
    "description": 0.05,
}

CMD_NAME_WEIGHT = 0.55
CMD_KEYWORD_WEIGHT = 0.30
CMD_DESC_WEIGHT = 0.15

CONFIDENCE_BANDS = (
    (0.90, "very strong"),
    (0.75, "strong"),
    (0.50, "possible"),
    (0.00, "weak"),
)

STOPWORDS = frozenset(
    "a an the this that these those with for on of to in at by my your me us is are "
    "was were do does did it its and or but not please can could would should help i "
    "we they he she something some any using use used up out over under from about "
    "into than then there here what which who whom".split()
)

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def normalize(text: str) -> str:
    if not text:
        return ""
    return " ".join(t for t in _TOKEN_RE.findall(text.lower()) if t not in STOPWORDS)


def tokens(text: str) -> set[str]:
    if not text:
        return set()
    return set(t for t in _TOKEN_RE.findall(text.lower()) if t not in STOPWORDS)


def phrase_matches(text_tokens: set[str], phrase: str) -> bool:
    pt = tokens(phrase)
    return bool(pt) and pt <= text_tokens


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
    bootstrap_generated: bool = False

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
        if isinstance(cmd, str):
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
        bootstrap_generated=bool(data.get("_bootstrap", {}).get("generated")),
    )


def discover_skills(root: Path | None = None) -> list[Skill]:
    """Discover every routable skill under <root>/skills.

    A skill is routable iff its folder contains both SKILL.md and a valid
    manifest.json. Broken/missing manifests are skipped here and reported by
    validate(). New skills are picked up without any change to this module.
    """
    skills_dir = (root or DEFAULT_ROOT) / SKILLS_DIR_NAME
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
            continue
    return found


def skill_folders(root: Path | None = None) -> list[Path]:
    """Every subfolder of skills/ (whether or not it has a manifest yet)."""
    skills_dir = (root or DEFAULT_ROOT) / SKILLS_DIR_NAME
    if not skills_dir.is_dir():
        return []
    return sorted(p for p in skills_dir.iterdir() if p.is_dir())


# --------------------------------------------------------------------------
# Bootstrap: candidate manifests from existing SKILL.md files
# --------------------------------------------------------------------------
def parse_frontmatter(text: str) -> dict[str, str]:
    """Tiny frontmatter parser for simple scalar keys (name, description)."""
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.S)
    if not m:
        return {}
    out: dict[str, str] = {}
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        k, _, v = line.partition(":")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and v and v != ">" and k not in out:
            out[k] = v
    return out


def guess_keywords(name: str, description: str) -> list[str]:
    """Derive a short keyword list from the description + skill name."""
    kws = [name]
    seen = set(kws)
    for t in tokens(description):
        if t not in seen and len(kws) < 8:
            kws.append(t)
            seen.add(t)
    return kws


def guess_commands(skill_dir: Path, name: str, text: str) -> list[str]:
    """Guess real commands from a SKILL.md: slash tokens, else the skill name."""
    cmds = []
    for tok in re.findall(r"`?/([a-z0-9][a-z0-9._-]*)`?", text):
        if tok not in cmds:
            cmds.append(tok)
    if not cmds:
        cmds.append(name)
    return cmds


def generate_candidate_manifest(skill_dir: Path) -> dict:
    """Build a best-effort manifest for a skill folder that lacks one.

    Result is flagged `"needs_review": true` — the agent should polish it
    (real capabilities, intent triggers, command descriptions). Deterministic,
    never guesses commands that are not at least hinted in the SKILL.md.
    """
    name = skill_dir.name
    doc_path = skill_dir / SKILL_FILENAME
    text = doc_path.read_text(encoding="utf-8") if doc_path.is_file() else ""
    front = parse_frontmatter(text)
    description = front.get("description") or (
        "Skill folder with no parseable description yet. See SKILL.md."
    )
    commands = [
        {
            "name": c,
            "syntax": c,
            "description": f"{name}: {description[:120]}",
            "keywords": [name],
        }
        for c in guess_commands(skill_dir, name, text)
    ]
    return {
        "name": name,
        "description": description,
        "keywords": guess_keywords(name, description),
        "aliases": [name],
        "capabilities": [description[:160]],
        "intents": {},
        "commands": commands,
        "_bootstrap": {"generated": True, "needs_review": True},
    }


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
    "ponytail-review" is mentioned) — the more specific skill wins.
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
    """Pick the best command within a skill: (name, score, reasons).

    Single-command skills always resolve to that command. Returns None when a
    multi-command skill has no command-level signal — the agent then decides.
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
    if skill is None:
        return None
    for intent_id, phrases in skill.intents.items():
        if matched_phrases(text_tokens, phrases):
            return intent_id
    return None


def _name_suppressed(skills: list[Skill], text_tokens: set[str]) -> set[str]:
    """Skills whose name is a token-prefix of a longer name also in the request."""
    occurring = {s.name for s in skills if tokens(s.name) and tokens(s.name) <= text_tokens}
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
def route(request: str, root: Path | None = None) -> dict:
    """Route a request to the best skill + command. See module docstring.

    status: "matched" | "ambiguous" | "no_match"
    """
    text_tokens = tokens(request)
    skills = discover_skills(root)

    result: dict = {"request": request, "status": "no_match", "intent": "unknown",
                    "skill": None, "command": None, "confidence": 0.0,
                    "reason": f"no skill scored at least {MIN_MATCH_CONFIDENCE:g}",
                    "validated": False}

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

    if second_score >= MIN_MATCH_CONFIDENCE and best_score - second_score < AMBIGUITY_DELTA:
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
        result.update({
            "status": "ambiguous",
            "intent": detect_intent(text_tokens, best_skill) or "ambiguous",
            "candidates": candidates,
            "selected": None,
            "confidence": round3(best_score),
            "reason": f"top candidates within {AMBIGUITY_DELTA:g} of each other; "
                      "ask the user which skill to use",
            "validated": all(
                c["command"] is None or c["command"] in cmds_by_skill.get(c["skill"], set())
                for c in candidates),
        })
        return result

    command_valid = best_cmd is None or best_cmd in best_skill.command_names
    alternatives = []
    for score, reasons, cmd, _, _, skill in scored[1:4]:
        if score < 0.25:
            break
        alternatives.append({"skill": skill.name, "command": cmd,
                             "confidence": round3(score)})

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
def build_registry(root: Path | None = None) -> dict:
    root_path = root or DEFAULT_ROOT
    skills = discover_skills(root_path)
    registry = {
        "schema_version": REGISTRY_SCHEMA_VERSION,
        "skills_dir": SKILLS_DIR_NAME,
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
    reg_dir = root_path / REGISTRY_DIR_NAME
    reg_dir.mkdir(parents=True, exist_ok=True)
    (reg_dir / REGISTRY_FILENAME).write_text(
        json.dumps(registry, indent=2) + "\n", encoding="utf-8")
    return registry


def load_registry(root: Path | None = None) -> dict | None:
    reg_path = (root or DEFAULT_ROOT) / REGISTRY_DIR_NAME / REGISTRY_FILENAME
    if not reg_path.is_file():
        return None
    try:
        return json.loads(reg_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def known_commands(root: Path | None = None) -> list[str]:
    cmds: set[str] = set()
    for skill in discover_skills(root):
        cmds.update(skill.command_names)
    return sorted(cmds)


def is_known_command(name: str, root: Path | None = None) -> bool:
    return name in known_commands(root)


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------
def validate_all(root: Path | None = None) -> dict:
    root_path = root or DEFAULT_ROOT
    skills_dir = root_path / SKILLS_DIR_NAME
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
        has_doc, has_manifest = doc.is_file(), manifest.is_file()
        if not has_doc and not has_manifest:
            continue
        if not has_doc:
            errors.append(f"{entry.name}: has manifest.json but no SKILL.md")
            continue
        if not has_manifest:
            errors.append(f"{entry.name}: skill has SKILL.md but no manifest.json "
                          "(not routable — create one or run bootstrap)")
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
        if skill.bootstrap_generated:
            warnings.append(f"{entry.name}: manifest is bootstrap-generated "
                            "(needs_review)")

    registry = load_registry(root_path)
    if registry is None:
        warnings.append(f"{REGISTRY_DIR_NAME}/{REGISTRY_FILENAME} missing — run "
                        "'python3 skill.py discover' or 'sync'")
    elif registry.get("schema_version") != REGISTRY_SCHEMA_VERSION:
        warnings.append("registry schema_version differs — regenerate with sync")

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "skills_checked": checked,
        "commands_registered": known_commands(root_path),
    }


# --------------------------------------------------------------------------
# Bootstrap + sync (the two entry points that make this skill reusable)
# --------------------------------------------------------------------------
def _contract_section() -> str:
    """The persistent agent.md contract (Part 6). Merge-safe, marker-guarded."""
    return (
        f"{CONTRACT_MARKER}\n"
        "# Skill Router & Dynamic Skill Registry (Skill_by_Satya)\n"
        "\n"
        "This repository has a skill-routing environment. `skill.py` discovers\n"
        "skills from `skills/` (each with a `manifest.json`), routes requests to\n"
        "the best skill + command, validates commands, and returns structured\n"
        "recommendations. It never executes anything; you decide and execute.\n"
        "\n"
        "CLI: `python3 skill.py list | route \"<request>\" | validate | sync | discover`\n"
        "\n"
        "Routing result: `matched` (recommended skill/command + confidence),\n"
        "`ambiguous` (ask the user), `no_match` (ask or handle directly).\n"
        "\n"
        "## Maintenance contract (mandatory)\n"
        "Whenever a skill is installed, added, modified, or removed, you MUST\n"
        "synchronize the routing environment:\n"
        "\n"
        "* New skill: inspect it -> create/verify `skills/<name>/manifest.json`\n"
        "  (name matches the folder; commands must actually exist; never invent\n"
        "  capabilities) -> `python3 skill.py sync` -> test routing with\n"
        "  `python3 skill.py route \"<sample request>\"`.\n"
        "* Modified skill: re-inspect -> update its manifest -> validate commands\n"
        "  -> `sync` -> test.\n"
        "* Removed skill: delete the folder -> `sync` (registry is regenerated,\n"
        "  stale entries vanish) -> `validate`.\n"
        "\n"
        "## Safety rules\n"
        "* NEVER execute a command the router did not return with `validated: true`\n"
        "  (i.e. a command not registered in a real manifest).\n"
        "* Low confidence -> ask. High confidence -> recommend. Invalid -> reject.\n"
        "* The router is deterministic; do not hand-edit the registry (it is\n"
        "  regenerated from manifests by `sync`).\n"
        "\n"
        "## Separation of responsibilities\n"
        "* `agent.md`: behavior, operating rules, this maintenance contract.\n"
        "* `skills/<name>/manifest.json`: skill identity, capabilities, keywords,\n"
        "  aliases, intents, commands (source of truth).\n"
        "* `skill-registry/registry.json`: generated index (never hand-edited).\n"
        "* `skill.py`: discovery, matching, ranking, resolution, validation.\n"
        "* You: interpret, decide, ask when ambiguous, execute.\n"
        f"\n{CONTRACT_MARKER}\n"
    )


def bootstrap(root: Path | None = None, force: bool = False) -> dict:
    """Establish the routing environment in <root>, conservatively.

    Works whether or not skills already exist:
      * creates skills/ and skill-registry/ if missing,
      * generates *candidate* manifests for skill folders that lack one
        (skipped when a manifest exists unless force=True),
      * writes the agent.md contract section (idempotent via marker),
      * installs this router as <root>/skill.py if missing,
      * rebuilds the registry.
    Never overwrites existing files or existing user instructions.
    """
    root_path = (root or DEFAULT_ROOT).resolve()
    skills_dir = root_path / SKILLS_DIR_NAME
    skills_dir.mkdir(parents=True, exist_ok=True)

    generated, existing, regenerated = [], [], []
    for folder in skill_folders(root_path):
        manifest = folder / MANIFEST_FILENAME
        if manifest.is_file():
            existing.append(folder.name)
            if force:
                # --force regenerates ONLY bootstrap-marked candidates, never
                # hand-written manifests.
                try:
                    data = json.loads(manifest.read_text(encoding="utf-8"))
                    marked = bool(data.get("_bootstrap", {}).get("generated"))
                except (json.JSONDecodeError, OSError):
                    marked = False
                if marked:
                    candidate = generate_candidate_manifest(folder)
                    manifest.write_text(
                        json.dumps(candidate, indent=2) + "\n", encoding="utf-8")
                    regenerated.append(folder.name)
            continue
        candidate = generate_candidate_manifest(folder)
        manifest.write_text(json.dumps(candidate, indent=2) + "\n", encoding="utf-8")
        generated.append(folder.name)

    registry = build_registry(root_path)

    agent_md = root_path / AGENT_MD_FILENAME
    contract = _contract_section()
    agent_md_status = "already-had-contract"
    if agent_md.is_file():
        content = agent_md.read_text(encoding="utf-8")
        if CONTRACT_MARKER not in content:
            with open(agent_md, "a", encoding="utf-8") as fh:
                fh.write("\n\n" + contract)
            agent_md_status = "contract-appended"
    else:
        agent_md.write_text(
            "# Agent instructions\n\n(Add your project's operating rules here.)\n\n"
            + contract, encoding="utf-8")
        agent_md_status = "created"

    router_status = "already-present"
    router_path = root_path / ROUTER_FILENAME
    if not router_path.is_file():
        shutil.copy2(__file__, router_path)
        router_status = "installed"

    return {
        "root": str(root_path),
        "skills_generated": generated,
        "skills_with_manifests": existing,
        "candidates_regenerated": regenerated,
        "agent_md": agent_md_status,
        "skill_py": router_status,
        "registry_skills": registry["skill_count"],
        "note": "Generated candidate manifests carry '_bootstrap.needs_review' — "
                "the agent should polish keywords/capabilities/intents/commands.",
    }


def sync(root: Path | None = None) -> dict:
    """Idempotent synchronization: rebuild registry + validate + report.

    Registry is regenerated wholesale from manifests, so running sync twice
    produces identical output and stale entries vanish automatically.
    """
    root_path = root or DEFAULT_ROOT
    orphan_skills = [p.name for p in skill_folders(root_path)
                     if not (p / MANIFEST_FILENAME).is_file()]
    registry = build_registry(root_path)
    report = validate_all(root_path)
    return {
        "registry": registry,
        "orphan_skills_without_manifests": orphan_skills,
        "validate": report,
        "idempotent": True,
    }


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def _usage() -> str:
    return (
        "skill.py — Portable Skill Router (Skill_by_Satya)\n\n"
        "usage:\n"
        "  python3 skill.py bootstrap [--root DIR] [--force]   establish the routing environment\n"
        "  python3 skill.py sync [--root DIR]                  idempotent discover+rebuild+validate\n"
        "  python3 skill.py discover [--root DIR]              rebuild skill-registry/registry.json\n"
        "  python3 skill.py list [--root DIR]                  print the skill index\n"
        "  python3 skill.py route \"<request>\" [--root DIR]    route a request, print JSON\n"
        "  python3 skill.py validate [--root DIR]              validate manifests + registry (exit 0/1)\n"
    )


def _parse_args(argv: list[str]) -> tuple[str, Path, bool, str]:
    root = DEFAULT_ROOT
    force = False
    positional: list[str] = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--root" and i + 1 < len(argv):
            root = Path(argv[i + 1]).resolve()
            i += 2
        elif a == "--force":
            force = True
            i += 1
        else:
            positional.append(a)
            i += 1
    cmd = positional[0] if positional else ""
    request = " ".join(positional[1:])
    return cmd, root, force, request


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(_usage())
        return 0

    cmd, root, force, request = _parse_args(argv)

    if cmd == "bootstrap":
        print(json.dumps(bootstrap(root, force=force), indent=2))
        return 0

    if cmd == "sync":
        print(json.dumps(sync(root), indent=2))
        return 0

    if cmd == "discover":
        print(json.dumps(build_registry(root), indent=2))
        return 0

    if cmd == "list":
        skills = discover_skills(root)
        if not skills:
            print("no routable skills found")
            return 1
        for s in skills:
            print(f"{s.name:32} commands: {', '.join(s.command_names) or '(none)'}")
        print(f"\n{len(skills)} skills, {len(known_commands(root))} commands")
        return 0

    if cmd == "route":
        if not request:
            print('missing request — try: python3 skill.py route "audit this ui"')
            return 1
        print(json.dumps(route(request, root), indent=2))
        return 0

    if cmd == "validate":
        report = validate_all(root)
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
