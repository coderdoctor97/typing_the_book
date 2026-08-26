# Skill_by_Satya — documentions.md

> Implementation / postmortem reference. What happened while building the
> reference router, WHAT failed, WHY it failed, HOW it was fixed, and WHAT we
> learned.
>
> Architecture spec (what the skill IS): see `SKILL.md`.
> Implementation history + lessons (this file): see below.

---

## 0. Reference implementation context

The reference router was built in `typing_the_book`, a browser-only typing
practice app that also hosts a growing agent-skill library. Before the router:

- 19 skill folders existed under `skills/` (ponytail family, impeccable,
  hallmark, antislop family, supanova family, css-protips), each with a
  `SKILL.md` doc but **no structured metadata**.
- `AGENTS.md` contained the ponytail behavioral ruleset only.
- No discovery, no registry, no routing, no command validation existed.

The task: build a deterministic `skill.py` that discovers skills, routes user
requests to skill + command, validates commands, and returns structured
results — with manifests as source of truth and a generated registry — while
never inventing commands and never executing anything.

Everything below is the actual history of that build, including the failures.

---

## 1. Problems encountered

### P1. Crash in the ambiguity branch — `TypeError: unhashable type: 'list'`

```
Problem
  Routing "Run /ponytail-review on this diff" crashed the process:
  TypeError: unhashable type: 'list' in the ambiguous-candidates branch.

Why it happened
  The ambiguous branch computed command validity with a broken expression:
      all(c["command"] in {s.command_names and s.command_names} ...)
  `s.command_names and s.command_names` evaluates to the *list* itself (the
  `and` idiom returns the second operand when truthy), and `{list}` tries to
  build a set of a list → unhashable.

Why the initial approach failed
  I wrote the set-construction inline and "cleverly", without a unit test
  covering the ambiguous branch. The branch was never exercised until manual
  testing hit it.

How it was diagnosed
  Ran the route command manually; Python emitted the traceback immediately.
  The line number pointed straight at the `{s.command_names and ...}` set
  construction.

Solution
  Precompute a name→set-of-commands map once per request:
      cmds_by_skill = {s.name: set(s.command_names) for s in skills}
  and use a plain membership test: c["command"] in cmds_by_skill[c["skill"]].

Why the solution worked
  No inline set-of-list; the membership check is over an actual set of strings.

Trade-offs
  One extra dict per request — negligible. The real fix was making the
  validation path obvious enough to read in one glance.

Final implementation
  `route()` builds `cmds_by_skill` before the ambiguity branch; the `validated`
  field of an ambiguous result is computed with it.
```

### P2. Prefix-name collision: "ponytail" vs "ponytail-review" routed ambiguous

```
Problem
  "Run /ponytail-review on this diff" returned `ambiguous` (ponytail 0.65,
  ponytail-review 0.65) instead of `matched → ponytail-review`. Same for
  "/ponytail-audit" vs "ponytail", "antislop" vs "antislop-code", etc.

Why it happened
  The base skill name "ponytail" is a token subset of "ponytail-review". When
  the request contained the longer name, BOTH skills earned name credit (0.5)
  plus identical alias/keyword credit — exact ties. The ambiguity delta (0.10)
  then fired as designed, but the design intent was wrong: naming a specific
  skill is the strongest signal, not a tie.

Why the initial approach failed
  I treated every name match as equal. I had not considered that skill names
  form a prefix hierarchy (families of skills sharing a stem).

How it was diagnosed
  Manual test batch showed the tie. Inspecting the scored list (I added
  temporary prints) confirmed both skills earned the name signal.

Solution
  Name-prefix disambiguation: before scoring, compute the set of skills whose
  name is a token-prefix of a longer skill name that the request also
  contains, and suppress the name/alias signal for the shorter ones. The most
  specific skill named in the request wins the name credit.

Why the solution worked
  The specificity signal now belongs to exactly one skill; ties dissolve.

Trade-offs
  A request that genuinely intends BOTH "ponytail" and "ponytail-review" loses
  the shorter name's credit — acceptable, because naming the longer skill is
  the more specific instruction.

Final implementation
  `_name_suppressed()` returns suppressed names; `score_skill()` takes
  `suppress_name_alias` and skips name+alias credit for suppressed skills.
```

### P3. Too-strict phrase matching: "check the accessibility" ≠ "accessibility checks"

