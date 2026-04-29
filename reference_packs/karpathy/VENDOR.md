# Karpathy Guidelines Vendor Notes

Source repository: https://github.com/forrestchang/andrej-karpathy-skills

Imported as local reference source on 2026-04-27.

Source commit:

```text
2c606141936f1eeef17fa3043a72095b4765b9c2
```

The source clone is kept at:

```text
reference_packs/karpathy_src/
```

That clone is intentionally ignored by Git. The project should commit only the
curated files in `reference_packs/karpathy/`.

## Use Policy

- Do not install the upstream Claude plugin from this orchestrator by default.
- Treat the upstream `CLAUDE.md` and skill as source material for concise,
  role-specific coding guidance.
- Use this pack mainly for Code Agents and the Integrator.
- Avoid applying this pack to Planner or QA roles unless the user explicitly
  wants coding-discipline guidance there.

## Source Files Reviewed

- `CLAUDE.md`
- `skills/karpathy-guidelines/SKILL.md`
- `README.md`

The curated files keep the useful coding behavior rules, but adjust the
clarification guidance for autonomous runs: agents should state assumptions and
proceed with the smallest safe interpretation unless implementation would be
unsafe, impossible, or likely to violate user intent.
