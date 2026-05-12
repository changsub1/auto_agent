# Stage 6: Prompt and Skill Configuration Plan

## Goal

Stage 6 makes agent behavior configurable from the desktop app without forcing
users to edit Python source files.

The product goal is simple:

- Users can inspect and edit each agent's System Prompt.
- Users can assign one or more skills or reference packs to each agent.
- Code Agents stay general by default; concrete work is assigned by the plan,
  contract, task manifest, and file ownership.
- The run timeline stays readable, while full prompts and raw logs remain
  available for debugging and reproducibility.

## Design Decisions

### 1. Use System Prompt as the agent role template

Do not introduce a separate `role_prompt` concept.

For this product, the agent's System Prompt is the full role template:

- what the agent is responsible for,
- what constraints it must follow,
- what output format it should use,
- what files or workspace boundaries it must respect,
- and what behavior should be prioritized.

For Codex CLI, this System Prompt is inserted near the top of the final stdin
prompt. For future API providers, the same field can map to the provider's real
system/instructions channel.

Provider mapping:

```text
Codex CLI:
  system_prompt -> top-level prompt prefix in stdin

OpenAI API:
  system_prompt -> system/instructions field

Anthropic API:
  system_prompt -> system parameter

Local LLM:
  system_prompt -> chat-template system section or prompt prefix
```

### 2. Keep skills separate from the System Prompt

Skills are supporting guidance, not the primary identity of the agent.

Examples:

- `karpathy/code_agent`
- `gstack/planner_a`
- `gstack/qa_agent`
- `accessibility_qa`
- `ethics_bias_qa`
- project-specific coding rules

Skills should be selected per agent or per run. The orchestrator should read
only the selected skill files, inject them into the agent prompt, and snapshot
the exact content used for that run.

### 3. Keep Code Agents general by default

Do not hard-code default Code Agents as `Frontend Agent`, `Backend Agent`, or
similar specialized roles.

Default Code Agents should share the same general implementation System Prompt.
Concrete responsibility should come from:

- the approved plan,
- contract bundle,
- `task_manifest.json`,
- file ownership,
- and per-run assignments.

This avoids mismatches where a "frontend" agent receives backend work or a small
single-page app has no meaningful frontend/backend split.

Specialization should be optional:

- users may override `code_2`'s System Prompt,
- users may assign a specialized skill,
- or the planner/architect may assign specialized tasks in the manifest.

### 4. Rename Planner labels in the UI, not necessarily internal IDs

Internal IDs can remain stable:

```text
planner_a
planner_b
planner_c
```

UI labels should be clearer:

```text
planner_a -> Planner / 기획자
planner_b -> Reviewer / 계획 검수자
planner_c -> Risk Reviewer / 리스크 검토자
```

The current data flow remains valid:

```text
Planner:
  user request -> initial plan

Reviewer:
  user request + Planner output + optional skill -> review findings

Planner:
  user request + previous plan + Reviewer output + user feedback -> final plan
```

## Current State

The current version already has important foundations:

- `PromptService` stores local prompt overrides in `local_prompt_overrides.json`.
- The GUI exposes `System Prompt`, `Skill / Guideline`, and effective preview
  fields for agent prompt editing.
- QA presets exist for default, ethics/bias, accessibility, and strict safety
  review.
- `reference_packs/` contains curated role guidance such as `karpathy` and
  `gstack` packs.
- Codex calls already persist raw prompt/stdout/stderr/meta logs under
  `runs/<run_id>/logs/`.
- Run prompt snapshots are partially persisted under `runs/<run_id>/prompts/`.

Current limitations:

- Many agent role prompts are still hard-coded inside `agents.py`.
- The GUI System Prompt currently behaves more like an added instruction block
  than the full editable agent role template.
- `Effective Prompt Preview` does not show the complete prompt actually sent to
  Codex CLI.
- Skill/reference pack selection is not yet a full GUI registry experience.
- The timeline can show agent outputs, but it should not become a raw prompt
  viewer.

## Target Prompt Assembly

Each agent call should be assembled from explicit, inspectable parts:

```text
[System Prompt]
Editable full agent role template.

[Skill / Guideline]
Selected skill.md or curated reference-pack content.

[Run Context]
User request, approved plan, contract, task assignment, file listing, QA report,
screenshots, or other stage-specific artifacts.

[Task Input]
The specific instruction for the current stage.
```

