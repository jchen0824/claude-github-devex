#!/usr/bin/env python3
"""Re-home Claude desktop sessions from one account/org bucket to another.

The desktop app scopes local session history by account and organization:

    <store>/claude-code-sessions/<accountUuid>/<organizationUuid>/<sessionId>.json
    <store>/local-agent-mode-sessions/<accountUuid>/<organizationUuid>/<sessionId>.json

Switching accounts does not delete anything -- the app simply stops looking in
the old bucket. This script copies session records (and, for agent-mode, their
working directories) from the old bucket into the new one, rewriting the bits
that carry the old identity or point back at the old bucket.

Design rules:
  * Non-destructive. The source bucket is never modified or removed.
  * Never overwrite anything already in the destination.
  * Only session records move. Bucket-level config that happens to share a
    filename across buckets (scheduled-tasks.json, rpm/, ...) is left alone,
    because the destination's copy is the live one.
  * Recurring scheduled-run artifacts are skipped by default; they are cron
    output, not conversation history. --include-scheduled overrides.
  * File mtimes are preserved so recency ordering survives the move.

Usage:
    python3 migrate_sessions.py --store <restored-store> [options]

Options:
    --store PATH            Store to read from and write into (required).
    --dest-root PATH        Root the migrated sessions will finally live under.
                            Used only to rewrite absolute cwd paths that point
                            into the old bucket. Defaults to --store.
    --from ACCT/ORG         Source bucket. Auto-detected if omitted.
    --to ACCT/ORG           Destination bucket. Auto-detected if omitted.
    --new-email / --new-name / --new-org-name
                            Identity to stamp on migrated agent-mode records.
                            Auto-detected from the destination bucket when
                            possible; otherwise stale values are removed rather
                            than carried over.
    --include-scheduled     Also migrate recurring scheduled-run sessions.
    --apply                 Actually write. Without it, this is a dry run.
    --manifest PATH         Write a JSON manifest of everything copied.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path

FAMILIES = ("claude-code-sessions", "local-agent-mode-sessions")

# Fields on an agent-mode session record that name the human who owned it.
RECORD_IDENTITY = {"emailAddress": "email", "accountName": "name"}
# Fields inside a working directory's .claude/.claude.json oauthAccount block.
OAUTH_IDENTITY = {
    "emailAddress": "email",
    "displayName": "name",
    "organizationName": "org_name",
}


# --------------------------------------------------------------------------
# discovery
# --------------------------------------------------------------------------

def is_session_record(path: Path) -> bool:
    """A session record is JSON with a sessionId. Config files are not."""
    if path.suffix != ".json":
        return False
    try:
        with path.open() as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return False
    return isinstance(data, dict) and "sessionId" in data


def load(path: Path) -> dict:
    with path.open() as fh:
        return json.load(fh)


def buckets(store: Path) -> dict[tuple[str, str], dict]:
    """Every <acct>/<org> bucket in the store, with a recency summary."""
    found: dict[tuple[str, str], dict] = {}
    for family in FAMILIES:
        base = store / family
        if not base.is_dir():
            continue
        for acct in sorted(p for p in base.iterdir() if p.is_dir()):
            for org in sorted(p for p in acct.iterdir() if p.is_dir()):
                key = (acct.name, org.name)
                info = found.setdefault(key, {"sessions": 0, "last_activity": 0})
                for f in org.glob("*.json"):
                    if not is_session_record(f):
                        continue
                    info["sessions"] += 1
                    rec = load(f)
                    info["last_activity"] = max(
                        info["last_activity"], int(rec.get("lastActivityAt") or 0)
                    )
    return found


def autodetect(found: dict[tuple[str, str], dict]) -> tuple[tuple[str, str], tuple[str, str]]:
    """Destination = bucket with the most recent activity (the account in use)."""
    if len(found) < 2:
        raise SystemExit(
            f"Expected at least two account buckets, found {len(found)}. "
            "Pass --from and --to explicitly."
        )
    ordered = sorted(found.items(), key=lambda kv: kv[1]["last_activity"], reverse=True)
    dest = ordered[0][0]
    src = max(
        (kv for kv in ordered[1:]), key=lambda kv: kv[1]["sessions"]
    )[0]
    return src, dest


def parse_bucket(text: str) -> tuple[str, str]:
    parts = [p for p in text.split("/") if p]
    if len(parts) != 2:
        raise SystemExit(f"--from/--to want ACCOUNT_UUID/ORG_UUID, got {text!r}")
    return parts[0], parts[1]


def detect_identity(store: Path, dest: tuple[str, str]) -> dict:
    """Learn the new owner's name/email from whatever already sits in the
    destination bucket. Returns only the keys it could actually establish."""
    ident: dict = {}
    for family in FAMILIES:
        base = store / family / dest[0] / dest[1]
        if not base.is_dir():
            continue
        for f in base.rglob("*.json"):
            try:
                data = load(f)
            except (json.JSONDecodeError, OSError):
                continue
            if not isinstance(data, dict):
                continue
            oauth = data.get("oauthAccount")
            if isinstance(oauth, dict):
                for key, slot in OAUTH_IDENTITY.items():
                    if oauth.get(key):
                        ident.setdefault(slot, oauth[key])
            for key, slot in RECORD_IDENTITY.items():
                if data.get(key):
                    ident.setdefault(slot, data[key])
    return ident


# --------------------------------------------------------------------------
# rewriting
# --------------------------------------------------------------------------

def make_cwd_rewriter(src: tuple[str, str], dest: tuple[str, str], dest_root: Path):
    """Rewrite any absolute path that points into the old bucket so it points
    at the same spot inside the new bucket under dest_root. Matches on the
    <family>/<acct>/<org> tail so it works regardless of where the store was
    restored from."""
    patterns = []
    for family in FAMILIES:
        old_tail = f"{family}/{src[0]}/{src[1]}"
        new_head = str(dest_root / family / dest[0] / dest[1])
        patterns.append((re.compile(r"^.*?" + re.escape(old_tail)), new_head))

    def rewrite(value):
        if not isinstance(value, str):
            return value, False
        for pattern, new_head in patterns:
            new_value, n = pattern.subn(new_head, value, count=1)
            if n:
                return new_value, True
        return value, False

    return rewrite


def apply_identity(block: dict, mapping: dict, ident: dict) -> list[str]:
    """Stamp the new identity onto a dict, or drop stale fields we can't
    replace. Carrying the previous owner's name forward is never correct."""
    changed = []
    for key, slot in mapping.items():
        if key not in block:
            continue
        if slot in ident:
            if block[key] != ident[slot]:
                block[key] = ident[slot]
                changed.append(key)
        else:
            block.pop(key)
            changed.append(f"-{key}")
    return changed


