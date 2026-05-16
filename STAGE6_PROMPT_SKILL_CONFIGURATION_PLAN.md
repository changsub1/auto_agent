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
planner_b -> Reviewer / 계획 검토자
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

- Most default agent role prompts have been moved out of `agents.py` into
  `agent_prompts/*.md`. `agents.py` should now be treated as a task prompt
  builder that injects run context and stage-specific inputs.
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

Implementation status: completed in the Stage 6A slice.

Goal: move the default role templates out of `agents.py` while preserving the
current behavior.

Scope:

1. Add committed default prompt templates:

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
  developer.md
```

2. Add a small prompt-template loader, for example `prompt_templates.py`:
   - map agent ids to role template ids,
   - load Markdown templates from `agent_prompts/`,
   - normalize missing/blank files,
   - keep safe in-code fallback strings for emergency compatibility.
3. Extract only the stable role/behavior instructions from `agents.py` into
   Markdown templates. Stage-specific runtime context should remain in Python
   for now.
4. Update agent prompt builders so the top section comes from the loaded
   template:
   - `PlannerAgentA._initial_plan_prompt`
   - `PlannerAgentA._final_plan_prompt`
   - `PlannerAgentB._review_prompt`
   - `CodeAgent._implement_prompt`
   - `CodeAgent._fix_prompt`
   - `IntegratorAgent._integrate_prompt`
   - `IntegratorAgent._repair_prompt`
   - `QAAgent._review_prompt`
5. Include `ArchitectAgent` and `ScaffoldAgent` in the extraction even though
   their prompt override wiring is currently less complete. Their defaults
   should still live in `agent_prompts/`.
6. Keep the exact output requirements and workspace constraints currently in
   `agents.py` when moving text. Do not loosen file-boundary or safety rules.
7. Add tests:
   - every role template loads,
   - missing template falls back instead of crashing,
   - code agent ids such as `code_1`, `code_2` map to `code_agent`,
   - QA ids such as `qa_1`, `qa_2` map to `qa_agent`.

Acceptance:

- Running with no local prompt overrides should behave the same as before.
- The default System Prompt text shown in the GUI comes from
  `agent_prompts/*.md`, not from short fallback summaries in `app_services.py`.
- `agents.py` still owns stage context assembly, but no longer owns the main
  role identity text.

Implemented notes:

- Added `agent_prompts/*.md` for Planner, Reviewer, Risk Reviewer, Architect,
  Scaffold, Code Agent, Integrator, and QA Agent.
- Added `prompt_templates.py` with agent-id to role mapping, committed-template
  loading, and in-code fallbacks.
- Updated `agents.py` and Planner C helper prompts to load their top-level role
  text from the template loader.
- Moved stable output formats, workspace constraints, manifest rules, QA
  verdict rules, and browser action JSON examples into `agent_prompts/*.md`.
- Reduced `agents.py` prompt builders so they mainly inject run context,
  previous-agent outputs, assignments, feedback, and stage-specific input data.
- Updated `PromptService` so default GUI System Prompt text is loaded from the
  template loader.
- Added tests for template loading and `code_*` / `qa_*` mapping.

### Stage 6B: System Prompt as full role template

Goal: make the GUI `System Prompt` field control the full role template used by
the agent, not an extra instruction block appended to a hard-coded prompt.

Backend tasks:

1. Update `PromptService._prompt_config()`:
   - default `system_prompt` should load from `agent_prompts/<role>.md`,
   - default `skill_markdown` should remain separate and continue to come from
     presets/reference packs,
   - reset should restore the committed default template.
2. Update `local_dashboard_runner._agent_reference_markdown()` or replace it
   with a clearer structure:

```text
system_prompt: full editable role template
skill_markdown: selected supporting guidance
```

3. Update agent constructors where needed so every active agent can receive the
   selected System Prompt:
   - Planner A/B already accept `reference_markdown`, but should receive a
     distinct `system_prompt`.
   - Code Agent, Integrator, and QA Agent should receive a distinct
     `system_prompt`.
   - Architect and Scaffold need prompt override support added.
4. Update each agent prompt builder so it starts with:

```text
{system_prompt}

[Skill / Guideline]
{skill_markdown}

[Run Context / Task Input]
...
```

5. Keep old behavior as fallback:
   - if no override exists, use the default template,
   - if template loading fails, use the existing in-code fallback.
6. Store user edits in `local_prompt_overrides.json` with the existing local
   ignore policy.
7. Continue to snapshot the prompt parts into `runs/<run_id>/prompts/`.
   Rename future final prompt artifacts in Stage 6C, but Stage 6B should at
   least keep `*_system.md` and `*_skill.md` accurate.

Frontend tasks:

1. Rename helper text so users understand that `System Prompt` means the
   agent's editable role template.
2. Keep the current right-side Prompt Editor layout.
3. Keep QA presets, but make it clear that QA presets can update both:
   - System Prompt,
   - Skill / Guideline.
4. Preserve save/reset behavior.

Tests:

1. `PromptService.get_prompt("qa_1")` returns the full QA role template as
   `system_prompt`.
2. Saving a custom `system_prompt` changes the prompt text used for the next
   run.
3. Reset returns to the committed template.
4. Architect and Scaffold prompt configs are inspectable even before a run.

Acceptance:

- Editing the GUI System Prompt changes the actual top-level role instruction
  sent to Codex CLI.
- Skills remain separate from the System Prompt.
- The same Code Agent default template is used for `code_1`, `code_2`, and
  additional manual Code Agents unless explicitly overridden.
- The course demo can show prompt engineering by editing QA Agent System
  Prompt and Skill / Guideline without modifying Python source.

Implemented notes:

- Replaced the runner-side combined prompt helper with separate
  `system_prompt` and `skill_markdown` resolution.
- Planner A/B/C, Architect, Scaffold, Code Agent, Integrator, and QA Agent now
  receive the selected System Prompt as their top-level role template.
- Architect and Scaffold now support System Prompt and Skill / Guideline input
  like the other active local agents.
- Skill / Guideline text is still injected only as advisory reference guidance.
- Backend and frontend effective previews now label the sections as
  `System Prompt` and `Skill / Guideline`.
- Added runtime prompt tests proving that edited System Prompt text replaces
  the role template while skill text stays separate.

### Stage 6C: Final prompt rendering

Goal: keep verifiable evidence of the exact prompt that was sent to Codex CLI
for each agent call.

Implemented notes:

- Codex runner already writes the exact stdin prompt to
  `logs/<call_id>_prompt.txt` before launching the CLI.
- Added log-backed final prompt snapshots that copy those exact prompt logs into
  `prompts/final/<call_id>_final_prompt.md` after each successful local agent
  call.
- Registered final prompt files in run `state.json` under
  `final_prompt_snapshots` and `artifacts`.
- Emitted `final_prompts_saved` timeline events with the saved prompt artifact
  paths.
- Added `prompts/` to artifact discovery so prompt snapshots remain visible
  even when they are discovered outside explicit state entries.
- Kept raw `logs/*_prompt.txt` as the low-level debug source of truth.
- Added a regression test for copying prompt logs into final prompt artifacts
  and avoiding duplicate snapshots.

Deferred refinement:

- A future preview API can assemble final prompts before execution for a dry-run
  view. The current implementation intentionally snapshots the exact executed
  prompt instead of maintaining a second parallel renderer that could drift from
  `agents.py`.

### Stage 6D: Skill registry

Goal: expose curated, language-neutral development guidance as selectable
Skill / Guideline sources without relying on native Codex/Claude skill
installation.

Implemented notes:

- Added `skill_registry.py`.
- The registry discovers:
  - `Karpathy Guidelines` from `external_skills/andrej-karpathy-skills-main`,
  - `agent-rules-books` `mini` and `nano` Markdown rules from
    `external_skills/agent-rules-books-main`.
- gstack remains available on disk for later advanced/Claude-provider work, but
  is intentionally excluded from the default Skill Registry because most gstack
  skills are long Claude/gstack workflow documents rather than lightweight
  language-neutral coding guidance.
- Code Agents default to `Karpathy Guidelines`.
- Planner, Architect, Integrator, and QA agents keep empty/default
  Skill / Guideline text unless the user selects or writes one.
- `/prompts` now returns `skills` alongside QA presets.
- The Prompt Editor `Skill / Guideline` tab now has a `Skill Source` selector.
  Selecting a skill inserts the source metadata and Markdown content into the
  editable guideline text.
- Saved prompt overrides now include `skill_id`, and run prompt snapshots record
  the selected skill id with the exact skill text.
- Added tests for registry discovery, Code Agent default Karpathy skill, and
  prompt catalog skill entries.

Deferred refinement:

- Native install into each `CODEX_HOME` skill directory is not part of the
  submission path. This remains a future provider-integration feature.
- Stack/language-specific rules can be recommended later after Planner chooses
  a stack, but they are not applied automatically in Stage 6D.

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
