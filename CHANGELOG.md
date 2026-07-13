# Changelog

All notable changes to this project are documented in this file.

This file is generated automatically by
[python-semantic-release](https://python-semantic-release.readthedocs.io/) from
the `feat:` / `fix:` / `perf:` / `BREAKING CHANGE:` commit messages on `main`.
Do not edit it by hand — your edits will be overwritten on the next release.

<!-- version list -->

## v3.6.1 (2026-07-13)

### Chores

- **skills**: Sync vendored dailybot skill pack to v3.9.0 + bump CLI pin
  ([#68](https://github.com/DailybotHQ/cli/pull/68),
  [`390e2fa`](https://github.com/DailybotHQ/cli/commit/390e2fad07d78bd29c60db612accda3e7b70a603))


## v3.6.0 (2026-07-13)

### Documentation

- **forms**: Update list visibility to reflect org-wide access
  ([#67](https://github.com/DailybotHQ/cli/pull/67),
  [`d241945`](https://github.com/DailybotHQ/cli/commit/d2419452ce81ded76b3aa8c451bc7e0323c3bab5))

### Features

- **form**: Add --owner filter, form owners picker, and migrate --mine to owner_user_ids
  ([#67](https://github.com/DailybotHQ/cli/pull/67),
  [`d241945`](https://github.com/DailybotHQ/cli/commit/d2419452ce81ded76b3aa8c451bc7e0323c3bab5))

- **form**: Owner filter, form owners picker, and org-wide list visibility
  ([#67](https://github.com/DailybotHQ/cli/pull/67),
  [`d241945`](https://github.com/DailybotHQ/cli/commit/d2419452ce81ded76b3aa8c451bc7e0323c3bab5))


## v3.5.2 (2026-07-13)

### Bug Fixes

- **tests**: Reset _app_url_override in test_get_app_url_default
  ([#66](https://github.com/DailybotHQ/cli/pull/66),
  [`b8e90c3`](https://github.com/DailybotHQ/cli/commit/b8e90c3dbd76c57a6a07ec794bbb7a916aaf630c))

### Chores

- **docker**: Bump devcontainer CLI pin to >= 3.5.1
  ([#66](https://github.com/DailybotHQ/cli/pull/66),
  [`b8e90c3`](https://github.com/DailybotHQ/cli/commit/b8e90c3dbd76c57a6a07ec794bbb7a916aaf630c))

- **skills**: Sync vendored dailybot skill pack to v3.7.1
  ([#66](https://github.com/DailybotHQ/cli/pull/66),
  [`b8e90c3`](https://github.com/DailybotHQ/cli/commit/b8e90c3dbd76c57a6a07ec794bbb7a916aaf630c))

- **skills**: Sync vendored skill pack v3.7.1 + bump devcontainer CLI pin
  ([#66](https://github.com/DailybotHQ/cli/pull/66),
  [`b8e90c3`](https://github.com/DailybotHQ/cli/commit/b8e90c3dbd76c57a6a07ec794bbb7a916aaf630c))


## v3.5.1 (2026-07-13)

### Bug Fixes

- **client**: Auto-retry agent requests with Bearer when API key is rejected
  ([#64](https://github.com/DailybotHQ/cli/pull/64),
  [`ff23b9e`](https://github.com/DailybotHQ/cli/commit/ff23b9e97f4783dfa5b6e4c128f523d42c66b86b))

### Code Style

- Apply ruff format ([#64](https://github.com/DailybotHQ/cli/pull/64),
  [`ff23b9e`](https://github.com/DailybotHQ/cli/commit/ff23b9e97f4783dfa5b6e4c128f523d42c66b86b))

- **tests**: Combine nested with statements (ruff SIM117)
  ([#64](https://github.com/DailybotHQ/cli/pull/64),
  [`ff23b9e`](https://github.com/DailybotHQ/cli/commit/ff23b9e97f4783dfa5b6e4c128f523d42c66b86b))

### Refactoring

- **client**: Unify auth priority — Bearer first everywhere
  ([#64](https://github.com/DailybotHQ/cli/pull/64),
  [`ff23b9e`](https://github.com/DailybotHQ/cli/commit/ff23b9e97f4783dfa5b6e4c128f523d42c66b86b))


## v3.5.0 (2026-07-12)

### Chores

- **skill**: Sync vendored forms skill with agent-skill v3.5.0
  ([#63](https://github.com/DailybotHQ/cli/pull/63),
  [`f4e7ddc`](https://github.com/DailybotHQ/cli/commit/f4e7ddcfa882981fa83ec8b1d373a7fbe7529757))

### Features

- **form**: Add --automation and --anonymous flags to form submit
  ([#63](https://github.com/DailybotHQ/cli/pull/63),
  [`f4e7ddc`](https://github.com/DailybotHQ/cli/commit/f4e7ddcfa882981fa83ec8b1d373a7fbe7529757))

- **form**: Add --guest-name, --guest-email, --source flags to form submit
  ([#63](https://github.com/DailybotHQ/cli/pull/63),
  [`f4e7ddc`](https://github.com/DailybotHQ/cli/commit/f4e7ddcfa882981fa83ec8b1d373a7fbe7529757))

- **form**: Add filtering, sorting, and source flags to form list and responses
  ([#63](https://github.com/DailybotHQ/cli/pull/63),
  [`f4e7ddc`](https://github.com/DailybotHQ/cli/commit/f4e7ddcfa882981fa83ec8b1d373a7fbe7529757))

- **form**: Full forms filtering, sorting, automation & guest identity
  ([#63](https://github.com/DailybotHQ/cli/pull/63),
  [`f4e7ddc`](https://github.com/DailybotHQ/cli/commit/f4e7ddcfa882981fa83ec8b1d373a7fbe7529757))


## v3.4.0 (2026-07-12)

### Features

- **cli**: Add --app-url flag, dashboard URL catalog, and skill pack sync
  ([#62](https://github.com/DailybotHQ/cli/pull/62),
  [`30c4979`](https://github.com/DailybotHQ/cli/commit/30c4979b2d10c4c0f411e536bc09a155ac2b6b80))


## v3.3.0 (2026-07-12)

### Bug Fixes

- **ci**: Resolve mypy unreachable error and fix display escaping test
  ([#60](https://github.com/DailybotHQ/cli/pull/60),
  [`bbf1106`](https://github.com/DailybotHQ/cli/commit/bbf11060163be15007617ba0983cfc054f9e72b8))

- **cli**: Add client-side search query length validation (CORE-2263)
  ([#60](https://github.com/DailybotHQ/cli/pull/60),
  [`bbf1106`](https://github.com/DailybotHQ/cli/commit/bbf11060163be15007617ba0983cfc054f9e72b8))

- **cli**: Resolve QA findings + conversation participant limit (CORE-2259)
  ([#60](https://github.com/DailybotHQ/cli/pull/60),
  [`bbf1106`](https://github.com/DailybotHQ/cli/commit/bbf11060163be15007617ba0983cfc054f9e72b8))

- **cli**: Resolve QA findings from CLI 3.2.x full-suite (CORE-2259)
  ([#60](https://github.com/DailybotHQ/cli/pull/60),
  [`bbf1106`](https://github.com/DailybotHQ/cli/commit/bbf11060163be15007617ba0983cfc054f9e72b8))

### Code Style

- **cli**: Apply ruff format to status, api_client_test, public_api_commands_test
  ([#60](https://github.com/DailybotHQ/cli/pull/60),
  [`bbf1106`](https://github.com/DailybotHQ/cli/commit/bbf11060163be15007617ba0983cfc054f9e72b8))

### Features

- **conversation**: Enforce Slack MPIM participant limit (max 7 + bot)
  ([#60](https://github.com/DailybotHQ/cli/pull/60),
  [`bbf1106`](https://github.com/DailybotHQ/cli/commit/bbf11060163be15007617ba0983cfc054f9e72b8))


## v3.2.2 (2026-07-11)

### Chores

- **ci**: Pin dev-container CLI floor to >=3.2.1 ([#58](https://github.com/DailybotHQ/cli/pull/58),
  [`844d37a`](https://github.com/DailybotHQ/cli/commit/844d37a1b09708d059b034a9114bbfefea80547d))

### Documentation

- **skill**: Sync vendored DeepWorkPlan skill to v2.16.0
  ([#59](https://github.com/DailybotHQ/cli/pull/59),
  [`df089ba`](https://github.com/DailybotHQ/cli/commit/df089ba6810d6bd74c4c3c0d0fcb52b77b9776c3))


## v3.2.1 (2026-07-11)

### Documentation

- **skill**: Sync vendored skill pack to v3.4.0 and pin dev container to CLI >= 3.2.0
  ([`d8d3bc4`](https://github.com/DailybotHQ/cli/commit/d8d3bc4c29afe4c997391fa6f374461efbbf5164))


## v3.2.0 (2026-07-11)

### Features

- **cli**: Org-scoped form list (--mine) and Slack group DM support (conversation open)
  ([`e8b4d06`](https://github.com/DailybotHQ/cli/commit/e8b4d0604f78e8b2cfb1de04d8825336ad88d179))


## v3.1.3 (2026-07-10)

### Documentation

- **skill**: Sync vendored skill pack to v3.3.0 and pin dev container to CLI >= 3.1.2
  ([`e73ce7c`](https://github.com/DailybotHQ/cli/commit/e73ce7ce8454947d3c060e1cd02917824b0c01be))


## v3.1.2 (2026-07-10)

### Bug Fixes

- **kudos**: Align with the API's role-audit fixes (org-admin code + kudos filter)
  ([`f21d980`](https://github.com/DailybotHQ/cli/commit/f21d980b92391179af0d3250252a952375d21835))


## v3.1.1 (2026-07-10)

### Documentation

- **skill**: Sync vendored Dailybot skill pack to v3.2.0
  ([`429e653`](https://github.com/DailybotHQ/cli/commit/429e653783e1a015010906fa7e3b27803b7e9203))


## v3.1.0 (2026-07-10)

### Features

- **cli**: Migrate to the always-paginated, uuid-keyed public API
  ([`3561f71`](https://github.com/DailybotHQ/cli/commit/3561f71427b59659e93f8d708818d815c18f8cf5))


## v3.0.2 (2026-07-10)

### Chores

- **docs**: Sync vendored Dailybot skill pack to v3.0.1
  ([`c33dde4`](https://github.com/DailybotHQ/cli/commit/c33dde492a47572799b7d6002b9db5f558ed5797))


## v3.0.1 (2026-07-10)

### Bug Fixes

- **docker**: Make the curl-pipe install fail loudly instead of silently skipping
  ([`23dbdd7`](https://github.com/DailybotHQ/cli/commit/23dbdd7b40acb0ef94f0bc28b98edb9c167b4096))


## v3.0.0 (2026-07-10)

### Features

- Align CLI major with the Dailybot agent skill pack (3.0)
  ([`b557979`](https://github.com/DailybotHQ/cli/commit/b557979adf9c7f3dce0dc0b6d1873ca555b57e08))

### Breaking Changes

- The CLI major version now tracks the Dailybot agent skill pack major line (3.x). No functional API
  change relative to 2.x.


## v2.0.1 (2026-07-10)

### Documentation

- **skill**: Sync vendored Dailybot skill pack to 3.0.0
  ([`9372cac`](https://github.com/DailybotHQ/cli/commit/9372cacb402c8bd5c122a1bbb84c3357e8cc415d))


## v2.0.0 (2026-07-10)

### Features

- Cut 2.0.0 and document the public-API-parity breaking changes
  ([`b423702`](https://github.com/DailybotHQ/cli/commit/b4237022740a87e984a48c8380779840cf4dbf5a))

### Breaking Changes

- List commands now return a paginated {count,next,previous,results} envelope and error handling
  dispatches on machine-readable codes. These consumer-visible contract changes shipped in 1.20.0
  and are now versioned as 2.0.0.


## v1.20.0 (2026-07-10)

### Chores

- **security**: Security review - Task 13 of PLAN_cli_full_public_api_support
  ([`33c96f8`](https://github.com/DailybotHQ/cli/commit/33c96f887725ac893b27a2af83ee20b744db16c6))

- **skills**: Skills & agents discovery - Task 14 of PLAN_cli_full_public_api_support
  ([`8a30f0f`](https://github.com/DailybotHQ/cli/commit/8a30f0f6cb49d7c16e4bdde954a1eb250b269444))

### Documentation

- **cli**: Document new commands, query flags, error codes - Task 10 of
  PLAN_cli_full_public_api_support
  ([`49a22e9`](https://github.com/DailybotHQ/cli/commit/49a22e930d81dd25fb3e0d9315b2b5a7b6a62eb1))

### Features

- **chat**: Add --send-as-user / --send-as-me identity - Task 12 of PLAN_cli_full_public_api_support
  ([`89a32bc`](https://github.com/DailybotHQ/cli/commit/89a32bc741c39c52514b77981bb1fafca4ad8925))

- **cli**: Add kudos list / org / wall-of-fame commands - Task 8 of PLAN_cli_full_public_api_support
  ([`e4bbdfa`](https://github.com/DailybotHQ/cli/commit/e4bbdfa3175639df292335021efbeb9277e23c70))

- **cli**: Add me / org / user get read-only commands - Task 7 of PLAN_cli_full_public_api_support
  ([`3361cc7`](https://github.com/DailybotHQ/cli/commit/3361cc70ba539f8ae12037d349cfb870b11efe54))

- **cli**: Add shared query-flags module - Task 5 of PLAN_cli_full_public_api_support
  ([`9be7f43`](https://github.com/DailybotHQ/cli/commit/9be7f433d92a63cdbe261e6296ed81ad69e247d9))

- **cli**: Add workflow list / get read commands - Task 9 of PLAN_cli_full_public_api_support
  ([`ed79cef`](https://github.com/DailybotHQ/cli/commit/ed79cef9711c382a786fc0036fa6efa90f37b22b))

- **cli**: Wire shared query flags into list commands - Task 6 of PLAN_cli_full_public_api_support
  ([`16a6f3d`](https://github.com/DailybotHQ/cli/commit/16a6f3ddb27ea51608a86a8a672cb6d0888197b1))

- **client**: Add shared paginated-GET helper - Task 1 of PLAN_cli_full_public_api_support
  ([`d603795`](https://github.com/DailybotHQ/cli/commit/d60379598f2e939084c65b85a90259c9b7c84f2e))

- **client**: Confirm API-key parity and keep logout Bearer-only - Task 4 of
  PLAN_cli_full_public_api_support
  ([`20abc57`](https://github.com/DailybotHQ/cli/commit/20abc57e61081d77630bbf1758a34b834dfc8891))

- **client**: Dispatch on error codes and handle rate limits - Task 2 of
  PLAN_cli_full_public_api_support
  ([`4a3e02b`](https://github.com/DailybotHQ/cli/commit/4a3e02b1c576fac9b0a528ce7368f4f6b49c064e))

- **config**: Free-plan awareness + allowlist short-circuit - Task 3 of
  PLAN_cli_full_public_api_support
  ([`123d157`](https://github.com/DailybotHQ/cli/commit/123d15717529f4ec1e51cf7798652b7cab0e3a4f))

### Testing

- **cli**: Comprehensive integration coverage of backend checklist - Task 11 of
  PLAN_cli_full_public_api_support
  ([`090597a`](https://github.com/DailybotHQ/cli/commit/090597a00febdd7eaf7521f9a25404024723788b))


## v1.19.2 (2026-07-08)

### Documentation

- **skill**: Sync vendored skill to 1.8.5 + resolve version-treadmill and config gaps
  ([`5f58e55`](https://github.com/DailybotHQ/cli/commit/5f58e55fc45f96e167e6a55ce94ba4b18f9e1f79))


## v1.19.1 (2026-07-08)

### Documentation

- **skill**: Sync vendored dailybot skill pack to 1.8.4
  ([`e93d3ea`](https://github.com/DailybotHQ/cli/commit/e93d3ea4230ae89932b95af16a5277eb7c8fd7e1))


## v1.19.0 (2026-07-08)

### Chores

- **config**: Enable continuous report mode for the cli repo
  ([`0d77060`](https://github.com/DailybotHQ/cli/commit/0d77060e0910c179fa8e8e5b7c7c698e85913748))

### Code Style

- **hooks**: Wrap long line in ledger to satisfy ruff format gate
  ([`68b6197`](https://github.com/DailybotHQ/cli/commit/68b619760155fd797af46ed8734dea885ccb6ac5))


## v1.18.2 (2026-07-07)

### Documentation

- **skill**: Sync vendored dailybot skill pack to 1.8.3
  ([`4d860e6`](https://github.com/DailybotHQ/cli/commit/4d860e6764275fdc09a192aa4d70f3dacd9e1d6d))


## v1.18.1 (2026-07-07)

### Documentation

- **docs**: Bump README install examples to 1.18.0
  ([`109bd20`](https://github.com/DailybotHQ/cli/commit/109bd20ad230ae7baa5b011f35005fc958a26520))


## v1.18.0 (2026-07-07)

### Features

- **checkin**: Align responses listing with restored all-participants default
  ([`407d3ee`](https://github.com/DailybotHQ/cli/commit/407d3ee67271d0a10d22e8f7f3e04b9ae2c9697b))


## v1.17.2 (2026-07-06)

### Documentation

- **skill**: Sync vendored skill to 1.8.1 + recommend the agent skill for AI agents
  ([`e8c9f30`](https://github.com/DailybotHQ/cli/commit/e8c9f303df56e0ead346f7fd56c5d32d8cf5877b))


## v1.17.1 (2026-07-06)

### Bug Fixes

- **forms,checkin**: Require at least one question at create (questions_required)
  ([`e29f25b`](https://github.com/DailybotHQ/cli/commit/e29f25b0114b1f8a18b7114065f099043719ab3c))


## v1.17.0 (2026-07-06)

### Bug Fixes

- **checkin**: Frequency_type is weekly-only; monthly/custom via frequency_advanced
  ([`c1d24ff`](https://github.com/DailybotHQ/cli/commit/c1d24ff1c2aca0480147e003849c56e2477c57c9))

- **checkin**: Friendly error for an unresolvable --user/--team participant
  ([`423668b`](https://github.com/DailybotHQ/cli/commit/423668bc201d670131176328bb6790f5b8f74a43))

- **cli**: Harden authoring validation and error mapping - Task 8 of
  PLAN_agent_forms_checkins_authoring
  ([`6c7f261`](https://github.com/DailybotHQ/cli/commit/6c7f261c38b8ea41a27691c516e851ca78489768))

- **client**: Question reorder sent the wrong field name (silent no-op)
  ([`218b4a6`](https://github.com/DailybotHQ/cli/commit/218b4a6d6fa932d3a11a2a007c2132b9361e2bb7))

- **client**: Unwrap {"channels": [...]} from the report-channels endpoint
  ([`0b0d20f`](https://github.com/DailybotHQ/cli/commit/0b0d20f083566a12aaee086a79e312a4eb9172f8))

- **forms,checkin**: Correct numeric logic operator spelling (_than suffix)
  ([`bdc0a7e`](https://github.com/DailybotHQ/cli/commit/bdc0a7e952732823f9714a61d901f645992cd49f))

### Chores

- **security**: Security review of authoring feature - Task 12 of
  PLAN_agent_forms_checkins_authoring
  ([`b734d22`](https://github.com/DailybotHQ/cli/commit/b734d226ae1ac069874ceb4cb7c26b4ac681aefe))

### Documentation

- Document forms/check-ins authoring commands - Task 10 of PLAN_agent_forms_checkins_authoring
  ([`ac03d08`](https://github.com/DailybotHQ/cli/commit/ac03d08dd7753a7de48ea23c0eba63db96766869))

- **skill**: Sync vendored dailybot skill with authoring - Task 11 of
  PLAN_agent_forms_checkins_authoring
  ([`c870893`](https://github.com/DailybotHQ/cli/commit/c870893bbcb2ee8ea29c018aa0c2f97e2fd928e4))

### Features

- **checkin**: Expose smart/AI, reminder tone & advanced cron config (100% web parity)
  ([`648311c`](https://github.com/DailybotHQ/cli/commit/648311c3af9a7c9aef236b2c5ca27c8fed1710e4))

- **checkin**: Full check-in configuration via create + config flags
  ([`68f7337`](https://github.com/DailybotHQ/cli/commit/68f7337a8a61f7a168d4aa1ba7eee595a8a4b9cb))

- **checkin**: Map server-side checkin_requires_participant error
  ([`a8eb201`](https://github.com/DailybotHQ/cli/commit/a8eb201a7c62df6e94c214ea4795d060ad2b3186))

- **checkin**: Require at least one participant; edit participants via config
  ([`a7ca34f`](https://github.com/DailybotHQ/cli/commit/a7ca34facb2bb0cfaf70b7a8d6cc9a1d266a9482))

- **cli**: Add channels list command - Task 4 of PLAN_agent_forms_checkins_authoring
  ([`d0628a7`](https://github.com/DailybotHQ/cli/commit/d0628a76747e86c40e1691d11f9b46e7f0662bc6))

- **cli**: Add check-in authoring commands - Task 6 of PLAN_agent_forms_checkins_authoring
  ([`5464066`](https://github.com/DailybotHQ/cli/commit/5464066af5532ea4980c69cfe32c46eeb4cadda8))

- **cli**: Add form authoring commands - Task 5 of PLAN_agent_forms_checkins_authoring
  ([`aaf4874`](https://github.com/DailybotHQ/cli/commit/aaf4874790c332bc061d35ea90bebac03e7bfb09))

- **cli**: Add forms/check-ins authoring helpers and display - Task 3 of
  PLAN_agent_forms_checkins_authoring
  ([`e7b2f18`](https://github.com/DailybotHQ/cli/commit/e7b2f18a374a79577fbdc32999552a9f8fbdad75))

- **cli**: Add interactive question builder - Task 7 of PLAN_agent_forms_checkins_authoring
  ([`db6dc41`](https://github.com/DailybotHQ/cli/commit/db6dc417995270e79c639f6c4f333862cc0b7aeb))

- **client**: Add check-ins authoring methods - Task 2 of PLAN_agent_forms_checkins_authoring
  ([`8aa8b75`](https://github.com/DailybotHQ/cli/commit/8aa8b757ab7c051c293075d62f8ee89946b15a2c))

- **client**: Add report-channel + forms authoring methods - Task 1 of
  PLAN_agent_forms_checkins_authoring
  ([`5b4e0b7`](https://github.com/DailybotHQ/cli/commit/5b4e0b7679cee33c45206eab0747149df0af143a))

- **client**: Request include_email so email resolution works (admin/manager)
  ([`3f9a2cd`](https://github.com/DailybotHQ/cli/commit/3f9a2cd702ef0b2158487cfdc917734c2638bb1c))

- **display**: Render report-channel names + map report_channel_not_found
  ([`3a76674`](https://github.com/DailybotHQ/cli/commit/3a766745670afd8a7be48415df9e05b7be11753f))

- **forms**: Align authoring surface to the finalized canonical contract
  ([`235ad93`](https://github.com/DailybotHQ/cli/commit/235ad93b9392f753808c5e2a763b56fe2cd4fc95))

- **forms**: Full form config authoring — workflow, permissions, approval, command
  ([`cf2f4d7`](https://github.com/DailybotHQ/cli/commit/cf2f4d7dc093786d6c98aa4e1d80661944583b9e))

- **forms,checkin**: Finalize question logic — required else, forward jumps, full operator set
  ([`1e95efe`](https://github.com/DailybotHQ/cli/commit/1e95efe4dca6ae5752d7c5d04b60cb0b22234e93))

- **forms,checkin**: Forward generate_short_question opt-in + map short_question_required
  ([`5bffa88`](https://github.com/DailybotHQ/cli/commit/5bffa88fcb655e3e42b1984dbaf744fcc87cca47))

- **forms,checkin**: Map reorder validation codes + explicit full-replace audiences
  ([`7c1ce87`](https://github.com/DailybotHQ/cli/commit/7c1ce87b706377adbe1dde620913831b428dd238))

- **forms,checkin**: Per-question extras (short title, variations, logic) + error mapping
  ([`c1d22dd`](https://github.com/DailybotHQ/cli/commit/c1d22dd1674970907a89e8bbcecc0881591ffefb))

- **forms,checkin**: Require an explicit short_question unless --ai-short-question
  ([`db869b1`](https://github.com/DailybotHQ/cli/commit/db869b10e12d25a3c32651f940402a80b17d8ebf))

- **forms,checkin**: Resolve users by email + --no-approvers to clear approvers
  ([`f894dd9`](https://github.com/DailybotHQ/cli/commit/f894dd944cea2c6d477327cc03e81c0ea3aaa55e))

- **forms,checkin**: Surface public_url + enforce the 3 report-channel cap
  ([`e23b06c`](https://github.com/DailybotHQ/cli/commit/e23b06cbd5811786b9d3a8c3fc1916a5b1da8f5d))

- **release**: Support minimum-version floor in installers
  ([`13d4a15`](https://github.com/DailybotHQ/cli/commit/13d4a156bb48a8417408a51f55e0682a7a39eeec))

### Refactoring

- **cli**: Attach report_channels inline on form create
  ([`128a821`](https://github.com/DailybotHQ/cli/commit/128a821db24989d9aaaef7757433baac5979c3bf))

- **display**: Drop question-shape fallbacks now the API contract is canonical
  ([`e8a13bb`](https://github.com/DailybotHQ/cli/commit/e8a13bb58ea458de452d557adb5c65afdb259eba))

### Testing

- **cli**: Add authoring lifecycle integration tests - Task 9 of PLAN_agent_forms_checkins_authoring
  ([`7bb74cf`](https://github.com/DailybotHQ/cli/commit/7bb74cf621c49221f6433e9fddeb56d4eb3acab4))


## v1.16.0 (2026-07-03)

### Features

- **release**: Let installers pin a specific CLI version
  ([`3d3d3fe`](https://github.com/DailybotHQ/cli/commit/3d3d3fe272f7299fb11175cbaf2f4f7000e204b0))


## v1.15.1 (2026-07-03)

### Bug Fixes

- **display**: Keep the report placement link on the "View:" line
  ([`b5cf145`](https://github.com/DailybotHQ/cli/commit/b5cf14504b4d40b92f5d2880d9b38c011e8aad03))

### Chores

- **agents**: Add Cursor hook config and pin repo report policy
  ([`257f432`](https://github.com/DailybotHQ/cli/commit/257f432dab350c3df5dfae887ddb60fb10be95c2))

- **skill**: Sync vendored Dailybot skill pack to latest
  ([`91e2230`](https://github.com/DailybotHQ/cli/commit/91e2230e16ac7def4507c615b2cd73ec7f4582c8))

### Code Style

- **tests**: Wrap long URL literal to satisfy ruff format
  ([`f5c5e63`](https://github.com/DailybotHQ/cli/commit/f5c5e637d2f82d974928324fa8520cb512756a74))


## v1.15.0 (2026-07-03)

### Bug Fixes

- **checkin**: Read template questions from the nested 'fields' object
  ([`e1d9262`](https://github.com/DailybotHQ/cli/commit/e1d9262420bb1d08e5239d5ffa12b951baa7be93))

- **interactive**: Satisfy mypy for form responses
  ([`e27cfc7`](https://github.com/DailybotHQ/cli/commit/e27cfc7a1256ffe935eec38dfe13a64186ce2fe8))

- **interactive**: Satisfy ruff format for terminal flows
  ([`776bd9d`](https://github.com/DailybotHQ/cli/commit/776bd9d9fce88441b7550cb328be2bded1960f23))

### Code Style

- Apply ruff format to check-in commands and helpers
  ([`cb8c339`](https://github.com/DailybotHQ/cli/commit/cb8c339b7133bc116f2ba28f5ea5e6a2f54071e4))

### Documentation

- **security**: Redact real internal identifiers + add open-source privacy rule
  ([`712362b`](https://github.com/DailybotHQ/cli/commit/712362b43205ef82ba91fed526c5b12569d83cd3))

### Features

- **ask**: Add headless `dailybot ask` AI command; deprecate `interactive`
  ([`abc64a7`](https://github.com/DailybotHQ/cli/commit/abc64a7a5b00b3210528782fd8b92aefd80b65fb))

- **ask**: Surface 429 rate-limit with Retry-After for AI chat
  ([`8dd24b4`](https://github.com/DailybotHQ/cli/commit/8dd24b4603c849a841cc5f0e7123d0e73ee52e76))

- **checkin**: Complete check-in lifecycle in the CLI (status/show/history/edit/reset)
  ([`4aeb9bf`](https://github.com/DailybotHQ/cli/commit/4aeb9bfa6759d1732ef67c059ae7337d357c2911))

- **cli**: Expand interactive terminal flows
  ([`6c1bf4d`](https://github.com/DailybotHQ/cli/commit/6c1bf4d7c37b7c15fa0c1a660796e01c9597701e))

- **interactive**: Add "Ask the Dailybot AI" menu entry that opens the chat
  ([`bf213a0`](https://github.com/DailybotHQ/cli/commit/bf213a0607e4e3e88dc2e0f7b53b3b331992ce59))

### Refactoring

- **tui**: Harden and polish Andrés's terminal flows
  ([`53355c9`](https://github.com/DailybotHQ/cli/commit/53355c993af1356b19acccf4f292dca6513fe4a1))


## v1.14.0 (2026-07-01)

### Bug Fixes

- **interactive**: Satisfy ruff format and mypy for chat TUI
  ([`92809c7`](https://github.com/DailybotHQ/cli/commit/92809c7e17b4a0f548c0b85e0e7b25ddbfbd24d5))

### Features

- **cli**: Add interactive chat TUI
  ([`a8a860d`](https://github.com/DailybotHQ/cli/commit/a8a860d4f051ed5322af07d475d65f6c75742054))


## v1.13.2 (2026-06-12)

### Chores

- **agents**: Adopt Deep Work Plan (deepworkplan-skill v2.12.0)
  ([`0151776`](https://github.com/DailybotHQ/cli/commit/01517763c1616c93308e2a9c71a43493cadff0d6))

- **agents**: Bump deepworkplan-skill vendored copy v2.12.0 → v2.15.0
  ([`e122d5e`](https://github.com/DailybotHQ/cli/commit/e122d5e692d1e89641c7aa96af8d02bd23f9725f))

- **skills**: Sync vendored dailybot pack to v1.7.1 (CLI 1.13.1 pin bump)
  ([`c19a20a`](https://github.com/DailybotHQ/cli/commit/c19a20a2210ad6d0a596b43b9e1eb1b57d3d0269))

### Documentation

- **design**: Adopt design-system addon — cli-output profile
  ([`f99e899`](https://github.com/DailybotHQ/cli/commit/f99e89925f578aae3a14ef6ca5935268a2d38f31))


## v1.13.1 (2026-06-12)

### Chores

- **skills**: Sync vendored dailybot pack to v1.7.0 (adds chat + teams)
  ([`3eece18`](https://github.com/DailybotHQ/cli/commit/3eece183be0bbe82768400d1bd41772c6a332a09))


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
