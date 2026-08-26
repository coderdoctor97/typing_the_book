"""Tests for skill.py — the Skill Discovery + Routing + Command Resolution engine.

Runnable with plain Python (no framework):
    python3 test/test_skill.py

Covers, per the router spec:
  * direct match, alias match, capability match
  * ambiguous request -> clarification candidates
  * unknown request -> no_match
  * invalid commands are never returned
  * a brand-new skill is discovered dynamically without touching skill.py
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import skill  # noqa: E402

n = 0


def ok(cond, msg):
    global n
    if not cond:
        raise AssertionError(msg)
    n += 1


def route(text):
    return skill.route(text, root=REPO)


# --- 1. Direct match -------------------------------------------------------
r = route("Audit this UI with impeccable")
ok(r["status"] == "matched", f"direct: expected matched, got {r['status']}")
ok(r["skill"] == "impeccable", f"direct: expected impeccable, got {r['skill']}")
ok(r["command"] == "audit", f"direct: expected command 'audit', got {r['command']}")
ok(r["confidence"] >= 0.75, f"direct: expected strong confidence, got {r['confidence']}")
ok(r["validated"] is True, "direct: validated must be True")

# --- 2. Alias match ----------------------------------------------------------
r = route("Run /ponytail-review on this diff")
ok(r["status"] == "matched", f"alias: expected matched, got {r['status']}")
ok(r["skill"] == "ponytail-review", f"alias: expected ponytail-review, got {r['skill']}")

r = route("Lazy mode please, make it minimal")
ok(r["status"] == "matched" and r["skill"] == "ponytail",
   f"alias2: expected ponytail via 'lazy mode', got {r['skill']}")

# --- 3. Capability match -----------------------------------------------------
r = route("Check the contrast and accessibility of this interface")
ok(r["status"] == "matched", f"capability: expected matched, got {r['status']}")
ok(r["skill"] == "antislop-human",
   f"capability: expected antislop-human, got {r['skill']}")

# --- 4. Ambiguous request -> clarification -----------------------------------
r = route("Redesign this landing page")
ok(r["status"] == "ambiguous", f"ambiguous: expected ambiguous, got {r['status']}")
ok(len(r["candidates"]) >= 2, "ambiguous: needs at least two candidates")
ok(r["selected"] is None, "ambiguous: nothing selected")
names = {c["skill"] for c in r["candidates"]}
ok("hallmark" in names and "supanova-redesign-engine" in names,
   f"ambiguous: expected design skills, got {names}")

# --- 5. Unknown request -> no_match ------------------------------------------
r = route("What's the weather in Paris?")
ok(r["status"] == "no_match", f"unknown: expected no_match, got {r['status']}")
ok(r["skill"] is None and r["command"] is None, "unknown: skill/command must be null")

r = route("Search GitHub repositories")
ok(r["status"] == "no_match",
   f"unknown2: no github skill exists, expected no_match, got {r['status']}")

# --- 6. Invalid commands are never returned ----------------------------------
ok(skill.is_known_command("github_search") is False,
   "invalid: github_search must not be registered (never invented)")
ok(skill.is_known_command("audit") is True, "invalid: 'audit' must be registered")
for phrase in ("Audit this UI with impeccable", "Generate a landing page",
               "Make my landing page premium", "Run /ponytail-review on this diff"):
    r = route(phrase)
    if r["status"] == "matched" and r["command"] is not None:
        ok(skill.is_known_command(r["command"]),
           f"invalid: returned command {r['command']} must be registered")
    if r["status"] == "ambiguous":
        for c in r["candidates"]:
            if c["command"] is not None:
                ok(skill.is_known_command(c["command"]),
                   f"invalid: ambiguous command {c['command']} must be registered")

# --- 7. New skill is discovered dynamically ----------------------------------
tmp_name = "router-test-echo"
tmp_dir = REPO / "skills" / tmp_name
try:
    tmp_dir.mkdir(parents=True, exist_ok=True)
    (tmp_dir / "SKILL.md").write_text(
        "---\nname: router-test-echo\ndescription: echo skill for router tests.\n---\n",
        encoding="utf-8")
    (tmp_dir / "manifest.json").write_text(json.dumps({
        "name": tmp_name,
        "description": "Echo test skill used by test/test_skill.py.",
        "keywords": ["echo", "repeat back"],
        "aliases": [tmp_name],
        "capabilities": ["echo back", "repeat the input"],
        "intents": {"echo": ["echo this back", "repeat this back"]},
        "commands": [
            {"name": tmp_name, "syntax": tmp_name,
             "description": "Echo the input back.", "keywords": ["echo", "repeat"]}
        ],
    }), encoding="utf-8")

    r = route("echo this back")
    ok(r["status"] == "matched" and r["skill"] == tmp_name,
       f"new skill: expected {tmp_name} matched, got {r}")
    ok(skill.is_known_command(tmp_name), "new skill: command must be registered")
finally:
    if tmp_dir.exists():
        import shutil
        shutil.rmtree(tmp_dir)

r = route("echo this back")
ok(r["status"] == "no_match", "new skill: after removal it must be unroutable")

# --- 8. Registry + validation ------------------------------------------------
report = skill.validate_all(root=REPO)
ok(report["ok"] is True, f"validate: expected OK, got {report['errors']}")
ok(report["skills_checked"] >= 19, "validate: expected 19+ skills checked")

with tempfile.TemporaryDirectory() as td:
    tmp_root = Path(td)
    (tmp_root / "skills" / tmp_name).mkdir(parents=True)
    (tmp_root / "skills" / tmp_name / "SKILL.md").write_text(
        "---\nname: router-test-echo\ndescription: x\n---\n", encoding="utf-8")
    (tmp_root / "skills" / tmp_name / "manifest.json").write_text(json.dumps({
        "name": tmp_name, "description": "x", "keywords": ["echo"],
        "aliases": [], "capabilities": ["echo"], "intents": {"e": ["echo"]},
        "commands": [{"name": tmp_name}],
    }), encoding="utf-8")
    reg = skill.build_registry(root=tmp_root)
    ok(reg["skill_count"] == 1, f"registry: expected 1 skill, got {reg['skill_count']}")
    ok((tmp_root / "skill-registry" / "registry.json").is_file(),
       "registry: registry.json must be written")

# --- 9. CLI smoke tests -------------------------------------------------------
out = subprocess.run([sys.executable, str(REPO / "skill.py"), "route",
                      "audit this ui with impeccable"], capture_output=True, text=True)
ok(out.returncode == 0, "cli route: non-zero exit")
ok(json.loads(out.stdout)["status"] == "matched", "cli route: not matched")

out = subprocess.run([sys.executable, str(REPO / "skill.py"), "list"],
                     capture_output=True, text=True)
ok(out.returncode == 0, "cli list: non-zero exit")

print(f"{n} skill-router tests passed")
