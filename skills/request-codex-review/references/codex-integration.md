# Codex Integration Details

## Bundled Polling Script

The `check_codex_review_state.py` polling script is bundled directly with this plugin at:
```
skills/request-codex-review/scripts/check_codex_review_state.py
```

No external installation or env var required. The `orchestrate_codex_review.py` script locates it automatically via `Path(__file__).parent`.

## Polling Script Interface

The `check_codex_review_state.py` script expects:
```bash
python3 scripts/check_codex_review_state.py \
  --owner <owner>              # GitHub repo owner
  --repo <repo>                # GitHub repo name
  --pr <pr>                    # Pull request number
  --state-file <path>          # State file (auto-created if missing)
  [--once]                     # Check once instead of polling loop
  [--author-regex <regex>]     # Regex to match Codex author (default: "(?i)codex")
```

## Exit Codes

- **0**: Loop completed (Codex said "good to go" or PR has 👍)
- **10**: New Codex comments detected (action needed)
- **Non-zero**: Error or unexpected state

## State File Format

The state file (`.codex/codex-review-loop-state-pr<PR>.json`) tracks:
```json
{
  "status": "needs_action" | "waiting" | "completed",
  "last_checked": "2026-03-15T...",
  "seen_comment_ids": ["pr_review_comment_123", ...],
  "new_comments": [...]
}
```

## Codex Review Comments

Codex comments are GitHub pull request review comments with:
- `author`: matches author regex (default: "codex")
- `body`: Markdown text describing the issue
- Properties:
  - Issue location: file, line numbers
  - Severity: implicit in wording (e.g., "Critical:", "Warning:", "Consider:")
  - Actionable: specific code changes requested

## Detecting Completion

The loop completes when **either**:
1. Codex posts a comment containing "good to go" (case-insensitive)
2. PR gets a 👍 (thumbs-up) reaction

**Note**: An 👀 (eyes) reaction indicates Codex has seen the changes but is still reviewing — not a completion signal.

## Workflow Loop Sequence

```
1. [TRIGGER] User asks: "request codex review for PR #X"
   ↓
2. [INITIALIZE] Extract owner/repo/PR, create state file
   ↓
3. [POLL] Run check_codex_review_state.py --once
   ↓
4. [CHECK STATUS]
   ├─ needs_action → go to step 5
   ├─ waiting → sleep 3 min, go to step 3
   ├─ completed → go to step 8
   └─ error → report and exit
   ↓
5. [EXTRACT FEEDBACK] Parse new Codex comments from JSON output
   ↓
6. [APPLY FIXES]
   ├─ Read Codex comment describing issue
   ├─ Modify code to fix the issue
   ├─ Run verification: <your-test-command>, <your-lint-command>
   ├─ Commit changes (e.g., /commit skill)
   ├─ Push to branch: git push
   └─ Reply to Codex comment (optional but good practice)
   ↓
7. [REQUEST REVIEW] Post comment: "@codex, please review again."
   ↓
8. [LOOP] Go back to step 3
   ↓
9. [COMPLETION] Codex says "good to go" or PR gets 👍
   ↓
10. [REPORT] "Completed the code quality guardrail workflow."
```

## Integration with Claude Code Skills

The skill can use these Claude Code skills to apply fixes:

- **`/commit`** — Commit changes after fixing code
- **`/superpowers:code-review`** — Review your own fixes before submitting
- **Bash commands** — Run `<your-test-command>`, `<your-lint-command>`, `git push`, etc.
- **`/superpowers:systematic-debugging`** — If fixes don't work on first try

## Error Handling

Common scenarios:

| Scenario | Action |
|----------|--------|
| Script not found | Plugin may be incomplete — reinstall: `/plugin install github-devex@jchen0824/claude-code-plugins` |
| `gh` auth fails | Run `gh auth status` to verify login |
| State file locked | Manually delete `.codex/codex-review-loop-state-pr<PR>.json` and restart |
| Codex not responding | Wait — Codex may be slow. Loop will check every 3 minutes indefinitely |
| Fix breaks tests | Codex will comment again. Read feedback and try different approach |
| PR is already merged | Codex polling will fail. Create a new PR to review |

## Notes on Automation

- **Don't manually reply to Codex** — the skill handles all feedback responses
- **Don't delete state file** — it tracks progress. Only delete if truly stuck
- **Codex may suggest multiple fixes** in a single comment — apply all of them before requesting re-review
- **Re-review requests** should reference the fixes applied for context
