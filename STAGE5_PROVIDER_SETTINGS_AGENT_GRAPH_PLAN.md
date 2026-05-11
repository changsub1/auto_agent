# Stage 5 Provider Settings And Agent Graph Plan

Stage 5 turns the desktop app from a run monitor into a practical local
operator console.  Stage 4 proved that the Tauri app can start the local API
sidecar and complete a real fast-mode run.  The next gap is that too many
required setup and routing decisions still live in terminals, environment
files, or hardcoded route rules.

The goal of Stage 5 is to let a non-technical local user configure providers,
accounts, models, runtime health, Discord, QA, and manual agent layout from the
GUI before starting a run.

## Product Direction

The app should answer these questions before the user starts a run:

- Is Codex installed and logged in?
- Which account and plan are active?
- How much 5-hour and weekly usage remains?
- Which models and reasoning levels are available?
- Which account, model, and reasoning level will each agent use?
- Is Claude Code installed and configured, if enabled?
- Is Discord bot integration configured and running?
- Are MCP servers healthy, or did one fail to start?
- Are executable QA, Playwright, local browser checks, and timeouts configured?
- What exact agent graph will run for this request?

Stage 5 should keep the product local-first.  It should not introduce a cloud
backend, hosted account service, or OpenAI API-key workflow unless the user
explicitly opts into one later.

## Current CLI Findings

Observed on the local machine with Codex CLI `0.124.0`:

- `codex login status` reports login state.
- `codex debug models` returns a JSON model catalog.
- `codex debug models --bundled` can return the bundled catalog without
  refreshing from the network.
- Model catalog entries include:
  - `slug`
  - `display_name`
  - `default_reasoning_level`
  - `supported_reasoning_levels`
- The interactive Codex TUI `/status` screen shows:
  - current model and reasoning level,
  - working directory,
  - sandbox and approval policy,
  - account email and plan,
  - session id,
  - 5-hour usage remaining and reset time,
  - weekly usage remaining and reset time,
  - update notices,
  - MCP startup failures.
- There is no confirmed standalone `codex status` command in `0.124.0`.
- `claude` is not currently available on PATH on this machine, so Claude Code
  support should be implemented through a provider adapter with installation
  detection first.

Implementation note: usage limits are available through the structured Codex
app-server protocol.  The verified request path is
`codex app-server --listen stdio://`, followed by `initialize` and
`account/rateLimits/read`.  Parsing the interactive TUI `/status` output should
remain a last-resort fallback because the text layout can change between Codex
CLI versions.

## Stage 5A: Provider And Runtime Settings Console

Goal: make provider setup and runtime health visible and controllable from the
desktop app.

### Initial Implementation Status

Implemented in the first Stage 5A slice:

- Added `ProviderService` to the local service layer.
- Added local API endpoints for:
  - provider list,
  - Codex status,
  - Codex model catalog,
  - Claude status,
  - runtime health,
  - runtime usage from Codex app-server.
- Codex install detection uses the local CLI path.
- Codex login detection uses `codex login status`.
- Codex model dropdown data is parsed from `codex debug models`, with bundled
  catalog fallback support.
- Claude Code is detected as missing when `claude` is not on PATH.
- The React `Resources` panel now shows provider health, Codex models,
  supported reasoning levels, runtime QA/Discord settings, and Codex 5-hour and
  weekly usage remaining/reset values.
- Tests cover Codex model catalog parsing, Codex login status parsing, and
  missing Claude detection, and Codex rate-limit mapping.

Still pending:

- Settings persistence and editing.
- Codex login/logout actions from the GUI.
- Discord bot start/stop supervisor.
- MCP health parsing.

### Backend Tasks

1. Add a provider runtime service, for example `ProviderService`, under the
   local service layer.
2. Add local API endpoints:
   - `GET /providers`
   - `GET /providers/codex/status`
   - `GET /providers/codex/models`
   - `POST /providers/codex/login`
   - `POST /providers/codex/logout`
   - `GET /providers/claude/status`
   - `GET /runtime/health`
   - `GET /runtime/mcp`
   - `GET /runtime/usage`
   - `GET /settings`
   - `PATCH /settings`
3. Detect installed CLIs:
   - Codex: `Get-Command codex` on Windows, `which codex` on Unix.
   - Claude Code: `Get-Command claude` on Windows, `which claude` on Unix.
4. Query Codex login state using `codex login status`.
5. Query Codex model catalog using `codex debug models`, with
   `codex debug models --bundled` as a fallback.
6. Extract model dropdown data:
   - model id,
   - display name,
   - default reasoning level,
   - supported reasoning levels,
   - visibility if available.
