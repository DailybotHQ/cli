---
name: quick-fix
description: Tiny, single-file bug fix or typo correction with minimal ceremony.
trigger: /quick-fix or #quick-fix
inputs: A description of the bug or typo. The user may also point at a specific file/line.
prereqs: Working tree is clean or the user has approved the existing diff.
---

# Skill: `quick-fix`

For one-line bug fixes, typos, or trivial corrections. Skip planning overhead and ship.

## When to use

- A single-line code change.
- A typo in a docstring, error message, help text, or doc.
- A wrong constant value (e.g., a misnamed flag short alias).
- A small rewording of a user-facing string.

## When NOT to use

- The fix touches more than one file → use `cli-command-add` or a custom plan.
- The fix changes a public CLI flag, command name, or output format → that's a feature, not a typo. Use `cli-command-add`.
- The fix requires a new test → use the standard TDD path, not this skill.

## Procedure

1. **Confirm scope.** State out loud: "I'm doing a single-file change to `<path>` that does <X>." If the user disagrees, stop.
2. **Read the file.** Even for a one-liner — confirm the surrounding context isn't doing something unexpected.
3. **Make the change.** Use `Edit` (preferred) or `Write` (only for a new file).
4. **Verify.** Run only what's relevant:
   - Code change → `pytest -k <related>` (or whole file).
   - Docstring/help-text change → `dailybot <cmd> --help` to eyeball the rendering.
   - Doc change → grep for any other place the same text appears so you don't leave it half-fixed.
5. **Commit.** Use a short conventional message:
   ```
   fix(<scope>): <one-line description>
   ```
   Skip the body for true one-liners.
6. **Stop.** Don't sweep adjacent code. Don't reformat the file. Don't add a test "while you're there." If the fix uncovered something larger, surface it — don't expand silently.

## Anti-patterns

| Anti-pattern | Why it's wrong |
|--------------|----------------|
| Adding `# noqa` or `# type: ignore` to silence a linter | The lint failure is a sign the change isn't as small as you think |
| Bumping the version in the same commit as the fix | Version bumps are their own commit (see `release-prep`) |
| Reformatting the whole file with `black` | The diff becomes unreviewable |
| Adding a CHANGELOG entry | We don't maintain one — release notes are auto-generated from git |

## Example

User: "The `--blocked` short alias in `dailybot update` should be `-x`, not `-b`. `-b` is wrong."

```
1. Read dailybot_cli/commands/update.py to confirm.
2. Edit the line: `@click.option("--blocked", "-b", help=...)` → `... "-x" ...`.
3. Run `pytest tests/commands_test.py -k update`.
4. Run `dailybot update --help` to eyeball.
5. Commit:
     fix(update): use -x as short alias for --blocked (was -b)
6. Stop. Do not also touch --done or --doing.
```
