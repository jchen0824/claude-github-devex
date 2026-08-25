# Benchmark: migrate-claude-sessions

| eval | config | pass | time (s) | tokens |
|---|---|---|---|---|
| full-migration-from-restored-store | with_skill | 12/12 | 276 | 84,694 |
| full-migration-from-restored-store | without_skill | 10/12 | 462 | 95,510 |
| diagnosis-without-premature-migration | with_skill | 4/4 | 167 | 66,113 |
| diagnosis-without-premature-migration | without_skill | 4/4 | 138 | 67,486 |
| agent-mode-identity-and-paths | with_skill | 8/8 | 257 | 89,179 |
| agent-mode-identity-and-paths | without_skill | 8/8 | 246 | 81,099 |

## Summary

- **with_skill**: pass 100%, time 233s, tokens 79,995
- **without_skill**: pass 94%, time 282s, tokens 81,365

## Analyst notes

- Only 4 of 24 assertions discriminate: every assertion in eval 2 (diagnosis) and eval 3 (agent-mode) passes in BOTH configurations, so those pass rates say nothing about the skill's value.
- The two genuine baseline failures are both in eval 1: the baseline never told the user to restart the app (so a correct migration would still show an empty list), and its rewritten cwd values do not resolve in the migrated tree.
- The unresolved-cwd failure is partly a scenario artifact: the baseline deliberately rewrote cwd to the live install path because it planned a separate stage-then-install step. Treat it as weaker evidence than the restart miss.
- Baselines were strong across the board. A capable model without the skill independently derived the path-scoping model, spotted the name-colliding config files, and found the self-referential cwd. The skill's value here is consistency and speed, not unlocking impossible work.
- Largest real effect is wall-clock on the full migration: 276s with the skill vs 462s without (-40%), and 84.7k vs 95.5k tokens (-11%). The bundled script replaces roughly 20 minutes of hand-rolled exploration.
- Evals 2 and 3 cost MORE with the skill (167s vs 138s; 257s vs 246s), because reading SKILL.md and running inventory has fixed overhead that a short diagnosis task does not amortize.
- Single run per cell, so stddev across evals reflects task difficulty, not run-to-run variance. No flakiness claim can be made from this data.