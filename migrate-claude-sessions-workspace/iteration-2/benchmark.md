# Benchmark: migrate-claude-sessions (iteration 2)

| eval | config | pass | time (s) | tokens |
|---|---|---|---|---|
| full-migration-from-restored-store | with_skill | 10/10 | 522 | 97,986 |
| full-migration-from-restored-store | without_skill | 8/10 | 350 | 90,706 |
| ambiguous-three-account-source | with_skill | 7/7 | 235 | 89,375 |
| ambiguous-three-account-source | without_skill | 7/7 | 267 | 82,221 |
| collision-must-not-clobber | with_skill | 5/5 | 218 | 87,313 |
| collision-must-not-clobber | without_skill | 5/5 | 278 | 81,026 |
| live-tree-mismatch | with_skill | 4/4 | 226 | 74,467 |
| live-tree-mismatch | without_skill | 2/4 | 234 | 82,507 |

## Summary

- **with_skill**: pass 100%, time 300s, tokens 87,285
- **without_skill**: pass 82%, time 282s, tokens 84,115

## Analyst notes

- Discrimination improved from 2/24 (iteration 1) to 4/26. Still not high, but the failures are now consequential rather than cosmetic.
- Eval 4 (live-tree mismatch) is the strongest new signal: the baseline migrated correctly into a tree the running app never reads, and never told the user, so the sessions would still not appear.
- Eval 1's remaining baseline failures: it copied the 8 recurring cron records, and again omitted the restart instruction — the same miss as iteration 1, independently reproduced.
- Evals 2 and 3 did NOT discriminate: both arms handled the decoy account sharing an org UUID, the skills-plugin directory, and the record-name collision correctly. Keep them as regression guards, not as evidence of skill value.
- Scoring correction during this iteration: the with-skill eval-1 run first scored 7/10 because the grader hardcoded the fixture's target bucket. The run had instead built the target from the LIVE account UUIDs — the better answer, since a restored backup's 'new account' bucket predates the current login. The grader was fixed to accept any non-source bucket.
- The with-skill eval-1 run found a real defect in the bundled script: path rewriting replaced only the account/org fragment, never the root prefix, so a staged or restored store kept cwd values pointing into the backup folder. Fixed via --final-root, and verify now fails on it.
- Cost moved the wrong way on eval 1: 522s with the skill vs 350s baseline, because the skill's run also rehearsed the landing step against a mock live tree. Thoroughness bought correctness here, not speed.
- Single run per cell again — no variance estimate, no flakiness claim.