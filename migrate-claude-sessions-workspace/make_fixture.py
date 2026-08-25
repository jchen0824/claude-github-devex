#!/usr/bin/env python3
"""Build a synthetic Claude session store for testing the migration skill.

Mirrors the real layout, including the parts that are easy to get wrong:
config files that collide by name across buckets, agent-mode records that
embed identity, recurring scheduled runs mixed in with real sessions, and a
cwd that points back into the source bucket.
"""
import json, os, shutil, sys, time
from pathlib import Path

OLD_ACCT, OLD_ORG = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa", "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"
NEW_ACCT, NEW_ORG = "cccccccc-3333-4333-8333-cccccccccccc", "dddddddd-4444-4444-8444-dddddddddddd"
OLD_EMAIL, OLD_NAME = "previous.owner@example.com", "Previous Owner"
NEW_EMAIL, NEW_NAME = "new.owner@example.com", "New Owner"

DAY = 86_400_000


def write(path: Path, data, mtime_days_ago: int):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))
    ts = time.time() - mtime_days_ago * 86_400
    os.utime(path, (ts, ts))


def build(root: Path):
    if root.exists():
        shutil.rmtree(root)
    now = int(time.time() * 1000)

    code_old = root / "claude-code-sessions" / OLD_ACCT / OLD_ORG
    code_new = root / "claude-code-sessions" / NEW_ACCT / NEW_ORG
    agent_old = root / "local-agent-mode-sessions" / OLD_ACCT / OLD_ORG
    agent_new = root / "local-agent-mode-sessions" / NEW_ACCT / NEW_ORG

    # --- Claude Code sessions: no embedded identity, pure path scoping ---
    for i in range(12):
        sid = f"local_code{i:04d}-0000-4000-8000-00000000{i:04d}"
        write(code_old / f"{sid}.json", {
            "sessionId": sid,
            "cliSessionId": f"cli{i:05d}-0000-4000-8000-00000000{i:04d}",
            "title": f"Old account session {i}",
            "cwd": f"/Users/example/Projects/repo-{i}",
            "createdAt": now - (40 - i) * DAY,
            "lastActivityAt": now - (30 - i) * DAY,
            "isArchived": False,
            "model": "claude-opus-5",
        }, mtime_days_ago=30 - i)

    write(code_new / "local_existing-0000-4000-8000-000000000001.json", {
        "sessionId": "local_existing-0000-4000-8000-000000000001",
        "cliSessionId": "cli99999-0000-4000-8000-000000000099",
        "title": "Session already on the new account",
        "cwd": "/Users/example/Projects/new",
        "createdAt": now - DAY, "lastActivityAt": now, "isArchived": False,
    }, mtime_days_ago=0)

    # Config that shares a filename across every bucket — must not be copied over.
    for bucket, marker in ((code_old, "old"), (code_new, "new"), (agent_old, "old"), (agent_new, "new")):
        write(bucket / "scheduled-tasks.json", {"tasks": [], "belongsTo": marker}, 5)
    (agent_old / "rpm").mkdir(parents=True, exist_ok=True)
    (agent_old / "rpm" / "manifest.json").write_text('{"plugins":[]}')
    (agent_new / "rpm").mkdir(parents=True, exist_ok=True)
    (agent_new / "rpm" / "manifest.json").write_text('{"plugins":["keep-me"]}')

    # --- Agent-mode sessions: embed identity, own a working directory ---
    def agent_record(sid, title, days, scheduled, cwd):
        rec = {
            "sessionId": sid, "cliSessionId": f"cli-{sid}",
            "accountName": OLD_NAME, "emailAddress": OLD_EMAIL,
            "title": title, "cwd": cwd,
            "createdAt": now - (days + 5) * DAY, "lastActivityAt": now - days * DAY,
            "isArchived": False, "model": "claude-opus-5",
        }
        if scheduled:
            rec["sessionType"] = "scheduled"
        write(agent_old / f"{sid}.json", rec, days)
        wd = agent_old / sid
        (wd / "outputs").mkdir(parents=True, exist_ok=True)
        (wd / "outputs" / "result.txt").write_text(f"output of {title}\n")
        (wd / ".claude").mkdir(parents=True, exist_ok=True)
        (wd / ".claude" / ".claude.json").write_text(json.dumps({
            "oauthAccount": {"accountUuid": OLD_ACCT, "organizationUuid": OLD_ORG,
                             "emailAddress": OLD_EMAIL, "displayName": OLD_NAME,
                             "organizationName": "Previous Org"}}, indent=2))

    # Four real sessions; two keep a cwd inside their own bucket (needs repointing).
    inside = str(agent_old)
    agent_record("local_agent001-0000-4000-8000-000000000001", "Real agent session A", 20, False,
                 f"{inside}/local_agent001-0000-4000-8000-000000000001/outputs")
    agent_record("local_agent002-0000-4000-8000-000000000002", "Real agent session B", 15, False,
                 f"{inside}/local_agent002-0000-4000-8000-000000000002/outputs")
    agent_record("local_agent003-0000-4000-8000-000000000003", "Real agent session C", 10, False,
                 "/sessions/vm-style-path")
    agent_record("local_agent004-0000-4000-8000-000000000004", "Real agent session D", 5, False,
                 "/Users/example/Desktop")
    # Recurring cron artifacts — excluded from migration by default.
    for i in range(8):
        agent_record(f"local_sched{i:03d}-0000-4000-8000-0000000{i:05d}",
                     "Tidy downloads daily", 8 - i, True, "/Users/example/Downloads")

    print(f"fixture built at {root}")
    print(f"  source bucket: {OLD_ACCT}/{OLD_ORG}  ({OLD_EMAIL})")
    print(f"  target bucket: {NEW_ACCT}/{NEW_ORG}  ({NEW_EMAIL})")




