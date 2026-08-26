---
name: Skill_by_Satya
description: >
  Reusable meta-skill: establish, bootstrap, maintain, and evolve an intelligent
  skill-routing environment (skill discovery + routing + command resolution) in
  any agent repository. Use when the user wants to set up a skill router in a
  new repo, synchronize the skill registry after adding/removing skills, or
  when they say "Skill by Satya", "set up the skill router", "bootstrap the
  routing environment", "sync the skill registry", or "install the routing
  meta-skill". Portable: works whether the target repo has zero skills or fifty.
commands: ["bootstrap", "sync", "discover", "list", "route", "validate"]
---

# Skill_by_Satya

> Establish, bootstrap, maintain, and evolve an intelligent skill-routing
> environment for an agent repository — once, then automatically.

## Identity

Skill_by_Satya is a **meta-skill**: a skill about skills. It does not add one
more capability to a repo; it installs the *machinery* that makes every other
skill discoverable and routable. It is portable — designed to be copied into
another agent repository and run there without rebuilding the architecture by
hand.

## Purpose

Normal agents struggle when many skills are installed: they either memorize a
growing list (and drift), or they guess which skill applies (and guess wrong).
Skill_by_Satya removes both failure modes by establishing a deterministic
routing environment:

```
User intent → router → skill → command → agent execution
```

The router decides *which capability applies and how confident it is*; the
agent makes the final call and executes. Nobody memorizes the list.

## Problem it solves

Without a router, an agent with N skills has an implicit O(N) lookup problem
that is solved by prompt stuffing (context bloat) or by guessing (wrong picks).
With a router, the agent asks one deterministic engine "what applies to this
request?" and gets a small, machine-readable recommendation with confidence and
alternatives — no memorization, no guessing, no context bloat.

## Architecture

The environment this skill establishes:

```
Agent
│
├── agent.md              ← persistent maintenance contract (behavioral rules)
│
├── skill.py              ← discovery + routing + command-resolution engine
│
├── skill-registry/
│   └── registry.json     ← generated index (never hand-edited)
│
└── skills/
    ├── existing-skill-1/
    │   ├── SKILL.md
    │   └── manifest.json ← source of truth per skill
    ├── existing-skill-2/
    └── ...
```

Routing pipeline (see `examples/sample-router/` for the architectural sketch):

```
Request
   ↓ Normalizer
   ↓ Intent Detector
   ↓ Skill Discovery
   ↓ Capability Matcher
   ↓ Command Resolver
   ↓ Command Validator
   ↓ Confidence / Ambiguity Layer
   ↓ Structured Routing Result
Agent → executes
```

## Installation / bootstrap behavior

`python3 skill.py bootstrap [--root DIR]` establishes the environment in
**both** situations:

- **Situation A — skills already exist** (repo has `skills/browser/`,
  `skills/github/`, … but no router): bootstrap inspects every skill folder,
  generates **candidate manifests** for any that lack one (derived from their
  SKILL.md, flagged `"needs_review": true`), builds the registry, appends the
  agent.md contract (merge-safe, marker-guarded), and installs `skill.py` if
  missing. Existing skills and instructions are preserved.
- **Situation B — no skills exist yet** (repo is just `agent.md`): bootstrap
  creates `skills/`, the registry mechanism, `skill.py`, and the agent.md
  contract. The environment is fully operational with zero skills — the moment
  a skill folder with a manifest appears, it is routable.

Bootstrap is **idempotent and conservative**: it never overwrites an existing
manifest, registry, router, or agent.md section. Running it twice changes
nothing the second time.

## agent.md synchronization (the persistent contract)

The most important mechanism for future evolution is the maintenance contract
bootstrap writes into `agent.md` (guarded by
`<!-- Skill_by_Satya:routing-contract -->`). It tells every future agent:

- **New skill** → Inspect → Register → Validate → Synchronize → Test.
- **Modified skill** → Reinspect → Update metadata → Validate commands →
  Synchronize → Test.
- **Removed skill** → Remove stale registry info → Validate router → Test.

Future agents automatically maintain the routing environment without being
asked to edit `skill.py`.

## Skill discovery

Discovery is dynamic and disk-driven: `skill.py` scans `skills/` on every call
and loads any folder containing a valid `manifest.json`. Adding a new skill =
adding a folder + manifest. No router edits, no recompilation, no hardcoded
list. Skills without a manifest are simply not routable (and `validate` reports
them so the agent can fix them).

## Command discovery

Commands come exclusively from manifests. Every command entry has a name,
syntax, description, and optional keywords. Before returning any command, the
router verifies it against the manifest of a discovered skill
(`validated: true`). **Invalid, stale, or invented commands are never
returned** — the router rejects them and keeps searching.

## Routing

Routing is deterministic scoring, not fuzzy guessing:

- Signals: skill name (0.5), alias (0.4), keyword (0.25), capability (0.2),
  intent phrase (0.15), description (0.05). A signal matches only when every
  token of its phrase appears in the request.
- Name-prefix disambiguation: if the request names a longer skill
  (e.g. `ponytail-review`), the shorter prefix skill (`ponytail`) gets no
  name/alias credit — specificity wins.
- Command resolution inside the top skill: command name (0.55), command
  keyword (0.3), command description (0.15). Single-command skills resolve to
  their only command.
- Confidence bands: ≥0.90 very strong · ≥0.75 strong · ≥0.50 possible ·
  <0.50 weak.
- Result: `matched` (skill + command + confidence + reason + alternatives) ·
  `ambiguous` (top candidates within a small delta — ask the user) ·
  `no_match` (nothing above the floor).

## Validation

`python3 skill.py validate` checks every skill folder: SKILL.md present,
manifest present and structurally valid, manifest `name` matches the folder
name, commands non-empty and unique, registry present and on-schema. Exit code
0/1 makes it CI-friendly. `python3 skill.py sync` is the idempotent
discover → rebuild → validate cycle: running it twice yields identical output,
and removed skills vanish from the regenerated registry automatically.

## Ambiguity

The router never silently transforms an uncertain match into an executable
command. Near-ties return `ambiguous` with the top candidates and their
confidence, and the agent asks the user. Low confidence → ask. High confidence
→ recommend. Invalid → reject. Unknown → no match.

## Maintenance

- `bootstrap` — establish the environment (both situations).
- `sync` — idempotent registry rebuild + validation + orphan report.
- `discover` — rebuild the registry index.
- `validate` — full integrity check.
- Self-evolution is enforced by the agent.md contract, not by the router.

## Constraints (what this skill must NOT do)

- Must NOT execute commands — it only recommends; the agent decides.
- Must NOT invent commands or capabilities — only manifest-registered ones.
- Must NOT hardcode a skill list in Python — discovery is always from disk.
- Must NOT hand-edit the registry — it is generated from manifests.
- Must NOT overwrite existing user instructions in agent.md — it merges.
- Must NOT silently guess on ambiguous input — it returns candidates.
- Must NOT assume the target repo's folder names, skills, or command names —
  everything is discovered or templated at bootstrap time.
- Must NOT depend on this repository's specific skills or implementation.

## Relationship to `documentions.md`

- `SKILL.md` (this file): what the skill IS and how it should behave.
- `documentions.md`: what happened while building the reference
  implementation, what failed, why, how it was fixed, and what was learned.