```
Problem
  "Check the contrast and accessibility of this interface" returned
  `no_match`, even though antislop-human's capability was "accessibility
  checks".

Why it happened
  Phrase matching is strict: every token of the phrase must appear in the
  request. "checks" (phrase) vs "check" (request) — different tokens — so the
  capability did not match. The router was doing exact-token matching, and
  natural language uses singular/plural freely.

Why the initial approach failed
  I chose strict whole-token containment for determinism and never seeded
  manifests with morphological variants. The manifests were written in the
  most natural phrase ("accessibility checks") while users phrase requests
  differently ("check accessibility").

How it was diagnosed
  Manual test batch; inspected the matched-signals reason and saw zero signals
  for antislop-human despite an obvious topical hit.

Solution
  Two-sided fix:
  1. Router: keep strict matching (determinism) — do NOT add a stemmer.
  2. Manifests: author phrases in both directions where morphology differs
     ("accessibility checks" AND "check accessibility"), and add
     capability phrases that mirror likely user phrasings.

Why the solution worked
  Strict matching remains inspectable; the vocabulary now covers the common
  surface forms.

Trade-offs
  Manifest authors must include plural/singular variants → slightly larger
  manifests. A stemmer would have been a smaller manifest but non-deterministic
  and language-specific — rejected deliberately (the spec forbids
  over-engineering).

Final implementation
  Router unchanged (strict matching); manifests carry variant phrases.
```

### P4. Incomplete metadata caused a wrong single match: "redesign this landing page"

```
Problem
  "Redesign this landing page" matched ONLY supanova-redesign-engine (0.6).
  Expected: ambiguous between supanova-redesign-engine and hallmark — both
  legitimately own "landing page redesign".

Why it happened
  hallmark's manifest did not include "landing page redesign" phrasing (its
  redesign intent listed "redesign a page", "redesign something"). The
  capability "landing page redesign" was missing from hallmark.

Why the initial approach failed
  Manifests were authored per-skill in isolation, not cross-checked for
  overlapping capability coverage. The router faithfully reflected incomplete
  metadata — a metadata bug, not a routing bug.

How it was diagnosed
  Manual test batch: single match; inspected hallmark's manifest; the missing
  phrase was obvious once the two design skills were compared.

Solution
  Added "landing page redesign" to hallmark's capabilities and "redesign a
  landing page" to its intent triggers. Result: both score 0.6 → `ambiguous`,
  which is the correct outcome (the user should pick).

Why the solution worked
  The ambiguity layer is exactly the tool for overlapping capabilities; the
  fix was giving it complete metadata to work with.

Trade-offs
  More ambiguity cases surface as manifests improve — that is a feature: the
  agent asks instead of guessing.

Final implementation
  hallmark manifest now covers the shared phrasing; test asserts the ambiguous
  result with both candidates.
```

### P5. Missing variants → no_match for valid intents

```
Problem
  "Clean up the slop comments in this code" → no_match (expected
  antislop-code). "Make my landing page premium" → no_match (expected
  supanova-premium-aesthetic).

Why it happened
  Same root cause as P3/P4: antislop-code's capability was "slop comment
  removal" (request says "clean up ... comments"); supanova-premium-aesthetic's
  capability was "premium aesthetic" (request says "premium landing page").

Why the initial approach failed
  Manifests listed noun-phrase capabilities, requests use verb phrases.

How it was diagnosed
  Test batch; missing signals confirmed by inspecting reasons.

Solution
  Added verb-phrase variants ("clean up code comments", "premium landing
  page") to capabilities and intent triggers.

Why the solution worked
  The deterministic matcher now finds the shared tokens.

Trade-offs
  Same as P3: manifest verbosity is the cost of strict matching.

Final implementation
  Manifests extended; tests assert `matched` with the correct skill.
```

### P6. Test-suite infrastructure failure: `FileNotFoundError` on temp skill

```
Problem
  First run of test/test_skill.py died with
  FileNotFoundError: skills/router-test-echo/SKILL.md — the parent directory
  did not exist.

Why it happened
  I assumed `Path.write_text()` creates parent directories. It does not.

Why the initial approach failed
  Assumption about stdlib behavior, not validated.

How it was diagnosed
  Traceback showed the exact missing path.

Solution
  `tmp_dir.mkdir(parents=True, exist_ok=True)` before writing.

Why the solution worked
  Explicit parent creation; also makes the test idempotent across runs.

Trade-offs
  None.

Final implementation
  Temp-skill test creates its folder first; `finally` block removes it.
```

