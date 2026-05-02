# Development Commands

Cheat sheet for the most common development tasks. All commands assume you're in the repo root with a virtualenv activated (or using `pipx`/`uv`).

## Environment Setup

```bash
# Option 1: virtualenv
python3 -m venv .venv
source .venv/bin/activate
pip install -e .                                  # editable install
pip install pytest pytest-cov ruff mypy black     # dev tools (add to a [project.optional-dependencies.dev] entry if not yet)

# Option 2: pipx (isolated)
pipx install -e .

# Option 3: uv (fast)
uv venv
uv pip install -e .
```

After install, confirm the entry point:

```bash
dailybot --version
```

If `dailybot` is not on PATH, your venv isn't activated, or your `--user` install dir isn't in PATH. See [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

## Running the CLI Locally

```bash
# Direct invocation through entry point
dailybot --help

# Via Python module (useful for debugging)
python -m dailybot_cli.main --help

# Override the API URL (staging, local backend)
dailybot --api-url http://localhost:8000 login --email me@example.com
DAILYBOT_API_URL=http://localhost:8000 dailybot status
```

## Testing

```bash
pytest                           # full suite
pytest -x                        # stop on first failure
pytest -v                        # verbose
pytest -k <keyword>              # filter by name
pytest tests/api_client_test.py  # single file
pytest -s                        # don't capture stdout (debug prints)
pytest --tb=short                # shorter tracebacks
```

See [TESTING_GUIDE.md](TESTING_GUIDE.md) for conventions.

## Linting & Type-checking

This project uses standard Python tooling. If `pyproject.toml` doesn't yet declare these as a `[project.optional-dependencies.dev]` extra, install them locally:

```bash
pip install ruff mypy black
```

Then:

```bash
ruff check dailybot_cli tests       # lint
ruff format dailybot_cli tests      # format (or `black .` if you prefer)
mypy dailybot_cli                   # type-check
```

> If/when these are wired into CI, the canonical commands will live here. For now, run them locally before committing.

## Building Distribution Artifacts

These are normally run by CI on tag push. You only need them locally to validate a release.

```bash
# Source distribution + wheel (PyPI)
pip install build
python -m build
ls dist/   # dailybot_cli-X.Y.Z.tar.gz, dailybot_cli-X.Y.Z-py3-none-any.whl

# Linux x86_64 binary (PyInstaller)
# NOTE: For broad compatibility, CI builds inside a glibc 2.31 container.
# Locally on macOS, the result will be a Mach-O binary, not a Linux ELF.
pip install pyinstaller
pyinstaller --onefile --name dailybot --clean dailybot_cli/main.py
ls dist/dailybot
```

To replicate the CI Linux build:

```bash
docker run --rm -v "$PWD":/src -w /src python:3.12-slim-bullseye sh -c '
  apt-get update && apt-get install -y binutils
  pip install pyinstaller
  pip install -e .
  pyinstaller --onefile --name dailybot --clean dailybot_cli/main.py
'
```

See [RELEASE_AND_DISTRIBUTION.md](RELEASE_AND_DISTRIBUTION.md) for the full release flow.

## Git & Releases

```bash
# Bump version (single source of truth)
# Edit pyproject.toml::project.version, commit standalone:
git add pyproject.toml
git commit -m "Version bump"

# Tag and push to trigger release pipeline
git tag v0.4.13
git push origin main --tags
```

The tag push fans out into PyPI publish + Linux binary build + GitHub Release + Homebrew tap update via `.github/workflows/release.yml`.

## Quick Reference

| Task | Command |
|------|---------|
| Install editable | `pip install -e .` |
| Run tests | `pytest` |
| Run one test | `pytest tests/<file>::Test<Class>::test_<name>` |
| Lint | `ruff check dailybot_cli tests` |
| Format | `ruff format dailybot_cli tests` |
| Type-check | `mypy dailybot_cli` |
| Run CLI | `dailybot --help` or `python -m dailybot_cli.main --help` |
| Build sdist+wheel | `python -m build` |
| Build Linux binary (CI parity) | `docker run … pyinstaller --onefile …` (see above) |
| Tag a release | `git tag v0.X.Y && git push --tags` |
| Wipe local config | `rm -rf ~/.config/dailybot/` |

## Useful Local Workflow

When iterating on a command:

```bash
# 1. Make code changes
$EDITOR dailybot_cli/commands/agent.py

# 2. Run targeted tests
pytest tests/commands_test.py -k agent_update -x

# 3. Try the command end-to-end against staging
dailybot --api-url https://staging.dailybot.com agent update "test" --name "Local Dev"

# 4. Run the whole suite
pytest

# 5. Lint + format
ruff check . && ruff format .

# 6. Commit
git add -p
git commit -m "feat(agent): ..."
```
