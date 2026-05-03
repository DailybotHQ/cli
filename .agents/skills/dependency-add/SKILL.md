---
name: dependency-add
description: Add a Python dependency to pyproject.toml AND update the Homebrew formula in release.yml.
trigger: /dependency-add or #dependency-add
inputs: Package name and minimum version (e.g., "tenacity>=8.2"). User-provided rationale.
prereqs: You've confirmed there's no existing way to do this without a new dep (check imports, stdlib alternatives).
---

# Skill: `dependency-add`

Adding a dep is a two-step act: it must land in **both** `pyproject.toml` and the Homebrew formula at `.github/workflows/release.yml`. Forgetting the formula breaks the next `brew install dailybot`.

## Pre-flight

- [ ] **Why this dep?** Confirm with the user. "We need <X> because <reason>. The stdlib / existing dep can't do this because <Y>."
- [ ] **License compatibility.** MIT/BSD/Apache: fine. GPL: stop and ask the user — the CLI is MIT-licensed.
- [ ] **Native code?** Pure-Python preferred. C extensions complicate the PyInstaller Linux binary build. If the dep has a C extension, build the binary in the glibc 2.31 container locally to confirm it still works.
- [ ] **Wheel availability.** Confirm `pip download <pkg>==<version> --no-binary :all: --no-deps` returns an sdist (Homebrew needs sdists, not wheels).

## Procedure

### 1. Add to `pyproject.toml`

```toml
dependencies = [
    "click>=8.1.0",
    "httpx>=0.25.0",
    "questionary>=2.0.0",
    "rich>=13.0.0",
    "<new-pkg>>=<min-version>",   # ← add here
]
```

Pin with `>=` (not `==`) — we want users to get patch fixes.

### 2. Install locally and run tests

```bash
pip install -e .
pytest -x
```

Confirm the new dep imports cleanly and nothing regressed.

### 3. Compute Homebrew resource blocks

The formula in `.github/workflows/release.yml` lists every **transitive** dep as a `resource` block. When adding `<pkg>`, you also need to add resources for any of its transitive deps that aren't already listed.

For each new package (`<pkg>` and any new transitive deps):

```bash
pip download <pkg>==<version> --no-binary :all: --no-deps -d /tmp
ls /tmp/<pkg>-<version>.tar.gz
sha256sum /tmp/<pkg>-<version>.tar.gz
```

The formula needs:

```ruby
resource "<pkg>" do
  url "https://files.pythonhosted.org/packages/source/<first-letter>/<pkg>/<pkg>-<version>.tar.gz"
  sha256 "<sha256>"
end
```

URL format note: PyPI normalizes some package names. The path is `/source/<first-letter>/<normalized-name>/<filename>`. The actual filename inside the URL may use underscores even if the import name uses hyphens (e.g., `markdown_it_py-4.0.0.tar.gz` for `markdown-it-py`).

To find the canonical sdist URL:

```bash
pip index versions <pkg>            # shows available versions
# Or check https://pypi.org/project/<pkg>/#files
```

### 4. Discover transitive deps

```bash
pip install <pkg>==<version> --dry-run --report - | jq '.install[].metadata.name'
```

Or, simpler:

```bash
python -m pip install <pkg>==<version>
pip show <pkg> | grep Requires
# Then `pip show <each>` recursively
```

Compare against the resources already in `release.yml`. Add any missing ones.

### 5. Update the inline formula in `release.yml`

The `update-homebrew` job rewrites `Formula/dailybot.rb` from a Python heredoc inside the workflow. Edit that heredoc to add (or update) the `resource` block(s).

Insert in alphabetical order with the existing list. Match the existing indentation exactly.

### 6. Verify the formula locally (optional but recommended)

If you have access to clone the tap and run `brew install --build-from-source ./Formula/dailybot.rb` locally:

```bash
git clone git@github.com:DailyBotHQ/homebrew-tap.git
cd homebrew-tap
# Hand-edit Formula/dailybot.rb to mirror the new release.yml inline formula
brew install --build-from-source ./Formula/dailybot.rb
```

If `brew install` fails with a sha mismatch, recompute the sha (the file may have been re-released).

### 7. Update docs

- `docs/RELEASE_AND_DISTRIBUTION.md` — only if the new dep changed how packaging works (e.g., now requires a binary wheel or breaks PyInstaller).
- `docs/ARCHITECTURE.md` — if the dep is significant (e.g., adds a new layer like async or templating).

### 8. Commit

```
build(deps): add <pkg> for <reason>

## Summary
Adds <pkg> to support <feature>.

## Change Log
- pyproject.toml: <pkg>>=<version>
- release.yml: Homebrew resource block for <pkg> and N transitive deps
- (any code that uses the new dep)

## Risks
- Increases install size by ~<n>MB
- Must verify Linux PyInstaller binary still builds (CI will catch on the next tag)
```

## Don'ts

- **Don't add a dep without confirming it's needed.** Stdlib first, then existing deps, then new dep.
- **Don't update only `pyproject.toml`.** The Homebrew formula update is mandatory in the same PR.
- **Don't pin with `==`.** Use `>=` for forward compatibility.
- **Don't add a dep with a viral license** (GPL) without explicit user approval.
- **Don't add a dep with a C extension** without verifying the PyInstaller Linux binary still builds.