### P7. Registry stored absolute manifest paths (portability bug)

```
Problem
  skill-registry/registry.json contained absolute paths like
  "/home/user/typing_the_book/skills/antislop/manifest.json".

Why it happened
  `load_manifest()` stores `str(path)` as given (absolute), and `build_registry`
  wrote it verbatim.

Why the initial approach failed
  I did not consider that the registry is a repo-local artifact that should be
  relocatable (cloned elsewhere, moved).

How it was diagnosed
  Read the generated registry and saw machine-specific paths.

Solution
  Registry writes `manifest` relative to the repo root:
  `str(Path(s.manifest_path).relative_to(root_path))` → "skills/antislop/manifest.json".

Why the solution worked
  Relative paths are portable; the registry remains valid after clone/move.

Trade-offs
  The registry is now only meaningful relative to its own repo root — which is
  exactly what it is.

Final implementation
  `build_registry()` relativizes all manifest paths; test asserts the
  registry contains no absolute paths.
```

### P8. Python bytecode pollution in the repo

```
Problem
  Running tests created `__pycache__/` at the repo root.

Why it happened
  Python 3 compiles imported modules to `__pycache__` by default.

Why the initial approach failed
  The repo had no Python .gitignore entries (it is a JS/Node project).

How it was diagnosed
  `git status` showed the untracked directory.

Solution
  Added `__pycache__/` and `*.pyc` to `.gitignore`.

Why the solution worked
  Standard practice; keeps the tree clean.

Trade-offs
  None.

Final implementation
  `.gitignore` now covers Python artifacts.
```

### P9. Spec-example skills don't exist in the target repo (deliberate no_match)

```
Problem
  The spec's worked examples assume "github" and "browser" skills with
  commands like github_search. This repo has none. "Search GitHub repositories"
  → no_match, not a github command.

Why it happened
  The spec is generic; the repo is real. Assuming the spec's examples exist
  would have meant inventing commands — explicitly forbidden.

Why the initial approach failed
  N/A — this was a deliberate design decision, not a failure.

How it was diagnosed
  Confirmed during discovery: no github/browser skill folders exist.

Solution
  The router returns no_match for unsupported domains. The test suite asserts
  this: "Search GitHub repositories" must be no_match and `github_search` must
  NOT be a known command.

Why the solution worked
  "Never invent commands" beats "match the spec example". The test locks the
  behavior in.

Trade-offs
  The user must install a github skill for github requests to route — the
  correct workflow, and exactly what the dynamic-discovery design enables.

Final implementation
  Test cases assert no_match + non-registration; documented here as a
  deliberate boundary.
```

### P10. Vendor-skill content carried hardcoded install paths

```
Problem
  impeccable's pre-built SKILL.md contained hardcoded
  ".claude/skills/impeccable/scripts/..." paths (its canonical Claude Code
  install layout), which do not exist in this repo's `skills/impeccable/`.

Why it happened
  Impeccable's build pipeline emits provider-specific skills; the repo's
  canonical folder is the portable `skills/` layout, but the shipped artifact
  was written for `.claude/skills/`.

Why the initial approach failed
  Installed the artifact verbatim during the earlier skill-install step.

How it was diagnosed
  Grep for ".claude/skills/impeccable" in the installed SKILL.md found 3 hits.

Solution
  sed-rewrite the path prefix to "skills/impeccable" at install time.

Why the solution worked
  The script paths in the doc now resolve in this repo's layout.

Trade-offs
  Manual fix at vendoring time; a lesson for the meta-skill: when ingesting
  third-party skills, scan for hardcoded install paths and repo-specific
  absolute paths.

Final implementation
  `skills/impeccable/SKILL.md` uses `skills/impeccable/scripts/...`; the
  meta-skill's bootstrap documents this check for generated manifests.
```

### P11. Intent fallback ambiguity (design decision, not a bug)

```
Problem
  When no intent phrase matched, intent became "skill.command" (e.g.
  "css-protips.css-protips") — noisy but honest. Is that right?

Why it happened
  Intent is derived from manifests; not every request triggers one.

Why the initial approach failed
  N/A — handled by design.

How it was diagnosed
  Review of routing outputs showed the fallback pattern.

Solution
  Keep the fallback but document it: intent is "the best signal we have"; when
  it is only the skill+command, the agent still has enough to act. Cleaner
  intents come from better manifest intent phrases.

Trade-offs
  Slightly noisy intent values vs. fabricating an intent label.

Final implementation
  `detect_intent()` returns None → fallback to `skill.command`; documented in
  skill.py docstring.
```

