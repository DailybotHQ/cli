---
name: release-prep
description: Pre-tag checklist and version bump for cutting a Dailybot CLI release. Supports both manual (.pypirc) and automated (GitHub Actions) flows.
trigger: /release-prep or #release-prep
inputs: Target version number (e.g., 0.4.13). Which flow to use: "manual" or "automated".
prereqs: Working tree clean. CI green on main. User has explicitly asked to cut a release.
---

# Skill: `release-prep`

Walks through the pre-release checklist for cutting a release. **Does not push the tag or upload to PyPI** — those are explicit user actions after this skill completes.

> Releases are irreversible (PyPI rejects re-uploads of an existing version). Treat this skill as a careful pre-flight, not a one-click button.

## Pre-flight

The user MUST explicitly ask to cut a release and provide:

1. **Target version** (e.g., `0.4.13`).
2. **Which flow**: manual (local `twine` with `.pypirc`) or automated (push tag, let `release.yml` handle it).

If either is missing:

> **STOP**. Ask: "What version are we cutting (e.g., 0.4.13)? And do you want the manual flow (local `twine` with `.pypirc`) or the automated flow (push tag, GitHub Actions handles PyPI + Linux binary + Homebrew)?"

If the user is unsure which flow, ask whether the GitHub repo has `PYPI_API_TOKEN` and `HOMEBREW_TAP_TOKEN` configured (`gh secret list`). If yes → automated is the default. If no → manual.

## Common Procedure (both flows)

### 1. Read the current state

```bash
git status -s                  # must be clean
git rev-parse --abbrev-ref HEAD  # confirm we're on main
git log --oneline -10
```

If the working tree isn't clean, stop. Ask the user to commit/stash first.

### 2. Confirm the version bump

Read `pyproject.toml::project.version`. Confirm with the user:

> "Current version is X.Y.Z. Bumping to <target>. Last 10 commits since the previous tag are: <list>. Proceed?"

If the diff doesn't justify the bump (e.g., bumping minor for a one-line typo fix), surface that.

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

### 4. Sync the Homebrew formula (if deps changed since last release)

For the **automated flow**, the formula is rendered inline in `.github/workflows/release.yml` as a Python heredoc. For the **manual flow**, the formula lives in `dailybothq/homebrew-tap/Formula/dailybot.rb` and is updated separately.

If `pyproject.toml::dependencies` changed since the last release, every transitive dep needs a current `resource` block:

```bash
pip download <pkg>==<version> --no-binary :all: --no-deps -d /tmp
sha256sum /tmp/<pkg>-<version>.tar.gz
```

Update the relevant location with new URL + sha. Commit separately.

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

---

## Manual Flow

### 6m. Verify `.pypirc` is configured

```bash
# Repo-local
ls -la ./.pypirc 2>/dev/null && stat -f "%Lp" ./.pypirc   # must show 600

# Or standard
ls -la ~/.pypirc 2>/dev/null && stat -f "%Lp" ~/.pypirc
```

Both must contain a `[pypi]` section and ideally a `[testpypi]` section. If missing, point the user at [docs/RELEASE_AND_DISTRIBUTION.md](../../../docs/RELEASE_AND_DISTRIBUTION.md#one-time-setup).

### 7m. Build

```bash
rm -rf dist/ build/ *.egg-info/
python -m build
twine check dist/*
ls dist/
```

### 8m. Print the upload commands. Do not run.

```
Ready to publish manually. Run when you're ready:

  # 1. Verify on TestPyPI
  twine upload --config-file ./.pypirc --repository testpypi dist/*
  #    (or: twine upload --repository testpypi dist/*  if using ~/.pypirc)

  # 2. Smoke-test in a fresh venv
  python3 -m venv /tmp/dailybot-test && source /tmp/dailybot-test/bin/activate
  pip install --index-url https://test.pypi.org/simple/ \
              --extra-index-url https://pypi.org/simple/ \
              dailybot-cli==<X.Y.Z>
  dailybot --version
  deactivate && rm -rf /tmp/dailybot-test

  # 3. Real PyPI
  twine upload --config-file ./.pypirc dist/*

  # 4. Tag
  git tag v<X.Y.Z>
  git push origin main
  git push origin v<X.Y.Z>
```

> **Heads-up:** if `release.yml` is wired up with a valid `PYPI_API_TOKEN`, pushing the tag will also fire the workflow, which will fail at the PyPI step (version already exists). That's harmless but noisy. Mention it to the user.

### 9m. (Optional) Linux binary + Homebrew

If the manual flow needs to cover those too, the user runs them after PyPI succeeds. Point them at the relevant sections of [docs/RELEASE_AND_DISTRIBUTION.md](../../../docs/RELEASE_AND_DISTRIBUTION.md).

---

## Automated Flow

### 6a. Verify GitHub secrets

```bash
gh secret list
```

Must show both `PYPI_API_TOKEN` and `HOMEBREW_TAP_TOKEN`. If missing, the workflow will fail. Tell the user to set them via `gh secret set <NAME>` before tagging.

### 7a. Print the tag commands. Do not run.

```
Ready to release via GitHub Actions. Run when you're ready:

  git push origin main
  git tag v<X.Y.Z>
  git push origin v<X.Y.Z>

The tag push triggers .github/workflows/release.yml which:
  - Builds the Linux x86_64 binary in a glibc 2.31 container
  - Publishes to PyPI
  - Creates a GitHub Release with the binary attached
  - Updates dailybothq/homebrew-tap

Watch progress at: https://github.com/DailyBotHQ/cli/actions
Or stream:         gh run watch
```

### 8a. After the user pushes the tag

(Optional follow-up if the user asks you to monitor the release.)

```bash
gh run list --workflow=release.yml -L 1
gh run watch <run-id>
```

After completion:

```bash
pip install --upgrade dailybot-cli && dailybot --version
gh release view v<X.Y.Z>
brew upgrade dailybot 2>/dev/null && dailybot --version
```

If any of these fail, surface to the user. Do not retry the workflow without diagnosing the failure.

---

## Hard Rules (NEVER violate)

1. **Never push a tag without an explicit "yes, push it" from the user.**
2. **Never run `twine upload` to real PyPI without an explicit "go ahead" from the user.**
3. **Never reuse a version that's been on PyPI before.** PyPI rejects re-uploads.
4. **Never bump the version + ship code in the same commit.** Version bumps are their own commit.
5. **Never skip the Homebrew formula update** when a dep changed.
6. **Never edit `install.sh` as part of a release** unless the user explicitly asks (CDN coordination required).
7. **Never commit `.pypirc`.** It's git-ignored, but `git status` it before any commit during release prep.

## Pre-Release Checklist (paste into chat)

### Common
- [ ] Working tree clean
- [ ] On `main` (or designated release branch)
- [ ] `pytest -x` green
- [ ] `pyproject.toml::project.version` bumped in its own commit named `Version bump`
- [ ] User has explicitly stated the target version
- [ ] User has explicitly asked to cut the release

### Manual flow only
- [ ] `.pypirc` exists and is `chmod 600`
- [ ] `python -m build` succeeded; `twine check dist/*` passed
- [ ] TestPyPI upload + smoke-test passed
- [ ] Real PyPI upload commands prepared but NOT run (user runs)
- [ ] Tag commands prepared but NOT pushed (user runs)

### Automated flow only
- [ ] `gh secret list` confirms `PYPI_API_TOKEN` and `HOMEBREW_TAP_TOKEN` exist
- [ ] No partial manual upload to PyPI for this version
- [ ] If deps changed: inline Homebrew formula in `release.yml` updated
- [ ] Tag commands prepared but NOT pushed (user runs)