7. Use Codex app-server protocol for structured usage/status data.
8. If the structured app-server protocol fails, implement a clearly isolated fallback
   parser for the interactive `/status` output.
9. Store local app settings in a safe local file such as
   `local_app_settings.json` or `.env.local`, excluding secrets by default.
10. Keep secrets separate:
    - Discord token should remain local-only.
    - API keys, if ever supported, should not be written into committed files.
11. Add tests for:
    - model catalog parsing,
    - login status parsing,
    - CLI missing cases,
    - usage status parser if fallback parsing is used,
    - settings read/write safety.

### Frontend Tasks

1. Add a Settings or Resources view for provider status.
2. Show provider cards:
   - Codex installed/missing,
   - Codex login status,
   - active account if known,
   - active plan if known,
   - Claude installed/missing,
   - Discord configured/running/stopped.
3. Add model dropdowns backed by `GET /providers/codex/models`.
4. Add reasoning dropdowns that update based on selected model.
5. Add account/profile selectors:
   - default Codex profile,
   - planner accounts,
   - code agent accounts,
   - QA accounts.
6. Show usage widgets:
   - 5-hour remaining percentage and reset time,
   - weekly remaining percentage and reset time,
   - stale/unknown state when unavailable.
7. Show Codex CLI update notices if detectable.
8. Show MCP health:
   - healthy servers,
   - failed servers,
   - last error text,
   - whether the failure blocks app runs.
9. Add Discord controls:
   - token configured/missing,
   - bot stopped/running,
   - start,
   - stop,
   - restart,
   - latest bot log tail.
10. Add QA controls:
    - executable QA enabled,
    - Playwright browser availability,
    - browser QA enabled,
    - executable QA timeout,
    - local command allow policy.

### Acceptance

- A user can see whether Codex is installed and logged in without opening a
  terminal.
- A user can select a model and reasoning level from actual Codex model catalog
  data.
- If usage data is available, the app shows 5-hour and weekly remaining
  percentages and reset times.
- If usage data is unavailable, the UI says so explicitly instead of showing
  fake values.
- A user can see Discord bot state and start or stop it from the app.
- Missing Claude Code is displayed as a provider setup issue, not a crash.

## Stage 5B: Per-Agent Provider Configuration

Goal: let each agent use an explicit provider, account, model, reasoning level,
and optional skill/profile configuration.

### Stage 5B Implementation Status

Implemented in the Stage 5B slice:

- The roster sidebar `Defaults` section now uses dropdowns for:
  - Codex account,
  - model,
  - reasoning effort.
- The model dropdown is populated from the Codex model catalog added in Stage 5A.
- The reasoning dropdown follows the selected model's supported reasoning levels
  when that metadata is available.
- The selected account/model/reasoning values are reflected on agent cards.
- Run creation sends the selected model, reasoning effort, and Codex home into
  the existing `RunCreateRequest` fields.
- `dashboard_config` records the selected values in run state.
- Agent cards expose per-agent Codex account/model/reasoning dropdowns.
- Per-agent selections are sent as `agent_configs` when a run starts.
- `dashboard_config` records the exact per-agent provider/account/model/reasoning
  choices used for the run.
- `LocalRunConfig` and workflow helpers now prefer per-agent settings when
  launching and recording Codex sessions.
- `GET /settings` and `PUT /settings` persist reusable local presets in
  `local_app_settings.json`.
- Unsupported execution providers are rejected explicitly until a provider
  adapter exists.
- Tests cover selected model/reasoning/Codex home recording and settings
  round-tripping.

Still pending for full Stage 5B:

- Provider abstraction beyond Codex execution.
- More polished named preset management beyond the current save/load defaults.

### Backend Tasks

1. Introduce an agent configuration model:

```json
{
  "agent_id": "code_1",
  "role": "code",
  "provider": "codex",
  "codex_home": "D:\\codex_profiles\\account_2",
  "model": "gpt-5.5",
  "reasoning_effort": "high",
  "reference_profile": "karpathy/code_agent",
  "enabled": true
}
```

2. Store run-time agent configs in `state.json` at run creation.
3. Store reusable presets in the local settings file.
4. Update `RunCreateRequest` to accept agent configs, not only role counts.
5. Keep backward compatibility with the current count-based fields.
6. Update route generation to derive counts and ownership from agent configs.
7. Update `LocalRunConfig` and workflow helpers to use per-agent settings.
8. Support provider abstraction while initially executing only Codex agents.
9. Add explicit unsupported-provider errors for Claude until its runner is
   implemented.
10. Add tests for config normalization and backward compatibility.

### Frontend Tasks

1. Extend agent cards with editable provider/account/model/reasoning fields.
2. Add default presets:
   - fast solo,
   - balanced review,
   - parallel two-code,
   - manual custom.
