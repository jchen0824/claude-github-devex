# claude-github-devex

GitHub developer experience tools for Claude Code.

## Installation

### Via Marketplace (Recommended)

```bash
# Add the marketplace
/plugin marketplace add jchen0824/claude-code-plugins

# Install this plugin
/plugin install github-devex@jchen0824/claude-code-plugins
```

## Skills

### `request-codex-review`

Automate Codex code review on GitHub PRs with full fix-and-iterate loops.

**When to use:** Request Codex review for a PR and have it automatically poll for feedback, apply fixes, commit changes, and iterate until completion.

**Example invocations:**
- `"Request codex review for PR #42 in owner/my-repo"`
- `"Run codex review on this PR"`
- `"Apply codex feedback automatically for PR #17"`

**What it does:**
1. Polls for Codex feedback every 3 minutes
2. Extracts issues from Codex comments
3. Reads flagged files and applies fixes
4. Runs project verification (tests, linting — auto-detected)
5. Commits and pushes changes
6. Requests another review
7. Repeats until Codex says "good to go"

### Prerequisites

Before using this skill:

1. **GitHub CLI** — authenticated: `gh auth status`
2. **Codex polling script** — install and set env var:
   ```bash
   export CODEX_REVIEW_SCRIPT=~/.codex/skills/gh-codex-review-loop/scripts/check_codex_review_state.py
   ```
3. **In repository root** with PR branch checked out
4. **Test/lint commands** — auto-detected from `package.json` or prompted

See `skills/request-codex-review/references/codex-integration.md` for full setup instructions.

## License

MIT
