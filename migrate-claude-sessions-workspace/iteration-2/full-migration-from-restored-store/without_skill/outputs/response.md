# Your old sessions are recovered

Good news: nothing was lost. Your history was never deleted — the app was just
looking in the wrong drawer. I've rebuilt it under your new team account inside
the restored backup, and verified it with 215 automated checks. There's one
manual step left at the end (copying it into the live app), which I deliberately
did not do for you — reasons below.

---

## What actually happened

The Claude desktop app stores local session history in two places, and both are
keyed by **which account you were signed in as**:

```
~/Library/Application Support/Claude/claude-code-sessions/<accountUuid>/<organizationUuid>/
~/Library/Application Support/Claude/local-agent-mode-sessions/<accountUuid>/<organizationUuid>/
```

When you switched from your personal account to the company team account, both
UUIDs changed. The app started reading from a brand-new, nearly-empty directory.
Your old sessions were sitting untouched in the old directory the whole time —
invisible, not gone.

In your restored backup:

| | account UUID | organization UUID |
|---|---|---|
| **Old (personal)** | `aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa` | `bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb` |
| **New (team)** | `cccccccc-3333-4333-8333-cccccccccccc` | `dddddddd-4444-4444-8444-dddddddddddd` |

What was stranded under the old key:

- **12 Claude Code sessions** (`local_code0000` … `local_code0011`)
- **4 agent-mode sessions** ("Real agent session A" through "D")
- **8 scheduled-run records** (all "Tidy downloads daily")
- **12 agent workspace directories**, each with its own `.claude/.claude.json`
  and `outputs/result.txt` — the actual work product of those runs

**36 items total.** All 36 are now under the new account.

---

## Why a plain copy would have broken things

This is the part worth knowing, because the obvious `cp -R old/* new/` would have
quietly destroyed data. Three traps:

1. **The new account isn't empty.** It already had a session
   ("Session already on the new account"), a `scheduled-tasks.json`, and an
   `rpm/manifest.json` listing an installed plugin (`keep-me`). A recursive copy
   overwrites those last two files with the old account's versions — you'd lose
   the plugin registration and your current scheduled-task config, with no error
   message.

2. **Absolute paths pointed into the old directory.** Two agent sessions
   (`local_agent001`, `local_agent002`) had a `cwd` hard-coded to the *old*
   account's workspace path. Copy them as-is and those sessions either open into
   a dead path or reach back into the old account's files.

3. **Every workspace carried the old account's identity.** All 12
   `.claude/.claude.json` files embedded an `oauthAccount` block still naming the
   personal account's UUIDs. Resuming a session from one of those workspaces
   would hand Claude Code a defunct account identity.

So the migration is additive and rewrites as it goes, rather than being a copy.

---

## What I did

### 1. Backup first

```bash
tar -czf .../outputs/pre-migration-backup-eval-1-without.tar.gz eval-1-without
```

Result: `pre-migration-backup-eval-1-without.tar.gz`, 104 entries. Full snapshot
of the restored store before I touched anything.

### 2. Dry run

I wrote `migrate_sessions.py` (in the outputs folder — it's re-runnable and takes
the store root and both account keys as arguments, so it works against the live
app too).

```bash
python3 migrate_sessions.py \
  --store-root .../fixtures/eval-1-without \
  --from aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa/bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb \
  --to   cccccccc-3333-4333-8333-cccccccccccc/dddddddd-4444-4444-8444-dddddddddddd
```

```
[claude-code-sessions]
    copied 12 session record(s) + 0 workspace dir(s)
    scheduled-tasks.json: old account has 0 tasks -> destination left untouched

[local-agent-mode-sessions]
    copied 12 session record(s) + 12 workspace dir(s)
    scheduled-tasks.json: old account has 0 tasks -> destination left untouched
    rpm/manifest.json: nothing to add -> untouched (keeps ['keep-me'])

TOTAL: 36 item(s) migrated, 0 left alone.
```

### 3. Applied it

Same command with `--apply`. Identical output. What the script does:

- Copies only `local_*` session records and `local_*` workspace directories.
- Treats `scheduled-tasks.json` and `rpm/` as **account-scoped settings, not
  history** — they get *merged* (union by task id / plugin name), never
  overwritten. Both were no-ops here: your old account had zero scheduled tasks
  registered, so your new account's files were left byte-for-byte untouched.
- Skips any name that already exists on the new side, so the pre-existing
  session couldn't be clobbered and re-running the script is safe.
- Rewrites `cwd` in migrated records that pointed into the old account directory.
- Rewrites `oauthAccount.accountUuid` / `organizationUuid` in each workspace's
  `.claude/.claude.json` to the new account.
- Preserves timestamps (`createdAt`, `lastActivityAt`, file mtimes), so your
  history sorts correctly instead of all landing under "today".