# --------------------------------------------------------------------------
# migration
# --------------------------------------------------------------------------

def copy_tree(src: Path, dst: Path):
    shutil.copytree(src, dst, symlinks=True, dirs_exist_ok=False)


def migrate(args) -> dict:
    store = Path(args.store).expanduser().resolve()
    dest_root = Path(args.dest_root).expanduser() if args.dest_root else store

    found = buckets(store)
    auto_src, auto_dest = autodetect(found)
    src = parse_bucket(args.from_bucket) if args.from_bucket else auto_src
    dest = parse_bucket(args.to_bucket) if args.to_bucket else auto_dest
    if src == dest:
        raise SystemExit("Source and destination bucket are the same; nothing to do.")

    ident = detect_identity(store, dest)
    for flag, slot in ((args.new_email, "email"), (args.new_name, "name"),
                       (args.new_org_name, "org_name")):
        if flag:
            ident[slot] = flag

    report = {
        "store": str(store),
        "dest_root": str(dest_root),
        "source_bucket": "/".join(src),
        "destination_bucket": "/".join(dest),
        "detected_identity": ident,
        "include_scheduled": args.include_scheduled,
        "applied": bool(args.apply),
        "migrated": [],
        "skipped": [],
    }

    rewrite_cwd = make_cwd_rewriter(src, dest, dest_root)

    for family in FAMILIES:
        src_dir = store / family / src[0] / src[1]
        dst_dir = store / family / dest[0] / dest[1]
        if not src_dir.is_dir():
            continue

        for record_path in sorted(src_dir.glob("*.json")):
            if not is_session_record(record_path):
                report["skipped"].append({
                    "family": family, "file": record_path.name,
                    "reason": "bucket config, not a session record",
                })
                continue

            record = load(record_path)
            sid = record["sessionId"]

            if record.get("sessionType") == "scheduled" and not args.include_scheduled:
                report["skipped"].append({
                    "family": family, "file": record_path.name, "sessionId": sid,
                    "title": record.get("title"),
                    "reason": "recurring scheduled-run artifact",
                })
                continue

            target_record = dst_dir / record_path.name
            workdir = src_dir / sid
            target_workdir = dst_dir / sid
            if target_record.exists() or (workdir.is_dir() and target_workdir.exists()):
                report["skipped"].append({
                    "family": family, "file": record_path.name, "sessionId": sid,
                    "reason": "already present in destination; left untouched",
                })
                continue

            changes = apply_identity(record, RECORD_IDENTITY, ident)
            new_cwd, moved = rewrite_cwd(record.get("cwd"))
            if moved:
                record["cwd"] = new_cwd
                changes.append("cwd")

            entry = {
                "family": family, "sessionId": sid,
                "title": record.get("title"),
                "record": str(target_record),
                "rewrote": changes,
                "workdir": None,
            }

            if args.apply:
                dst_dir.mkdir(parents=True, exist_ok=True)
                target_record.write_text(json.dumps(record, indent=2) + "\n")
                shutil.copystat(record_path, target_record)

            # Agent-mode sessions own a working directory next to the record.
            if workdir.is_dir():
                entry["workdir"] = str(target_workdir)
                if args.apply:
                    copy_tree(workdir, target_workdir)
                    # The CLI config snapshot inside pins the old account.
                    for cfg in target_workdir.rglob(".claude.json"):
                        try:
                            data = load(cfg)
                        except (json.JSONDecodeError, OSError):
                            continue
                        oauth = data.get("oauthAccount")
                        if not isinstance(oauth, dict):
                            continue
                        oauth["accountUuid"] = dest[0]
                        oauth["organizationUuid"] = dest[1]
                        apply_identity(oauth, OAUTH_IDENTITY, ident)
                        st = cfg.stat()
                        cfg.write_text(json.dumps(data, indent=2) + "\n")
                        os.utime(cfg, (st.st_atime, st.st_mtime))
                    shutil.copystat(workdir, target_workdir)

            report["migrated"].append(entry)

    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--store", required=True)
    ap.add_argument("--dest-root")
    ap.add_argument("--from", dest="from_bucket")
    ap.add_argument("--to", dest="to_bucket")
    ap.add_argument("--new-email")
    ap.add_argument("--new-name")
    ap.add_argument("--new-org-name")
    ap.add_argument("--include-scheduled", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--manifest")
    args = ap.parse_args(argv)

    report = migrate(args)

    mode = "APPLIED" if report["applied"] else "DRY RUN (nothing written)"
    print(f"== {mode} ==")
    print(f"store            {report['store']}")
    print(f"from bucket      {report['source_bucket']}")
    print(f"to   bucket      {report['destination_bucket']}")
    print(f"cwd rewrite root {report['dest_root']}")
    print(f"new identity     {report['detected_identity'] or '(unknown - stale fields dropped)'}")
    print()
    by_family: dict[str, int] = {}
    for e in report["migrated"]:
        by_family[e["family"]] = by_family.get(e["family"], 0) + 1
    for family in FAMILIES:
        print(f"  {family}: {by_family.get(family, 0)} session(s)")
    print(f"  skipped: {len(report['skipped'])}")
    print()
    for e in report["migrated"]:
        wd = "  +workdir" if e["workdir"] else ""
        rw = f"  [rewrote: {', '.join(e['rewrote'])}]" if e["rewrote"] else ""
        print(f"  MIGRATE {e['sessionId']}  {e['title']!r}{wd}{rw}")
    for s in report["skipped"]:
        print(f"  SKIP    {s.get('sessionId') or s['file']}  -- {s['reason']}")

    if args.manifest:
        Path(args.manifest).write_text(json.dumps(report, indent=2) + "\n")
        print(f"\nmanifest written to {args.manifest}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
