"""Tests for the Skill_by_Satya meta-skill bootstrap/sync behavior.

Validates the two bootstrap situations from the spec:

  Environment A — existing skills + existing agent.md
      Skill_by_Satya discovers existing skills, establishes routing,
      preserves the existing environment (user agent.md content intact,
      existing manifests untouched, candidate manifests generated only
      for skill folders that lack one).

  Environment B — empty/new repository
      Skill_by_Satya creates the routing environment (skills/, registry,
      router, agent.md contract) and a later-added skill becomes routable
      without touching the router.

Also verifies idempotency (sync/bootstrap twice → no drift) and that
Skill_by_Satya itself is routable by the reference router in this repo.

Run: python3 test/test_skill_by_satya.py
"""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
META_SKILL_DIR = REPO / "skills" / "Skill_by_Satya"
META_SKILL_PY = META_SKILL_DIR / "skill.py"
sys.path.insert(0, str(REPO))

import skill  # noqa: E402

n = 0


def ok(cond, msg):
    global n
    if not cond:
        raise AssertionError(msg)
    n += 1


def run_meta(*args, root=None):
    cmd = [sys.executable, str(META_SKILL_PY), *args]
    if root is not None:
        cmd += ["--root", str(root)]
    return subprocess.run(cmd, capture_output=True, text=True)


