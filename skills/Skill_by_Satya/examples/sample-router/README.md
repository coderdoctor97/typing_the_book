# Sample Router — architectural reference

This is a *representative* sketch of the routing pipeline, not a copy of any
specific repository's implementation. Use it to communicate the design or as a
starting skeleton for a router written in a different language/stack.

## Pipeline

```
Request
   ↓
Normalizer
   ↓
Intent Detector
   ↓
Skill Discovery
   ↓
Capability Matcher
   ↓
Command Resolver
   ↓
Command Validator
   ↓
Confidence / Ambiguity Layer
   ↓
Structured Routing Result
   ↓
Agent
   ↓
Command Execution
```

## Layer responsibilities

| Layer | Owns | Stops when |
|---|---|---|
| **Normalizer** | lowercase, tokenize, drop stopwords | input is empty/unknown |
| **Intent Detector** | map request to an intent id from skill manifests | no intent phrase matches (fall back to `skill.command`) |
| **Skill Discovery** | scan `skills/` for folders with `manifest.json`; load | no routable skills |
| **Capability Matcher** | score skills by name/alias/keyword/capability/intent/description signals | all scores below the confidence floor |
| **Command Resolver** | pick the best command within the top skill (name/keyword/description) | single-command skill, or no command signal (agent decides) |
| **Command Validator** | verify the command exists in the manifest of a discovered skill | command missing → never return it |
| **Confidence / Ambiguity** | rank, band scores, detect near-ties | tie → return `ambiguous` + candidates, ask the user |
| **Structured Result** | emit `{status, intent, skill, command, confidence, reason, validated, alternatives}` | — |
| **Agent** | interpret, decide, ask, execute | the router's output boundary |

## Minimal skeleton (pseudocode)

```python
def route(request, skills):
    tokens = normalize(request)                    # 1 Normalizer
    if not tokens: return no_match()
    intent = detect_intent(tokens, skills)         # 2 Intent Detector
    candidates = []
    for skill in discover_skills():                # 3 Skill Discovery
        score = score_skill(tokens, skill)         # 4 Capability Matcher
        if score >= FLOOR:
            cmd = resolve_command(tokens, skill)   # 5 Command Resolver
            if cmd and not exists(cmd, skill):     # 6 Command Validator
                cmd = None                         #    never return invalid
            candidates.append((score, skill, cmd))
    candidates.sort(by_score, desc)
    if not candidates: return no_match()
    if tie_within(delta): return ambiguous(candidates)   # 7 Confidence/Ambiguity
    return matched(candidates[0])                  # 8 Structured Result
```

## Invariants the sample encodes

1. The router returns data; it never runs a command.
2. A command is only ever returned if the manifest of a *discovered* skill
   declares it.
3. Near-ties return `ambiguous` with the top candidates, never a silent guess.
4. Everything is deterministic: same request → same result.
5. The skill list is read from disk every time; adding a folder makes a skill
   routable with zero router changes.
