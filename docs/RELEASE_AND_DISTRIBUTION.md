# Release & Distribution

The CLI ships through three channels, all triggered by pushing a `v*` git tag:

1. **PyPI** — Python users, CI pipelines (`pip install dailybot-cli`)
2. **Homebrew tap** — macOS users (`brew install dailybothq/tap/dailybot`)
3. **Linux x86_64 binary** — distros without a recent Python (`curl -sSL https://cli.dailybot.com/install.sh | bash`)

The pipeline is defined in [`.github/workflows/release.yml`](../.github/workflows/release.yml).

## Single Source of Truth: `pyproject.toml`

The version lives in **exactly one place**: `pyproject.toml::project.version`. Everything else reads it dynamically.

- `dailybot --version` → `importlib.metadata.version("dailybot-cli")` (set by setuptools at install time)
- The git tag `v0.4.13` matches `version = "0.4.13"` (the workflow strips the leading `v`)

**Never** hardcode the version anywhere in `dailybot_cli/` source.

## Release Flow

```
                   ┌─ git tag v0.4.13 ─┐
                   └─────────┬─────────┘
                             │ push
                             ▼
              ┌──────────────────────────────┐
              │ .github/workflows/release.yml │
              └──┬───────────┬───────────┬───┘
                 │           │           │
        ┌────────┘           │           └─────────┐
        ▼                    ▼                     ▼
┌──────────────┐   ┌─────────────────┐   ┌──────────────────┐
│ build-linux  │   │ publish-pypi    │   │ update-homebrew  │
│ pyinstaller  │   │ python -m build │   │ wait for PyPI    │
│ in glibc 2.31│   │ twine upload    │   │ recompute sha256 │
│ container    │   │                 │   │ rewrite formula  │
└──────┬───────┘   └────────┬────────┘   └──────────────────┘
       │                    │
       │   ┌────────────────┘
       │   │
       ▼   ▼
┌──────────────────────────────┐
│ release (GitHub Release)     │
│ uploads dailybot-linux-x86_64│
│ generates release notes      │
└──────────────────────────────┘
```

### Step-by-step (cutting a release)

1. Implement and test changes; merge to `main`.
2. Bump `pyproject.toml::project.version` in **its own commit**:
   ```bash
   git add pyproject.toml
   git commit -m "Version bump"
   git push
   ```
3. Tag and push:
   ```bash
   git tag v0.4.13
   git push origin v0.4.13
   ```
4. Watch the Actions tab. The full pipeline takes 5–10 minutes (most of it is the Homebrew "wait for PyPI propagation" step).
5. Verify:
   ```bash
   pip install --upgrade dailybot-cli
   brew upgrade dailybot
   curl -sSL https://cli.dailybot.com/install.sh | bash
   ```

## Linux Binary (PyInstaller)

The binary is built inside `python:3.12-slim-bullseye`, which ships glibc 2.31 — old enough to run on most current distros (Ubuntu 20.04+, Debian 11+, RHEL 9+, etc.).

The workflow command:

```yaml
- name: Build binary in container with glibc 2.31
  run: |
    docker run --rm -v "$PWD":/src -w /src python:3.12-slim-bullseye sh -c '
      apt-get update && apt-get install -y binutils
      pip install pyinstaller
      pip install -e .
      pyinstaller --onefile --name dailybot --clean dailybot_cli/main.py
    '
```

### Reproducing locally (Linux parity)

```bash
docker run --rm -v "$PWD":/src -w /src python:3.12-slim-bullseye sh -c '
  apt-get update && apt-get install -y binutils
  pip install pyinstaller
  pip install -e .
  pyinstaller --onefile --name dailybot --clean dailybot_cli/main.py
'
ls -la dist/dailybot
```

### Why x86_64 only

The current installer (`install.sh`) and release pipeline produce only `dailybot-linux-x86_64`. On `aarch64` (Linux ARM, Apple Silicon Linux VMs, Docker Desktop on Mac), the installer falls back to pip. If/when we add ARM, both `install.sh` and `release.yml` need updates.

## PyPI

