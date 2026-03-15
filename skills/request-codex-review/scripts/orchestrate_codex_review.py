#!/usr/bin/env python3
"""
Orchestrate Codex review polling and action.

This script:
1. Calls the Codex polling script to check for new comments
2. Parses the JSON output to extract new Codex feedback
3. Returns structured data for Claude to process and apply fixes
"""

import json
import os
import subprocess
import sys
from pathlib import Path


def run_codex_poll(owner: str, repo: str, pr: int, state_file: str, once: bool = True) -> dict:
    """
    Run the Codex polling script and return parsed results.

    Returns:
    {
        "status": "needs_action" | "waiting" | "completed" | "error",
        "exit_code": int,
        "new_comments": [{"id": "...", "body": "...", "author": "codex", ...}],
        "raw_output": str
    }
    """
    codex_script_path = os.environ.get("CODEX_REVIEW_SCRIPT")
    if not codex_script_path:
        return {
            "status": "error",
            "exit_code": -1,
            "new_comments": [],
            "raw_output": (
                "Error: CODEX_REVIEW_SCRIPT is not set. "
                "Set it to the path of your Codex polling script, e.g.: "
                "export CODEX_REVIEW_SCRIPT=~/.codex/skills/gh-codex-review-loop/scripts/check_codex_review_state.py"
            )
        }
    codex_script = Path(codex_script_path)
    if not codex_script.exists():
        return {
            "status": "error",
            "exit_code": -1,
            "new_comments": [],
            "raw_output": f"Error: Codex script not found at {codex_script}. Check your CODEX_REVIEW_SCRIPT env var."
        }

    cmd = [
        "python3",
        str(codex_script),
        "--owner", owner,
        "--repo", repo,
        "--pr", str(pr),
        "--state-file", state_file
    ]

    if once:
        cmd.append("--once")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        output = result.stdout

        # Try to parse JSON output
        try:
            data = json.loads(output)
            return {
                "status": data.get("status", "unknown"),
                "exit_code": result.returncode,
                "new_comments": data.get("new_comments", []),
                "raw_output": output
            }
        except json.JSONDecodeError:
            # Fallback: raw output
            return {
                "status": "unknown",
                "exit_code": result.returncode,
                "new_comments": [],
                "raw_output": output + "\n" + result.stderr
            }
    except subprocess.TimeoutExpired:
        return {
            "status": "error",
            "exit_code": -1,
            "new_comments": [],
            "raw_output": "Error: Polling script timed out after 30 seconds"
        }
    except Exception as e:
        return {
            "status": "error",
            "exit_code": -1,
            "new_comments": [],
            "raw_output": f"Error: {str(e)}"
        }


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print(json.dumps({
            "status": "error",
            "error": "Usage: orchestrate_codex_review.py <owner> <repo> <pr> [state_file] [--once]"
        }))
        sys.exit(1)

    owner = sys.argv[1]
    repo = sys.argv[2]
    pr = int(sys.argv[3])
    state_file = sys.argv[4] if len(sys.argv) > 4 else f".codex/codex-review-loop-state-pr{pr}.json"
    once = "--once" in sys.argv

    result = run_codex_poll(owner, repo, pr, state_file, once)
    print(json.dumps(result, indent=2))
