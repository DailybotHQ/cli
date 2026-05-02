# PR Review Workflow

How to read and respond to bot review comments on a PR without picking up stale feedback.

## Why This Doc Exists

If automated reviewers are wired into this repo, they typically re-run on every push. When a reviewer leaves comments and you push a fix, the reviewer **collapses** its previous comments as `OUTDATED` and posts a fresh review.

If you naively read all comments on a PR, you'll mix the latest review with stale feedback from earlier pushes — and risk re-implementing fixes that were already applied.

## The Rules

1. **Skip `isMinimized == true` comments.** GitHub auto-collapses outdated review threads with this flag.
2. **Find the most recent `<!-- claude-review-marker -->` comment.** This HTML comment is left by the reviewer at the start of every review pass, and it includes the SHA the review was performed against.
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

1. **Identify the live review SHA.** Filter top-level comments where `isMinimized == false` and `body` contains `<!-- claude-review-marker -->`. The most recent one is authoritative.
2. **Filter review threads.** For each thread, drop any comment with `isMinimized == true`. Keep threads where at least one live comment survives.
3. **Apply.** For each surviving comment, decide:
   - Is the issue still real on the current SHA?
   - Is it a duplicate of something already addressed?
   - Is it actionable, or just informational?
4. **Reply or push a fix.** If you push a fix, the bot will re-review and the previous live comments become `OUTDATED` automatically.

## Common Pitfalls

| Pitfall | Fix |
|---------|-----|
| "I see 30 comments but only 5 are real" | You're reading minimized ones; filter by `isMinimized == false` |
| "I fixed something the reviewer already verified" | You read a stale review; anchor on the latest marker SHA |
| "The bot keeps complaining about a thing I already fixed" | Your fix didn't actually land in a commit, or was reverted in a later push |
| "Two PRs from different agents are diverging" | Coordinate via the PR description; one agent should own the rebase |

## When There's No `<!-- claude-review-marker -->`

If the PR doesn't have automated review (e.g., human-only), the rules collapse:

- Read all non-minimized comments.
- Use commit timestamps and `createdAt` to order them.
- Trust the most recent feedback per file.

## What This Repo Does

This repo (`cli`) does not yet have an automated reviewer wired in. When that changes, this doc and `AGENTS.md` should be updated together — make sure they reference the actual marker tag the reviewer emits.