# ---------------------------------------------------------------------------
# Harder variant: the traps that a naive approach actually falls into.
# ---------------------------------------------------------------------------
ACC_B = "eeeeeeee-5555-4555-8555-eeeeeeeeeeee"      # different person, SAME org as the source
OTHER_EMAIL, OTHER_NAME = "other.person@example.com", "Other Person"
COLLIDE = "local_code0003-0000-4000-8000-000000000003"


def build_hard(root: Path):
    """Adds, on top of the base fixture:

    - a second account sharing the source's org UUID, owned by someone else
    - a non-UUID directory (skills-plugin) sitting among the account dirs
    - a record name that exists in BOTH source and target with different content
    """
    build(root)
    now = int(time.time() * 1000)

    # A second account under the SAME org UUID. Guessing the source from the
    # directory name alone cannot distinguish these two.
    other = root / "claude-code-sessions" / ACC_B / OLD_ORG
    for i in range(5):
        sid = f"local_other{i:04d}-0000-4000-8000-11111111{i:04d}"
        write(other / f"{sid}.json", {
            "sessionId": sid, "cliSessionId": f"cliother{i:04d}",
            "title": f"Other person's session {i}",
            "cwd": "/Users/other/Projects/theirs",
            "createdAt": now - (20 - i) * DAY, "lastActivityAt": now - (18 - i) * DAY,
            "isArchived": False,
        }, mtime_days_ago=18 - i)
    wd = other / f"local_other0000-0000-4000-8000-111111110000"
    (wd / ".claude").mkdir(parents=True, exist_ok=True)
    (wd / ".claude" / ".claude.json").write_text(json.dumps({
        "oauthAccount": {"accountUuid": ACC_B, "organizationUuid": OLD_ORG,
                         "emailAddress": OTHER_EMAIL, "displayName": OTHER_NAME,
                         "organizationName": "Shared Org"}}, indent=2))

    # Not an account — a naive glob over the store treats this as one.
    for store in ("claude-code-sessions", "local-agent-mode-sessions"):
        junk = root / store / "skills-plugin" / OLD_ORG
        junk.mkdir(parents=True, exist_ok=True)
        (junk / "cache.json").write_text('{"plugins":[]}')

    # Same record name in source and target, different content. Copying blindly
    # destroys the target's version.
    tgt = root / "claude-code-sessions" / NEW_ACCT / NEW_ORG
    write(tgt / f"{COLLIDE}.json", {
        "sessionId": COLLIDE, "cliSessionId": "cli-target-owned",
        "title": "TARGET VERSION - MUST SURVIVE",
        "cwd": "/Users/example/Projects/target-owned",
        "createdAt": now - DAY, "lastActivityAt": now, "isArchived": False,
    }, mtime_days_ago=0)

    print(f"  hard variant: +{ACC_B[:8]} ({OTHER_EMAIL}) sharing org {OLD_ORG[:8]}")
    print(f"  hard variant: +skills-plugin non-UUID dir, +{COLLIDE[:18]} name collision")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--hard"]
    target = Path(args[0] if args else "/tmp/claude-session-fixture").expanduser()
    (build_hard if "--hard" in sys.argv else build)(target)