- **Copies, doesn't move.** The old account directory is still fully intact as a
  second safety net on top of the tarball.

### 4. Verified

`verify.py` checks the result independently of the migration code:

```bash
python3 verify.py
# 215/215 checks passed
```

Covering:

- All 12 code sessions and all 12 agent sessions present under the new account.
- `sessionId`, `cliSessionId`, `title`, `createdAt`, `lastActivityAt`,
  `isArchived`, `model`, `sessionType` preserved byte-identical on every record.
- The pre-existing new-account session untouched.
- `scheduled-tasks.json` still reads `belongsTo: "new"` in both stores.
- `rpm/manifest.json` still lists `["keep-me"]`.
- Zero occurrences of the old UUIDs or old account identity anywhere under the
  new account.
- All 12 workspaces present with both their `.claude.json` and `result.txt`.
- Every rewritten `cwd` resolves to a directory that actually exists on disk.
- The old tree still holds all 24 sessions.
- Every JSON file under the new account parses.

---

## Two judgement calls I made without asking

You weren't around, so I picked defaults and flagged them here.

**1. I stripped the old owner's name and email rather than inventing new ones.**

Every migrated agent record carried `"accountName": "Previous Owner"` and
`"emailAddress": "previous.owner@example.com"`, and every workspace
`.claude.json` carried `displayName: "Previous Owner"` / `organizationName:
"Previous Org"`. The restored backup contains no authoritative record of your
team account's display name or organization name, so I had two bad options —
leave your history labelled with the old account, or make up team values.

I removed the fields instead. This is safe because the schema treats them as
optional: all 12 of your Claude Code sessions and the session already on the new
account have never had them. The app repopulates them from your live login the
first time it writes to each session. The UUIDs, which *are* authoritative
(they're the directory names), were rewritten properly.

**Worth a glance from you:** "Previous Owner / Previous Org / previous.owner@example.com"
is oddly impersonal for a personal account. If that doesn't look like how your
old personal account was named, tell me before you install this — it would
suggest the backup contains a different account's data than we assumed, and
that's worth sorting out first.

**2. I did not touch your live Claude installation.**

I could have written straight into `~/Library/Application Support/Claude`, but I
deliberately didn't. Writing session files underneath a running Electron app
risks the app overwriting them from its in-memory state, or worse, half-writing
during a flush. The install step below takes about thirty seconds and is much
safer done with the app closed. The commands are ready to paste.

---

## Installing it into the live app

**Quit Claude completely first** (Cmd-Q, not just closing the window — check that
it's gone from the Dock).

```bash
# 1. Back up your live store first.
cd ~/Library/Application\ Support/Claude
tar -czf ~/Desktop/claude-sessions-live-backup.tar.gz \
    claude-code-sessions local-agent-mode-sessions

# 2. Copy the migrated new-account trees in.
SRC=/Users/chenhouren/Projects/claude-github-devex/migrate-claude-sessions-workspace/fixtures/eval-1-without
DST=~/Library/Application\ Support/Claude
NEW=cccccccc-3333-4333-8333-cccccccccccc/dddddddd-4444-4444-8444-dddddddddddd

rsync -av --ignore-existing \
  "$SRC/claude-code-sessions/$NEW/"  "$DST/claude-code-sessions/$NEW/"
rsync -av --ignore-existing \
  "$SRC/local-agent-mode-sessions/$NEW/" "$DST/local-agent-mode-sessions/$NEW/"
```

`--ignore-existing` is the important flag: it guarantees nothing already in your
live store gets overwritten, including your real `scheduled-tasks.json` and
`rpm/manifest.json`.

```bash
# 3. Re-point the two workspace paths at their final home.
cd "$DST/local-agent-mode-sessions/$NEW"
sed -i '' "s|$SRC/local-agent-mode-sessions/|$DST/local-agent-mode-sessions/|g" \
    local_agent001-*.json local_agent002-*.json
```

Step 3 is only needed because those two `cwd` values are absolute — they
currently point at the restore folder. If you'd rather not hand-edit, just
re-run the migration script with `--store-root` set to your live Claude
directory; it produces the same result.

Then reopen Claude. Your 12 code sessions and 12 agent sessions should be in the
list alongside the one that was already there.

**Before you delete anything:** confirm the history looks right in the app, then
keep `pre-migration-backup-eval-1-without.tar.gz` and the restore folder around
for a week or so. The old account directory inside the restore is still complete,
so if something looks off, nothing is unrecoverable.

---

## Files in this folder

| File | What it is |
|---|---|
| `pre-migration-backup-eval-1-without.tar.gz` | Snapshot of the restored store before any changes |
| `migrate_sessions.py` | The migration tool — re-runnable, dry-run by default, takes any store root |
| `verify.py` | Independent 215-check verification |
| `dry-run.log`, `apply.log`, `verify.log` | Output from each run |