```yaml
- name: Build package
  run: |
    pip install build twine
    python -m build

- name: Publish to PyPI
  env:
    TWINE_USERNAME: __token__
    TWINE_PASSWORD: ${{ secrets.PYPI_API_TOKEN }}
  run: |
    twine upload dist/*
```

The PyPI token is configured as a GitHub Actions secret (`PYPI_API_TOKEN`). It is project-scoped to `dailybot-cli`.

If publishing fails:
- **Conflict (409)**: the version already exists on PyPI. Bump `pyproject.toml::project.version` and re-tag. PyPI does not allow re-uploads of the same version.
- **Auth error**: the token is invalid or expired. Generate a new one at <https://pypi.org/manage/account/token/>.

## Homebrew Tap

The formula lives in a separate repo: `DailyBotHQ/homebrew-tap`. The workflow:

1. Waits up to 3 minutes for the version to appear on PyPI.
2. Downloads the sdist and computes its sha256.
3. Rewrites `Formula/dailybot.rb` with the new version and sha.
4. Pushes the change to `homebrew-tap`.

### When to update the resource list

The formula declares every transitive Python dependency as a `resource` block (sdist URL + sha256). When you **add a new dependency** to `pyproject.toml`, you MUST add a corresponding `resource` block to the inline formula in `release.yml`.

To compute a resource block:

```bash
pip download <pkg>==<version> --no-binary :all: --no-deps -d /tmp
sha256sum /tmp/<pkg>-<version>.tar.gz
```

Then add to `release.yml`:

```ruby
resource "<pkg>" do
  url "https://files.pythonhosted.org/packages/source/<first>/<pkg>/<pkg>-<version>.tar.gz"
  sha256 "<hash>"
end
```

> Forgetting this is the most common cause of a broken Homebrew release. The PyPI publish succeeds, but `brew install` fails because the formula references a dep that doesn't exist locally and the resource list is incomplete.

## Curl Installer (`install.sh`)

The script in `install.sh` is published at `https://cli.dailybot.com/install.sh`. It:

1. **macOS**: requires Homebrew, runs `brew install dailybothq/tap/dailybot`.
2. **Linux**: tries the pre-built x86_64 binary first; falls back to `pipx`/`uv`/`pip`.
3. **Other**: skips to the pip fallback chain.

**The script is served from a CDN.** Updates to the hosted version do not happen automatically when you push to this repo — the CDN needs to be refreshed out-of-band. Confirm with the maintainer before changing user-visible installer behavior.

## GitHub Release

The `release` job in the workflow:

- Downloads the Linux binary built in `build-linux`.
- Renames it to `dailybot-linux-x86_64`.
- Creates a GitHub Release tagged with the version.
- Auto-generates release notes from PR titles since the previous tag.

If you want curated release notes, edit them on GitHub after the workflow finishes.

## Troubleshooting Releases

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| PyPI upload failed: 409 | Version already published | Bump version, re-tag |
| PyPI upload failed: 403 | Token expired / wrong scope | Regenerate `PYPI_API_TOKEN` |
| Homebrew job timed out waiting for PyPI | Propagation slow | Re-run only the `update-homebrew` job |
| `brew install` fails: "resource X not found" | Missing resource block in formula | Add the resource to `release.yml` and re-tag |
| Linux binary won't run on user's distro | glibc too old (< 2.31) | The user is on a very old distro; recommend pip install |
| `curl -sSL https://cli.dailybot.com/install.sh \| bash` runs old script | CDN caches it | Coordinate with the team that controls the CDN |

## Pre-Release Checklist

Before pushing a tag:

- [ ] All PRs merged are reflected in the changelog (or `git log --oneline` is clean enough for auto-generated notes)
- [ ] `pyproject.toml::project.version` bumped in a dedicated commit
- [ ] `pytest` green on `main`
- [ ] If a new dependency was added: Homebrew `resource` block updated in `release.yml`
- [ ] If `install.sh` changed: someone with CDN access is queued to deploy the new version
- [ ] No `0o600` regression (audit `os.chmod` calls if you touched config.py)
- [ ] Tested locally:
  ```bash
  pip install --force-reinstall -e .
  dailybot --version
  dailybot --help
  ```
