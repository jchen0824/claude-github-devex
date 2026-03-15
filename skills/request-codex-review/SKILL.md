---
name: request-codex-review
description: Automate Codex code review on GitHub PRs with full fix-and-iterate loops. Use this whenever you need to request Codex review for a PR and have it automatically poll for feedback, apply fixes, commit changes, and iterate until completion. Mention this for requests like "request codex review for PR #42", "run codex review on this PR", "trigger codex review for owner/my-repo#42", or "apply codex feedback automatically". The skill handles the complete loop—polling, detecting issues, reading and fixing code, running tests, committing, pushing, re-requesting review, and repeating until Codex gives "good to go" or the PR gets a thumbs-up.
---

# Request Codex Review — Automated Loop

Fully automate Codex code review polling, feedback detection, fix application, and iteration until completion.

## Quick Start

When you ask for Codex review on a PR, you need to provide:
- **Repository owner** (e.g., `owner`)
- **Repository name** (e.g., `my-repo`)
- **Pull request number** (e.g., `42`)

Or just ask: `"codex review for PR #42"` and infer from git context if in a repo.

The skill will then **automatically**:
1. Poll for Codex feedback every 3 minutes
2. When Codex posts comments, extract the issues
3. Read the flagged files and apply fixes
4. Run verification (tests, linting)
5. Commit and push changes
6. Request another review
7. Repeat until Codex says "good to go"

## Prerequisites

Before using this skill, ensure:
- ✅ GitHub CLI (`gh`) is authenticated: `gh auth status`
- ✅ You're in the repository root directory
- ✅ The PR branch is checked out and ready to modify
- ✅ Project has test/lint commands available (`<your-test-command>`, `<your-lint-command>`, etc.)

## The Automated Workflow

### Phase 1: Initialize & Poll

**Your role**: Provide owner/repo/PR number (or ask to infer from git)

**Claude's role**:
1. Extract owner, repo, PR number from your request
2. Initialize state file path: `.codex/codex-review-loop-state-pr<PR>.json`
3. Run the polling script **once** (non-blocking):
   ```bash
   # Locate the bundled orchestration script from the plugin install cache
   ORCHESTRATE_SCRIPT=$(find ~/.claude/plugins -name "orchestrate_codex_review.py" 2>/dev/null | head -1)

   python3 "$ORCHESTRATE_SCRIPT" \
     <owner> <repo> <pr> \
     .codex/codex-review-loop-state-pr<pr>.json \
     --once
   ```
4. Capture JSON output and check `status` field:
   - **`needs_action`** → Go to Phase 2
   - **`waiting`** → Wait 3 minutes, return to step 3
   - **`completed`** → Go to Phase 4
   - **`error`** → Report error and exit

### Phase 2: Extract & Parse Feedback

**When Codex posts new comments** (status: `needs_action`)

**Claude's role**:
1. Parse the JSON output from the polling script
2. Extract `new_comments` array from the response
3. For each comment, record:
   - `id` — needed to reply directly to this comment thread
   - `source` — `"review_comment"` (line-level) or `"issue_comment"` (top-level)
   - `body` (the Codex feedback text)
   - **file path** (mentioned in comment or inferred from context)
   - **line number(s)** (mentioned in comment)
   - **issue summary** (what Codex flagged)
   - **suggested fix** (explicit or implied in comment)

**Example Codex comment**:
```
File: src/worker/provision-processor.ts
Lines: 295-310

Missing error handling in applyBdReferralCredit. The findUnique and updateMany
calls execute before the try/catch, so a transient DB error here escapes
the function and can fail the provisioning job.

Suggested fix: Wrap entire function body in try/catch with referralId
tracking outside the try block.
```

**Claude extracts**:
- File: `src/worker/provision-processor.ts`
- Lines: `295-310`
- Issue: "DB errors in findUnique/updateMany escape and fail provisioning"
- Fix: "Wrap function body in try/catch"

### Phase 3: Apply Fixes (Automated)

**For each Codex comment**, Claude must:

#### Step 3a: Read the Code
```bash
# Read the flagged file
cat src/worker/provision-processor.ts
```

Locate the exact lines mentioned by Codex. If line numbers are off, search for the function/code block mentioned.

#### Step 3b: Understand the Issue
Before writing fixes, understand:
- **What Codex flagged**: The specific problem (missing error handling, performance issue, wrong pattern)
- **Why it's a problem**: Context or impact (could fail provisioning, security risk, maintainability)
- **Existing code context**: Surrounding functions, error patterns used elsewhere in the file

#### Step 3c: Apply the Fix
Make the code change directly. Examples:

**Example 1: Add error handling**
```typescript
// BEFORE (Codex flagged this)
async function applyBdReferralCredit(...) {
  const referral = await prisma.bdReferral.findUnique(...); // Can throw!
  // ... rest of function
}

// AFTER (Your fix)
let referralId = null;
try {
  const referral = await prisma.bdReferral.findUnique(...);
  if (!referral) return;
  // ... rest of function
  referralId = referral.id;
} catch (error) {
  console.error("Credit grant failed:", error);
  if (referralId) {
    await prisma.bdReferral.updateMany(...).catch(() => {});
  }
}
```