3. Add per-role defaults in Settings.
4. Warn when too many agents are mapped to the same account while usage is low.
5. Show whether each agent will start a new session or resume an existing one.
6. Keep the simple mode buttons for users who do not want advanced config.

### Acceptance

- The user can choose different Codex accounts for Planner, Code, and QA
  agents.
- The user can choose model and reasoning level per agent.
- The run state records the exact provider/account/model/reasoning selection
  used by every agent.
- Existing fast/balanced/parallel flows still work with default settings.

## Stage 5C: Manual Agent Graph Builder

Goal: make manual mode a real user-configurable workflow graph instead of a
count-based shortcut.

Detailed implementation plan: see `STAGE5C_MANUAL_AGENT_GRAPH_PLAN.md`.

The current manual mode is limited.  It lets the UI add/remove agent cards and
passes active role counts into `POST /runs`.  If more than one code agent is
active, routing currently resolves to the existing parallel route.  That is
useful, but it is not a freeform manual workflow.

### Graph Model

Represent manual workflows as explicit stages:

```json
{
  "mode": "manual",
  "stages": [
    {
      "id": "planning",
      "type": "planning",
      "agents": ["planner_a", "planner_b"],
      "parallel": false
    },
    {
      "id": "approval_plan",
      "type": "approval",
      "after": ["planning"]
    },
    {
      "id": "code",
      "type": "code",
      "agents": ["code_1", "code_2"],
      "parallel": true
    },
    {
      "id": "integration",
      "type": "integration",
      "agents": ["integrator"],
      "after": ["code"]
    },
    {
      "id": "qa",
      "type": "qa",
      "agents": ["mechanical_qa", "qa_1"],
      "parallel": false
    }
  ]
}
```

### Backend Tasks

1. Define a validated workflow graph schema.
2. Add workflow validation:
   - no duplicate stage ids,
   - no missing `after` dependencies,
   - no cycles,
   - approval stages cannot run in parallel,
   - integration requires at least one code stage,
   - parallel code stages require file ownership or task assignment rules.
3. Save approved graph into `state.json`.
4. Update `workflow_engine.py` to execute graph stages instead of only route
   presets when `mode == "manual"`.
5. Reuse existing stage functions where possible:
   - planning,
   - contract,
   - scaffold,
   - single code,
   - parallel code agents,
   - integration,
   - mechanical QA,
   - LLM QA,
   - fix loop.
6. Add graph-level active step reporting.
7. Add graph-level timeline summaries.
8. Add graph tests:
   - valid simple graph,
   - valid parallel code graph,
   - invalid cycle,
   - missing integrator after parallel code,
   - approval checkpoint behavior.

### Frontend Tasks

1. Replace manual-mode card order with an editable workflow graph surface.
2. Support simple operations:
   - add agent,
   - remove agent,
   - duplicate agent,
   - change role,
   - move stage earlier/later,
   - group selected code agents as parallel,
   - insert approval checkpoint,
   - toggle integrator,
   - toggle QA agent review.
3. Keep a compact path preview above the cards:
   - `Planner A + Planner B -> Approval -> Code 1 + Code 2 -> Integrator -> QA`.
4. Add validation warnings before run start.
5. Save graph presets.
6. Load graph presets.
7. Keep `fast`, `balanced`, and `parallel` modes as one-click presets.

### Acceptance

- Manual mode can express at least:
  - single planner, single code, mechanical QA,
  - two planners, single code, QA agent,
  - contract/scaffold, two code agents in parallel, integrator, QA,
  - custom approval checkpoint after planning.
- The UI prevents invalid graphs before run creation.
- The backend rejects invalid graphs even if the UI misses them.
- The run monitor shows graph stages in the same order the user configured.

## Stage 5G: QA Prompt and Guideline Editor

Goal: support the course-submission demonstration that prompt engineering and
AI ethics guidelines can change the same LLM QA Agent's judgment without adding
a separate ethics-agent implementation.

### Implemented Slice: Stage 5G-1

- The roster sidebar shows whether the selected route will run an LLM QA Agent
  or mechanical QA only.
- Each agent card's skill row and settings icon open a large right-side Prompt
  Editor.
- The editor has three tabs:
  - Skill / Guideline
  - System Prompt
  - Effective Prompt Preview
- The editor can be resized with a width control.
- QA presets are available:
  - Default QA
  - Ethics & Bias QA
  - Accessibility QA
  - Strict Safety QA
- Prompt edits are stored locally in `local_prompt_overrides.json`, which is
  ignored by Git.
- Run creation snapshots prompt text into `runs/<run_id>/prompts/` and records
  `prompt_settings.json`.
