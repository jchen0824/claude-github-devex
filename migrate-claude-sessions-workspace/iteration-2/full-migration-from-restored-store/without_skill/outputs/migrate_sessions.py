#!/usr/bin/env python3
"""
Move Claude desktop session history from one account/org store key to another.

The Claude macOS app keeps local session history under:

    <store-root>/claude-code-sessions/<accountUuid>/<organizationUuid>/
    <store-root>/local-agent-mode-sessions/<accountUuid>/<organizationUuid>/

Signing in with a different account changes that key, so the app looks in a new,
empty directory and the old history appears to be gone.  This script copies the
session records (and, for agent-mode, their workspace directories) from the old
key to the new one, additively: nothing in the destination is overwritten.

Usage:
  migrate_sessions.py --store-root DIR --from ACCT/ORG --to ACCT/ORG [--apply]

Defaults to a dry run; pass --apply to write.
"""

import argparse
import json
import os
import shutil
import sys

STORES = ("claude-code-sessions", "local-agent-mode-sessions")

# Files/dirs in the account dir that are account-scoped settings, not session
# history.  They must never be blindly copied over the destination's own copy.
SETTINGS_FILES = {"scheduled-tasks.json"}
SETTINGS_DIRS = {"rpm"}

# Identity fields that describe *which account owned the session*.  They are
# stale after a migration and there is no authoritative source for the new
# values in the restored data, so they are dropped rather than invented.
# They are optional in the schema (Claude Code session records omit them).
STALE_SESSION_FIELDS = ("accountName", "emailAddress")
STALE_OAUTH_FIELDS = ("emailAddress", "displayName", "organizationName")

log = []


def note(msg):
    log.append(msg)
    print(msg)


def load(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def dump(path, obj, mtime_src=None):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2)
        fh.write("\n")
    if mtime_src:
        st = os.stat(mtime_src)
        os.utime(path, (st.st_atime, st.st_mtime))


def rewrite_session(path, old_prefix, new_prefix):
    """Re-point cwd out of the old account dir and strip stale owner identity."""
    data = load(path)
    changed = []
    cwd = data.get("cwd")
    if isinstance(cwd, str) and cwd.startswith(old_prefix):
        data["cwd"] = new_prefix + cwd[len(old_prefix):]
        changed.append("cwd")
    for field in STALE_SESSION_FIELDS:
        if field in data:
            del data[field]
            changed.append(field)
    if changed:
        dump(path, data, mtime_src=path)
    return changed


def rewrite_workspace_claude_json(path, ids):
    """Point the workspace's embedded oauthAccount at the new account/org."""
    data = load(path)
    acct = data.get("oauthAccount")
    if not isinstance(acct, dict):
        return []
    changed = []
    if acct.get("accountUuid") == ids["from_acct"]:
        acct["accountUuid"] = ids["to_acct"]
        changed.append("accountUuid")
    if acct.get("organizationUuid") == ids["from_org"]:
        acct["organizationUuid"] = ids["to_org"]
        changed.append("organizationUuid")
    for field in STALE_OAUTH_FIELDS:
        if field in acct:
            del acct[field]
            changed.append(field)
    if changed:
        dump(path, data, mtime_src=path)
    return changed


def merge_scheduled_tasks(src, dst, apply):
    """Union task lists by id; never clobber the destination's own settings."""
    if not os.path.exists(src):
        return
    src_tasks = load(src).get("tasks") or []
    if not src_tasks:
        note(f"    scheduled-tasks.json: old account has 0 tasks -> destination left untouched")
        return
    if not os.path.exists(dst):
        if apply:
            shutil.copy2(src, dst)
        note(f"    scheduled-tasks.json: copied ({len(src_tasks)} tasks)")
        return
    dst_data = load(dst)
    dst_tasks = dst_data.get("tasks") or []
    have = {t.get("id") for t in dst_tasks if isinstance(t, dict)}
    added = [t for t in src_tasks if isinstance(t, dict) and t.get("id") not in have]
    if added:
        dst_data["tasks"] = dst_tasks + added
        if apply:
            dump(dst, dst_data)
        note(f"    scheduled-tasks.json: merged {len(added)} task(s), kept destination's own keys")
    else:
        note("    scheduled-tasks.json: nothing new to merge -> untouched")


