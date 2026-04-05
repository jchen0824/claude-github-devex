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

### `codex-review-loop`

Automated local code quality loop using the Codex CLI plugin that iterates until Codex approves — no GitHub PR required.

**When to use:** Run a local review loop against a base branch, iterate on code quality until Codex signs off, or automate the fix-review-repeat cycle.

**Example invocations:**
- `"Run the codex review loop against main"`
- `"Iterate until codex approves"`
- `"Adversarial review loop against develop"`

**What it does:**
1. Orchestrates three plugins: **ralph-loop** (iteration driver), **codex adversarial-review** (local Codex CLI review), and **superpowers** (disciplined skill usage)
2. Each iteration: runs an adversarial review against the base branch, parses the verdict
3. If `needs-attention` — fixes every finding, verifies with tests, and commits
4. If `approve` — exits the loop
5. Repeats until Codex approves (typically 2-4 rounds)

**Requires:** Codex CLI, ralph-loop plugin, and superpowers plugin installed locally.

### Prerequisites

Before using these skills:

1. **GitHub CLI** — authenticated: `gh auth status`
2. **In repository root** with PR branch checked out
3. **Test/lint commands** — auto-detected from `package.json` or prompted

The Codex polling script is bundled with the plugin — no separate installation needed.

## License

MIT
