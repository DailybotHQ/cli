# Changelog

All notable changes to this project are documented in this file.

This file is generated automatically by
[python-semantic-release](https://python-semantic-release.readthedocs.io/) from
the `feat:` / `fix:` / `perf:` / `BREAKING CHANGE:` commit messages on `main`.
Do not edit it by hand — your edits will be overwritten on the next release.

<!-- version list -->

## v1.4.0 (2026-05-02)

### Features

- **cli**: Add `dailybot upgrade` command with install-method detection
  ([`8e8b9f9`](https://github.com/DailybotHQ/cli/commit/8e8b9f9bff37e06f6ee861a4ebcd1eb3c1544eb0))


## v1.3.0 (2026-05-02)

### Bug Fixes

- **ci**: Serialize auto-release.yml and sync-installer-checksums.yml
  ([`3a8947a`](https://github.com/DailybotHQ/cli/commit/3a8947a50a0ec74da01208e35df9ff458c0613be))

### Chores

- **installer**: Regenerate installer checksums [skip ci]
  ([`e1b37d7`](https://github.com/DailybotHQ/cli/commit/e1b37d7a83604bffa4bd85d870dbc785893cec63))

### Continuous Integration

- Trigger code_check.yml on PR (workflow event was missed on initial open)
  ([`d0cd262`](https://github.com/DailybotHQ/cli/commit/d0cd262348e8bf60f8bd0a87ec709dd0d7c54e01))

### Documentation

- **readme**: Position install.sh as the default for Windows users with WSL or Git Bash
  ([`95fd83a`](https://github.com/DailybotHQ/cli/commit/95fd83ad797a45bbd715f8bd4fb46689028371fb))

### Features

- **installer**: Add Windows PowerShell installer (install.ps1)
  ([`fa59958`](https://github.com/DailybotHQ/cli/commit/fa599588d0c202dfffbdc62da1a5accc5f87f984))


## v1.2.0 (2026-05-02)

### Features

- **installer**: Publish install.sh.sha256 and keep it in sync via CI
  ([`e0d5fa2`](https://github.com/DailybotHQ/cli/commit/e0d5fa233116684cc77597f483b21d5b9501560f))


## v1.1.0 (2026-05-02)

### Chores

- **release**: Attribute auto-release commits and tags to dailybotops
  ([`a3eff13`](https://github.com/DailybotHQ/cli/commit/a3eff13a9a45344bf70972ef747f919815b2284f))

- **release**: Use 'DailyBot Automations <automations@dailybot.com>' as commit author
  ([`1b937a8`](https://github.com/DailybotHQ/cli/commit/1b937a858d1b20edc92a40e9b9e31a2e476f5ce6))

- **release**: Use ops@dailybot.com as the auto-release commit email
  ([`b846ba8`](https://github.com/DailybotHQ/cli/commit/b846ba80a7be267356050f350c8f0f972cbc768d))

### Features

- **release**: Cut a release on every merge to main, regardless of prefix
  ([`f2893c4`](https://github.com/DailybotHQ/cli/commit/f2893c4781975ff1c5a46a6350b75dc4b0916de2))


## v1.0.1 (2026-05-02)

### Bug Fixes

- **ci**: Add workflow_dispatch to release.yml for stuck-tag recovery
  ([`f37fccb`](https://github.com/DailybotHQ/cli/commit/f37fccbc5f6bdd9aa96e779805a414631953ec38))

- **ci**: Explicitly dispatch release.yml after PSR pushes the tag
  ([`fb6ff63`](https://github.com/DailybotHQ/cli/commit/fb6ff6333f73e7a44fdb838d6050764ab37a9aa9))


## v1.0.0 (2026-05-02)

### Bug Fixes

- **ci**: Drop --strict=false flag (PSR 10 changed it to a boolean)
  ([`75dd382`](https://github.com/DailybotHQ/cli/commit/75dd382ba05c775418601376ba83a2132a78e552))

- **install**: Match actual Python check to MIN_PYTHON=3.10
  ([`6e17ef5`](https://github.com/DailybotHQ/cli/commit/6e17ef58cbc00146b99211a736cab02a6e5eb297))

- **release**: Sync Homebrew formula resources with requirements/base.txt
  ([`4867824`](https://github.com/DailybotHQ/cli/commit/48678243365275d9a9a918bf5a32492d97103d93))

- **version**: Show binary path in PyInstaller frozen builds
  ([`15f947e`](https://github.com/DailybotHQ/cli/commit/15f947e54f1b8a79d8d39c6f7cbaee5920b70ccf))

### Build System

- **deps**: Pin deps via pip-tools lock files and expand Docker context
  ([`f0c9b32`](https://github.com/DailybotHQ/cli/commit/f0c9b328a5a0aaf310c5f5ec652ad477e0f5b2cb))

### Chores

- Bump LICENSE year to 2026 and clean up .gitignore
  ([`a985757`](https://github.com/DailybotHQ/cli/commit/a985757a11b4f3b82490b28fd0b37134fff749a6))

- **deps**: Bump python-semantic-release 9 → 10 and isolate via pipx
  ([`c0de9d0`](https://github.com/DailybotHQ/cli/commit/c0de9d049ddff5ea88e399dc9a058dd99c646c25))

- **deps**: Pin all dependencies to exact versions in pyproject.toml
  ([`1311abc`](https://github.com/DailybotHQ/cli/commit/1311abc4a3764bc050575aff9f49b3a9becc2b57))

- **quality**: Wire ruff + mypy as dev deps with project-wide config
  ([`1b2b382`](https://github.com/DailybotHQ/cli/commit/1b2b382035aaac01de6c64cbc74c65c3801d6e6b))

- **repo**: Add tmp/ scratchpad with AGENTS.md rule
  ([`c51077e`](https://github.com/DailybotHQ/cli/commit/c51077e63e72e62a9d704e35858828261d9d520f))

### Continuous Integration

- Add code_check.yml as PR gate (ruff + mypy + pytest + build)
  ([`8c9bcff`](https://github.com/DailybotHQ/cli/commit/8c9bcff2d5441472518bf5789e8d929eccc45edc))

- **release**: Add fully automated release on PR merge to main
  ([`67b759d`](https://github.com/DailybotHQ/cli/commit/67b759db71773ee089e1df1caba48e3246b757ee))

### Documentation

- Correct stale claim about install.sh CDN deploy
  ([`862e34d`](https://github.com/DailybotHQ/cli/commit/862e34d62543295dfc9846b62e6c1efb78cb2c27))

- **agents**: Forbid direct push to main in Common Mistakes
  ([#22](https://github.com/DailybotHQ/cli/pull/22),
  [`8e64843`](https://github.com/DailybotHQ/cli/commit/8e648437508284ee75b14b226db0f9521ed34325))

- **readme**: Mention v1.0.0 in version examples and add bug-report tip
  ([`98943ec`](https://github.com/DailybotHQ/cli/commit/98943ec90062af210ecec65ca1aa75efae088c78))

- **release**: Document devcontainer env-var flow for .pypirc
  ([`fd3e9fc`](https://github.com/DailybotHQ/cli/commit/fd3e9fccb0c60d8a07ed2a2248e988faa988cfec))

### Features

- **build**: Add devcontainer setup with PyPI tokens via env vars
  ([`33b0ff2`](https://github.com/DailybotHQ/cli/commit/33b0ff244b2d4d6379dc4159be20780f37fb4af8))

- **cli**: Add `dailybot version` command and richer --version output
  ([`4b957a3`](https://github.com/DailybotHQ/cli/commit/4b957a3a1321f2257f88e342663d21d94284d51b))

- **deps**: Drop Python 3.9 support, modernize type hints (PEP 604)
  ([`693426e`](https://github.com/DailybotHQ/cli/commit/693426e339d78bd2cc5d016100c7190e0a3d1235))

- **devcontainer**: Add codecheck command for linters + tests
  ([`3471fa7`](https://github.com/DailybotHQ/cli/commit/3471fa7ec9768295c626ac9de14b25cb899300f1))

- **devcontainer**: Add pkg_test for end-to-end package smoke testing
  ([`a53db3f`](https://github.com/DailybotHQ/cli/commit/a53db3f7444ddecb244cd9c75bb7f2fd076de30c))

- **devcontainer**: Turn pkg_test into clitest sandbox manager
  ([`08daa1b`](https://github.com/DailybotHQ/cli/commit/08daa1b1d589ccfe78a631ca45fbb91e6954754c))

### Refactoring

- **build**: Copy any id_* SSH key from host into devcontainer
  ([`c629bfb`](https://github.com/DailybotHQ/cli/commit/c629bfbe3e6799ab1f9f96a2c34083ddf6b1a1cd))