---

## 2. Failed tests (detailed record)

| # | Test | Expected | Actual | Failure reason | Debugging | Fix | Final result |
|---|------|----------|--------|----------------|-----------|-----|--------------|
| F1 | Route "Run /ponytail-review on this diff" (manual) | matched → ponytail-review | **crash: `TypeError: unhashable type: 'list'`** | broken set-of-list construction in the ambiguity branch | traceback → line pointed at `{s.command_names and ...}` | precompute `cmds_by_skill` map; plain membership test | matched → ponytail-review, validated true |
| F2 | Route "Run /ponytail-review on this diff" (manual, pre-fix) | matched → ponytail-review | **ambiguous** (ponytail 0.65, ponytail-review 0.65) | prefix-name collision: both earned name credit | printed scored list; both had name signal | name-prefix disambiguation (`_name_suppressed`) | matched → ponytail-review |
| F3 | Route "Check the contrast and accessibility of this interface" | matched → antislop-human | **no_match** | strict token matching; "checks" vs "check" | no signals in reason | manifest variant phrases ("check accessibility") | matched → antislop-human (0.6) |
| F4 | Route "Redesign this landing page" | ambiguous (hallmark + supanova-redesign-engine) | **matched → supanova-redesign-engine only** | hallmark manifest lacked "landing page redesign" phrasing | compared the two manifests | added phrases to hallmark | ambiguous with both candidates (0.6/0.6) |
| F5 | Route "Clean up the slop comments in this code" | matched → antislop-code | **no_match** | capability was noun-phrase only | inspected manifest | added "clean up code comments" capability | matched → antislop-code |
| F6 | Route "Make my landing page premium" | matched → supanova-premium-aesthetic | **no_match** | capability "premium aesthetic" vs request "premium landing page" | inspected manifest | added "premium landing page" + intent phrase | matched → supanova-premium-aesthetic |
| F7 | test/test_skill.py run #1 | 30+ tests pass | **FileNotFoundError** (temp skill dir missing) | assumed `Path.write_text` creates parents | traceback | `mkdir(parents=True, exist_ok=True)` | 33 tests pass |
| F8 | (design) "Search GitHub repositories" | no_match + `github_search` NOT known | no_match ✅ (from the start) | spec example assumed a github skill; repo has none | discovery confirmed no github folder | deliberate: never invent commands; test asserts it | no_match, github_search not registered |

**Note on F1/F2:** the crash (F1) and the tie (F2) were found in the same
manual test batch — the first time the ambiguous branch was ever executed.
This is the classic case of untested branches: the happy path was exercised,
the ambiguity path was not. The lesson became the test suite's coverage rule
(see §4).

---

## 3. Successful tests

The final suite (`test/test_skill.py`, 33 tests) — grouped with
Expected / Actual / Status:

### Direct match
- "Audit this UI with impeccable" → skill `impeccable`, command `audit`, conf ≥ 0.75, validated.
  Expected: matched. Actual: matched (conf 1.0). **Status: pass.**

### Alias match
- "Run /ponytail-review on this diff" → `ponytail-review`.
  Expected: matched. Actual: matched. **Status: pass.**
- "Lazy mode please, make it minimal" → `ponytail` (alias "lazy mode").
  Expected: matched. Actual: matched. **Status: pass.**

### Capability match
- "Check the contrast and accessibility of this interface" → `antislop-human`.
  Expected: matched. Actual: matched (conf 0.6). **Status: pass.**

### Intent match
- "Generate a landing page for our product" → `supanova-design-engine`, intent
  `generate_landing_page`.
  Expected: matched. Actual: matched. **Status: pass.**

### Command resolution
- "Audit this UI with impeccable" → command `audit` (multi-command skill,
  resolved via name+keyword).
  Expected: command audit. Actual: command audit. **Status: pass.**

### Command validation
- `is_known_command("audit")` → True; `is_known_command("github_search")` → False.
  Expected: as stated. Actual: as stated. **Status: pass.**
- Every returned/candidate command must be registered — loop over matched +
  ambiguous outputs.
  Expected: all registered. Actual: all registered. **Status: pass.**

### Ambiguity handling
- "Redesign this landing page" → ambiguous, ≥2 candidates (hallmark,
  supanova-redesign-engine), selected None.
  Expected: ambiguous. Actual: ambiguous. **Status: pass.**

