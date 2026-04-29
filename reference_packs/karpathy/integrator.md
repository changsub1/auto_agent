# Integrator Reference

Use this as default advisory guidance for merge and repair agents.

## Operating Bias

Integrate the smallest coherent final app from the available slices. Do not
turn integration into a rewrite unless the slices cannot be connected safely.

## Merge Discipline

- Preserve implemented behavior that matches the approved contract.
- Remove duplicate partial entrypoints in favor of one canonical runtime path.
- Resolve conflicts by following the approved plan, task ownership, and existing
  project style.
- Do not redesign module boundaries unless a real integration bug requires it.
- Avoid speculative cleanup in files unrelated to the integration failure.
- Keep dependency files minimal and consistent with the final app.

## Verification

- Make the final `generated_app` runnable from one documented root.
- Ensure README instructions and `codex_app_manifest.json` describe the same
  entrypoint and checks.
- Prefer focused syntax, unit, smoke, or browser checks over broad unrelated
  commands.
- If a slice cannot be integrated, state the exact missing contract, file, or
  behavior instead of hiding it.

## Final Summary

Report:

1. Slices merged
2. Conflicts resolved
3. Final entrypoint
4. Checks run
5. Remaining risks
