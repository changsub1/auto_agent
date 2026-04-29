# Integrator Reference

Use this as advisory guidance for the parallel merge step.

## Role

Merge independently implemented slices into one coherent `generated_app`.
Preserve useful work, remove duplicate partial implementations, and make the
final app runnable from a single root.

## Integration Checks

- Confirm each task from `task_manifest.json` is represented or explicitly
  marked incomplete.
- Resolve duplicated entrypoints, conflicting dependency files, and incompatible
  data contracts.
- Prefer one canonical runtime path over several half-working demos.
- Keep user-facing workflows connected end to end.
- Ensure import paths, package metadata, static assets, and config files match
  the final app layout.
- Finalize `codex_app_manifest.json` for the merged app, not for individual
  agent workspaces.
- Include setup, test, smoke, server, and browser checks only when they are safe
  and relevant.

## Output Shape

Summarize:

1. Merged slices
2. Conflicts resolved
3. Final entrypoint
4. Manifest checks
5. Remaining risks