**Example 2: Use advisory lock for serialization**
```typescript
// BEFORE (Codex flagged concurrent write race condition)
const currentLimit = await getProvisionedKeyByHash({ keyId });
await updateProvisionedKeyLimit({ keyId, limit: currentLimit + 3 });

// AFTER (Your fix)
await runSerializableTransactionWithRetries(async (tx) => {
  await tx.$executeRaw`SELECT pg_advisory_xact_lock(hashtext(${keyId}))`;
  const keyDetails = await getProvisionedKeyByHash({ keyId });
  await updateProvisionedKeyLimit({ keyId, limit: keyDetails.limit + 3 });
});
```

**Example 3: Defer operation until after guard check**
```typescript
// BEFORE (Codex flagged phantom records on rollback)
const bdFirstPaymentAmountCents = billingObject.amount_paid ?? 0;
if (billingReason === "subscription_create" && bdPartnerMetadata?.bdPartnerId) {
  await createBdCommissionForFirstPayment(...); // Created before capacity check!
}

const provisioningResult = await createOrEnqueueProvisioningJob(...);

if (provisioningResult.kind === "capacity_blocked") {
  await rollbackCapacityBlockedSubscription(...); // But subscription rolled back!
}

// AFTER (Your fix)
const bdFirstPaymentAmountCents = billingObject.amount_paid ?? 0;

const provisioningResult = await createOrEnqueueProvisioningJob(...);

if (provisioningResult.kind === "capacity_blocked") {
  await rollbackCapacityBlockedSubscription(...);
  return NextResponse.json({ received: true }); // Early return, skip commission
}

// Only create commission after capacity guard passes
if (billingReason === "subscription_create" && bdPartnerMetadata?.bdPartnerId) {
  await createBdCommissionForFirstPayment(...);
}
```

#### Step 3d: Verify the Fix Locally
Run project verification commands:

> **Before starting the loop**: detect the project's verification commands from `package.json` scripts (look for keys like `test`, `test:unit`, `lint`), or ask the user which commands to run.

```bash
# Detect and run your project's test suite.
# Auto-detect from package.json scripts, or ask the user.
# Examples: npm run test:unit, npm test, pytest, go test ./...
<your-test-command>

# Detect and run your project's linter.
# Examples: npm run lint, flake8, golangci-lint run
<your-lint-command>
```

**All must pass**. If they don't:
- Review your fix
- Check if you introduced a new bug
- Adjust and re-test
- If the fix is fundamentally wrong, explain the issue in the PR comment when you request re-review

#### Step 3e: Commit the Fix
Use the `/commit` skill to create a descriptive commit:

**Commit message format**:
```
<type>(<scope>): <subject>

<body - explain the fix>

Addresses Codex review feedback on <file>:<lines>
```

**Example**:
```
/commit

fix(provision): guard BD credit errors from failing provisioning

- Wrap entire applyBdReferralCredit body in try/catch so transient DB
  errors in findUnique/updateMany don't escape and deprovision a running
  instance. referralId is tracked outside the try block so the APPLYING
  → FAILED rollback still works when the error fires after the claim.

Addresses Codex review feedback on src/worker/provision-processor.ts:295-310
```

#### Step 3f: Reply to This Comment's Thread

Immediately after committing, reply **directly to this specific Codex comment thread** — before moving to the next comment. Use the comment's `id` and `source` from Phase 2:

**If `source == "review_comment"`** (line-level):
```bash
gh api repos/{owner}/{repo}/pulls/{pr}/comments/{comment_id}/replies \
  --method POST \
  --field body="@codex I've applied the fix you suggested:

- [File]: <file>
- [Change]: <description of fix>
- [Verification]: <your-test-command> ✅ passed"
```

**If `source == "issue_comment"`** (top-level — no thread reply API):
```bash
gh api repos/{owner}/{repo}/issues/{pr}/comments \
  --method POST \
  --field body="@codex I've applied the fix you suggested (in reply to your comment <comment_url>):

- [File]: <file>
- [Change]: <description of fix>
- [Verification]: <your-test-command> ✅ passed"
```

### Phase 3 Loop

When there are **multiple Codex comments in the same round**, repeat steps 3a–3f **for each comment individually** — apply fix, verify, commit, then reply to that specific comment's thread before moving to the next.

After **all comments** are processed, push all commits at once:

```bash
git push
```

### Phase 4: Request Another Review

Since each Codex comment already has an individual reply (Step 3f), post a single top-level PR comment to trigger the next review pass:

```bash
gh pr comment {pr} --repo {owner}/{repo} --body "@codex, please review again.

I've addressed all feedback from this review pass. Please perform
another code quality pass on the updated code."
```

