#!/usr/bin/env python3
import json, os, sys

ROOT = "/Users/chenhouren/Projects/claude-github-devex/migrate-claude-sessions-workspace/fixtures/eval-1-without"
OLD_A, OLD_O = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa", "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"
NEW_A, NEW_O = "cccccccc-3333-4333-8333-cccccccccccc", "dddddddd-4444-4444-8444-dddddddddddd"
STORES = ("claude-code-sessions", "local-agent-mode-sessions")

fails, checks = [], []
def check(name, ok, detail=""):
    checks.append((ok, name, detail))
    if not ok: fails.append(name)

def sessions(store, a, o):
    d = os.path.join(ROOT, store, a, o)
    if not os.path.isdir(d): return {}
    out = {}
    for n in os.listdir(d):
        if n.startswith("local_") and n.endswith(".json"):
            out[n] = json.load(open(os.path.join(d, n)))
    return out

# 1. every old session is present on the new account
for store in STORES:
    old, new = sessions(store, OLD_A, OLD_O), sessions(store, NEW_A, NEW_O)
    missing = sorted(set(old) - set(new))
    check(f"{store}: all {len(old)} old sessions present on new account", not missing, f"missing={missing}")
    for n, o in old.items():
        if n in new:
            for k in ("sessionId", "cliSessionId", "title", "createdAt", "lastActivityAt", "isArchived", "model", "sessionType"):
                if k in o:
                    check(f"{store}/{n}: {k} preserved", new[n].get(k) == o[k], f"{o[k]!r} -> {new[n].get(k)!r}")

# 2. the session that was already on the new account is untouched
pre = json.load(open(os.path.join(ROOT, "claude-code-sessions", NEW_A, NEW_O,
                                  "local_existing-0000-4000-8000-000000000001.json")))
check("pre-existing new-account session intact",
      pre.get("title") == "Session already on the new account" and pre.get("cliSessionId") == "cli99999-0000-4000-8000-000000000099",
      json.dumps(pre))

# 3. account-scoped settings on the new side were not clobbered
for store in STORES:
    p = os.path.join(ROOT, store, NEW_A, NEW_O, "scheduled-tasks.json")
    d = json.load(open(p))
    check(f"{store}: new scheduled-tasks.json still belongsTo=new", d.get("belongsTo") == "new", json.dumps(d))
m = json.load(open(os.path.join(ROOT, "local-agent-mode-sessions", NEW_A, NEW_O, "rpm", "manifest.json")))
check("new rpm/manifest.json still lists keep-me", m.get("plugins") == ["keep-me"], json.dumps(m))

# 4. no reference to the old account/org survives anywhere under the new account
stale = []
for store in STORES:
    base = os.path.join(ROOT, store, NEW_A, NEW_O)
    for dp, _, fns in os.walk(base):
        for fn in fns:
            fp = os.path.join(dp, fn)
            try: txt = open(fp, encoding="utf-8").read()
            except Exception: continue
            for needle in (OLD_A, OLD_O, "Previous Owner", "previous.owner@example.com", "Previous Org"):
                if needle in txt:
                    stale.append((os.path.relpath(fp, ROOT), needle))
check("no stale old-account identifiers under the new account", not stale, str(stale))

# 5. agent workspaces migrated with their contents, cwd re-pointed, oauthAccount updated
agent_new = os.path.join(ROOT, "local-agent-mode-sessions", NEW_A, NEW_O)
ws = sorted(d for d in os.listdir(agent_new) if d.startswith("local_") and os.path.isdir(os.path.join(agent_new, d)))
check("12 agent workspaces present on new account", len(ws) == 12, str(len(ws)))
for w in ws:
    cj = os.path.join(agent_new, w, ".claude", ".claude.json")
    rt = os.path.join(agent_new, w, "outputs", "result.txt")
    check(f"{w}: workspace files present", os.path.exists(cj) and os.path.exists(rt))
    acct = json.load(open(cj))["oauthAccount"]
    check(f"{w}: oauthAccount re-keyed",
          acct.get("accountUuid") == NEW_A and acct.get("organizationUuid") == NEW_O, json.dumps(acct))

for n, s in sessions("local-agent-mode-sessions", NEW_A, NEW_O).items():
    cwd = s.get("cwd", "")
    if "/local-agent-mode-sessions/" in cwd:
        check(f"{n}: cwd points at new account dir", f"/{NEW_A}/{NEW_O}/" in cwd, cwd)
        check(f"{n}: cwd exists on disk", os.path.isdir(cwd), cwd)

# 6. old tree still intact (nothing lost)
for store in STORES:
    check(f"{store}: old account tree still intact", len(sessions(store, OLD_A, OLD_O)) == 12)

# 7. every migrated file is valid JSON
bad = []
for store in STORES:
    for dp, _, fns in os.walk(os.path.join(ROOT, store, NEW_A, NEW_O)):
        for fn in fns:
            if fn.endswith(".json"):
                try: json.load(open(os.path.join(dp, fn)))
                except Exception as e: bad.append((fn, str(e)))
check("all JSON under the new account parses", not bad, str(bad))

for ok, name, detail in checks:
    if not ok:
        print(f"FAIL  {name}   {detail}")
print(f"\n{len(checks) - len(fails)}/{len(checks)} checks passed")
sys.exit(1 if fails else 0)
