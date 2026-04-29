# Reference Packs

This directory stores curated, repo-local reference material that can be passed
to Codex-backed agents as optional guidance.

Reference packs are not executable plugins. They should not install tools,
change global Codex or Claude configuration, run update checks, or write outside
the current run workspace.

The intended flow is:

1. Keep third-party source clones in ignored local cache directories.
2. Extract small, role-specific guidance into committed Markdown files.
3. Select role profiles with `pack/role` identifiers such as
   `karpathy/code_agent` or `gstack/planner_b`.
4. Pass only the curated Markdown to Planner, Code, Integrator, or QA agents.
5. Keep command execution, screenshots, timeouts, and safety policy in the
   Python orchestrator and QA harness.

Default role profiles:

- `planner_a`: none
- `planner_b`: none
- `code_agent`: `karpathy/code_agent`
- `integrator`: `karpathy/integrator`
- `qa_agent`: none

If a reference pack later becomes stable enough to behave like a Codex skill,
promote the curated file into `.agents/skills/<name>/SKILL.md` with a narrow
trigger and no host-specific installer side effects.