def merge_rpm_manifest(src, dst, apply):
    """Union plugin lists; the destination's plugins must survive."""
    if not os.path.exists(src):
        return
    src_plugins = load(src).get("plugins") or []
    if not os.path.exists(dst):
        if apply:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
        note(f"    rpm/manifest.json: copied ({len(src_plugins)} plugins)")
        return
    dst_data = load(dst)
    dst_plugins = dst_data.get("plugins") or []
    added = [p for p in src_plugins if p not in dst_plugins]
    if added:
        dst_data["plugins"] = dst_plugins + added
        if apply:
            dump(dst, dst_data)
        note(f"    rpm/manifest.json: added {len(added)} plugin(s), kept {dst_plugins}")
    else:
        note(f"    rpm/manifest.json: nothing to add -> untouched (keeps {dst_plugins})")


def migrate(root, ids, apply):
    total_copied = total_skipped = 0
    for store in STORES:
        src_dir = os.path.join(root, store, ids["from_acct"], ids["from_org"])
        dst_dir = os.path.join(root, store, ids["to_acct"], ids["to_org"])
        note(f"\n[{store}]")
        if not os.path.isdir(src_dir):
            note("    no data under the old account -> skipped")
            continue
        if apply:
            os.makedirs(dst_dir, exist_ok=True)

        old_prefix = src_dir + os.sep
        new_prefix = dst_dir + os.sep

        entries = sorted(os.listdir(src_dir))
        copied, skipped = [], []
        for name in entries:
            if name in SETTINGS_FILES or name in SETTINGS_DIRS or name.startswith("."):
                continue
            src = os.path.join(src_dir, name)
            dst = os.path.join(dst_dir, name)
            if os.path.exists(dst):
                skipped.append(name)
                continue
            if not apply:
                copied.append(name)
                continue
            if os.path.isdir(src):
                shutil.copytree(src, dst, symlinks=True)
                inner = os.path.join(dst, ".claude", ".claude.json")
                if os.path.exists(inner):
                    rewrite_workspace_claude_json(inner, ids)
            else:
                shutil.copy2(src, dst)
                if name.endswith(".json"):
                    rewrite_session(dst, old_prefix, new_prefix)
            copied.append(name)

        n_json = len([c for c in copied if c.endswith(".json")])
        n_dir = len(copied) - n_json
        note(f"    copied {n_json} session record(s) + {n_dir} workspace dir(s)")
        if skipped:
            note(f"    skipped {len(skipped)} name(s) already present in destination: {skipped}")
        total_copied += len(copied)
        total_skipped += len(skipped)

        merge_scheduled_tasks(
            os.path.join(src_dir, "scheduled-tasks.json"),
            os.path.join(dst_dir, "scheduled-tasks.json"),
            apply,
        )
        merge_rpm_manifest(
            os.path.join(src_dir, "rpm", "manifest.json"),
            os.path.join(dst_dir, "rpm", "manifest.json"),
            apply,
        )
    note(f"\nTOTAL: {total_copied} item(s) migrated, {total_skipped} left alone.")


def split_key(value, label):
    parts = value.strip("/").split("/")
    if len(parts) != 2:
        sys.exit(f"--{label} must look like <accountUuid>/<organizationUuid>")
    return parts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--store-root", required=True)
    ap.add_argument("--from", dest="src", required=True)
    ap.add_argument("--to", dest="dst", required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    from_acct, from_org = split_key(args.src, "from")
    to_acct, to_org = split_key(args.dst, "to")
    ids = dict(from_acct=from_acct, from_org=from_org, to_acct=to_acct, to_org=to_org)

    note(("APPLY" if args.apply else "DRY RUN") + f" - store root: {args.store_root}")
    note(f"  from {from_acct}/{from_org}")
    note(f"    to {to_acct}/{to_org}")
    migrate(os.path.abspath(args.store_root), ids, args.apply)


if __name__ == "__main__":
    main()
