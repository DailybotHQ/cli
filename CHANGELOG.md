# Changelog

All notable changes to this project are documented in this file.

This file is generated automatically by
[python-semantic-release](https://python-semantic-release.readthedocs.io/) from
the `feat:` / `fix:` / `perf:` / `BREAKING CHANGE:` commit messages on `main`.
Do not edit it by hand — your edits will be overwritten on the next release.

<!-- version list -->

## v1.13.0 (2026-06-12)

### Features

- **chat**: Add `dailybot chat send`/`update` for bot messages to chat platforms
  ([`f7ac99e`](https://github.com/DailybotHQ/cli/commit/f7ac99e8aefd7b786ca9d69d1b69e889d82a141d))

- **chat**: Thread replies, login auth, role scoping, reply editing
  ([`7f502b9`](https://github.com/DailybotHQ/cli/commit/7f502b94bf5ac14ed0e7dc70b216360659bd933c))


## v1.12.1 (2026-06-10)

### Chores

- **cli**: Enable autonomous Dailybot report hooks for this repo
  ([`4149810`](https://github.com/DailybotHQ/cli/commit/4149810f300dcff7411ba70e2736b0882ab3eddd))


## v1.12.0 (2026-06-10)

### Code Style

- **cli**: Apply ruff format to hook, ledger, and ledger tests
  ([`e33862f`](https://github.com/DailybotHQ/cli/commit/e33862fa4261c2513dd4bb986f929f6905dd62fd))

### Features

- **cli**: Add dailybot hook lifecycle commands and local report ledger
  ([`ca3efe9`](https://github.com/DailybotHQ/cli/commit/ca3efe9171f99346dae12acd7cbbe630e2b42137))


## v1.11.0 (2026-06-09)

### Features

- **agent**: Show report placement link after agent update
  ([`70c1c59`](https://github.com/DailybotHQ/cli/commit/70c1c591963f01c5c1e4454b4627a47793b41761))


## v1.10.1 (2026-05-26)

### Bug Fixes

- **user**: List active org members by default
  ([`2d9bc2c`](https://github.com/DailybotHQ/cli/commit/2d9bc2c43fa5b81d4b725454fd91fcedb97a9338))


## v1.10.0 (2026-05-26)

### Documentation

- Document forms lifecycle + teams + team-aware kudos surface
  ([`9e3e474`](https://github.com/DailybotHQ/cli/commit/9e3e47412922f6f4adf24bf84499863d4ddf06a6))

- **troubleshooting**: Document form-response Markdown subset
  ([`fa25062`](https://github.com/DailybotHQ/cli/commit/fa25062872bec82955271740e97e48a259159655))

### Features

- **form,team,kudos**: Forms lifecycle + team-aware kudos
  ([`4119e76`](https://github.com/DailybotHQ/cli/commit/4119e7614ebae063c339b64552948b116b900624))


## v1.9.0 (2026-05-22)

### Bug Fixes

- **codecheck**: Ruff format config.py valid keys line
  ([`446f6d9`](https://github.com/DailybotHQ/cli/commit/446f6d9239a0bbb43fbe9dc9fd1e59f38f50adc4))

### Chores

- **skills**: Replace dailybot-progress-report with full skill pack
  ([`0068638`](https://github.com/DailybotHQ/cli/commit/0068638a93170ec6d56291058da62a201fb59314))

### Documentation

- Document .dailybot_example template as best practice
  ([`ae61bce`](https://github.com/DailybotHQ/cli/commit/ae61bce0dbd00fde12fdc8aee8ba8e7a4a78dab0))

- Document vars key in repo profile
  ([`b71a00e`](https://github.com/DailybotHQ/cli/commit/b71a00ec581c481a3b6176bb4e66600c5deab8ab))

### Features

- **config**: Support `vars` key in .dailybot/profile.json and gitignore .dailybot/
  ([`21451ea`](https://github.com/DailybotHQ/cli/commit/21451eae0a4352b1224c447b08d25f0339a65ec8))


## v1.8.0 (2026-05-22)

### Bug Fixes

- **auth**: Improve multi-org selection in interactive login
  ([`0f25ff3`](https://github.com/DailybotHQ/cli/commit/0f25ff397facd119477871f74fde1d79bba40cb2))

- **codecheck**: Ruff format + fix isolated_global_agents test fixture
  ([`58fdcd8`](https://github.com/DailybotHQ/cli/commit/58fdcd81b4bb2c04fda0e494b0dc1656f45ea591))

- **codecheck**: Security hardening and linter cleanup for user-scoped API
  ([`8b9ef78`](https://github.com/DailybotHQ/cli/commit/8b9ef7890014aceb5bfe450a007083f23ff4dea5))

### Build System

- **docker**: Improve clitest with API env pinning and network
  ([`060b0b4`](https://github.com/DailybotHQ/cli/commit/060b0b40fb6523e18c46e4142d7fb559aaf62b5e))

### Documentation

- Update all docs for user-scoped commands (checkin, form, kudos, user)
  ([`066c195`](https://github.com/DailybotHQ/cli/commit/066c1951fe8298ef314b68bf6a720b46ceac1b8a))

- **readme**: Document user-scoped commands (checkin, form, kudos, user)
  ([`086381f`](https://github.com/DailybotHQ/cli/commit/086381ff3485e7eff8a53c2445eef4a3e2b579c3))

### Features

- **cli**: Add checkin, form, and kudos commands
  ([`9c2c278`](https://github.com/DailybotHQ/cli/commit/9c2c278e3d07d9311edda10a4fb6b131651af0a5))

- **client**: Add user-scoped public API methods
  ([`4598d3f`](https://github.com/DailybotHQ/cli/commit/4598d3f1a5fa8b96721595fd645d81840d963c7c))

- **config**: Honor DAILYBOT_CONFIG_DIR for sandbox isolation
  ([`b8b4277`](https://github.com/DailybotHQ/cli/commit/b8b42774215c518cbf8d298a5769c51cb6c26946))

- **interactive**: Expand menu with public API flows
  ([`00a46f3`](https://github.com/DailybotHQ/cli/commit/00a46f35086aff2e0c37937eae050fcb3995fbcb))

- **interactive**: Show API URL and handle login failures gracefully
  ([`380c37b`](https://github.com/DailybotHQ/cli/commit/380c37b301bd494fafff6a06ae4c923102269efd))

### Refactoring

- **cli**: Extract user_scoped_actions shared handlers
  ([`43e975f`](https://github.com/DailybotHQ/cli/commit/43e975fdf3129de6775e0d71dfbe4cc41e486602))

### Testing

- **cli**: Add coverage for checkin, form, and kudos commands
  ([`914d077`](https://github.com/DailybotHQ/cli/commit/914d0771e175c20b2d1e3bbb07bcba80e368d53e))

- **cli**: Cover user list and interactive kudos menu
  ([`bf5f7cf`](https://github.com/DailybotHQ/cli/commit/bf5f7cf7f1ba1a2a1417ff2ba0f172bfd5707870))


## v1.7.1 (2026-05-04)

### Bug Fixes

- **upgrade**: Pin version + verify post-install to prevent silent no-ops
  ([`5a26bbf`](https://github.com/DailybotHQ/cli/commit/5a26bbf8c0e68542750c6af4db8f192c202a51b0))


## v1.7.0 (2026-05-04)

### Features

- **agent**: Onboarding wizard, --repo flag, and first-run nudge
  ([`228f22d`](https://github.com/DailybotHQ/cli/commit/228f22dcd55eb88c7f5ab11bc4df1df276474d58))


## v1.6.1 (2026-05-03)


## v1.6.0 (2026-05-03)

### Features

- **cli**: Add `dailybot uninstall` command with install-method detection
  ([`4af6279`](https://github.com/DailybotHQ/cli/commit/4af62799719fa2c1afc3c40b91f7973d90ad2e96))


## v1.5.0 (2026-05-03)


## v1.4.1 (2026-05-03)

### Bug Fixes

- **ci**: Use PSR 10's PATCH level for default_bump_level
  ([`cbb375c`](https://github.com/DailybotHQ/cli/commit/cbb375c527949d4474fc0143d328963f477bf0c6))

### Continuous Integration

- Bump actions/checkout to v6 and setup-python to v6
  ([`7e9cbe6`](https://github.com/DailybotHQ/cli/commit/7e9cbe633e774c585dd99d5e8a79407f6a8b8f4b))


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
