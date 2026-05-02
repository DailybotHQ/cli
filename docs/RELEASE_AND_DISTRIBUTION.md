# Release & Distribution

The CLI ships through three channels:

1. **PyPI** — Python users, CI pipelines (`pip install dailybot-cli`)
2. **Homebrew tap** — macOS users (`brew install dailybothq/tap/dailybot`)
3. **Linux x86_64 binary** — distros without a recent Python (`curl -sSL https://cli.dailybot.com/install.sh | bash`)

There are **two supported release flows**:

| Flow | When to use | Effort | Surface area |
|------|-------------|--------|--------------|
| [**Manual**](#manual-flow) — local `twine` with `.pypirc` | Emergency hotfix, dry-run on TestPyPI, or when CI is broken | Higher per release | PyPI only (binary + Homebrew skipped) |
| [**Automated**](#automated-flow-github-actions) — `git push --tags` triggers `release.yml` | Default for normal releases | One-time setup | PyPI + Linux binary + GitHub Release + Homebrew |

The automated flow is the **recommended default**. Manual flow is the documented fallback.

## Single Source of Truth: `pyproject.toml`

The version lives in **exactly one place**: `pyproject.toml::project.version`. Everything else reads it dynamically.

- `dailybot --version` → `importlib.metadata.version("dailybot-cli")`
- The git tag `v0.4.13` matches `version = "0.4.13"` (strip the leading `v`)

**Never** hardcode the version anywhere in `dailybot_cli/` source.

---

## Manual Flow

For when you need to publish from your local Mac without going through CI.

### One-time setup

Pick **one** of the three options below. They all produce a working `~/.pypirc` (or repo-local `./.pypirc`); the difference is where the secret lives and how it gets there.

| Option | Best for | Secret lives in |
|---|---|---|
| [Devcontainer env vars](#devcontainer-env-vars-recommended) | Anyone using the VS Code devcontainer / `docker-compose` setup in this repo | `docker/local/cli/.env` (git-ignored) |
| [Repo-local `./.pypirc`](#repo-local-pypirc) | Bare-metal dev not using the devcontainer, who wants per-project tokens | `./.pypirc` (git-ignored) |
| [Standard `~/.pypirc`](#alternative-pypirc) | Bare-metal dev who already has a global PyPI config | `~/.pypirc` |

#### Devcontainer env vars (recommended)

If you're working inside the devcontainer (`docker/local/docker-compose.yaml`), keep your tokens in `docker/local/cli/.env` and let the entrypoint generate `~/.pypirc` for you on container start.

1. Copy the template once:

   ```bash
   cp docker/local/cli/.env.example docker/local/cli/.env
   ```

2. Edit `docker/local/cli/.env` and set either or both:

   ```env
   PYPI_API_TOKEN=pypi-AgEI...
   TESTPYPI_API_TOKEN=pypi-AgEI...
   ```

3. Restart the container so docker-compose reloads `env_file`:

   ```bash
   docker compose -f docker/local/docker-compose.yaml up -d --force-recreate clivscode
   ```

   On startup, `docker/local/cli/entrypoint.sh::setup_pypirc_from_env_for_user` writes `/home/dev-user/.pypirc` with `chmod 600`. If neither token is set, no file is written.

4. Verify inside the container:

   ```bash
   ls -la ~/.pypirc        # should be -rw------- (0600)
   twine check dist/*      # smoke test
   ```

> **Why this is the default for the devcontainer:** the secret never touches the repo or a hand-edited dotfile, and it survives container rebuilds because `.env` is on the host. The generated `~/.pypirc` is regenerated from env vars on every start, so rotating a token is a one-line edit + restart.
>
> **Caveat:** the token is duplicated on disk inside the container at `~/.pypirc`. The container is ephemeral and the file is `0600` for `dev-user` only, but treat it like any other secret-bearing file.

#### Repo-local `./.pypirc`

Create a `.pypirc` file **in the repo root** (`./` ., next to `pyproject.toml`). It is git-ignored — see `.gitignore`.

```ini
[distutils]
index-servers =
    pypi
    testpypi

[pypi]
username = __token__
password = pypi-AgEI...                 # PyPI API token

[testpypi]
repository = https://test.pypi.org/legacy/
username = __token__
password = pypi-AgEI...                 # TestPyPI API token
```

Tokens come from:
- PyPI: <https://pypi.org/manage/account/token/>
- TestPyPI: <https://test.pypi.org/manage/account/token/>

Use the smallest scope possible — project-scoped to `dailybot-cli`, not account-wide.

Restrict permissions:

```bash
chmod 600 .pypirc
```

> **Critical:** never commit `.pypirc`. The file pattern is in `.gitignore`, but double-check with `git status` before any commit.

<a id="alternative-pypirc"></a>
#### Alternative: `~/.pypirc`

If you prefer the standard location (`$HOME/.pypirc`), `twine` reads it automatically without a `--config-file` flag. Same content as above. The trade-off:

| | Repo-local `./.pypirc` | Standard `~/.pypirc` |
|---|------------------------|----------------------|
| Pros | Project-scoped; less risk of cross-project leakage | Standard location; no `--config-file` flag |
| Cons | Must pass `--config-file` every time; one slip and it could be staged | If your home is on a shared/synced drive, the token rides along |

Pick one. Don't keep both — you'll lose track of which is current.

#### Build tools

```bash
pip install build twine
```

### Procedure

#### 1. Pre-flight

```bash
git status -s                    # working tree clean
git rev-parse --abbrev-ref HEAD  # on main
pytest -x                        # green
# Confirm a .pypirc exists (one of the three options above) and is 0600.
# Devcontainer: ~/.pypirc is auto-generated from docker/local/cli/.env on startup.
ls -la ~/.pypirc 2>/dev/null || ls -la ./.pypirc 2>/dev/null
```

#### 2. Bump the version (its own commit)

Edit `pyproject.toml::project.version`, then:

```bash
git add pyproject.toml
git commit -m "Version bump"
```

#### 3. Clean and build

```bash
rm -rf dist/ build/ *.egg-info/
python -m build
twine check dist/*               # validates README rendering, metadata
ls dist/
# Expect:
#   dailybot_cli-X.Y.Z.tar.gz
#   dailybot_cli-X.Y.Z-py3-none-any.whl
```

#### 4. Verify on TestPyPI first

```bash
# Repo-local config
twine upload --config-file ./.pypirc --repository testpypi dist/*

# Or with ~/.pypirc
twine upload --repository testpypi dist/*
```

Then in a **fresh virtualenv**, smoke-test the install:

```bash
python3 -m venv /tmp/dailybot-test && source /tmp/dailybot-test/bin/activate
pip install --index-url https://test.pypi.org/simple/ \
            --extra-index-url https://pypi.org/simple/ \
            dailybot-cli==X.Y.Z
dailybot --version          # should print X.Y.Z
dailybot --help             # should render cleanly
deactivate
rm -rf /tmp/dailybot-test
```

The `--extra-index-url` is needed so transitive deps come from real PyPI (TestPyPI doesn't mirror them).

#### 5. Publish to real PyPI

```bash
twine upload --config-file ./.pypirc dist/*
# or: twine upload dist/*  (with ~/.pypirc)
```

PyPI rejects re-uploads of an existing version. If you typo'd the version, bump to the next patch — you cannot reuse `X.Y.Z`.

#### 6. Tag and push

```bash
git tag v<X.Y.Z>
git push origin main
git push origin v<X.Y.Z>
```

> **Note:** in the manual flow, the tag is just a marker. It does NOT trigger the automated workflow's PyPI step (you've already done that). If `release.yml` is wired up, pushing the tag WILL also trigger it — and the workflow will fail at the PyPI step because the version already exists. To avoid confusion, comment the workflow out before pushing the tag, or just accept that you'll see a failed Action run. See [Combining the flows](#combining-the-flows).

#### 7. Verify

```bash
pip install --upgrade dailybot-cli
dailybot --version
```

Wait ~30s for CDN propagation if you see the old version.

### Manual flow does NOT cover

- **Linux x86_64 binary** — build it locally and attach to a GitHub Release manually:
  ```bash
  docker run --rm -v "$PWD":/src -w /src python:3.12-slim-bullseye sh -c '
    apt-get update && apt-get install -y binutils
    pip install pyinstaller
    pip install -e .
    pyinstaller --onefile --name dailybot --clean dailybot_cli/main.py
  '
  mv dist/dailybot dist/dailybot-linux-x86_64
  gh release create v<X.Y.Z> dist/dailybot-linux-x86_64 --generate-notes
  ```
- **Homebrew formula update** — see [Homebrew tap](#homebrew-tap-update) below.

If you need to ship to all three channels manually, expect ~30 minutes of work versus ~5 minutes with the automated flow.

---

## Automated Flow (GitHub Actions)

Triggered by pushing a `v*` git tag. Defined in [`.github/workflows/release.yml`](../.github/workflows/release.yml).

### What it does

```
                   ┌─ git tag v0.4.13 ─┐
                   └─────────┬─────────┘
                             │ push
                             ▼
              ┌──────────────────────────────┐
              │  release.yml workflow         │
              └──┬───────────┬───────────┬───┘
                 │           │           │
        ┌────────▼────┐  ┌───▼─────────┐ │
        │ build-linux │  │ publish-pypi│ │
        │ pyinstaller │  │ twine upload│ │
        │ glibc 2.31  │  │             │ │
        └──────┬──────┘  └─────┬───────┘ │
               │               │         │
               └───────┬───────┘         │
                       │                 │
                       ▼                 ▼
               ┌──────────────┐  ┌──────────────────┐
               │ release      │  │ update-homebrew  │
               │ GitHub       │  │ wait for PyPI    │
               │ Release +    │  │ update formula   │
               │ binary attach│  │ push to tap repo │
               └──────────────┘  └──────────────────┘
```

### One-time setup (per maintainer / per repo)

The current workflow uses **API token-based** authentication. Two GitHub repository secrets are required:

| Secret | Where | Used for |
|--------|-------|----------|
| `PYPI_API_TOKEN` | This repo → Settings → Secrets and variables → Actions | `twine upload` to PyPI |
| `HOMEBREW_TAP_TOKEN` | Same place | Push commits to `dailybothq/homebrew-tap` |

To create / verify:

```bash
# List existing secrets (won't show values)
gh secret list

# Set if missing
gh secret set PYPI_API_TOKEN
gh secret set HOMEBREW_TAP_TOKEN
```

The `PYPI_API_TOKEN` should be project-scoped to `dailybot-cli` (not account-wide). The `HOMEBREW_TAP_TOKEN` is a GitHub fine-grained PAT with `Contents: write` on `dailybothq/homebrew-tap`.

> **Modern alternative — Trusted Publishing (OIDC).** PyPI now supports OIDC-based publishing where GitHub Actions authenticates to PyPI via short-lived tokens, eliminating `PYPI_API_TOKEN` entirely. See [Migrating to OIDC](#migrating-to-trusted-publishing-oidc) below. Recommended but requires a one-time PyPI configuration change. Not in use yet for this repo.

### Procedure

#### 1. Pre-flight

```bash
git status -s
pytest -x
gh secret list                   # confirm both secrets exist
```

#### 2. (If deps changed) Sync the Homebrew formula in the workflow

The formula is rendered inline in `release.yml` and includes pinned `resource` blocks for every transitive Python dep. When `pyproject.toml::dependencies` changes, the formula MUST be updated in the same PR.

For each new or changed dep:

```bash
pip download <pkg>==<version> --no-binary :all: --no-deps -d /tmp
sha256sum /tmp/<pkg>-<version>.tar.gz
```

Then add or update the `resource "<pkg>"` block in `release.yml`.

#### 3. Bump version (its own commit)

```bash
# Edit pyproject.toml::project.version
git add pyproject.toml
git commit -m "Version bump"
git push origin main
```

#### 4. Tag and push

```bash
git tag v<X.Y.Z>
git push origin v<X.Y.Z>
```

#### 5. Watch the workflow

```bash
gh run watch
```

Or open <https://github.com/DailyBotHQ/cli/actions> in a browser. The full run takes ~5–10 minutes (the Homebrew job waits up to 3 min for PyPI propagation).

#### 6. Verify

```bash
pip install --upgrade dailybot-cli
brew upgrade dailybot
gh release view v<X.Y.Z>           # confirm binary attached
dailybot --version
```

### What can go wrong

| Symptom | Cause | Fix |
|---------|-------|-----|
| `publish-pypi` job: 409 Conflict | Version already on PyPI | Bump version, retag |
| `publish-pypi` job: 403 Forbidden | `PYPI_API_TOKEN` invalid/expired | Regenerate, `gh secret set` |
| `update-homebrew` job: timeout | PyPI propagation slow | Re-run only that job |
| `update-homebrew` job: push rejected | `HOMEBREW_TAP_TOKEN` lacks `Contents: write` | Reissue PAT with correct scope |
| `build-linux` job fails | A new dep has a C extension or PyInstaller bug | Run the docker build locally to repro |
| Release runs twice (tag + manual flow) | You ran manual then pushed the tag | Delete the failed Action run and the duplicate GitHub Release if any. PyPI/Homebrew remain on the manually-published version |

### Migrating to Trusted Publishing (OIDC)

[PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/) eliminates the need for `PYPI_API_TOKEN`. The workflow authenticates via OIDC — short-lived, repo-scoped, no secret to leak.

**One-time setup:**

1. On PyPI: project settings → "Publishing" → "Add a new publisher" → fill in:
   - Repository: `DailyBotHQ/cli`
   - Workflow filename: `release.yml`
   - Environment name: `pypi` (optional but recommended)

2. In `release.yml`, replace the PyPI publish step:

   ```yaml
   publish-pypi:
     runs-on: ubuntu-latest
     environment: pypi
     permissions:
       id-token: write          # Required for OIDC
     steps:
       - uses: actions/checkout@v4
       - uses: actions/setup-python@v5
         with: { python-version: "3.12" }
       - run: pip install build && python -m build
       - uses: pypa/gh-action-pypi-publish@release/v1
   ```

3. Delete the `PYPI_API_TOKEN` secret from the repo: `gh secret delete PYPI_API_TOKEN`.

This is the recommended end-state but is a separate task from a normal release. Don't migrate during a release window — do it on a quiet day, with a test run on TestPyPI first (TestPyPI also supports trusted publishing, configured separately).

---

## Homebrew Tap Update

The formula lives in `dailybothq/homebrew-tap`, file `Formula/dailybot.rb`. The automated flow updates it via the `update-homebrew` job. To do it manually:

### Compute the new sdist sha256

```bash
pip download dailybot-cli==X.Y.Z --no-binary :all: --no-deps -d /tmp/sdist
sha256sum /tmp/sdist/dailybot_cli-X.Y.Z.tar.gz
```

### Update the formula

In `dailybothq/homebrew-tap/Formula/dailybot.rb`:

- Bump the URL to the new version
- Replace the `sha256` with the new value
- If you added or removed a Python dep this release, also update the matching `resource` block(s). Each transitive dep is listed there with its own URL + sha256. To compute a new resource:

  ```bash
  pip download <pkg>==<version> --no-binary :all: --no-deps -d /tmp
  sha256sum /tmp/<pkg>-<version>.tar.gz
  ```

Commit and push to `dailybothq/homebrew-tap`. The formula is published the moment it lands on `main` of the tap repo.

### Verify

```bash
brew update
brew upgrade dailybot
dailybot --version
```

---

## Curl Installer (`install.sh`)

The script in `install.sh` is also published at `https://cli.dailybot.com/install.sh`. The hosted version is updated **out-of-band** — pushing to this repo does NOT redeploy the CDN copy. Confirm with the maintainer before changing user-visible installer behavior.

---

## Combining the Flows

If you start a manual release and partway through decide to switch to automated, **don't push the tag** until you've decided which flow owns the PyPI publish. PyPI rejects re-uploads, so whoever publishes first "wins".

Common patterns:

- **Manual on TestPyPI, then automated for real:** publish to TestPyPI manually for verification, then push the tag and let CI handle real PyPI + binary + Homebrew.
- **Automated entirely:** just push the tag.
- **Manual entirely:** skip the tag push, or push it knowing the workflow's PyPI step will fail (which is harmless — Linux binary and Homebrew jobs still depend on PyPI succeeding, so they'll skip too).

---

## Pre-Release Checklist

### For both flows
- [ ] Working tree clean
- [ ] On `main`
- [ ] `pytest -x` green
- [ ] `pyproject.toml::project.version` bumped in its own "Version bump" commit
- [ ] If a dep changed: Homebrew formula synced (in `release.yml` for automated, in the tap repo for manual)

### Manual flow
- [ ] Tokens available via one of: `docker/local/cli/.env` (devcontainer), `./.pypirc` (repo-local), or `~/.pypirc`
- [ ] If using a `.pypirc` file, it is `chmod 600`
- [ ] If using a `.pypirc` file, it is in `.gitignore` (already there for the repo-local case)
- [ ] `python -m build` succeeded; `twine check dist/*` passed
- [ ] TestPyPI upload + smoke-test install passed
- [ ] Real PyPI upload succeeded
- [ ] Git tag pushed (knowing the CI workflow will run if active)

### Automated flow
- [ ] `gh secret list` shows `PYPI_API_TOKEN` and `HOMEBREW_TAP_TOKEN`
- [ ] No partial manual upload to PyPI for this version
- [ ] Tag pushed
- [ ] Workflow run succeeded (`gh run watch`)
- [ ] PyPI / Homebrew / GitHub Release verified
