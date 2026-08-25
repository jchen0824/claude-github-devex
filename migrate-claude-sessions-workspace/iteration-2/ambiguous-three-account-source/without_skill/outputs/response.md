# Session migration: old personal account → work account

Done. 35 items (23 sessions plus their payload directories) moved from your old personal account onto your work account. Your colleague's data was not touched, and nothing that already belonged to the work account was overwritten.

---

## Which account was which

The store keys everything by `<kind>/<accountUuid>/<organizationUuid>/`. Three accounts were present. I identified them from the `oauthAccount` blocks in the per-session `.claude/.claude.json` files and from the session metadata:

| Account UUID | Org UUID | Identity | Role |
|---|---|---|---|
| `aaaaaaaa-1111-…` | `bbbbbbbb-2222-…` | previous.owner@example.com — "Previous Owner" / "Previous Org" | **Source** — your old personal account |
| `cccccccc-3333-…` | `dddddddd-4444-…` | no email on disk; holds "Session already on the new account", `scheduled-tasks.json` marked `belongsTo: "new"` | **Target** — your work account |
| `eeeeeeee-5555-…` | `bbbbbbbb-2222-…` | other.person@example.com — "Other Person" / "Shared Org" | **Colleague — left completely alone** |

Two calls I had to make without you, and why:

**Target identification.** The work account carries no email anywhere in the store, so I identified it by elimination and by positive markers: it is neither the old-personal account nor the colleague's, its `scheduled-tasks.json` is tagged `belongsTo: "new"`, and it already holds a session titled "Session already on the new account". That is unambiguous enough to proceed on.

**A shared organization UUID.** Your old account and your colleague's account sit under the *same* org UUID (`bbbbbbbb-2222-…`). Anything keyed by org alone is therefore shared between the two of you. I scoped every operation by the **account** UUID, never by org, and left the org-keyed `skills-plugin/bbbbbbbb-2222-…/cache.json` untouched in both trees. Migrating by org would have swept your colleague's five sessions along with yours.

---

## What moved

**23 sessions, plus 12 payload directories** (each containing `.claude/.claude.json` and `outputs/result.txt`):

- **11 Claude Code sessions** — "Old account session 0–11", minus #3 (see conflict below)
- **4 agent sessions** — "Real agent session A–D", with payloads
- **8 scheduled-run sessions** — "Tidy downloads daily" runs, with payloads

The work account now shows 13 Claude Code sessions and 12 agent-mode sessions, spanning 2026-07-26 through 2026-08-25.

## What deliberately did *not* move

**One ID collision — target version preserved.** `local_code0003-…` existed on *both* accounts as genuinely different sessions:

- old account: "Old account session 3", cwd `/Users/example/Projects/repo-3`
- work account: **"TARGET VERSION - MUST SURVIVE"**, cwd `/Users/example/Projects/target-owned`

Because the store keys sessions by ID within an account, both cannot coexist there. I kept the work account's version untouched and left your old copy where it was, at:

```
fixtures/eval-2-without/claude-code-sessions/aaaaaaaa-1111-…/bbbbbbbb-2222-…/local_code0003-0000-4000-8000-000000000003.json
```

Nothing was lost — it just did not migrate. If you want it on the work account too, it needs a fresh session ID (rename the file *and* rewrite the `sessionId` field inside to match). I did not do that unilaterally, because minting a synthetic ID for a record you may not care about is a bigger surprise than leaving one session in place.

**Account-level config files — not merged.** These are per-account settings, not history, and the target's own versions matter:

- `scheduled-tasks.json` (both kinds) — old account's had `tasks: []`, so there was nothing to migrate anyway. Copying it would have clobbered the target's `belongsTo: "new"` marker.
- `local-agent-mode-sessions/…/rpm/manifest.json` — the target's lists `["keep-me"]`; the old account's was empty. Copying would have silently dropped that plugin.
- `skills-plugin/bbbbbbbb-2222-…/cache.json` — org-keyed and therefore shared with your colleague. Out of bounds.

---

## Commands run

Backup and pre-state inventory:

```bash
STORE=…/fixtures/eval-2-without
OUT=…/without_skill/outputs
cd "$STORE"
find . -type f | sort | xargs shasum -a 256 > "$OUT/pre-migration-manifest.txt"   # 64 files
tar -czf "$OUT/backup-pre-migration.tar.gz" -C "$(dirname "$STORE")" "$(basename "$STORE")"
```

Copy phase — iterates the source account only, skips config files, and refuses to overwrite any existing target file:

```bash
SRC_ACC=aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa/bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb
DST_ACC=cccccccc-3333-4333-8333-cccccccccccc/dddddddd-4444-4444-8444-dddddddddddd
for KIND in claude-code-sessions local-agent-mode-sessions; do
  S="$STORE/$KIND/$SRC_ACC"; D="$STORE/$KIND/$DST_ACC"
  for item in "$S"/*; do
    base=$(basename "$item")
    case "$base" in scheduled-tasks.json|rpm) continue;; esac      # account config, target keeps its own
    [ -e "$D/$base" ] && { echo "CONFLICT $base — target preserved"; continue; }
    cp -a "$item" "$D/$base"
  done
done
```

Result: `35 COPIED`, `1 CONFLICT` (local_code0003), `3 SKIP-CFG`.

Verify every copy is byte-identical (`diff -r` per item), then complete the move by deleting only verified originals:

```bash
diff -r "$item" "$D/$base" >/dev/null || { echo "ABORT unverified"; exit 1; }
rm -rf "$item"
```

All 35 verified `OK`, `verify_exit=0`, then removed.

## Verification results

```
file count before / after ...................... 64 / 64
pre-migration content checksums now missing .... none (no content destroyed)
colleague tree (eeeeeeee-5555-…) ............... IDENTICAL — untouched
shared-org skills-plugin cache ................. IDENTICAL — untouched
target local_code0003 .......................... UNCHANGED ("TARGET VERSION - MUST SURVIVE")
target local_existing .......................... UNCHANGED
target scheduled-tasks.json (both kinds) ....... UNCHANGED
target rpm/manifest.json ....................... UNCHANGED ({"plugins":["keep-me"]})
```

The checksum comparison is the strong check: every content hash present before the migration is still present after it, so the move relocated data without altering a single byte.

---

## One thing to check when you next open Claude

I moved the files **as-is**, without rewriting the identity stamped inside them. 24 files now on your work account still contain `previous.owner@example.com` — the `emailAddress`/`accountName` fields on the 12 agent-mode session records, and the `oauthAccount` block in each session's `.claude/.claude.json`.

I left these alone deliberately. Ownership in this store is determined by the directory path, which is now correct. Rewriting the embedded identity would mean fabricating data: your work account's email, display name, and org name appear nowhere on disk, so I could only have changed the UUIDs and left the email mismatched — a record whose `accountUuid` and `emailAddress` disagree is worse than one that is honestly stale.

If the migrated sessions show up correctly under your work account, nothing more is needed. If they do not appear, or appear attributed to the old account, that stale metadata is the cause and it is a one-line fix — tell me your work account's email and display name and I will rewrite the 24 files consistently.

## Rollback

The pre-migration state is captured in full:

- `outputs/backup-pre-migration.tar.gz` — complete copy of the store as it was
- `outputs/pre-migration-manifest.txt` / `post-migration-manifest.txt` — SHA-256 of every file, before and after
- `outputs/migration-log.txt` — every copy, skip, conflict, and removal decision

To undo everything, delete the store directory and extract the tarball in its place.