def make_skill(root, name, manifest=None, doc="---\nname: {n}\ndescription: {n} skill.\n---\n"):
    folder = root / "skills" / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_text(doc.format(n=name), encoding="utf-8")
    if manifest is not None:
        (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


# ---------------------------------------------------------------------------
# Environment B — empty repository
# ---------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as td:
    T = Path(td)

    out = run_meta("bootstrap", root=T)
    ok(out.returncode == 0, f"envB bootstrap: non-zero exit {out.returncode}")

    ok((T / "skills").is_dir(), "envB: skills/ created")
    ok((T / "skill-registry" / "registry.json").is_file(), "envB: registry created")
    ok((T / "skill.py").is_file(), "envB: skill.py installed")
    ok((T / "agent.md").is_file(), "envB: agent.md created")
    contract = (T / "agent.md").read_text(encoding="utf-8")
    ok("Skill_by_Satya:routing-contract" in contract, "envB: agent.md has contract")
    ok("Maintenance contract (mandatory)" in contract, "envB: contract has maintenance rules")

    reg = json.loads((T / "skill-registry" / "registry.json").read_text(encoding="utf-8"))
    ok(reg["skill_count"] == 0, f"envB: empty registry expected, got {reg['skill_count']}")

    # Later-added skill becomes routable without router edits
    make_skill(T, "echo", manifest={
        "name": "echo",
        "description": "Echo test skill.",
        "keywords": ["echo", "repeat"],
        "aliases": ["echo"],
        "capabilities": ["echo back"],
        "intents": {"echo": ["echo this back", "repeat this back"]},
        "commands": [{"name": "echo", "syntax": "echo",
                      "description": "Echo the input.", "keywords": ["echo"]}],
    })
    out = run_meta("sync", root=T)
    ok(out.returncode == 0, "envB: sync after adding skill failed")
    reg2 = json.loads((T / "skill-registry" / "registry.json").read_text(encoding="utf-8"))
    ok(reg2["skill_count"] == 1, f"envB: registry must now have 1 skill, got {reg2['skill_count']}")

    out = run_meta("route", "echo this back", root=T)
    d = json.loads(out.stdout)
    ok(d["status"] == "matched" and d["skill"] == "echo",
       f"envB: later skill must route, got {d}")

    # Idempotency: sync twice → identical registry
    out_a = run_meta("sync", root=T)
    out_b = run_meta("sync", root=T)
    reg_a = json.loads((T / "skill-registry" / "registry.json").read_text(encoding="utf-8"))
    reg_b = json.loads((T / "skill-registry" / "registry.json").read_text(encoding="utf-8"))
    ok(reg_a == reg_b, "envB: sync twice must produce identical registry")
    ok(reg_a == reg2, "envB: sync must be a no-op on an up-to-date registry")

    # Removed skill → registry regenerated without it
    shutil.rmtree(T / "skills" / "echo")
    run_meta("sync", root=T)
    reg3 = json.loads((T / "skill-registry" / "registry.json").read_text(encoding="utf-8"))
    ok(reg3["skill_count"] == 0, "envB: removed skill must vanish from registry")

# ---------------------------------------------------------------------------
# Environment A — existing skills + existing agent.md
# ---------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as td:
    T = Path(td)
    (T / "skills" / "browser").mkdir(parents=True)
    (T / "skills" / "browser" / "SKILL.md").write_text(
        "---\nname: browser\ndescription: Interact with web pages and links.\n---\n",
        encoding="utf-8")
    (T / "agent.md").write_text("# My repo\n\nPRESERVE-ME user instructions.\n",
                                encoding="utf-8")

    out = run_meta("bootstrap", root=T)
    ok(out.returncode == 0, f"envA bootstrap: non-zero exit {out.returncode}")

    ok((T / "skills" / "browser" / "SKILL.md").is_file(), "envA: existing SKILL.md preserved")
    manifest_path = T / "skills" / "browser" / "manifest.json"
    ok(manifest_path.is_file(), "envA: candidate manifest generated for browser")
    man = json.loads(manifest_path.read_text(encoding="utf-8"))
    ok(man["_bootstrap"].get("generated") is True, "envA: candidate flagged as generated")
    ok(man["_bootstrap"].get("needs_review") is True, "envA: candidate flagged needs_review")

    agent = (T / "agent.md").read_text(encoding="utf-8")
    ok("PRESERVE-ME" in agent, "envA: user agent.md content preserved")
    ok("Skill_by_Satya:routing-contract" in agent, "envA: contract appended to agent.md")

    # Routing operational immediately
    out = run_meta("route", "use the browser skill", root=T)
    d = json.loads(out.stdout)
    ok(d["status"] == "matched" and d["skill"] == "browser",
       f"envA: browser must be routable after bootstrap, got {d}")

    # Idempotency: bootstrap twice → manifest bytes unchanged
    before = manifest_path.read_bytes()
    run_meta("bootstrap", root=T)
    after = manifest_path.read_bytes()
    ok(before == after, "envA: bootstrap twice must not rewrite manifests")

    # --force regenerates ONLY bootstrap-marked manifests, never handwritten ones
    handwritten = T / "skills" / "github"
    handwritten.mkdir()
    (handwritten / "SKILL.md").write_text("---\nname: github\ndescription: git.\n---\n",
                                          encoding="utf-8")
    (handwritten / "manifest.json").write_text(json.dumps({
        "name": "github", "description": "git.", "keywords": ["git"],
        "aliases": [], "capabilities": ["git"], "intents": {}, "commands": [
            {"name": "gh", "syntax": "gh", "description": "git command",
             "keywords": ["git"]}]}), encoding="utf-8")
    out = run_meta("bootstrap", "--force", root=T)
    ok(out.returncode == 0, "envA: bootstrap --force failed")
    gh_manifest = json.loads((handwritten / "manifest.json").read_text(encoding="utf-8"))
    ok(gh_manifest["name"] == "github" and "_bootstrap" not in gh_manifest,
       "envA: --force must not touch handwritten manifests")
    browser_after = json.loads(manifest_path.read_text(encoding="utf-8"))
    ok(browser_after["_bootstrap"].get("generated") is True,
       "envA: --force regenerates bootstrap-marked manifests")

# ---------------------------------------------------------------------------
# Skill_by_Satya itself is routable by the reference router in this repo
# ---------------------------------------------------------------------------
r = skill.route("Bootstrap the skill router for this repo", root=REPO)
ok(r["status"] == "matched", f"meta routable: expected matched, got {r['status']}")
ok(r["skill"] == "Skill_by_Satya", f"meta routable: expected Skill_by_Satya, got {r['skill']}")
ok(r["command"] == "bootstrap", f"meta routable: expected command bootstrap, got {r['command']}")
ok(r["validated"] is True, "meta routable: validated must be True")

report = skill.validate_all(root=REPO)
ok(report["ok"] is True, f"meta: repo validate must be OK, got {report['errors']}")
ok(report["skills_checked"] >= 20, "meta: expected 20+ skills now")

# All six meta commands must be registered
for cmd in ("bootstrap", "sync", "discover", "list", "route", "validate"):
    ok(skill.is_known_command(cmd), f"meta: command {cmd} must be registered")

print(f"{n} Skill_by_Satya tests passed")