### Unknown requests
- "What's the weather in Paris?" → no_match, skill/command null.
  Expected: no_match. Actual: no_match. **Status: pass.**
- "Search GitHub repositories" → no_match (no github skill; nothing invented).
  Expected: no_match. Actual: no_match. **Status: pass.**

### New-skill discovery
- Temp skill `router-test-echo` with manifest → "echo this back" routes to it;
  after removal → no_match again.
  Expected: discovered then unroutable. Actual: both. **Status: pass.**

### Registry behavior
- `build_registry()` in a temp root → skill_count 1, registry.json written.
  Expected: as stated. Actual: as stated. **Status: pass.**

### Validation
- `validate_all()` → ok True, skills_checked ≥ 19 (now ≥ 20).
  Expected: OK. Actual: OK. **Status: pass.**

### CLI smoke
- `skill.py route "audit this ui with impeccable"` → exit 0, matched.
  `skill.py list` → exit 0.
  Expected: as stated. Actual: as stated. **Status: pass.**

### Non-router regression (preserve existing functionality)
- `npm test` → 10 focused tests pass; `npm run build` → success.
  Expected: pass. Actual: pass. **Status: pass.**

---

## 4. Architectural lessons

### What was correct (keep by default)
- **Manifests as source of truth, registry as generated index.** Zero
  duplication; the registry is disposable.
- **Deterministic stdlib-only routing.** Same input → same output, fully
  inspectable via the `reason` field. No LLM/embeddings in the hot path.
- **Dynamic disk-driven discovery.** Adding a skill folder + manifest makes it
  routable; `skill.py` never changes.
- **The router never executes.** Hard boundary between recommendation and
  execution.
- **Command validation as a hard gate.** A command is returned only if a
  discovered manifest declares it.
- **Ambiguity over guessing.** Near-ties return candidates; the agent asks.
- **Lenient discovery + strict validation.** Discovery skips broken manifests
  silently; `validate` reports them loudly.
- **Name-prefix disambiguation.** Specificity wins when skill names nest.
- **Separate behavior (agent.md), metadata (manifests), index (registry),
  engine (skill.py), decision (agent).**

### What was initially wrong
- Inline "clever" expressions in untested branches (the set-of-list crash).
- Absolute paths in generated artifacts.
- Manifests authored as noun phrases only, ignoring user verb phrasings.
- Not accounting for skill-name prefix hierarchies at first.
- Assuming `Path.write_text` creates parents; assuming the spec's example
  skills exist in the real repo.

### What should never be repeated
- Never return a command that is not validated against a discovered manifest.
- Never hardcode the skill list in Python.
- Never hand-edit the registry.
- Never silently pick on ambiguity.
- Never overwrite existing agent instructions during bootstrap.

### What future projects should do by default
- Seed manifests with both noun and verb phrase variants.
- Write a test for EVERY routing branch before/while implementing it
  (especially the ambiguous branch — F1/F2 died there).
- Make the registry a relative-path, regenerated artifact.
- Add `python3 skill.py validate` to CI.
- Cross-check manifests of overlapping skills for shared phrasing (P4).

### Assumptions the router must never make
- That a named command exists because the user asked for it.
- That a skill exists just because keywords match (match must reach the floor).
- That the spec/example skills exist in the target repo.
- That one skill owns a request (ambiguity must be representable).
- That skill names are disjoint (they form prefix families).
- That manifests are perfect (validate is a separate, loud step).

### What should remain dynamic
- The skill list (from disk, every call).
- Commands, keywords, aliases, capabilities, intents (from manifests).
- Confidence thresholds and weights (top-of-file constants).

### What should remain deterministic
- Matching logic, scoring order, tie-breaking, output schema.

### Where the agent makes the final decision
- Whether to execute, whether to ask on ambiguity, what to do when the
  command is null (multi-command skill with no signal).

### Where the router stops
- At the structured recommendation. It never touches the execution layer.

### What belongs in skill metadata (manifest)
- name (== folder name), description, keywords, aliases, capabilities,
  intents (id → trigger phrases), commands (name, syntax, description,
  keywords).

### What belongs in agent.md
- Operating rules, the maintenance contract, safety constraints, the
  separation-of-responsibilities statement. Not the skill list.

### What belongs inside skill.py
- Discovery, indexing, intent matching, ranking, command resolution,
  command validation, registry generation, CLI. Not skill content.

