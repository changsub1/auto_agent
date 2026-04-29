# Code Agent Reference

Use this as advisory guidance for single or parallel Code Agents.

## Role

Implement the assigned app or slice according to the approved plan and file
ownership. Favor a working, testable vertical slice over speculative structure.

## Implementation Rules

- Edit only files needed for the assigned work.
- In parallel routes, respect file ownership and do not overwrite another
  agent's slice.
- Keep the app runnable from the final app root.
- Add focused tests or smoke checks when practical.
- Update README run instructions when an app has a manual startup command.
- Create or update `codex_app_manifest.json` for any runnable app or slice.
- Use language-neutral manifest commands as JSON arrays, not shell strings.
- Prefer safe local checks such as syntax, unit tests, CLI smoke commands, or a
  local dev server plus browser target.
- Do not include destructive commands, global installs, secrets, or commands
  that write outside the app workspace.

## Done Criteria

The assignment is done only when:

1. The requested behavior is implemented.
2. The entrypoint is discoverable through `codex_app_manifest.json`.
3. The local checks in the manifest are realistic for the generated app.
4. The README and source files agree on how the app runs.
5. Known gaps are stated clearly instead of hidden.