- Saved QA prompts are injected into the Codex-backed QA Agent review prompt.

### Submission Demo Use

1. Run the same generated-app request in a route that enables `qa_1`.
2. Save `Default QA`, run QA, and keep the resulting `qa_report.md`.
3. Switch only the QA preset to `Ethics & Bias QA` or `Strict Safety QA`.
4. Run again and compare the QA Agent findings and PASS/FAIL rationale.

This demonstrates prompt engineering and AI ethics review criteria while
keeping the underlying agent implementation stable.

### Deferred

- Full OpenAI API-key provider execution remains deferred. The current product
  stays Codex CLI centered for the submission build, while the provider
  abstraction leaves room for an API adapter later.

## Stage 5D: Discord Bot Control

Goal: make Discord a controllable integration instead of a separate terminal
process.

### Tasks

1. Add a local Discord bot supervisor.
2. Start/stop the bot from the FastAPI sidecar or a child process manager.
3. Keep the bot optional.
4. Show bot state in the GUI:
   - not configured,
   - stopped,
   - starting,
   - running,
   - failed.
5. Show latest Discord bot log tail.
6. Add safe token configuration:
   - detect token presence,
   - do not echo token back to the UI,
   - support updating token through a local-only settings write.
7. Add tests for supervisor state transitions without requiring a real token.

### Acceptance

- A user can turn Discord integration on or off from the app.
- Bot startup failures are visible in the app.
- The app remains fully usable without Discord configured.

## Stage 5E: Diagnostics And Setup Assistant

Goal: make setup and failure recovery self-service from the app.

### Tasks

1. Add a diagnostics endpoint that checks:
   - Python executable,
   - Python dependencies,
   - Node dependencies,
   - Rust/Cargo when packaging tools are needed,
   - Codex CLI version,
   - Codex login,
   - Codex model catalog,
   - usage status if available,
   - Claude CLI presence,
   - Discord token presence,
   - Playwright install,
   - Tauri sidecar health,
   - writable run directory,
   - Windows sandbox setting.
2. Add a diagnostics UI page.
3. Add one-click copy/export of a diagnostics report.
4. Add guided fix actions where safe:
   - open Codex login,
   - refresh model catalog,
   - restart sidecar,
   - restart Discord bot,
   - open settings file location.
5. Do not run broad installers or destructive commands without explicit user
   confirmation.

### Acceptance

- A user can diagnose most setup failures without opening a terminal.
- The report avoids secrets.
- The report is useful enough to paste into a support issue.

## Stage 5F: Packaging UX Follow-Through

Goal: connect Stage 5 settings to the remaining Stage 4C packaging work.

### Tasks

1. Decide sidecar packaging:
   - keep source + existing Python for developer builds,
   - or build a PyInstaller sidecar for installer builds.
2. Surface missing prerequisites in the GUI.
3. Add packaged-app path handling for:
   - repo root,
   - bundled resources,
   - settings file,
   - logs,
   - sidecar executable.
4. Verify the settings console works in packaged builds.
5. Verify login flows still work when launched outside a development terminal.

### Acceptance

- A packaged Windows app can show provider health and start a run.
- Missing prerequisites are shown clearly.
- The app does not require manual `.env` editing for ordinary use.

## Recommended Implementation Order

1. Codex model catalog endpoint and settings UI dropdowns.
2. Codex login/status card.
3. Usage status through Codex app-server, with fallback parser only if needed.
4. Local settings persistence.
5. Per-agent provider/model/reasoning config.
6. Discord bot supervisor.
7. Manual graph schema and validation.
8. Manual graph UI.
9. Diagnostics page.
10. Packaged-app verification.

This order gives the app immediate user-facing value without blocking on the
full graph builder.  It also creates the data model needed for per-agent manual
graphs.

## Non-Goals For Stage 5

- No hosted backend.
- No multi-user SaaS account system.
- No automatic purchase, subscription, or quota management.
- No unsupported scraping of private web pages for usage data.
- No broad plugin marketplace.
- No full LangGraph migration unless the explicit workflow graph becomes too
  hard to maintain with the current engine.
- No removal of legacy paths until the new settings and graph flows are stable.

## Stage 5 Exit Criteria

Stage 5 is complete when:

- The app can show Codex install/login/model state from the GUI.
- The app can populate model and reasoning dropdowns from real provider data.
- The app can show usage limits when the provider exposes them, or explicitly
  mark them unavailable.
- The app can start/stop Discord integration from the GUI.
- The app can configure provider/account/model/reasoning per agent.
- Manual mode can save and execute at least one validated custom graph with
  parallel code agents.
- Diagnostics can identify the common setup failures without opening a
  terminal.
