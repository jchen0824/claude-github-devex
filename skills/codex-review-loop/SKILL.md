---
name: codex-review-loop
description: "Automated local code quality loop using the Codex CLI plugin that iterates until Codex approves. Orchestrates ralph-loop to drive iterations, superpowers for disciplined skill usage, and codex adversarial-review (via local Codex CLI) for rigorous code review against a base branch. Requires the codex CLI and codex plugin to be installed locally. Use this skill whenever the user wants to run a review loop, iterate on code quality until approved, get Codex to sign off on their changes, or automate the fix-review-repeat cycle. Trigger on phrases like 'review loop', 'iterate until codex approves', 'code quality loop', 'keep fixing until approved', or 'adversarial review loop against main'."
compatibility:
  plugins:
    - ralph-loop
    - codex
    - superpowers
  tools:
    - codex CLI (installed locally, provides the adversarial-review command)
---

# Codex Review Loop

An automated code-quality feedback loop that runs entirely locally via the Codex CLI plugin — no GitHub PR required. Codex reviews your local changes against a base branch, you fix what it flags, Codex reviews again — repeating until it approves. The loop runs itself via ralph-loop so you don't have to babysit it.

## Prerequisites

- **Codex CLI** must be installed and available locally. The codex plugin (`codex:adversarial-review`) depends on it to run reviews against your local working tree and branch diffs.
- **ralph-loop plugin** must be installed (drives the iteration cycle).
- **superpowers plugin** must be installed (ensures disciplined skill usage each iteration).

## How It Works

Three plugins collaborate:

1. **ralph-loop** drives the iteration — it re-feeds the same prompt after each cycle, letting you see previous work in files and git history.
2. **codex adversarial-review** (via the local Codex CLI plugin) provides the actual review — a challenging, design-level critique that runs locally against your branch diff, going beyond surface linting to question assumptions, tradeoffs, and failure modes. This is not a GitHub PR review — it runs directly on your local code via the Codex CLI.
3. **superpowers** ensures disciplined skill usage throughout each iteration — invoking the right skills at the right time rather than freestyling.

The loop exits only when Codex returns a verdict of `approve`.

## Quick Start

When the user asks you to run the codex review loop, set it up like this:

```
/ralph-loop:ralph-loop "Run a Codex adversarial review loop. Each iteration: (1) invoke /superpowers:using-superpowers to ensure disciplined skill usage, (2) run /codex:adversarial-review --wait --base main, (3) parse the verdict — if 'needs-attention', fix every finding, verify with tests, and commit, then let the loop continue; if 'approve', output the completion promise." --max-iterations 10 --completion-promise "CODEX_REVIEW_APPROVED"
```

That's it. Ralph-loop handles re-running the prompt. Each iteration sees the accumulated fixes from prior rounds.

## What Happens Each Iteration

### Step 1: Invoke Superpowers

Before doing anything, invoke `/superpowers:using-superpowers`. This ensures that any relevant skills (debugging, TDD, etc.) are properly activated for the work ahead. Superpowers establishes the discipline of checking for applicable skills before acting — which matters because the fixes you apply might benefit from specialized workflows.

### Step 2: Run the Adversarial Review

Run the Codex adversarial review in foreground mode against the base branch:

```
/codex:adversarial-review --wait --base main
```

This compares the current branch against `main` and returns structured findings. The review focuses on material risks: auth/permissions issues, data loss, race conditions, version skew, and observability gaps. It also challenges design choices and assumptions — it's not just a linter.

### Step 3: Parse the Verdict

The review output contains a `verdict` field:

- **`approve`** — Codex is satisfied. Output `CODEX_REVIEW_APPROVED` (the completion promise) to exit the loop. You're done.
- **`needs-attention`** — Codex found issues. Proceed to Step 4.

### Step 4: Fix Each Finding

For each finding in the review output:

1. **Read the flagged code** — open the file at the reported lines. If line numbers are stale, search for the function/pattern mentioned.
2. **Understand the issue** — don't just patch the symptom. Understand why Codex flagged it and what the real risk is. The adversarial review questions design choices, so some findings may require rethinking an approach rather than adding a try/catch.
3. **Apply the fix** — make the code change. Match the codebase's existing patterns and conventions.
4. **Verify locally** — run the project's test suite and linter. Detect these from `package.json`, `Makefile`, `pyproject.toml`, or ask the user on the first iteration. All checks must pass before committing.
5. **Commit the fix** — write a descriptive commit message that references the Codex finding:
   ```
   fix(<scope>): <what you fixed>

   Addresses Codex adversarial review finding: <brief description>
   ```

Repeat for every finding in this review pass before letting the loop continue.

### Step 5: Loop Continues

After committing all fixes, the iteration ends. Ralph-loop re-feeds the same prompt, starting a fresh cycle. The next iteration will see your commits in git history and run a new adversarial review against `main` — which now evaluates your fixes plus any remaining issues.

## Customizing the Loop

### Different Base Branch

If comparing against a branch other than `main`:

```
/ralph-loop:ralph-loop "Run a Codex adversarial review loop. Each iteration: (1) invoke /superpowers:using-superpowers, (2) run /codex:adversarial-review --wait --base develop, (3) if 'needs-attention' fix all findings and commit, if 'approve' output the completion promise." --max-iterations 10 --completion-promise "CODEX_REVIEW_APPROVED"
```

### Focused Review

Add focus text to steer the review toward specific concerns:

```
/codex:adversarial-review --wait --base main error handling and concurrency
```

### Max Iterations

The `--max-iterations` flag on ralph-loop is a safety net, not a target. Default of 10 is generous — most code reaches approval in 2-4 rounds. Increase it if you're working on a large changeset with many files.

## Important Constraints

- **Don't auto-apply fixes without understanding them.** Codex adversarial review is review-only. It flags issues but the fixes are your responsibility. Read the finding, understand the risk, then fix it properly.
- **Don't output the completion promise prematurely.** Ralph-loop enforces this — only output `CODEX_REVIEW_APPROVED` when Codex genuinely returns `approve`. Attempting to escape the loop early defeats the purpose.
- **Don't skip verification.** Every fix must pass tests before committing. A fix that breaks tests is worse than the original issue.
- **Don't ignore design-level feedback.** Unlike a linter, adversarial review may challenge your entire approach. If Codex says "this pattern will fail under concurrent writes," adding a mutex might not be enough — you may need to rethink the design.

## Troubleshooting

### Codex keeps finding new issues each round
This is normal for the first 2-3 rounds — fixes can expose previously-hidden issues. If it persists beyond 5 rounds, check whether your fixes are introducing new problems or if there's a fundamental design issue worth discussing with the user.

### Review output is empty or malformed
Check that the codex plugin is properly installed: the adversarial-review command should be available. If the review returns no findings and no explicit verdict, do NOT treat it as approval — this likely indicates a plugin failure, parse error, or command issue. Retry the review. Only exit the loop when Codex explicitly returns `verdict: approve`.

### Tests fail after applying fixes
Don't commit. Debug the test failure first. Your fix may have introduced a regression or the test may be asserting outdated behavior that your fix correctly changed (in which case, update the test).
