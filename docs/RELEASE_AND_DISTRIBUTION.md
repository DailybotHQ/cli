# Release & Distribution

The CLI ships through three channels:

1. **PyPI** — Python users, CI pipelines (`pip install dailybot-cli`)
2. **Homebrew tap** — macOS users (`brew install dailybothq/tap/dailybot`)
3. **Linux x86_64 binary** — distros without a recent Python (`curl -sSL https://cli.dailybot.com/install.sh | bash`)
4. **Windows PowerShell installer** — `install.ps1` for native Windows users (`irm https://cli.dailybot.com/install.ps1 | iex`). The script wraps `pipx` / `uv tool` / `pip --user` over a host-side Python 3.10+; there is no Windows `.exe` build today (WSL2 / Git Bash users can use `install.sh` instead).

There are **three supported release flows**, in order of preference:

| Flow | Trigger | Effort per release | Surface area |
|------|---------|--------------------|--------------|
| [**Fully automated**](#fully-automated-flow-recommended) — PR merge to `main` triggers `auto-release.yml`, which decides the bump from conventional commits and pushes the tag, which triggers `release.yml` | Just merge a PR with `feat:` / `fix:` / `perf:` commits | None — zero ceremony | PyPI + Linux binary + GitHub Release + Homebrew |
| [**Tag-triggered automated**](#tag-triggered-automated-flow) — `git push origin v<X.Y.Z>` triggers `release.yml` directly | Manual `git tag` + push | Low | PyPI + Linux binary + GitHub Release + Homebrew |
| [**Manual**](#manual-flow) — local `twine` with `.pypirc` | Run from your machine | Higher | PyPI only (binary + Homebrew skipped) |

The fully automated flow is the **recommended default**. The other two are documented fallbacks for when CI is unavailable or you need to publish a specific version out-of-band.

## Single Source of Truth: `pyproject.toml`

The version lives in **exactly one place**: `pyproject.toml::project.version`. Everything else reads it dynamically.

- `dailybot --version` → `importlib.metadata.version("dailybot-cli")`
- The git tag `v0.4.13` matches `version = "0.4.13"` (strip the leading `v`)

**Never** hardcode the version anywhere in `dailybot_cli/` source.

---

## Fully Automated Flow (recommended)

The fully automated flow makes releases a side-effect of merging PRs. You never run `git tag`, you never edit `pyproject.toml::version` by hand, you never call `twine`. The bump level is derived from the conventional-commit prefixes of the commits you merged.

### What it does

```
       ┌─ PR opened / pushed ────────┐
       └──────────────┬──────────────┘
                      │
                      ▼
       ┌──────────────────────────────┐
       │ code_check.yml                │  ← gate (matrix: Py 3.10 + 3.12)
       │  ruff check / format          │
       │  mypy                         │
       │  pytest -x                    │
       │  build smoke-test             │
       └──────────────┬───────────────┘
                      │ (must pass — required check on `main`)
                      ▼
       ┌──────────────────────────────┐
       │ PR merged to main             │
       └──────────────┬───────────────┘
                      │
                      ▼
              ┌────────────────────────────┐
              │ auto-release.yml            │
              │  (python-semantic-release)  │
              ├────────────────────────────┤
              │ 1. Inspect commits since    │
              │    last tag                 │
              │ 2. Decide bump:             │
              │      feat -> minor          │
              │      fix/perf -> patch      │
              │      BREAKING -> major      │
              │      others -> no release   │
              │ 3. Update pyproject.toml    │
              │    + CHANGELOG.md           │
              │ 4. Commit + tag vX.Y.Z      │
              │ 5. Push commit + tag        │
              └─────────────┬───────────────┘
                            │ tag push
                            ▼
              ┌────────────────────────────┐
              │ release.yml                 │
              │  (existing tag-triggered    │
              │   workflow)                 │
              ├────────────────────────────┤
              │  publish-pypi               │
              │  build-linux + release      │
              │  update-homebrew            │
              └────────────────────────────┘
```

### One-time setup

**Branch protection on `main`** — go to `Settings → Branches → main` and:

1. Enable "Require a pull request before merging".
2. Enable "Require status checks to pass before merging" and add `Code Check (Python 3.10)`, `Code Check (Python 3.12)`, and `Build smoke-test (sdist + wheel)` from `code_check.yml` as required checks.
3. Add the actor that owns `AUTOMATION_GITHUB_TOKEN` (see below) to the bypass list of "Require a pull request before merging" — `auto-release.yml` needs to push the `chore(release): X.Y.Z` commit + tag directly to `main`.

**Repository secrets** — three are required:

| Secret | Used by | Notes |
|---|---|---|
| `PYPI_API_TOKEN` | `release.yml` | Same as the tag-triggered flow. Project-scoped to `dailybot-cli`. |
| `HOMEBREW_TAP_TOKEN` | `release.yml` | Same as the tag-triggered flow. Fine-grained PAT with `Contents: write` on `dailybothq/homebrew-tap`. |
| `AUTOMATION_GITHUB_TOKEN` | `auto-release.yml` | Fine-grained PAT with `Contents: write` on **this** repo, allowed to bypass branch protection on `main` (push the bump commit + tag). |

The default `${{ secrets.GITHUB_TOKEN }}` cannot push to a protected `main`, which is why `auto-release.yml` uses a separate PAT (same pattern as `xergioalex.com`'s `release_and_publish.yml`).

To create / verify:

```bash
gh secret list                        # confirm all three exist
gh secret set AUTOMATION_GITHUB_TOKEN  # paste the PAT value
```

### Configuration

All version-bump behavior is configured in `pyproject.toml::[tool.semantic_release]`. The defaults that matter:

- `version_toml = ["pyproject.toml:project.version"]` — single source of truth stays here
- `tag_format = "v{version}"` — matches the existing `release.yml` trigger pattern
- `commit_message = "chore(release): {version}\n\n[skip ci]"` — keeps the bump commit out of any future push-triggered jobs
- `allow_zero_version = true` + `major_on_zero = true` — once the CLI went production-grade, breaking changes on a 0.x version DO promote to 1.0.0 (uniform semver)
- `default_bump_level = 2` — `chore:`/`docs:`/`refactor:` commits and unprefixed merges still cut a PATCH release (PSR 10 LevelBump: 0=NO_RELEASE, 1=PRERELEASE_REVISION, **2=PATCH**, 3=MINOR, 4=MAJOR). Setting this to `1` silently breaks releases — PSR will try to bump a non-prerelease tag with a prerelease level and fail with `Cannot increment a non-prerelease version with a prerelease level bump`

### Conventional commit cheat sheet

| Prefix | Effect on release | Example |
|---|---|---|
| `feat:` | Minor bump (`0.4.12` → `0.5.0`) | `feat(agent): add --co-authors flag` |
| `fix:` | Patch bump (`0.4.12` → `0.4.13`) | `fix(release): handle 429 from PyPI` |
| `perf:` | Patch bump | `perf(client): cache org list per session` |
| `feat!:` / `BREAKING CHANGE:` in body | Major bump (`0.4.12` → `1.0.0` or `0.5.0` while we're on 0.x) | See `major_on_zero` note above |
| `docs:`, `chore:`, `refactor:`, `style:`, `test:`, `ci:`, `build:` | No release | Used freely without cutting a version |

### Procedure

1. Land your work in a PR with proper conventional-commit messages.
2. Merge the PR (squash-merge or merge-commit; either is fine — the workflow inspects commits since the last tag).
3. Watch the run:
   ```bash
   gh run watch
   ```
4. If the PR contained at least one releasable commit, you'll see two runs in sequence: first `auto-release.yml` (~30s), then `release.yml` (~5–10 min).
5. Verify:
   ```bash
   pip install --upgrade dailybot-cli
   dailybot --version
   ```

### Manually triggering an extra release

If `auto-release.yml` was skipped (e.g. CI was down at merge time), you can re-run it from the Actions tab via `workflow_dispatch`. It will inspect commits since the last tag and bump if appropriate.

If you need a release for commits that don't qualify (e.g. an emergency `chore`-only release), fall back to the tag-triggered flow below.

### Opt-in release skip — the `[skip release]` marker

> Every PR releases by default. This is the **only** way to suppress it.

`auto-release.yml` honours a literal `[skip release]` token in the body of the head commit on `main` (i.e. the squash-merge commit GitHub creates when the PR is merged). When the marker is present, the workflow logs an `::notice` line, writes a dedicated step summary explaining the skip, and exits 0 — PSR is never invoked, no `v*` tag is created, and `release.yml` is **not** dispatched.

#### When (and only when) to use it

There is **one** accepted use case: a PR whose entire diff is the synchronisation of the in-repo Dailybot agent skill pack at `.agents/skills/dailybot/` to a newly published [`DailybotHQ/agent-skill`](https://github.com/DailybotHQ/agent-skill) release (plus the minimal catalog / `AGENTS.md` updates that reference it). Without the marker, that PR would auto-bump the CLI, which in turn would push the skill pack out of sync with the CLI version it just pinned, creating an infinite sync→bump→resync loop. See [AGENTS.md Rule 15.a](../AGENTS.md#15a-opt-in-release-skip--skip-release-marker) for the full rationale.

Any other use of the marker is a bug. In particular, do **not** apply it to:

- Doc-only PRs (let the PATCH go out — the changelog entry is the record that the doc shipped).
- CI-only or workflow-only PRs (same reason).
- Dependency-bump PRs (downstream users need to see the bump).
- Refactors, test-only PRs, comment-only PRs — same.

If you are not sure, **don't apply it**. The penalty for releasing-when-you-shouldn't-have is essentially zero (one tiny PATCH version); the penalty for not-releasing-when-you-should-have is silent drift between the published CLI and what users get from `pip install`.

#### How to apply it

In the GitHub merge dialog, after clicking **Squash and merge**, edit the commit body so the final line looks like:

```
[skip release]
```

Or, from the command line:

```bash
gh pr merge <number> --squash \
  --subject "chore(skills): sync vendored dailybot pack to v1.8.0" \
  --body "Mirrors DailybotHQ/agent-skill release v1.8.0 into .agents/skills/dailybot/.

[skip release]
"
```

The match is **exact, case-sensitive, literal text** — `[skip release]`, square brackets included, no flexibility. Internal whitespace and surrounding lines do not matter. The check uses `grep -F` so regex metacharacters in the rest of the body are safe.

#### How to verify it worked

After the merge, `gh run watch` will show `auto-release.yml` finishing in ~5 seconds with a step summary that reads:

```
⏭️  Release skipped on author request.
The head commit on `main` contains the `[skip release]` marker, so:
  - python-semantic-release was not invoked
  - no new v* tag was created
  - release.yml was not dispatched (no PyPI / binary / Homebrew publish)
```

You can re-derive the full history of suppressed releases at any time with:

```bash
git log --grep '\[skip release\]' --oneline
```

#### Recovering from a misapplied marker

If you set the marker by mistake and the release should have happened, you have two options:

1. **Preferred**: open any trivial follow-up PR (a typo fix, a doc tweak, anything) without the marker. The next merge will trigger `auto-release.yml` normally and PSR will look at *all* commits since the last tag — including the dogfood commit — and produce a single PATCH that covers both.
2. **Workaround**: dispatch `auto-release.yml` manually from the Actions tab (`workflow_dispatch`). It re-checks out `main`, looks at the *current* head commit body, sees the marker is still there, and exits — so this option is mostly useful when option 1 is impractical and you need to first push a no-op commit (e.g. a CHANGELOG comment) without the marker, then dispatch.

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

## Tag-triggered Automated Flow

Triggered by pushing a `v*` git tag. Defined in [`.github/workflows/release.yml`](../.github/workflows/release.yml). Use this when you need to publish a specific version explicitly — for example, an emergency hotfix on a non-`feat`/`fix` commit, or a re-release after the fully automated flow misfired.

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

The formula is rendered inline in `release.yml` and includes pinned `resource` blocks for every transitive Python dep. **The list of resources MUST mirror `requirements/base.txt`** (with one Python-version caveat — see below). If `pyproject.toml::dependencies` or any transitive in `requirements/base.txt` changed, the formula must be updated in the same PR.

**Bulk regeneration recipe:**

```bash
# Download every base dep as an sdist and print "name version sha256" rows
mkdir -p /tmp/sdists && rm -f /tmp/sdists/*
while read -r line; do
  pkg="${line%%==*}"; ver="${line##*==}"
  pip download --no-binary :all: --no-deps --quiet -d /tmp/sdists "$pkg==$ver"
done < <(grep -E "^[a-z]" requirements/base.txt)

for f in /tmp/sdists/*.tar.gz; do
  sha="$(sha256sum "$f" | cut -d' ' -f1)"
  printf "%-30s sha256=%s\n" "$(basename "$f")" "$sha"
done
```

Then update each `resource "<pkg>"` block in `release.yml` so its `url` and `sha256` match.

**Python-version caveat:** the formula declares `depends_on "python@3.12"`, but `requirements/base.txt` is locked under whichever Python ran `pip-compile` (typically the dev container's Python 3.14). Some transitives are conditional on Python version (`anyio` requires `typing_extensions; python_version < "3.13"`, `exceptiongroup; python_version < "3.11"`, etc.). If the lock was generated under a Python newer than 3.13, you must **manually add** the missing conditionals to the formula. Today that means `typing-extensions` is in the formula even though it's absent from `base.txt`.

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

The public URL `https://cli.dailybot.com/install.sh` is a **Cloudflare 301 redirect** to `https://raw.githubusercontent.com/DailyBotHQ/cli/main/install.sh`. There is no separate CDN copy to deploy.

**Implication:** any change to `install.sh` merged into `main` is live within ~5 minutes (the upper bound for GitHub's `raw.githubusercontent.com` cache). New installations triggered by `curl -sSL https://cli.dailybot.com/install.sh | bash` execute the latest committed version automatically.

**Be deliberate** when editing `install.sh` — there is no staging step between merge and rollout. Test the script locally (`bash install.sh` from a checkout, or `curl -sSL https://raw.githubusercontent.com/DailyBotHQ/cli/<branch>/install.sh | bash` on a feature branch) before merging.

### `install.sh.sha256` (supply-chain verification)

Consumers like [`DailyBotHQ/agent-skill`](https://github.com/DailyBotHQ/agent-skill) verify `install.sh` against a SHA-256 sidecar before executing it:

```bash
curl -sSL https://cli.dailybot.com/install.sh        -o /tmp/install.sh
curl -sSL https://cli.dailybot.com/install.sh.sha256 -o /tmp/install.sh.sha256
( cd /tmp && shasum -a 256 -c install.sh.sha256 ) || {
  echo "Refusing to run unverified install.sh" >&2
  exit 1
}
bash /tmp/install.sh
```

An equivalent verified path exists for `install.ps1` (Windows) — same files (`install.ps1` + `install.ps1.sha256`), same workflows keep them in sync. See the README for the PowerShell-flavored verification snippet.

`install.sh.sha256` lives next to `install.sh` in this repo and is kept in sync by:

1. **`code_check.yml`** — every PR is gated on the checksum matching `install.sh`. If a contributor edits the script but forgets the `.sha256`, CI fails with a clear regenerate command.
2. **`sync-installer-checksums.yml`** — runs on every push to `main` whose paths include `install.sh`, regenerates the `.sha256`, and commits it directly to `main` as `DailyBot Automations`. So even if a PR slips through with stale checksum (e.g. the workflow is bypassed), `main` self-heals.

To regenerate locally before opening a PR:

```bash
shasum -a 256 install.sh > install.sh.sha256
git add install.sh install.sh.sha256
git commit -m "fix(installer): tweak Linux fallback and refresh checksum"
```

### Cloudflare DNS / Worker rules

For `cli.dailybot.com/install.sh.sha256` (and any other file we add next to `install.sh`) to be served by the CDN, the Cloudflare zone needs the redirect rule to be a **wildcard** rather than a single-path rule. Recommended Page Rule / Bulk Redirect:

```
Source URL:      cli.dailybot.com/(.*)
Destination URL: https://raw.githubusercontent.com/DailyBotHQ/cli/main/$1
HTTP code:       301
Preserve query string: yes
```

If today's rule is hard-coded to `/install.sh`, a Cloudflare admin must update it to the wildcard form (or add a second specific rule for `/install.sh.sha256`). Without this change, the new sidecar lands on `main` but stays inaccessible at `cli.dailybot.com/install.sh.sha256`. **Verify after a Cloudflare config change:**

```bash
curl -fsSL https://cli.dailybot.com/install.sh.sha256
# Expected: <64-char-hex>  install.sh
```

---

## Combining the Flows

If you start a manual release and partway through decide to switch to automated, **don't push the tag** until you've decided which flow owns the PyPI publish. PyPI rejects re-uploads, so whoever publishes first "wins".

Common patterns:

- **Manual on TestPyPI, then automated for real:** publish to TestPyPI manually for verification, then push the tag and let CI handle real PyPI + binary + Homebrew.
- **Automated entirely:** just push the tag.
- **Manual entirely:** skip the tag push, or push it knowing the workflow's PyPI step will fail (which is harmless — Linux binary and Homebrew jobs still depend on PyPI succeeding, so they'll skip too).

---

## Pre-Release Checklist

### For all flows
- [ ] `pytest -x` green on `main` (the auto-release flow doesn't run tests itself — that's the PR's job)
- [ ] If a dep changed: Homebrew formula synced inside `release.yml`'s formula template

### Fully automated flow
- [ ] `gh secret list` shows `PYPI_API_TOKEN`, `HOMEBREW_TAP_TOKEN`, and `AUTOMATION_GITHUB_TOKEN`
- [ ] Branch protection on `main` requires the `Code Check` and `Build smoke-test` checks, AND allows `AUTOMATION_GITHUB_TOKEN`'s actor to push the bump commit + tag
- [ ] PR commits use conventional-commit prefixes (`feat:` / `fix:` / `perf:` to release; `chore:` / `docs:` / `refactor:` to skip)
- [ ] PR's `code_check.yml` and `build_smoke_test` are green (will be enforced by branch protection once configured)
- [ ] After merge: `gh run watch` confirms `auto-release.yml` then `release.yml` both succeeded
- [ ] PyPI / Homebrew / GitHub Release verified

### Tag-triggered automated flow
- [ ] Working tree clean, on `main`
- [ ] `pyproject.toml::project.version` bumped in its own "Version bump" commit
- [ ] `gh secret list` shows `PYPI_API_TOKEN` and `HOMEBREW_TAP_TOKEN`
- [ ] No partial manual upload to PyPI for this version
- [ ] Tag pushed
- [ ] Workflow run succeeded (`gh run watch`)
- [ ] PyPI / Homebrew / GitHub Release verified

### Manual flow
- [ ] Working tree clean, on `main`
- [ ] `pyproject.toml::project.version` bumped in its own "Version bump" commit
- [ ] Tokens available via one of: `docker/local/cli/.env` (devcontainer), `./.pypirc` (repo-local), or `~/.pypirc`
- [ ] If using a `.pypirc` file, it is `chmod 600`
- [ ] If using a `.pypirc` file, it is in `.gitignore` (already there for the repo-local case)
- [ ] `python -m build` succeeded; `twine check dist/*` passed
- [ ] TestPyPI upload + smoke-test install passed
- [ ] Real PyPI upload succeeded
- [ ] Git tag pushed (knowing the CI workflow will run if active)
