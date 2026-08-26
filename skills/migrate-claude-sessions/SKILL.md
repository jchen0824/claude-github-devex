---
name: migrate-claude-sessions
description: "Migrate local Claude desktop app session history from one account or organization to another on macOS — after switching from a personal account to a team/work account, joining an org, or consolidating two accounts on the same Mac. Use this skill whenever a user says their old sessions, chats, or conversation history disappeared, vanished, or are missing after signing into a different Claude account, whenever they ask to move/transfer/merge/recover session history between accounts, and whenever they ask why the session list is empty on a new account even though the old work is 'still on my machine'. Also use it when someone asks how Claude stores sessions locally or wants to inventory which accounts have session history on their Mac, even if they never use the word 'migrate'."
---

# Migrating Claude Sessions Between Accounts

Someone switches their Claude desktop app from a personal account to their company team account, opens it up, and their entire session history is gone. It looks like data loss. It isn't — the sessions are still on disk, just filed under the previous account.

This skill covers finding them and moving them.

## The mental model

The desktop app partitions local session history by **directory path**:

```
~/Library/Application Support/Claude/<store>/<accountUuid>/<organizationUuid>/
```

There are two stores, both using that same layout:

| Store | Holds | Contents |
|---|---|---|
| `claude-code-sessions/` | Claude Code sessions | `local_<uuid>.json` records |
| `local-agent-mode-sessions/` | Agent-mode / Cowork sessions | `local_<uuid>.json` records **+** a `local_<uuid>/` working directory each |

Two consequences follow, and most of the work comes from them:

**Nothing is server-side.** The app doesn't query an API to decide which sessions you may see; it lists the directory for the account you're signed into. So migration is a file copy, and it works entirely offline.

**Transcripts are not account-scoped.** The actual conversation content lives in `~/.claude/projects/<slug>/<cliSessionId>.jsonl`, which has no account partitioning at all. Every account on the machine can already read it. Never copy transcripts — you'd double the disk usage to no effect. Each session record points at its transcript through its `cliSessionId` field.

So what you're migrating is the *index*, not the content.

## Before you start

Confirm you're on macOS. This skill's paths and verification steps were developed and tested there; Windows and Linux layouts differ and aren't covered.

Then confirm you're looking at the tree the *running app* reads. When someone restores a store from Time Machine or copies one off an old machine, it is easy to migrate that copy flawlessly and change nothing the user can see — the app never opens it. The `inventory` and `migrate` subcommands warn when the signed-in account owns no bucket in the tree you gave them, which is the tell. If that fires, the migration still has to finish by landing in `~/Library/Application Support/Claude`, and the live bucket UUIDs have to be re-checked there rather than assumed to match the backup's.

## Workflow

### 1. Take inventory

Run the bundled script — it enumerates every bucket, counts sessions, dates them, and works out who owns each one:

```bash
python3 scripts/claude_session_migrate.py inventory
```

Owner identification is worth understanding, because it's the one place the two stores differ. Agent-mode records carry `accountName` and `emailAddress` inline. Claude Code records carry **no identity whatsoever** — so the script resolves those from the sibling store, or from the `oauthAccount` blob inside a session's sandbox home (`local_<uuid>/.claude/.claude.json`). Without that cross-referencing you get a table full of `unknown`, which tells the user nothing.

The row marked `*` is the currently signed-in account, read from `~/.claude.json`, and is almost always the migration target.

### 2. Agree on scope before touching anything

Show the user the inventory table and settle three questions. They matter enough to ask rather than assume:

- **Which source account?** There are often more than two buckets — old personal accounts, a previous employer, a shared machine. Emails may belong to *different people*, which the user needs to see before you merge anyone's history into their work account.
- **Include recurring scheduled runs?** A single daily scheduled task can generate a hundred near-identical session records that bury the real ones. The script excludes them by default (`--include-scheduled` to keep them).
- **Copy or move?** Default to copy. The old account is no longer signed in, so leaving its records costs nothing but keeps the migration trivially reversible. If you do move, pass `--manifest <path>`: a move empties the source, so without a record of what was migrated there is nothing left to verify the target against.

### 3. Back up

```bash
python3 scripts/claude_session_migrate.py backup
```

Writes a timestamped `.tar.gz` of both stores to the user's home directory — outside the app's own tree, so the app never scans it.

### 4. Migrate

```bash
python3 scripts/claude_session_migrate.py migrate \
  --source <oldAccount>/<oldOrg> --target <newAccount>/<newOrg> --dry-run
```

Read the dry-run counts back to the user, then re-run without `--dry-run`.

The script handles four things that are easy to miss by hand:

- **Config files are excluded.** `scheduled-tasks.json`, `rpm/`, `cowork_settings.json` and friends sit in the same directory as sessions and share a filename across every bucket. Copy them and you overwrite the target account's own settings with the source account's.
- **Identity fields are rewritten.** Agent-mode records embed `accountName` and `emailAddress`. Untouched, migrated sessions display the previous owner's name. The new values come from `~/.claude.json`; if the account's `displayName` is `null`, `null` is the correct value to write, because that's exactly what a natively-created session records.
- **Paths are repointed.** An agent-mode `cwd` often points inside its *own* bucket. Migrate the record without rewriting it and the session silently keeps reading and writing files in the old account's tree. VM-style paths (`/sessions/<name>`) and ordinary paths like `~/Desktop` are left alone.
- **Timestamps are preserved.** `cp -p` semantics throughout, so the app's session list stays in chronological order instead of showing everything as migrated-today.

If the tree you're working in is *not* where it will finally live — a restored backup you'll copy into place afterwards — pass `--final-root "$HOME/Library/Application Support/Claude"`. Rewriting only the account/org fragment leaves stored paths rooted in the backup folder, and those sessions break the moment the tree lands somewhere real. `verify` flags this if you forget — pass it the same `--final-root` so it validates against the destination rather than the staging area.

### 5. Verify

```bash
python3 scripts/claude_session_migrate.py verify --source <old> --target <new>
```

Checks record counts, JSON validity, that no record still references the source bucket, that every local `cwd` resolves, and — if you copied — that the source is untouched.

### 6. Report the caveats

Two things belong in the report because the user will otherwise hit them as surprises:

- **Some sessions will have no transcript.** Transcript retention prunes `~/.claude/projects` on its own schedule, so older sessions often lost their `.jsonl` before the migration ever happened. Those cards appear in the list but won't resume. Say the number. It is not something the migration caused, and the honest framing matters — the gaps were pre-existing.
- **Migrated agent-mode working directories keep the old `oauthAccount`** in their sandbox `.claude/.claude.json`. This is per-session state, and rewriting it means inventing billing and subscription fields for the new account. Leaving it is the defensible default; offer to rewrite the identity fields if the user wants.

### 7. Tell them to restart the app

Don't let this one fall off the end. The session list is a directory scan cached in memory at launch, so until the app restarts the user sees exactly what they saw before — an empty list — and reasonably concludes the migration failed. Every file can be in the right place and the job still reads as botched.

So the last thing you say is the restart, not a summary. Two details go with it: if you're running inside the desktop app, restarting ends the current session, so warn before they lose their place. And if the live-tree warning fired in step 1, restarting alone won't help — the files have to reach the live tree first.

## Things that bite

**`Application Support` has a space in it.** An unquoted `$VAR` in a shell loop splits it into `/Users/x/Library/Application` and `Support/Claude/...`, and you get a cascade of "No such file or directory" halfway through a migration. Quote every expansion, or work in Python.

**Don't infer identity from the directory name.** Account and org UUIDs are opaque. The same org UUID legitimately appears under several accounts (a user who belonged to that org from two accounts), and the same account appears under several orgs. Read the identity out of the records.

**Not every directory under a store is an account.** `skills-plugin` and similar sit alongside the UUID directories. Filter to UUID-shaped names or the inventory fills with phantom accounts.

**Working on a store from a backup or another machine?** Pass `--root <path>` or set `CLAUDE_APP_SUPPORT_DIR`. Every subcommand honors it — and pair it with `--final-root` on `migrate` so stored paths point at the destination rather than the staging area.

**The target account's UUID in a backup is not necessarily the live one.** A restored store's "new account" bucket may predate the account the user is signed into now. Read the live UUIDs from `~/.claude.json` and build the target bucket from those rather than reusing whatever the backup happened to contain.

## Script reference

`scripts/claude_session_migrate.py` — one CLI, four subcommands:

| Subcommand | Purpose |
|---|---|
| `inventory` | Enumerate buckets with counts, date spans, owners. `--json` for machine-readable, `--all` to include empties. |
| `backup` | Tar both stores. `--dest` to choose the path. |
| `migrate` | Copy or move sessions. `--dry-run`, `--include-scheduled`, `--move`, `--stores`, `--target-email`, `--target-name`, `--final-root`, `--manifest`. |
| `verify` | Post-migration checks. Exits non-zero if anything failed. `--include-scheduled`, `--final-root`, and `--manifest` should match the flags you passed to `migrate`, since each one changes what a correct result looks like. |

Bucket arguments accept `account/org`, or a bare `account` when that account has exactly one org. A bare target resolves its org once across both stores, so the two can't disagree and strand agent-mode records under an org the account doesn't use.