This asks Codex to perform another full review.

### Phase 5: Loop Back (Repeat Cycle)

1. **Wait 3-5 minutes** (Codex is working)
2. **Poll again** (go back to Phase 1, step 3)
3. Codex will either:
   - Post new feedback → Apply new fixes (Phase 2-4)
   - Post "good to go" → Loop completes (Phase 6)
   - React with 👍 → Loop completes (Phase 6)

### Phase 6: Report Completion

When polling returns `status: completed`:

Output:
```
Completed the code quality guardrail workflow.

Summary:
- Total review cycles: <N>
- Issues found and fixed: <count>
- All Codex feedback addressed ✅
```

## Handling Edge Cases

### Multiple Issues in One Comment
If Codex posts one comment with 3 issues:
1. Extract all 3 from the JSON
2. Apply all 3 fixes to the code
3. Run tests once (after all fixes)
4. Commit all fixes together
5. Then request re-review

**Don't** commit after each individual fix.

### Codex References Moved/Non-Existent Code
If Codex mentions lines that don't exist or reference outdated code:
1. Read the full file and search for the function/pattern mentioned
2. Make your best judgment on what needs fixing
3. Apply the fix based on the intent (even if line numbers are stale)
4. When requesting re-review, note: "Line numbers in previous review were outdated, but I've applied the fix to [function X]"

Codex will clarify if your interpretation was wrong.

### Fix Breaks Tests
If `<your-test-command>` or `<your-lint-command>` fails after your fix:
1. **Don't commit** — read the error
2. Debug locally:
   - What tests are failing?
   - What does the error message say?
   - Does your fix have a logic error?
3. Fix the issue and re-test
4. Once tests pass, commit

Repeat as needed until all tests pass before requesting re-review.

### Codex Still Complains After Your Fix
It's normal for Codex to ask for refinements:
- Apply the new feedback
- Test again
- Commit
- Request re-review

This continues until Codex is satisfied.

### Loop Gets Stuck
If polling returns `waiting` for more than 10 minutes and you suspect something is wrong:
1. Check the state file: `.codex/codex-review-loop-state-pr<PR>.json`
2. Look at the `status` field
3. If status is `needs_action` but you've already applied those fixes, manually comment: `@codex, please review again.` and continue polling
4. If status is `error`, check PR comments to see if there's a Codex error message

## Tips for Success

✅ **Do**:
- Apply all feedback from a single review pass before requesting re-review
- Run tests after **every** fix to catch problems early
- Write descriptive commit messages that reference the Codex feedback
- Wait 3-5 minutes between polling (Codex needs time to review)
- Check PR comments if something seems stuck

❌ **Don't**:
- Manually edit the state file (let Codex script manage it)
- Request re-review without running tests first
- Commit fixes individually (batch them)
- Ignore Codex feedback (apply it accurately)
- Panic if Codex asks for multiple iterations (it's normal)

## Example: Full Automation Loop

**You ask**:
```
Request codex review for PR #42 in owner/my-repo
```

**Claude automatically does**:

1. **Polling cycle 1** (Phase 1)
   - Polls PR #42
   - Codex has posted 2 comments flagging issues

2. **Extract feedback** (Phase 2)
   - Comment 1: "Missing error handling in `processPayment` (line 87)"
   - Comment 2: "Potential race condition in `updateBalance` (line 134)"

3. **Apply fix #1** (Phase 3 — Comment 1)
   - Reads `src/payments/processor.ts:87`
   - Wraps function in try/catch with proper error recovery
   - Tests pass ✅
   - Commits: `fix: guard processPayment errors from propagating`
   - Replies directly to Comment 1's thread: "Applied try/catch, tests pass"

4. **Apply fix #2** (Phase 3 — Comment 2)
   - Reads `src/balances/updater.ts:134`
   - Adds serializable transaction with advisory lock
   - Tests pass ✅
   - Commits: `fix: serialize balance updates to prevent race condition`
   - Replies directly to Comment 2's thread: "Added advisory lock, tests pass"
   - Pushes all commits

5. **Request re-review** (Phase 4)
   - Posts top-level: `@codex, please review again.`

6. **Wait & poll** (Phase 5)
   - Waits 3 minutes
   - Polls PR #42
   - Codex posts: "good to go"

7. **Report completion** (Phase 6)
   - Output: `Completed the code quality guardrail workflow.`

All without manual intervention after the initial request!

## Prerequisites Checklist

Before requesting Codex review, verify:

- [ ] `gh auth status` shows you're logged in
- [ ] You're in the repository root directory
- [ ] PR branch is checked out: `git branch --show-current`
- [ ] No uncommitted changes: `git status`
- [ ] Tests pass locally: `<your-test-command>`
- [ ] Linting passes locally: `<your-lint-command>`
- [ ] Plugin installed (polling script bundled): `find ~/.claude/plugins -name "check_codex_review_state.py" | head -1`

If any fail, fix them first before requesting Codex review.
