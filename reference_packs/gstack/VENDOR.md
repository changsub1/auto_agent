# gstack Vendor Notes

Source repository: https://github.com/garrytan/gstack

Imported as local reference source on 2026-04-27.

Source commit:

```text
dde55103fcc42bd446d804ddc15567ced8455ac1
```

The source clone is kept at:

```text
reference_packs/gstack_src/
```

That clone is intentionally ignored by Git. The project should commit only the
curated files in `reference_packs/gstack/`.

## Use Policy

- Do not run `setup` or install gstack into global Codex or Claude directories
  from this orchestrator by default.
- Do not execute gstack browser, update, telemetry, or environment-bootstrap
  scripts inside generated app runs.
- Treat the original skills as design references, not as direct runtime
  instructions.
- Pass curated role files to agents as advisory context below the system prompt.
- Keep actual tool execution in the orchestrator, especially QA execution,
  screenshots, timeouts, and command allowlists.

## Source Skills Reviewed

- `plan-ceo-review/SKILL.md`
- `plan-eng-review/SKILL.md`
- `qa-only/SKILL.md`
- `qa/SKILL.md`
- `review/SKILL.md`
- `agents/openai.yaml`

The original files contain host-specific assumptions and interactive flows. The
curated files below keep the useful role discipline while avoiding direct
installer or tool-calling behavior.
