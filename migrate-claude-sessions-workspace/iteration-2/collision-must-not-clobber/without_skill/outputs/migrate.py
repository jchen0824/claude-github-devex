#!/usr/bin/env python3
"""Migrate Claude session records from one account bucket to another.

Guarantees:
  * Never overwrites: every destination path is checked before writing.
  * Never deletes: the source bucket is left byte-identical.
  * Only touches the two named buckets; other accounts are not read or written.
"""
import json, shutil, sys
from pathlib import Path

STORE = Path("/Users/chenhouren/Projects/claude-github-devex/migrate-claude-sessions-workspace/fixtures/eval-3-without")
SRC_ACCT, SRC_ORG = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa", "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"
DST_ACCT, DST_ORG = "cccccccc-3333-4333-8333-cccccccccccc", "dddddddd-4444-4444-8444-dddddddddddd"
BUCKETS = ["claude-code-sessions", "local-agent-mode-sessions"]

APPLY = "--apply" in sys.argv
log = []


def note(kind, msg):
    log.append((kind, msg))
    print(f"[{kind:8}] {msg}")


def is_session_record(p: Path):
    """A session record is a top-level .json whose object carries a sessionId.
    This structurally excludes config files (scheduled-tasks.json etc.)."""
    if p.suffix != ".json" or not p.is_file():
        return None
    try:
        d = json.loads(p.read_text())
    except Exception:
        return None
    return d if isinstance(d, dict) and "sessionId" in d else None


def retarget(rec, src_dir: Path, dst_dir: Path):
    """Rewrite identity + any cwd that points into the source bucket."""
    changes = []
    for field in ("accountName", "emailAddress"):
        if field in rec:
            rec.pop(field)
            changes.append(f"dropped stale {field}")
    cwd = rec.get("cwd")
    if isinstance(cwd, str) and cwd.startswith(str(src_dir)):
        rec["cwd"] = str(dst_dir) + cwd[len(str(src_dir)):]
        changes.append("repointed cwd into new bucket")
    return changes


def fix_claude_json(p: Path):
    d = json.loads(p.read_text())
    oa = d.get("oauthAccount")
    if not isinstance(oa, dict):
        return False
    oa["accountUuid"], oa["organizationUuid"] = DST_ACCT, DST_ORG
    for k in ("emailAddress", "displayName", "organizationName"):
        oa.pop(k, None)
    if APPLY:
        p.write_text(json.dumps(d, indent=2))
    return True


def copy_tree_no_clobber(src: Path, dst: Path):
    """Copy src tree into dst, skipping any file that already exists."""
    copied, skipped = [], []
    for s in sorted(src.rglob("*")):
        rel = s.relative_to(src)
        d = dst / rel
        if s.is_dir():
            if APPLY:
                d.mkdir(parents=True, exist_ok=True)
            continue
        if d.exists():
            skipped.append(str(rel))
            continue
        if APPLY:
            d.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(s, d)
        copied.append(str(rel))
    return copied, skipped


stats = dict(migrated=0, collisions=0, scheduled_skipped=0, config_skipped=0, wd_files=0)

for bucket in BUCKETS:
    src_dir = STORE / bucket / SRC_ACCT / SRC_ORG
    dst_dir = STORE / bucket / DST_ACCT / DST_ORG
    if not src_dir.is_dir():
        note("SKIP", f"{bucket}: no source bucket")
        continue
    note("BUCKET", f"{bucket}")
    if APPLY:
        dst_dir.mkdir(parents=True, exist_ok=True)

    for entry in sorted(src_dir.iterdir()):
        if entry.is_dir():
            continue  # session working dirs are handled with their record
        rec = is_session_record(entry)
        if rec is None:
            stats["config_skipped"] += 1
            note("CONFIG", f"{entry.name}: not a session record -> left alone "
                           f"(target keeps its own copy)")
            continue
        if rec.get("sessionType") == "scheduled":
            stats["scheduled_skipped"] += 1
            note("CRON", f"{entry.name}: sessionType=scheduled ({rec.get('title')!r}) "
                         f"-> excluded, left in source")
            continue

        dest = dst_dir / entry.name
        if dest.exists():
            stats["collisions"] += 1
            note("COLLIDE", f"{entry.name}: ALREADY EXISTS on the new account "
                            f"-> target version kept, source NOT copied")
            continue

        changes = retarget(rec, src_dir, dst_dir)
        if APPLY:
            dest.write_text(json.dumps(rec, indent=2))
            shutil.copystat(entry, dest)
        stats["migrated"] += 1
        note("MIGRATE", f"{entry.name}: {rec.get('title')!r}"
                        + (f"  [{'; '.join(changes)}]" if changes else ""))

        # bring along the session's working directory, if it has one
        wd_src = src_dir / rec["sessionId"]
        if wd_src.is_dir():
            wd_dst = dst_dir / rec["sessionId"]
            copied, skipped = copy_tree_no_clobber(wd_src, wd_dst)
            stats["wd_files"] += len(copied)
            note("WORKDIR", f"{rec['sessionId']}/: {len(copied)} file(s) copied"
                            + (f", {len(skipped)} pre-existing left alone" if skipped else ""))
            cj = wd_dst / ".claude" / ".claude.json"
            if APPLY and cj.exists() and fix_claude_json(cj):
                note("IDENTITY", f"{rec['sessionId']}/.claude/.claude.json -> new account UUIDs")
            elif not APPLY and (wd_src / ".claude" / ".claude.json").exists():
                note("IDENTITY", f"{rec['sessionId']}/.claude/.claude.json would be rewritten")

print()
print("MODE:", "APPLY" if APPLY else "DRY RUN")
print(json.dumps(stats, indent=2))
