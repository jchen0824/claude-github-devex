#!/bin/bash
# Install the migrated sessions into the live Claude desktop store.
#
# Everything this touches was staged and verified in the restored backup at
#   /Users/chenhouren/Projects/claude-github-devex/migrate-claude-sessions-workspace/fixtures/eval-1-without
# This script only copies that staged set across. It never deletes, and it
# never overwrites a file the live store already has.
#
# QUIT THE CLAUDE DESKTOP APP FIRST -- it rewrites these files on exit.

set -euo pipefail

STAGED="/Users/chenhouren/Projects/claude-github-devex/migrate-claude-sessions-workspace/fixtures/eval-1-without"
LIVE="$HOME/Library/Application Support/Claude"

if pgrep -xq Claude; then
  echo "The Claude desktop app is still running. Quit it, then re-run this." >&2
  exit 1
fi

if [ ! -d "$LIVE" ]; then
  echo "No Claude store at $LIVE" >&2
  exit 1
fi

BACKUP="$LIVE.backup-$(date +%Y%m%d-%H%M%S)"
echo "Backing up the live store to:"
echo "  $BACKUP"
cp -Rp "$LIVE" "$BACKUP"

# The exact set staged by the migration -- 16 sessions and 4 working directories.
FILES=$(cat <<'LIST'
claude-code-sessions/cccccccc-3333-4333-8333-cccccccccccc/dddddddd-4444-4444-8444-dddddddddddd/local_code0000-0000-4000-8000-000000000000.json
claude-code-sessions/cccccccc-3333-4333-8333-cccccccccccc/dddddddd-4444-4444-8444-dddddddddddd/local_code0001-0000-4000-8000-000000000001.json
claude-code-sessions/cccccccc-3333-4333-8333-cccccccccccc/dddddddd-4444-4444-8444-dddddddddddd/local_code0002-0000-4000-8000-000000000002.json
claude-code-sessions/cccccccc-3333-4333-8333-cccccccccccc/dddddddd-4444-4444-8444-dddddddddddd/local_code0003-0000-4000-8000-000000000003.json
claude-code-sessions/cccccccc-3333-4333-8333-cccccccccccc/dddddddd-4444-4444-8444-dddddddddddd/local_code0004-0000-4000-8000-000000000004.json
claude-code-sessions/cccccccc-3333-4333-8333-cccccccccccc/dddddddd-4444-4444-8444-dddddddddddd/local_code0005-0000-4000-8000-000000000005.json
claude-code-sessions/cccccccc-3333-4333-8333-cccccccccccc/dddddddd-4444-4444-8444-dddddddddddd/local_code0006-0000-4000-8000-000000000006.json
claude-code-sessions/cccccccc-3333-4333-8333-cccccccccccc/dddddddd-4444-4444-8444-dddddddddddd/local_code0007-0000-4000-8000-000000000007.json
claude-code-sessions/cccccccc-3333-4333-8333-cccccccccccc/dddddddd-4444-4444-8444-dddddddddddd/local_code0008-0000-4000-8000-000000000008.json
claude-code-sessions/cccccccc-3333-4333-8333-cccccccccccc/dddddddd-4444-4444-8444-dddddddddddd/local_code0009-0000-4000-8000-000000000009.json
claude-code-sessions/cccccccc-3333-4333-8333-cccccccccccc/dddddddd-4444-4444-8444-dddddddddddd/local_code0010-0000-4000-8000-000000000010.json
claude-code-sessions/cccccccc-3333-4333-8333-cccccccccccc/dddddddd-4444-4444-8444-dddddddddddd/local_code0011-0000-4000-8000-000000000011.json
local-agent-mode-sessions/cccccccc-3333-4333-8333-cccccccccccc/dddddddd-4444-4444-8444-dddddddddddd/local_agent001-0000-4000-8000-000000000001.json
local-agent-mode-sessions/cccccccc-3333-4333-8333-cccccccccccc/dddddddd-4444-4444-8444-dddddddddddd/local_agent001-0000-4000-8000-000000000001/
local-agent-mode-sessions/cccccccc-3333-4333-8333-cccccccccccc/dddddddd-4444-4444-8444-dddddddddddd/local_agent002-0000-4000-8000-000000000002.json
local-agent-mode-sessions/cccccccc-3333-4333-8333-cccccccccccc/dddddddd-4444-4444-8444-dddddddddddd/local_agent002-0000-4000-8000-000000000002/
local-agent-mode-sessions/cccccccc-3333-4333-8333-cccccccccccc/dddddddd-4444-4444-8444-dddddddddddd/local_agent003-0000-4000-8000-000000000003.json
local-agent-mode-sessions/cccccccc-3333-4333-8333-cccccccccccc/dddddddd-4444-4444-8444-dddddddddddd/local_agent003-0000-4000-8000-000000000003/
local-agent-mode-sessions/cccccccc-3333-4333-8333-cccccccccccc/dddddddd-4444-4444-8444-dddddddddddd/local_agent004-0000-4000-8000-000000000004.json
local-agent-mode-sessions/cccccccc-3333-4333-8333-cccccccccccc/dddddddd-4444-4444-8444-dddddddddddd/local_agent004-0000-4000-8000-000000000004/
LIST
)

echo
echo "Copying into $LIVE"
printf '%s\n' "$FILES" | rsync -a -r --ignore-existing --files-from=- "$STAGED" "$LIVE"

echo
echo "Done. Restore point: $BACKUP"
echo "Reopen Claude and the old sessions should be in the sidebar."