### What belongs inside individual skills
- Their own docs (SKILL.md) and their own manifest. Nothing else.

---

## 5. Sample of the current router architecture

See `examples/sample-router/` for the full architectural sketch. In one
paragraph: the router **normalizes** the request, **discovers** skills from
disk, **scores** each against name/alias/keyword/capability/intent/description
signals with a weighted deterministic matcher, **resolves** the best command
within the top skill, **validates** it against that skill's manifest, then
applies **confidence bands + ambiguity detection** before emitting a
**structured result** the agent decides on.

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
Agent → Command Execution
```

The reference implementation in this repo (`skill.py` at the root) is the
concrete instance; `Skill_by_Satya/skill.py` is the generalized engine plus
`bootstrap`/`sync`.

---

## 6. Portability notes

The reusable skill generalizes the reference:

| Reference repo | Skill_by_Satya |
|---|---|
| `skills/ponytail/`, `skills/hallmark/`, … | `skills/<anything>/` — discovered, never enumerated |
| repo-specific manifests | templates + bootstrap-generated candidates |
| `AGENTS.md` (this repo's name) | `agent.md` (target repo's name), merge-safe |
| root `skill.py` | any `skill.py` — the same file bootstraps itself |
| hardcoded commands in tests | test fixtures built from temp dirs |

Non-goals baked in: no dependency on this repo's skills, folder names, command
names, or implementation. `bootstrap --root DIR` works against an empty dir.

---

## 7. Practical validation (Part 16 of the spec)

### Environment A — existing skills + existing agent.md (temp dir)

Setup: `T/skills/browser/SKILL.md` (no manifest), plus an `agent.md` with
user content.

Run: `python3 Skill_by_Satya/skill.py bootstrap --root T`

Verified:
- browser/SKILL.md preserved; candidate `manifest.json` generated
  (`_bootstrap.needs_review: true`).
- User content in agent.md preserved; contract section appended under its
  marker.
- `T/skill.py` installed; registry built with 1 skill.
- `route "interact with web pages"` (or "use the browser skill") →
  matched → browser. Result: routing operational immediately.
- Idempotency: second bootstrap changed nothing.

### Environment B — empty/new repository (temp dir)

Setup: empty `T/` (no skills, no agent.md).

Run: same bootstrap.

Verified:
- `T/skills/`, `T/skill-registry/registry.json`, `T/skill.py`, `T/agent.md`
  (with contract) all created.
- Later-added skill `T/skills/echo/` with a manifest → `route "echo this
  back"` → matched → echo. Zero router edits.
- `sync` twice → identical registry (idempotent); removed skill → registry
  regenerates without it.

Both paths converge on the same final architecture:

```
agent.md → maintenance contract
skills/<skill>/manifest.json → capabilities + commands (source of truth)
skill-registry/registry.json → generated index
skill.py → routes intent → skill → command
agent → decides and executes
```

---

## 8. Future evolution (room left on purpose)

The architecture leaves seams for, without implementing now:

- new-skill detection (bootstrap already flags missing manifests; a watcher
  could hook `skill_folders()`)
- skill/command versioning (manifest already has an optional `version` field;
  `_bootstrap` marks generation)
- dependency detection, capability-conflict detection, skill priority (extra
  manifest fields + a ranking hook)
- confidence scoring tuning (weights are top-of-file constants)
- semantic matching / embeddings / LLM-assisted intent (a pluggable scorer
  slot — currently the deterministic scorer)
- context-aware routing (thread/state passed into `route()`)
- router diagnostics (`sync` already returns a full report; a `--json` doctor
  mode is a thin wrapper)
- registry validation + automatic migration (schema_version exists;
  `validate` warns on mismatch)

The rule: the deterministic engine stays the default; semantic layers are
opt-in upgrades, never the base.

---

## 9. Golden rules (the tl;dr of everything above)

1. Manifest = truth. Registry = generated. Router = deterministic. Agent = decides.
2. Never invent a command or capability.
3. Never return an unvalidated command.
4. Never guess silently on ambiguity.
5. Never execute from the router.
6. Discovery from disk, always.
7. Test every branch, especially the ambiguity branch.
8. Seed manifests with user-shaped phrases, not just noun phrases.
9. Bootstrap conservatively: inspect, merge, preserve, never overwrite.
10. Idempotent sync: run twice, same result, no corruption.
