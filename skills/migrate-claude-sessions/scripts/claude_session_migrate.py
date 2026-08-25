#!/usr/bin/env python3
"""Inventory and migrate Claude desktop app session stores between accounts.

The desktop app partitions local session history by directory path:

    <app-support>/<store>/<accountUuid>/<organizationUuid>/

Nothing about that partitioning is server-side, so moving history between
accounts is a file operation. This script does the mechanical parts that are
easy to get subtly wrong by hand: finding the buckets, identifying who owns
each one, copying only the session records (not the config files that collide
by name), rewriting the identity fields that agent-mode records embed, and
repointing paths that would otherwise write back into the source account.

Subcommands:
    inventory   Show every account/org bucket with counts, dates, and owner.
    migrate     Copy (or move) sessions from one bucket to another.
    verify      Re-check a completed migration.

Point --root at a different tree (or set CLAUDE_APP_SUPPORT_DIR) to work on a
store restored from a backup or copied from another machine.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

DEFAULT_ROOT = Path.home() / "Library" / "Application Support" / "Claude"

# Both stores use the same <account>/<org>/local_*.json layout. claude-code-sessions
# holds Claude Code session records; local-agent-mode-sessions holds agent-mode /
# Cowork sessions plus a per-session working directory.
STORES = ("claude-code-sessions", "local-agent-mode-sessions")

# Config that lives alongside sessions in the same directory. These share a
# filename across every bucket, so copying them would clobber the target's own
# settings with the source account's.
CONFIG_NAMES = {
    "scheduled-tasks.json",
    "cowork_settings.json",
    "remote-session-spaces.json",
    "rpm",
    "cowork_plugins",
    "remote_cowork_plugins",
    "debug",
}


# --------------------------------------------------------------------------
# discovery
# --------------------------------------------------------------------------

def resolve_root(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    env = os.environ.get("CLAUDE_APP_SUPPORT_DIR")
    if env:
        return Path(env).expanduser()
    return DEFAULT_ROOT


UUID_RE = __import__("re").compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def is_uuid_dir(path: Path) -> bool:
    """Stores also hold non-account directories (e.g. skills-plugin); skip those."""
    return path.is_dir() and bool(UUID_RE.match(path.name))


def read_json(path: Path):
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def is_session_record(path: Path) -> bool:
    return path.is_file() and path.name.startswith("local_") and path.suffix == ".json"


def session_records(bucket: Path) -> list[Path]:
    if not bucket.is_dir():
        return []
    return sorted(p for p in bucket.iterdir() if is_session_record(p))


def workdir_for(record: Path) -> Path:
    """Agent-mode sessions keep a sibling directory named after the record."""
    return record.parent / record.stem


def current_account() -> dict:
    """The account the CLI is signed into, used as the default migration target."""
    cfg = read_json(Path.home() / ".claude.json") or {}
    return cfg.get("oauthAccount") or {}


def identify_owner(bucket: Path) -> dict:
    """Work out whose account a bucket belongs to.

    Agent-mode records carry accountName/emailAddress directly. Claude Code
    records carry no identity at all, so fall back to the per-session sandbox
    home, which stores a full oauthAccount blob.
    """
    for record in session_records(bucket):
        data = read_json(record) or {}
        email = data.get("emailAddress")
        if email:
            return {"emailAddress": email, "accountName": data.get("accountName"),
                    "source": "session record"}

    for nested in bucket.glob("local_*/.claude/.claude.json"):
        oauth = (read_json(nested) or {}).get("oauthAccount") or {}
        if oauth.get("emailAddress"):
            return {"emailAddress": oauth["emailAddress"],
                    "accountName": oauth.get("displayName"),
                    "organizationName": oauth.get("organizationName"),
                    "source": "sandbox .claude.json"}
    return {}


def cross_store_owner(root: Path, account: str, org: str) -> dict:
    """Claude Code records embed no identity at all, so borrow it from the same
    account/org bucket in the other store, which does."""
    for store in STORES:
        found = identify_owner(root / store / account / org)
        if found:
            return dict(found, source=found.get("source", "") + f" (via {store})")
    return {}


def scan(root: Path) -> list[dict]:
    """Enumerate every <store>/<account>/<org> bucket under root."""
    buckets = []
    for store in STORES:
        store_dir = root / store
        if not store_dir.is_dir():
            continue
        for account_dir in sorted(p for p in store_dir.iterdir() if is_uuid_dir(p)):
            for org_dir in sorted(p for p in account_dir.iterdir() if is_uuid_dir(p)):
                records = session_records(org_dir)
                scheduled = sum(
                    1 for r in records
                    if (read_json(r) or {}).get("sessionType") == "scheduled"
                )
                stamps = [
                    (read_json(r) or {}).get("lastActivityAt")
                    for r in records
                ]
                stamps = [s for s in stamps if isinstance(s, (int, float))]
                buckets.append({
                    "store": store,
                    "account": account_dir.name,
                    "org": org_dir.name,
                    "path": str(org_dir),
                    "sessions": len(records),
                    "scheduled": scheduled,
                    "regular": len(records) - scheduled,
                    "workdirs": sum(1 for r in records if workdir_for(r).is_dir()),
                    "first": iso(min(stamps)) if stamps else None,
                    "last": iso(max(stamps)) if stamps else None,
                    "owner": identify_owner(org_dir) or cross_store_owner(root, account_dir.name, org_dir.name),
                })
    return buckets


def live_tree_check(root: Path, buckets: list[dict]) -> list[str]:
    """Warn when the scanned tree is not the one the running app reads.

    A store restored from a backup or copied off another machine migrates
    perfectly and changes nothing the user can see, because the app never looks
    at it. Catching that here is cheaper than catching it after a restart.
    """
    notes = []
    account = current_account()
    uuid = account.get("accountUuid")
    if not uuid:
        return ["Could not read the signed-in account from ~/.claude.json; "
                "confirm the migration target manually."]
    if uuid not in {b["account"] for b in buckets}:
        notes.append(
            f"The signed-in account ({account.get('emailAddress')}) owns no bucket in this tree. "
            "That is expected for a backup or a copy from another machine — but the running app "
            f"reads {DEFAULT_ROOT}, so migrating here will not change what the user sees. "
            "Finish by copying the target bucket into the live tree, re-checking its UUIDs with "
            "`inventory` rather than assuming they match."
        )
    if root.resolve() != DEFAULT_ROOT.resolve():
        notes.append(f"Working on {root}, not the default app support directory.")
    return notes


def iso(ms: float) -> str:
    return dt.datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d")


# --------------------------------------------------------------------------
# inventory
# --------------------------------------------------------------------------

def cmd_inventory(args) -> int:
    root = resolve_root(args.root)
    if not root.is_dir():
        print(f"No Claude app support directory at {root}", file=sys.stderr)
        return 1

    all_buckets = scan(root)
    # The live-tree check has to see every bucket. A freshly switched-to account
    # often owns a bucket holding only config and zero sessions; filtering that
    # out first makes the check report "owns no bucket here", which is exactly
    # the signal users are told to read as a restored or non-live tree.
    warnings = live_tree_check(root, all_buckets)
    buckets = all_buckets if args.all else [b for b in all_buckets if b["sessions"]]
    if args.json:
        print(json.dumps({"root": str(root), "current_account": current_account(),
                          "buckets": buckets, "warnings": warnings}, indent=2))
        return 0

    account = current_account()
    print(f"root: {root}")
    if account:
        print(f"signed in as: {account.get('emailAddress')} "
              f"(account {account.get('accountUuid','?')[:8]}…, "
              f"org {account.get('organizationName','?')})")
    if not buckets:
        print("\nNo session buckets found.")
        return 0

    print()
    header = f"{'store':<25} {'account':<10} {'org':<10} {'sess':>5} {'sched':>6} {'dirs':>5}  {'span':<24} owner"
    print(header)
    print("-" * len(header))
    for b in buckets:
        span = f"{b['first']} .. {b['last']}" if b["first"] else "-"
        owner = b["owner"].get("emailAddress", "unknown")
        marker = " *" if account and b["account"] == account.get("accountUuid") else ""
        print(f"{b['store']:<25} {b['account'][:8]:<10} {b['org'][:8]:<10} "
              f"{b['sessions']:>5} {b['scheduled']:>6} {b['workdirs']:>5}  {span:<24} {owner}{marker}")
    if account:
        print("\n* = currently signed-in account (the usual migration target)")
    for note in warnings:
        print(f"\n!  {note}")
    return 0


# --------------------------------------------------------------------------
# migrate
# --------------------------------------------------------------------------

def parse_bucket(spec: str, root: Path, store: str) -> Path | None:
    """Accept 'account/org', or a bare account when the org is unambiguous.

    Returns None when the account simply has no presence in this store, which is
    normal — an account often has Claude Code sessions but no agent-mode ones.
    Only genuine ambiguity (several orgs to choose from) is an error.
    """
    parts = [p for p in spec.split("/") if p]
    if len(parts) == 2:
        return root / store / parts[0] / parts[1]
    if len(parts) == 1:
        account_dir = root / store / parts[0]
        orgs = sorted(p for p in account_dir.iterdir() if is_uuid_dir(p)) if account_dir.is_dir() else []
        if len(orgs) == 1:
            return orgs[0]
        if not orgs:
            return None
        raise SystemExit(
            f"'{spec}' matches {len(orgs)} orgs in {store}; specify account/org explicitly."
        )
    raise SystemExit(f"Could not parse bucket spec '{spec}'")


def resolve_plan(args, root: Path) -> list[tuple[str, Path, Path]]:
    """Work out every (store, source, target) up front.

    Stores are migrated in sequence, so resolving lazily means an error on the
    second store surfaces after the first has already been written — and with
    --move, after its source records are gone. Failing during planning keeps a
    bad spec from turning into a half-finished destructive migration.
    """
    plan = []
    for store in STORES:
        if args.stores and store not in args.stores:
            continue
        src = parse_bucket(args.source, root, store)
        dst = parse_bucket(args.target, root, store)
        if src is None or not src.is_dir():
            continue
        if dst is None:
            # Target has no bucket in this store yet; derive it from the source's
            # own org when the spec was a bare account.
            parts = [p for p in args.target.split("/") if p]
            dst = root / store / parts[0] / (parts[1] if len(parts) == 2 else src.name)
        plan.append((store, src, dst))
    return plan


def make_backup(root: Path, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(dest, "w:gz") as tar:
        for store in STORES:
            store_dir = root / store
            if store_dir.is_dir():
                tar.add(store_dir, arcname=store)
    return dest


def rewrite_paths(obj, old: str, new: str):
    """Replace the source bucket path fragment wherever it appears.

    Agent-mode records store a cwd pointing into their own bucket. Left alone,
    a migrated session keeps writing into the source account's tree.
    """
    if isinstance(obj, str):
        return obj.replace(old, new)
    if isinstance(obj, list):
        return [rewrite_paths(v, old, new) for v in obj]
    if isinstance(obj, dict):
        return {k: rewrite_paths(v, old, new) for k, v in obj.items()}
    return obj


def cmd_migrate(args) -> int:
    root = resolve_root(args.root)
    target_email = args.target_email
    target_name = args.target_name
    if target_email is None:
        account = current_account()
        target_email = account.get("emailAddress")
        if target_name is None:
            target_name = account.get("displayName")

    plan = resolve_plan(args, root)          # raises before anything is written
    results = []
    for store, src, dst in plan:
        results.append(migrate_bucket(src, dst, store, args, target_email, target_name, root))

    if not results:
        print("Nothing to migrate: no matching source buckets.", file=sys.stderr)
        return 1

    for note in live_tree_check(root, scan(root)):
        print(f"!  {note}\n", file=sys.stderr)
    if args.dry_run:
        print("\nDry run — no files were written.")
    print(json.dumps({"dry_run": args.dry_run, "results": results}, indent=2))
    return 0


def migrate_bucket(src: Path, dst: Path, store: str, args,
                   target_email: str | None, target_name: str | None,
                   root: Path | None = None) -> dict:
    old_frag = f"{src.parent.name}/{src.name}"
    new_frag = f"{dst.parent.name}/{dst.name}"

    # Rewriting only the account/org fragment is right for an in-place migration,
    # but leaves stored paths rooted at the tree you are working in. Stage a
    # restored backup and every rewritten cwd still points into the backup folder,
    # so the sessions break the moment the tree is copied somewhere real.
    final_root = Path(args.final_root).expanduser() if getattr(args, "final_root", None) else None
    root_from = str(root) if root else None
    root_to = str(final_root) if final_root else None
    rewrite_root = bool(root_from and root_to and root_from != root_to)

    copied, skipped_existing, skipped_scheduled, dirs_copied, repointed, retagged = 0, 0, 0, 0, 0, 0
    dir_collisions = 0
    copied_names: list[str] = []   # only these are safe to delete under --move

    if not args.dry_run:
        dst.mkdir(parents=True, exist_ok=True)

    for record in session_records(src):
        if record.name in CONFIG_NAMES:
            continue
        data = read_json(record)
        if data is None:
            print(f"  skipping unreadable {record.name}", file=sys.stderr)
            continue
        if data.get("sessionType") == "scheduled" and not args.include_scheduled:
            skipped_scheduled += 1
            continue

        out = dst / record.name
        if out.exists():
            skipped_existing += 1
            continue

        changed = dict(data)
        # Agent-mode records embed the account that created them. Left as-is,
        # migrated sessions display the previous owner.
        if target_email and "emailAddress" in changed:
            changed["emailAddress"] = target_email
            retagged += 1
        if "accountName" in changed:
            changed["accountName"] = target_name

        before = json.dumps(changed)
        changed = rewrite_paths(changed, old_frag, new_frag)
        if rewrite_root:
            changed = rewrite_paths(changed, root_from, root_to)
        if json.dumps(changed) != before:
            repointed += 1

        if not args.dry_run:
            if changed == data:
                shutil.copy2(record, out)          # byte-identical, keep mtime
            else:
                out.write_text(json.dumps(changed, indent=2))
                st = record.stat()
                os.utime(out, (st.st_atime, st.st_mtime))
        copied += 1

        # Agent-mode sessions own a sibling working directory. If the destination
        # already has one (an interrupted earlier run, say) we must not copy over
        # it — and we must not let --move delete the source either, because the
        # source is then the only complete copy and the target session would be
        # left pointing at unrelated state.
        wd = workdir_for(record)
        if wd.is_dir():
            if (dst / wd.name).exists():
                dir_collisions += 1
                print(f"  workdir already exists for {record.name}; left the source in place",
                      file=sys.stderr)
            else:
                if not args.dry_run:
                    shutil.copytree(wd, dst / wd.name, symlinks=True)
                dirs_copied += 1
                copied_names.append(record.name)
        else:
            copied_names.append(record.name)

    if args.move and not args.dry_run:
        # Delete only what this run actually copied. A record skipped because the
        # target already had it was not written here, so removing the source copy
        # would be destroying data this run never duplicated.
        for name in copied_names:
            record = src / name
            if not record.exists() or not (dst / name).exists():
                continue
            wd = workdir_for(record)
            record.unlink()
            if wd.is_dir():
                shutil.rmtree(wd)

    return {
        "store": store, "source": str(src), "target": str(dst),
        "copied": copied, "workdirs_copied": dirs_copied,
        "identity_retagged": retagged, "paths_repointed": repointed,
        "skipped_existing": skipped_existing, "skipped_scheduled": skipped_scheduled,
        "workdir_collisions": dir_collisions,
        "mode": "move" if args.move else "copy",
        "final_root": root_to if rewrite_root else None,
    }


# --------------------------------------------------------------------------
# verify
# --------------------------------------------------------------------------

def cmd_verify(args) -> int:
    root = resolve_root(args.root)
    problems, checks = [], []

    for store in STORES:
        if args.stores and store not in args.stores:
            continue
        src = parse_bucket(args.source, root, store)
        dst = parse_bucket(args.target, root, store)
        if not dst.is_dir():
            continue

        records = session_records(dst)
        checks.append(f"{store}: {len(records)} session records in target")

        bad = [r.name for r in records if read_json(r) is None]
        if bad:
            problems.append(f"{store}: unparseable JSON in {', '.join(bad[:5])}")

        frag = f"{src.parent.name}/{src.name}"
        stale = [r.name for r in records if frag in r.read_text()]
        if stale:
            problems.append(f"{store}: {len(stale)} records still reference the source bucket")

        missing, foreign = [], []
        for r in records:
            cwd = (read_json(r) or {}).get("cwd")
            if not isinstance(cwd, str):
                continue
            if cwd.startswith(str(root)):
                if not Path(cwd).is_dir():
                    missing.append(r.name)
            elif f"{dst.parent.name}/{dst.name}" in cwd:
                # Points at this bucket, but rooted in some other tree — the stale
                # prefix left behind when a store is migrated somewhere it won't stay.
                foreign.append(cwd)
        if missing:
            problems.append(f"{store}: {len(missing)} records point at a cwd that does not exist")
        if foreign:
            problems.append(
                f"{store}: {len(foreign)} records store a path rooted outside this tree "
                f"(e.g. {foreign[0]}) — re-run migrate with --final-root so they point where the tree will live")

        if src.is_dir():
            checks.append(f"{store}: {len(session_records(src))} records still in source")

        nested = [p for p in dst.glob("local_*/.claude/.claude.json")
                  if src.parent.name in p.read_text()]
        if nested:
            checks.append(
                f"{store}: {len(nested)} migrated workdirs keep the previous account "
                f"in their sandbox .claude.json (per-session state; harmless unless you want it rewritten)"
            )

    # Transcripts are not account-scoped, so they are shared rather than migrated.
    projects = Path.home() / ".claude" / "projects"
    if projects.is_dir() and not args.stores:
        dst = parse_bucket(args.target, root, "claude-code-sessions")
        have = miss = 0
        for r in session_records(dst):
            cli = (read_json(r) or {}).get("cliSessionId")
            if not cli:
                continue
            if any(projects.glob(f"*/{cli}.jsonl")):
                have += 1
            else:
                miss += 1
        if have or miss:
            checks.append(
                f"transcripts: {have} of {have + miss} found in ~/.claude/projects "
                f"({miss} absent — typically pruned by transcript retention before the migration, "
                f"since transcripts are shared and were never copied)"
            )

    for line in checks:
        print(f"  ok    {line}")
    for line in problems:
        print(f"  FAIL  {line}")
    print()
    print("verification passed" if not problems else f"{len(problems)} problem(s) found")
    return 1 if problems else 0


# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", help="app support dir (default: $CLAUDE_APP_SUPPORT_DIR or the macOS path)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("inventory", help="list every account/org bucket")
    p.add_argument("--json", action="store_true")
    p.add_argument("--all", action="store_true", help="include buckets with no sessions")
    p.set_defaults(func=cmd_inventory)

    p = sub.add_parser("migrate", help="copy sessions between buckets")
    p.add_argument("--source", required=True, help="source bucket: account/org, or account if unambiguous")
    p.add_argument("--target", required=True, help="target bucket: account/org")
    p.add_argument("--stores", nargs="*", choices=STORES, help="limit to specific stores")
    p.add_argument("--include-scheduled", action="store_true",
                   help="include recurring scheduled-task runs (excluded by default: they are cron artifacts)")
    p.add_argument("--move", action="store_true", help="delete source records after copying (default: copy)")
    p.add_argument("--dry-run", action="store_true", help="report what would happen without writing")
    p.add_argument("--target-email", help="override the email written into migrated records")
    p.add_argument("--target-name", help="override the display name written into migrated records")
    p.add_argument("--final-root", help="where this tree will ultimately live (e.g. the real app "
                                        "support dir). Stored paths are rewritten to it, so a "
                                        "staged or restored store still works once it lands.")
    p.set_defaults(func=cmd_migrate)

    p = sub.add_parser("verify", help="re-check a completed migration")
    p.add_argument("--source", required=True)
    p.add_argument("--target", required=True)
    p.add_argument("--stores", nargs="*", choices=STORES)
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("backup", help="tar both session stores before migrating")
    p.add_argument("--dest", help="output path for the .tar.gz")
    p.set_defaults(func=lambda a: cmd_backup(a))

    args = ap.parse_args()
    return args.func(args)


def cmd_backup(args) -> int:
    root = resolve_root(args.root)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = Path(args.dest).expanduser() if args.dest else (
        Path.home() / f"claude-session-backup-{stamp}" / "session-stores.tar.gz")
    make_backup(root, dest)
    with tarfile.open(dest) as tar:
        count = len(tar.getnames())
    print(f"{dest}  ({dest.stat().st_size / 1_048_576:.1f} MB, {count} entries)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
