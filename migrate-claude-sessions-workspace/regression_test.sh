#!/bin/bash
# Regression suite for claude_session_migrate.py.
#
# There is no package.json here, so verification is a syntax check plus
# end-to-end runs against fixtures built by make_fixture.py. Every case below
# maps to a defect that was real at some point; each one failed before its fix.
#
#   usage: ./regression_test.sh        (exits non-zero if anything regresses)
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
SC="$HERE/../skills/migrate-claude-sessions/scripts/claude_session_migrate.py"
MK="$HERE/make_fixture.py"
S=aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa/bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb
D=cccccccc-3333-4333-8333-cccccccccccc/dddddddd-4444-4444-8444-dddddddddddd
LIVE="$HOME/Library/Application Support/Claude"
T="${TMPDIR:-/tmp}/claude-session-migrate-regression"; rm -rf "$T"; mkdir -p "$T"
fail=0
chk(){ if [ "$2" = "$3" ]; then echo "  PASS  $1"; else echo "  FAIL  $1 (got '$2', want '$3')"; fail=1; fi; }

python3 -m py_compile "$SC" 2>&1 && echo "  PASS  syntax" || { echo "  FAIL  syntax"; exit 1; }

# 1. base migration end-to-end
python3 "$MK" "$T/base" >/dev/null
out=$(CLAUDE_APP_SUPPORT_DIR="$T/base" python3 "$SC" migrate --source "$S" --target "$D" 2>/dev/null)
chk "base: 12 code copied" "$(echo "$out"|python3 -c 'import json,sys;print(json.load(sys.stdin)["results"][0]["copied"])')" "12"
CLAUDE_APP_SUPPORT_DIR="$T/base" python3 "$SC" verify --source "$S" --target "$D" >/dev/null 2>&1
chk "base: verify exits 0" "$?" "0"

# 2. verify must FAIL when nothing was migrated (Codex #3849102432)
python3 "$MK" "$T/empty" >/dev/null
CLAUDE_APP_SUPPORT_DIR="$T/empty" python3 "$SC" verify --source "$S" --target "$D" >/dev/null 2>&1
chk "empty target: verify exits nonzero" "$([ $? -ne 0 ] && echo yes || echo no)" "yes"

# 3. bare-account spec must not explode on a store the account is absent from (#3849102434)
python3 "$MK" "$T/bare" >/dev/null
rm -rf "$T/bare/local-agent-mode-sessions/aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
CLAUDE_APP_SUPPORT_DIR="$T/bare" python3 "$SC" migrate --source aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa --target "$D" >/dev/null 2>&1
chk "bare spec, store absent: exits 0" "$?" "0"

# 4. --move must not delete a source workdir whose dest dir already exists (#3849102439)
python3 "$MK" "$T/mv" >/dev/null
AG="$T/mv/local-agent-mode-sessions"
mkdir -p "$AG/cccccccc-3333-4333-8333-cccccccccccc/dddddddd-4444-4444-8444-dddddddddddd/local_agent001-0000-4000-8000-000000000001"
CLAUDE_APP_SUPPORT_DIR="$T/mv" python3 "$SC" migrate --source "$S" --target "$D" --stores local-agent-mode-sessions --move >/dev/null 2>&1
chk "move+dir collision: source workdir survives" \
  "$([ -d "$AG/aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa/bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb/local_agent001-0000-4000-8000-000000000001" ] && echo yes || echo no)" "yes"

# 5. --final-root: verify must ACCEPT the correctly-staged case (#3849828720)
python3 "$MK" "$T/fr" >/dev/null
CLAUDE_APP_SUPPORT_DIR="$T/fr" python3 "$SC" migrate --source "$S" --target "$D" --stores local-agent-mode-sessions --final-root "$LIVE" >/dev/null 2>&1
CLAUDE_APP_SUPPORT_DIR="$T/fr" python3 "$SC" verify --source "$S" --target "$D" --stores local-agent-mode-sessions --final-root "$LIVE" >/dev/null 2>&1
chk "final-root used: verify exits 0" "$?" "0"
# and REJECT the un-rewritten one when a final root was intended
python3 "$MK" "$T/fr2" >/dev/null
CLAUDE_APP_SUPPORT_DIR="$T/fr2" python3 "$SC" migrate --source "$S" --target "$D" --stores local-agent-mode-sessions >/dev/null 2>&1
CLAUDE_APP_SUPPORT_DIR="$T/fr2" python3 "$SC" verify --source "$S" --target "$D" --stores local-agent-mode-sessions --final-root "$LIVE" >/dev/null 2>&1
chk "final-root intended but not applied: verify nonzero" "$([ $? -ne 0 ] && echo yes || echo no)" "yes"

# 6. unreadable record must not traceback (#3849828726)
python3 "$MK" "$T/bad" >/dev/null
CLAUDE_APP_SUPPORT_DIR="$T/bad" python3 "$SC" migrate --source "$S" --target "$D" >/dev/null 2>&1
printf '\xff\xfe\x00bad' > "$T/bad/claude-code-sessions/cccccccc-3333-4333-8333-cccccccccccc/dddddddd-4444-4444-8444-dddddddddddd/local_corrupt.json"
err=$(CLAUDE_APP_SUPPORT_DIR="$T/bad" python3 "$SC" verify --source "$S" --target "$D" 2>&1)
chk "corrupt record: no traceback" "$(echo "$err"|grep -c Traceback)" "0"

# 7. live-tree check must not false-alarm on a config-only bucket (#3849102442)
python3 "$MK" "$T/lt" >/dev/null
ME=$(python3 -c "import json,pathlib;print((json.load(open(pathlib.Path.home()/'.claude.json'))['oauthAccount']['accountUuid']))")
MYORG=$(python3 -c "import json,pathlib;print((json.load(open(pathlib.Path.home()/'.claude.json'))['oauthAccount']['organizationUuid']))")
mkdir -p "$T/lt/claude-code-sessions/$ME/$MYORG"; echo '{}' > "$T/lt/claude-code-sessions/$ME/$MYORG/scheduled-tasks.json"
n=$(CLAUDE_APP_SUPPORT_DIR="$T/lt" python3 "$SC" inventory 2>/dev/null | grep -c "owns no bucket")
chk "config-only bucket: no false live-tree warning" "$n" "0"

echo; [ $fail -eq 0 ] && echo "ALL CHECKS PASS" || echo "SOME CHECKS FAILED"
exit $fail
