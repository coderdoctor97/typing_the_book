<!-- Skill_by_Satya:routing-contract -->
# Skill Router & Dynamic Skill Registry (Skill_by_Satya)

This repository has a skill-routing environment. `skill.py` discovers skills from `skills/` (each with a `manifest.json`), routes requests to the best skill + command, validates commands, and returns structured recommendations. It never executes anything; you decide and execute.

CLI: `python3 skill.py list | route "<request>" | validate | sync | discover`

Routing result: `matched` (recommended skill/command + confidence), `ambiguous` (ask the user), `no_match` (ask or handle directly).

## Maintenance contract (mandatory)
Whenever a skill is installed, added, modified, or removed, you MUST synchronize the routing environment:

* New skill: inspect it -> create/verify `skills/<name>/manifest.json` (name matches the folder; commands must actually exist; never invent capabilities) -> `python3 skill.py sync` -> test routing with `python3 skill.py route "<sample request>"`.
* Modified skill: re-inspect -> update its manifest -> validate commands -> `sync` -> test.
* Removed skill: delete the folder -> `sync` (registry is regenerated, stale entries vanish) -> `validate`.

## Safety rules
* NEVER execute a command the router did not return with `validated: true` (i.e. a command not registered in a real manifest).
* Low confidence -> ask. High confidence -> recommend. Invalid -> reject.
* The router is deterministic; do not hand-edit the registry (it is regenerated from manifests by `sync`).

## Separation of responsibilities
* `agent.md`: behavior, operating rules, this maintenance contract.
* `skills/<name>/manifest.json`: skill identity, capabilities, keywords, aliases, intents, commands (source of truth).
* `skill-registry/registry.json`: generated index (never hand-edited).
* `skill.py`: discovery, matching, ranking, resolution, validation.
* You: interpret, decide, ask when ambiguous, execute.

<!-- Skill_by_Satya:routing-contract -->
