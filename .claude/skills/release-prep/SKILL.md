---
name: release-prep
description: Pre-tag checklist and version bump for cutting a Dailybot CLI release.
trigger: /release-prep or #release-prep
inputs: Target version number (e.g., 0.4.13). The user must provide this — do not infer.
prereqs: Working tree clean. CI green on main. User has explicitly asked to cut a release.
---

# Skill: `release-prep`

Walks through the pre-tag checklist before a release. **Does not push the tag** — that's an explicit user action after this skill completes.

> Releases are irreversible (PyPI versions can't be re-uploaded). Treat this skill as a careful pre-flight, not a one-click button.

## Pre-flight

The user MUST explicitly ask to cut a release and provide the target version. If they didn't:

> **STOP**. Ask: "What version are we cutting? (e.g., 0.4.13). And to confirm — you want me to bump the version, run the checks, and prepare the tag command? You'll push the tag yourself."

## Procedure

### 1. Read the current state

```bash
git status -s                  # must be clean
git rev-parse --abbrev-ref HEAD  # confirm we're on main (or the user's release branch)
git log --oneline main..HEAD   # what's in this release? (if not on main)
git log --oneline -10          # recent context
```

If the working tree isn't clean, stop. Ask the user to commit/stash first.

### 2. Confirm the version bump

Read `pyproject.toml::project.version`. Confirm with the user:

> "Current version is X.Y.Z. Bumping to <target>. Last 10 commits since the previous tag are: <list>. Proceed?"

If the diff doesn't justify the bump (e.g., trying to bump minor for a one-line typo fix), surface that.

### 3. Run pre-release checks

```bash
pytest -x
```

If a test fails, stop. The fix goes in its own commit (or PR) before the release.

If linting/type-checking is wired:

```bash
ruff check dailybot_cli tests
ruff format --check dailybot_cli tests
mypy dailybot_cli
```

### 4. Check the dependency graph (if any deps changed)

If `pyproject.toml::dependencies` changed since the last release:

- The Homebrew formula in `.github/workflows/release.yml` MUST list every transitive dep as a `resource` block with current sha256.
- Walk through the formula and confirm each `resource` entry exists for the latest version.

If a dep is missing or stale:

```bash
pip download <pkg>==<version> --no-binary :all: --no-deps -d /tmp
sha256sum /tmp/<pkg>-<version>.tar.gz
```

Update the inline formula in `release.yml` with the new URL + sha. Commit separately.

### 5. Bump the version

Edit `pyproject.toml`:

```toml
version = "<new-version>"
```

Commit on its own:

```bash
git add pyproject.toml
git commit -m "Version bump"
```

### 6. Final pre-tag checks

```bash
git status -s              # should be clean
git log --oneline -3       # last commit should be the version bump
pytest -x                  # final sanity
dailybot --version         # confirm runtime picks up the new version after re-installing locally
```

### 7. Prepare the tag command

**Don't run it.** Print it for the user to execute:

```
Ready to tag. Run when you're ready:

  git push origin <branch>
  git tag v<new-version>
  git push origin v<new-version>

The tag push triggers .github/workflows/release.yml which:
  - Publishes to PyPI
  - Builds the Linux x86_64 binary
  - Creates a GitHub Release
  - Updates the dailybothq/homebrew-tap formula

Watch progress at: https://github.com/DailyBotHQ/cli/actions
```

### 8. After the user pushes the tag

(Optional follow-up if the user asks you to monitor the release.)

```bash
gh run list --workflow=release.yml -L 1
gh run watch <run-id>          # streams the workflow output
```

After completion:

```bash
pip install --upgrade dailybot-cli            # confirm PyPI
dailybot --version                            # should match the new tag
gh release view v<new-version>                # confirm GitHub Release exists with the binary
```

## Checklist (paste this into the chat for visibility)

- [ ] Working tree clean
- [ ] `pytest -x` green
- [ ] Linting / type-checking green (if configured)
- [ ] Homebrew formula in `release.yml` has a `resource` block for every dep
- [ ] `pyproject.toml::project.version` bumped
- [ ] Version bump is in its own commit named `Version bump`
- [ ] Tag command prepared but NOT pushed (user pushes)
- [ ] User has been told what the workflow will do

## Don'ts

- **Don't push the tag yourself.** The user must do this explicitly.
- **Don't bump the version + change other code in the same commit.** "Version bump" is its own commit.
- **Don't skip the tests.** A failing test that was about-to-be-fixed-anyway is still a failing test.
- **Don't bump a version that's already on PyPI.** PyPI rejects re-uploads. Pick the next number.
- **Don't update `install.sh` or the CDN-served install script as part of this skill** — the hosted installer at `cli.dailybot.com/install.sh` is updated out-of-band, separate from a release.
