# PR Review Workflow

How to read and respond to bot review comments on a PR without picking up stale feedback.

## Why This Doc Exists

When an automated reviewer runs more than once on a PR, it **collapses** its previous comments as `OUTDATED` and posts a fresh review. In this repo the re-run is **label-gated, not push-triggered**: the workflow deliberately omits the `synchronize` event, so pushing a fix does NOT re-review — a maintainer must remove and re-apply the `Ready` label (see [Re-running the review after a fix push](#re-running-the-review-after-a-fix-push)).

If you naively read all comments on a PR, you'll mix the latest review with stale feedback from earlier pushes — and risk re-implementing fixes that were already applied.

## The Rules

1. **Skip `isMinimized == true` comments.** GitHub auto-collapses outdated review threads with this flag.
2. **Find the most recent review marker comment.** Prefer `<!-- ai-pr-reviewer-marker -->` (AI Diff Reviewer / Flow B CI). Legacy Claude reviews may still use `<!-- claude-review-marker -->`. The marker includes the SHA the review was performed against.
3. **Only act on comments tied to that SHA.** Anything older is stale.

## GraphQL Query (ready to copy)

```graphql
query PRReviewComments($owner: String!, $repo: String!, $number: Int!) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $number) {
      reviewThreads(first: 100) {
        nodes {
          isResolved
          isOutdated
          comments(first: 50) {
            nodes {
              id
              author { login }
              body
              isMinimized
              minimizedReason
              createdAt
              path
              line
            }
          }
        }
      }
      comments(first: 100) {
        nodes {
          author { login }
          body
          isMinimized
          createdAt
        }
      }
    }
  }
}
```

Run via `gh`:

```bash
gh api graphql -f query='...' -F owner=DailyBotHQ -F repo=cli -F number=<PR>
```

## Step-by-Step

1. **Identify the live review SHA.** Filter top-level comments where `isMinimized == false` and `body` contains `<!-- ai-pr-reviewer-marker -->` (or the legacy `<!-- claude-review-marker -->`). The most recent one is authoritative.
2. **Filter review threads.** For each thread, drop any comment with `isMinimized == true`. Keep threads where at least one live comment survives.
3. **Apply.** For each surviving comment, decide:
   - Is the issue still real on the current SHA?
   - Is it a duplicate of something already addressed?
   - Is it actionable, or just informational?
4. **Reply or push a fix.** Pushing alone does NOT re-review in this repo (no `synchronize` trigger). After the fix push, remove + re-apply the `Ready` label; the fresh review then collapses the previous live comments as `OUTDATED`.

## Common Pitfalls

| Pitfall | Fix |
|---------|-----|
| "I see 30 comments but only 5 are real" | You're reading minimized ones; filter by `isMinimized == false` |
| "I fixed something the reviewer already verified" | You read a stale review; anchor on the latest marker SHA |
| "The bot keeps complaining about a thing I already fixed" | Your fix didn't actually land in a commit, or was reverted in a later push |
| "Two PRs from different agents are diverging" | Coordinate via the PR description; one agent should own the rebase |

## When There's No Review Marker

If the PR doesn't have automated review (e.g., human-only, or `Ready` never applied), the rules collapse:

- Read all non-minimized comments.
- Use commit timestamps and `createdAt` to order them.
- Trust the most recent feedback per file.

## What This Repo Does

This repo (`cli`) uses **AI Diff Reviewer v2** in Flow B (local skill + CI):

- **CI workflow:** [`.github/workflows/pr-review.yml`](../.github/workflows/pr-review.yml)
- **Trigger:** apply the **`Ready`** label on a PR targeting `main` (remove + re-add to re-run)
- **Extension:** [`.review/extension.md`](../.review/extension.md) (shared by local + CI)
- **Merge gate check name:** `AI review gate`
- **Secret:** `CURSOR_API_KEY`
- **Emergency bypass:** `skip-ai-review` (protect with a ruleset if the gate is required)
- **Marker:** `<!-- ai-pr-reviewer-marker -->`

Local reviews (DWP Security Review augmentation) use the vendored skill at
[`.agents/skills/ai-diff-reviewer/`](../.agents/skills/ai-diff-reviewer/).

## Re-running the review after a fix push

The workflow triggers only on `opened` and `labeled` — **not** `synchronize`
(cost control). Consequences every maintainer must know:

1. **Pushing a fix does not re-review.** The `AI review gate` check keeps its
   last verdict, so a PR can accumulate unaudited commits while the gate stays
   green. After every fix push, remove + re-apply the **`Ready`** label to
   force a fresh review of the new HEAD.
2. **Check the marker SHA before trusting a green gate.** The live
   `<!-- ai-pr-reviewer-marker -->` comment records the SHA it reviewed; if it
   is not the PR's current HEAD, the verdict is stale — re-label before merging.

## Fork and external-contributor PRs skip the gate

The `scope` job only runs the review for authors in the
`author-association` whitelist (`OWNER,MEMBER,COLLABORATOR`) — an API-budget
protection. For fork/external PRs the review job is skipped, and **GitHub
treats a skipped required check as passing**, so `AI review gate` is satisfied
without any review having run. Maintainers must therefore:

- **Review fork PRs by hand** (or push the branch to the main repo and apply
  `Ready` from a trusted account to get an AI pass).
- **Not treat a green `AI review gate` on a fork PR as evidence of review** —
  it only means the gate was skipped by design.
