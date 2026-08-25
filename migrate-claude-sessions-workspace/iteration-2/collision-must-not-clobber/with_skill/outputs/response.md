# Session migration: previous.owner@example.com → your new account

Done. **15 sessions moved across, and everything that was already on the new account is byte-for-byte untouched** — including one session that would have been silently overwritten.

## What I found first

Store: `/Users/chenhouren/Projects/claude-github-devex/migrate-claude-sessions-workspace/fixtures/eval-3-with`

```
store                     account    org         sess  sched  dirs  span                     owner
--------------------------------------------------------------------------------------------------
claude-code-sessions      aaaaaaaa   bbbbbbbb      12      0     0  2026-07-26 .. 2026-08-06 previous.owner@example.com
claude-code-sessions      cccccccc   dddddddd       2      0     0  2026-08-25 .. 2026-08-25 unknown
claude-code-sessions      eeeeeeee   bbbbbbbb       5      0     1  2026-08-07 .. 2026-08-11 other.person@example.com
local-agent-mode-sessions aaaaaaaa   bbbbbbbb      12      8    12  2026-08-05 .. 2026-08-24 previous.owner@example.com
local-agent-mode-sessions cccccccc   dddddddd       0      0     0  -                        unknown
```

Three decisions I made without you, and why:

- **Source = `aaaaaaaa/bbbbbbbb`** — the only bucket owned by `previous.owner@example.com`. There is a *third* account here, `eeeeeeee/bbbbbbbb`, owned by **other.person@example.com**. That is a different person, so I left it completely alone. Flagging it in case you didn't know it was on this machine.
- **Target = `cccccccc/dddddddd`** — the bucket holding the two sessions dated today, which matches "I've already done a bit of work on the new account".
- **Copy, not move.** Your old records are still in their original bucket. Nothing is deleted, so this is trivially reversible. Say the word and I'll re-run with `--move` to clear the old bucket out.

## The collision you were worried about

There was one, and it was real. `local_code0003-0000-4000-8000-000000000003.json` existed in **both** buckets with different contents:

| | title | cwd |
|---|---|---|
| already on new account | `TARGET VERSION - MUST SURVIVE` | `/Users/example/Projects/target-owned` |
| on old account | `Old account session 3` | `/Users/example/Projects/repo-3` |

**Your version won.** The old account's copy was skipped, not merged and not written. It is still sitting in the old bucket and in the backup if you ever want it — but it cannot be added under its own name without displacing yours, since the filename *is* the session id.

The same trap existed for config: `scheduled-tasks.json` sits in the same directory as the session records and has the same name in every bucket. Yours says `"belongsTo": "new"`, the old account's says `"belongsTo": "old"`. Config files were excluded from the copy, so yours is intact — as is your `rpm/manifest.json`.

## Commands run

```bash
cd /Users/chenhouren/Projects/claude-github-devex/skills/migrate-claude-sessions
FIX=/Users/chenhouren/Projects/claude-github-devex/migrate-claude-sessions-workspace/fixtures/eval-3-with

# 1. inventory
python3 scripts/claude_session_migrate.py --root "$FIX" inventory --all

# 2. backup (written into the outputs dir, not your home dir)
python3 scripts/claude_session_migrate.py --root "$FIX" backup \
  --dest .../outputs/session-stores-backup.tar.gz
# -> session-stores-backup.tar.gz  (0.0 MB, 120 entries)

# 3. dry run
python3 scripts/claude_session_migrate.py --root "$FIX" migrate \
  --source aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa/bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb \
  --target cccccccc-3333-4333-8333-cccccccccccc/dddddddd-4444-4444-8444-dddddddddddd \
  --dry-run

# 4. the real thing (same command, no --dry-run)

# 5. verify
python3 scripts/claude_session_migrate.py --root "$FIX" verify --source ... --target ...
```

### Results

| store | copied | workdirs | skipped: already there | skipped: scheduled |
|---|---|---|---|---|
| `claude-code-sessions` | 11 | 0 | **1** | 0 |
| `local-agent-mode-sessions` | 4 | 4 | 0 | **8** |

Identity rewritten on 4 agent-mode records, `cwd` repointed on 2 (they pointed inside the old account's own bucket and would otherwise have kept reading and writing there).

The 8 skipped agent-mode records are recurring scheduled runs — "Tidy downloads daily" and friends, the same task firing over and over. They're excluded by default because a hundred near-identical cards bury the sessions you actually care about. Re-run with `--include-scheduled` if you want them.

### Verification

```
  ok    claude-code-sessions: 13 session records in target
  ok    claude-code-sessions: 12 records still in source
  ok    local-agent-mode-sessions: 4 session records in target
  ok    local-agent-mode-sessions: 12 records still in source
  ok    local-agent-mode-sessions: 4 migrated workdirs keep the previous account in their sandbox .claude.json
  ok    transcripts: 0 of 13 found in ~/.claude/projects

verification passed
```

I also ran my own independent check — SHA-256 and mtime of every pre-existing file, before and after:

```
UNCHANGED  .../cccc.../dddd.../local_code0003-...json       <- the collision
UNCHANGED  .../cccc.../dddd.../local_existing-...json
UNCHANGED  .../cccc.../dddd.../scheduled-tasks.json
UNCHANGED  .../local-agent-mode-sessions/cccc.../dddd.../rpm/manifest.json
UNCHANGED  .../local-agent-mode-sessions/cccc.../dddd.../scheduled-tasks.json
```

All 57 files in the old account's bucket and in other.person's bucket: unchanged too.

Final state — 13 Claude Code sessions (11 migrated + your 2) and 4 agent-mode sessions on the new account, dates preserved so the list stays in chronological order.

## Three things to know

**1. This store is not the one your app reads.** The tool flagged it and I want to be explicit: the running desktop app reads `~/Library/Application Support/Claude`, and the account you're signed into (`jc@mindoralabs.io`) owns no bucket in the store you pointed me at. So this migration is correct but **not yet visible in the app**. To finish, the target bucket has to be copied into the live tree — and the live bucket UUIDs re-checked there with `inventory` rather than assumed to match these. I didn't touch your live tree; that's your call to make.

**2. Transcripts are missing for all 13.** Conversation content lives in `~/.claude/projects/<slug>/<id>.jsonl`, which isn't account-scoped and was never copied — every account on the Mac can already read it. None of these session ids have a transcript on disk. That's transcript retention pruning them on its own schedule, and it happened before this migration, not because of it. Those cards will appear in the list but won't resume.

**3. The 4 migrated agent-mode working directories still carry the old account** in their sandbox `.claude/.claude.json`. That's per-session state; rewriting it means inventing billing and subscription fields for the new account, so I left it. Happy to rewrite just the identity fields if you'd rather.

## Restart the app

Nothing above shows up until you do. The session list is a directory scan cached in memory at launch, so until Claude restarts you'll see exactly the same list you see now and reasonably conclude this failed.

Two caveats on the restart: if you're reading this inside the desktop app, restarting ends your current session — finish what you're doing first. And per point 1, restarting alone won't be enough here; the files need to reach the live tree first.

---

Backup at `outputs/session-stores-backup.tar.gz` (120 entries, both stores, pre-migration). Baselines and raw command output alongside it: `baseline-target.txt`, `baseline-source-and-other.txt`, `dry-run.txt`, `migrate.txt`, `verify.txt`, `inventory-after.txt`, `nochange-target.txt`.
