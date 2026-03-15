# Workflow for Applying Codex Fixes

When Codex posts a review comment with feedback, here's how to apply fixes:

## Step 1: Understand the Feedback

Read the Codex comment carefully. It will typically:
- Mention the **file** and **line number(s)**
- Describe the **problem** (missing error handling, wrong pattern, performance issue, etc.)
- Suggest a **fix** (not always explicit, sometimes implied)

Example Codex comment:
```
**Line 42 in src/worker/provision-processor.ts**

Missing error handling. The `findUnique` call in `applyBdReferralCredit`
can throw a database error, but there's no try-catch around it.
This could fail the provisioning job.

Suggested fix: Wrap the entire function body in try-catch.
```

## Step 2: Locate and Fix the Code

1. Open the file mentioned by Codex
2. Navigate to the line number
3. Apply the suggested fix (or equivalent fix if suggestion needs adaptation)
4. Read the surrounding code to ensure the fix makes sense

Example fix:
```typescript
// BEFORE (Codex flagged this)
async function applyBdReferralCredit(...) {
  const referral = await prisma.bdReferral.findUnique(...); // Can throw!
  // ... rest of function
}

// AFTER (Your fix)
async function applyBdReferralCredit(...) {
  try {
    const referral = await prisma.bdReferral.findUnique(...);
    // ... rest of function
  } catch (error) {
    console.error("Credit grant failed:", error);
    // ... error handling
  }
}
```

## Step 3: Verify the Fix Locally

Run the project's verification commands to ensure your fix doesn't break anything:

```bash
# Run your project's test suite (detect from package.json, or ask user)
# Examples: npm run test:unit, npm test, pytest, go test ./...
<your-test-command>

# Run your project's linter (detect from package.json, or ask user)
# Examples: npm run lint, flake8, golangci-lint run
<your-lint-command>

# Run your project's build (if applicable — detect from package.json or ask user)
# Examples: npm run build, cargo build, go build ./...
<your-build-command>
```

All of these should pass. If not, adjust your fix.

## Step 4: Commit the Fix

Use the `/commit` skill to create a descriptive commit:

```
/commit

# In the commit message, reference Codex's feedback:
fix(provision): add error handling in applyBdReferralCredit

Codex flagged that findUnique can throw database errors without
being caught. Wrap function body in try-catch with appropriate
error logging and recovery logic.

Addresses Codex review feedback on src/worker/provision-processor.ts line 42.
```

## Step 5: Push to the Branch

Push your changes to the PR branch:

```bash
git push
```

## Step 6: Request Another Review

Comment on the PR to ask Codex to review again:

```
@codex, please review again.

I've applied fixes for the feedback on src/worker/provision-processor.ts.
Added try-catch error handling in applyBdReferralCredit and verified
with <your-test-command>. Ready for re-review.
```

## Multiple Issues in One Comment

If Codex mentions multiple issues in a single comment, fix **all of them** before requesting re-review.

Example Codex comment with multiple issues:
```
File: src/app/api/stripe/webhook/route.ts

1. **Line 1979**: Use hydrated invoice amount_paid, not billingObject.amount_paid
2. **Line 2028**: Defer BD commission creation until after capacity-blocked check
3. **Line 325**: Serialize key limit updates with advisory lock

All three need fixes for the BD referral system to be robust.
```

Fix all three, verify tests pass, commit, push, then request re-review.

## When a Fix Fails

Sometimes Codex will comment again on the same issue even after you've tried to fix it.

**Example scenario:**
1. Codex flags: "Missing error handling in X"
2. You add try-catch
3. Codex responds: "That's better, but the error recovery logic is incomplete"

This is normal. Apply the new feedback and re-request review. The loop will continue until Codex is satisfied.

## Handling Ambiguous Feedback

Sometimes Codex's feedback might be unclear or could be implemented multiple ways.

**Best practice**: Apply your best interpretation of the feedback, commit, and let Codex respond. If your interpretation is off, Codex will provide clarification. This is faster than trying to guess.

## When to Ask for Clarification

If Codex feedback references code that doesn't exist or seems impossible to apply:

1. Manually inspect the file and line numbers
2. Post a PR comment asking for clarification: `@codex, the file/line you referenced seems outdated. Can you point to the exact code that needs fixing?`
3. Wait for Codex's response

**Note**: This breaks the automation loop, so use only when truly stuck.