For Codex CLI, the assembled text is sent through stdin to `codex exec`.

For API providers, the same model can be split into provider-native fields:

```text
system/instructions:
  System Prompt

user/content:
  Skill / Guideline
  Run Context
  Task Input
```

The exact mapping may vary by provider, but the desktop app should keep one
provider-neutral configuration model.

## Proposed Files

Move default agent role templates out of Python source over time:

```text
agent_prompts/
  planner.md
  reviewer.md
  risk_reviewer.md
  architect.md
  scaffold.md
  code_agent.md
  integrator.md
  qa_agent.md
```

Local user overrides stay out of Git:

```text
local_prompt_overrides.json
```

Run snapshots should be stored with the run:

```text
runs/<run_id>/prompts/
  planner_system.md
  planner_skill.md
  planner_final_prompt.md
  code_1_system.md
  code_1_skill.md
  code_1_final_prompt.md
  qa_1_system.md
  qa_1_skill.md
  qa_1_final_prompt.md
  prompt_settings.json
```

Raw execution logs should continue to be stored separately:

```text
runs/<run_id>/logs/
  *_prompt.txt
  *_stdout.txt
  *_stderr.txt
  *_meta.txt
```

## GUI Behavior

### Prompt Editor

The Prompt Editor should expose:

- `System Prompt`
- `Skill / Guideline`
- `Final Prompt Preview`

The System Prompt tab should show the complete editable role template, not only
an additional instruction.

The Final Prompt Preview should render the actual prompt that will be sent to
the provider for a representative or current run context.

### Timeline

The run timeline should stay concise.

Show:

- agent label,
- stage,
- input summary,
- skill names or profile IDs,
- output preview,
- artifact links,
- approval/change/error events.

Do not show by default:

- full System Prompt text,
- full skill body,
- full final prompt,
- raw stdout/stderr.

Those should be available from a detail/debug panel or artifact viewer.

Example timeline item:

```text
Reviewer / Done
Input: User request + Planner output
Skills: gstack/planner_b
Output: 3 findings, approval gate recommended
Artifacts: planning/planner_b_review.md
```

## Implementation Steps

### Stage 6A: Template extraction

1. Add `agent_prompts/` with default Markdown templates.
2. Move the current hard-coded role instructions from `agents.py` into those
   templates without changing behavior.
3. Keep a Python fallback if a template file is missing.
4. Add tests that verify default templates load for each role.

### Stage 6B: System Prompt as full role template

1. Update `PromptService` so `system_prompt` is the complete editable role
   template.
2. Store user edits in `local_prompt_overrides.json`.
3. Preserve default/reset behavior.
4. Update labels/help text so users understand that System Prompt controls the
   agent's core behavior.

### Stage 6C: Final prompt rendering

1. Add a prompt assembly function shared by agents and preview APIs.
2. Render the actual final prompt before execution.
3. Save `*_final_prompt.md` artifacts for every agent call.
4. Keep existing raw `logs/*_prompt.txt` for low-level debugging.

### Stage 6D: Skill registry

1. Expose available skill/reference profiles through the local API.
2. Let users assign skills per agent card.
3. Read and inject only selected skill files for that run.
4. Store selected skill IDs and injected content in run prompt snapshots.
5. Keep default Code Agent skill general, such as `karpathy/code_agent`.

### Stage 6E: Timeline and artifact polish

1. Add sanitized `input_summary` and `skill_ids` to timeline events.
2. Keep full prompt bodies out of the default timeline.
3. Add links from timeline items to prompt artifacts, output artifacts, and raw
   logs.
4. Add an explicit debug/detail view for full prompts and stdout/stderr.

## Non-goals

- Do not build a general arbitrary-DAG runtime in this stage.
- Do not force Code Agents into fixed frontend/backend roles by default.
- Do not expose every raw prompt/log line in the main timeline.
- Do not require API-provider support before improving the Codex CLI prompt
  configuration flow.

## Success Criteria

- A user can inspect and edit the default System Prompt for Planner, Reviewer,
  Code Agent, Integrator, and QA Agent from the GUI.
- Code Agent 1/2/3 use the same default System Prompt unless explicitly
  overridden.
- A user can assign a skill/reference profile to an agent and see the skill name
  in the run timeline.
- Each run stores the exact system prompt, skill content, final prompt, stdout,
  stderr, and meta information used by each agent call.
- The main timeline remains readable and focuses on agent progress and output,
  not raw prompt internals.
