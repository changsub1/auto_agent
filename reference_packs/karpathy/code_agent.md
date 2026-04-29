# Code Agent Reference

Use this as default advisory guidance for implementation agents.

## Operating Bias

Build the smallest correct version that satisfies the approved assignment. Avoid
speculative architecture, extra features, broad rewrites, or style cleanup that
is not required for the task.

## Before Editing

- Restate the concrete success criteria in your own short terms.
- If the assignment is ambiguous, choose the smallest safe interpretation and
  state the assumption in your final summary.
- Ask for clarification only when continuing would be unsafe, impossible, or
  likely to violate the user's intent.
- If there is a simpler implementation path than the apparent one, prefer the
  simpler path and explain the tradeoff briefly.

## While Editing

- Touch only files required by your assignment and ownership rules.
- Match the existing project style instead of introducing a new pattern.
- Do not refactor adjacent code unless the assignment or failing check requires
  it.
- Do not add configurability, frameworks, or abstractions for a single current
  use case.
- Remove only unused code that your own changes created.
- Keep every changed line traceable to the user's request, approved plan, or QA
  feedback.

## Verification

- Convert requested behavior into a concrete check when practical.
- For bug fixes, prefer a small reproducer or test before the fix when the
  project supports it.
- Run the most focused safe check available.
- If a check cannot run, explain exactly why and name the command that should be
  run later.
- Keep `codex_app_manifest.json` aligned with the real setup, test, smoke,
  server, and browser checks for the app.

## Final Summary

Report:

1. Files changed
2. Behavior implemented
3. Checks run
4. Assumptions or skipped checks
