#!/bin/bash
# Land the recovered session history in the tree the running Claude app reads.
#
# The migration was already rehearsed inside the Time Machine restore at
# $RESTORED. The app never looks there, so nothing changed on screen. This
# script repeats it against the live app-support directory.
#
#   ./land-in-live-tree.sh            # dry run, writes nothing to the live tree
#   ./land-in-live-tree.sh --apply    # do it
#
# Override CLAUDE_APP_SUPPORT_DIR to point at a different tree (used to
# rehearse this script against a mock live tree).

set -euo pipefail

SKILL="/Users/chenhouren/Projects/claude-github-devex/skills/migrate-claude-sessions/scripts/claude_session_migrate.py"
RESTORED="/Users/chenhouren/Projects/claude-github-devex/migrate-claude-sessions-workspace/fixtures/eval-1-with"
LIVE="${CLAUDE_APP_SUPPORT_DIR:-$HOME/Library/Application Support/Claude}"

SRC_ACCOUNT="aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"   # previous.owner@example.com
SRC_ORG="bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"
TGT_ACCOUNT="b06f4a71-c3d9-41ad-b793-d68dba9217d3"   # jc@mindoralabs.io / MindoraLabs
TGT_ORG="484fd71a-32ee-4fe5-ad1f-2bb2ebf8c7fb"

STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_DEST="${BACKUP_DEST:-$HOME/claude-session-backup-$STAMP/session-stores.tar.gz}"
APPLY="${1:-}"

# Every path expansion below is quoted: "Application Support" has a space in it,
# and an unquoted $LIVE splits into two nonexistent paths halfway through.
echo "live tree : $LIVE"
echo "restored  : $RESTORED"
[ -d "$LIVE" ] || { echo "No Claude app support directory at $LIVE" >&2; exit 1; }
echo

echo "== 1. back up the live tree =================================="
python3 "$SKILL" --root "$LIVE" backup --dest "$BACKUP_DEST"
echo

echo "== 2. stage the old account's buckets into the live tree ======"
# Landing them under their ORIGINAL account UUID is inert: the app only lists
# the bucket of the account you are signed into, and that is not this one.
for store in claude-code-sessions local-agent-mode-sessions; do
  src="$RESTORED/$store/$SRC_ACCOUNT/$SRC_ORG"
  dst_parent="$LIVE/$store/$SRC_ACCOUNT"
  [ -d "$src" ] || continue
  if [ -e "$dst_parent/$SRC_ORG" ]; then
    echo "   $store: already staged, left alone"
    continue
  fi
  mkdir -p "$dst_parent"
  cp -Rp "$src" "$dst_parent/"          # -p keeps mtimes, so the list stays in order
  echo "   $store: staged -> $dst_parent/$SRC_ORG"
done
echo

echo "== 3. repoint absolute paths from the restore into the live tree"
# Agent-mode records embed an absolute cwd. In the restored copy those point at
# $RESTORED; once the files live under $LIVE they have to say so, or the
# sessions read and write inside a backup folder you may later delete.
python3 - "$LIVE" "$RESTORED" "$SRC_ACCOUNT" "$SRC_ORG" <<'PY'
import os, pathlib, sys
live, restored, account, org = sys.argv[1:5]
rewritten = 0
for store in ("claude-code-sessions", "local-agent-mode-sessions"):
    bucket = pathlib.Path(live) / store / account / org
    if not bucket.is_dir():
        continue
    for record in sorted(bucket.glob("local_*.json")):
        raw = record.read_text()
        if restored not in raw:
            continue
        stat = record.stat()
        record.write_text(raw.replace(restored, live))
        os.utime(record, (stat.st_atime, stat.st_mtime))   # preserve ordering
        rewritten += 1
print(f"   rewrote {rewritten} record(s)")
PY
echo

echo "== 4. inventory the live tree ================================="
# Confirm the target UUIDs here rather than trusting the ones in the backup.
python3 "$SKILL" --root "$LIVE" inventory
echo

echo "== 5. dry run ================================================="
python3 "$SKILL" --root "$LIVE" migrate \
  --source "$SRC_ACCOUNT/$SRC_ORG" --target "$TGT_ACCOUNT/$TGT_ORG" --dry-run
echo

if [ "$APPLY" != "--apply" ]; then
  echo "Dry run only. Re-run with --apply to write to the live tree."
  exit 0
fi

echo "== 6. migrate ================================================="
python3 "$SKILL" --root "$LIVE" migrate \
  --source "$SRC_ACCOUNT/$SRC_ORG" --target "$TGT_ACCOUNT/$TGT_ORG"
echo

echo "== 7. verify =================================================="
python3 "$SKILL" --root "$LIVE" verify \
  --source "$SRC_ACCOUNT/$SRC_ORG" --target "$TGT_ACCOUNT/$TGT_ORG"
echo

cat <<'EOF'
Now quit Claude completely (Cmd-Q) and reopen it.

The session list is a directory scan cached at launch, so until the app
restarts you will see exactly the empty list you saw before, and reasonably
conclude this failed. If you are reading this inside the Claude desktop app,
the restart ends this session.
EOF
