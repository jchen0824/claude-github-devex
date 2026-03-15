#!/usr/bin/env python3
"""Poll GitHub PR comments for Codex review-loop state."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


EXIT_COMPLETED = 0
EXIT_NEEDS_ACTION = 10
EXIT_WAITING = 11
EXIT_ERROR = 2


def run_gh_api(path: str, extra_args: list[str] | None = None) -> Any:
    cmd = ["gh", "api", path, "--header", "Accept: application/vnd.github+json"]
    if extra_args:
        cmd.extend(extra_args)
    try:
        proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise RuntimeError("gh CLI not found. Install GitHub CLI first.") from exc
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() if exc.stderr else "unknown error"
        raise RuntimeError(f"gh api failed for '{path}': {stderr}") from exc

    out = proc.stdout.strip()
    if not out:
        return []
    return json.loads(out)


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"last_seen_comment_id": 0}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"last_seen_comment_id": 0}


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def normalize_comments(raw: list[dict[str, Any]], source: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for comment in raw:
        items.append(
            {
                "id": int(comment.get("id", 0)),
                "source": source,
                "author": (comment.get("user") or {}).get("login") or "",
                "url": comment.get("html_url") or "",
                "created_at": comment.get("created_at") or "",
                "body": comment.get("body") or "",
                "path": comment.get("path"),
                "line": comment.get("line"),
            }
        )
    return items


def filter_authored(items: list[dict[str, Any]], author_regex: re.Pattern[str]) -> list[dict[str, Any]]:
    return [item for item in items if author_regex.search(item["author"])]


def get_pr_state(
    owner: str,
    repo: str,
    pr: int,
    author_regex: re.Pattern[str],
    good_to_go_regex: re.Pattern[str],
    last_seen_comment_id: int,
) -> dict[str, Any]:
    issue_comments_raw = run_gh_api(
        f"repos/{owner}/{repo}/issues/{pr}/comments?per_page=100&sort=created&direction=asc"
    )
    review_comments_raw = run_gh_api(
        f"repos/{owner}/{repo}/pulls/{pr}/comments?per_page=100&sort=created&direction=asc"
    )
    reactions_raw = run_gh_api(f"repos/{owner}/{repo}/issues/{pr}/reactions?per_page=100")

    issue_comments = normalize_comments(issue_comments_raw, "issue_comment")
    review_comments = normalize_comments(review_comments_raw, "review_comment")
    codex_comments = filter_authored(issue_comments + review_comments, author_regex)
    codex_comments.sort(key=lambda c: c["id"])

    new_comments = [c for c in codex_comments if c["id"] > last_seen_comment_id]
    good_to_go_comment = next(
        (c for c in codex_comments if good_to_go_regex.search(c.get("body", ""))),
        None,
    )

    thumbs_up_reactions = [r for r in reactions_raw if r.get("content") == "+1"]
    eyes_reactions = [r for r in reactions_raw if r.get("content") == "eyes"]

    completed = bool(good_to_go_comment) or bool(thumbs_up_reactions)

    status = "completed" if completed else ("needs_action" if new_comments else "waiting")

    return {
        "status": status,
        "last_seen_comment_id": max(
            [last_seen_comment_id, *[c["id"] for c in codex_comments]]
        ),
        "new_comment_count": len(new_comments),
        "new_comments": [
            {
                "id": c["id"],
                "source": c["source"],
                "author": c["author"],
                "url": c["url"],
                "created_at": c["created_at"],
                "body_excerpt": c["body"].strip().replace("\n", " ")[:280],
                "path": c["path"],
                "line": c["line"],
            }
            for c in new_comments
        ],
        "completion_signal": {
            "good_to_go_comment_id": good_to_go_comment["id"] if good_to_go_comment else None,
            "thumbs_up_reaction_count": len(thumbs_up_reactions),
            "eyes_reaction_count": len(eyes_reactions),
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Check Codex feedback state for a PR. "
            "Exits 0 when completed, 10 when new comments need action, 11 when waiting."
        )
    )
    parser.add_argument("--owner", required=True, help="Repository owner/org")
    parser.add_argument("--repo", required=True, help="Repository name")
    parser.add_argument("--pr", required=True, type=int, help="Pull request number")
    parser.add_argument("--state-file", required=True, help="Path to persistent state JSON")
    parser.add_argument(
        "--author-regex",
        default="(?i)codex",
        help="Regex to match Codex author login",
    )
    parser.add_argument(
        "--good-to-go-regex",
        default=r"(?i)\bgood to go\b",
        help='Regex to detect completion comment text, default: "good to go"',
    )
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=180,
        help="Polling interval in seconds when waiting (default: 180)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Check once and exit (no polling loop)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    state_path = Path(args.state_file)
    state = load_state(state_path)

    author_regex = re.compile(args.author_regex)
    good_to_go_regex = re.compile(args.good_to_go_regex)

    while True:
        try:
            result = get_pr_state(
                owner=args.owner,
                repo=args.repo,
                pr=args.pr,
                author_regex=author_regex,
                good_to_go_regex=good_to_go_regex,
                last_seen_comment_id=int(state.get("last_seen_comment_id", 0)),
            )
        except RuntimeError as exc:
            print(json.dumps({"status": "error", "message": str(exc)}), file=sys.stderr)
            return EXIT_ERROR

        state["last_seen_comment_id"] = result["last_seen_comment_id"]
        save_state(state_path, state)

        print(json.dumps(result, indent=2))

        if result["status"] == "completed":
            return EXIT_COMPLETED
        if result["status"] == "needs_action":
            return EXIT_NEEDS_ACTION
        if args.once:
            return EXIT_WAITING

        time.sleep(args.interval_seconds)


if __name__ == "__main__":
    sys.exit(main())
