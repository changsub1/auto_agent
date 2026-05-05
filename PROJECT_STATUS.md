# Project Status

## Purpose

This repository is a local Codex CLI multi-agent development automation MVP.
It verifies that a Python orchestrator can call the locally logged-in Codex CLI
instead of using an OpenAI API key or OpenAI SDK directly.

The current system can receive a development request, let multiple Codex-backed
agents discuss the plan, ask a human for approval in Discord, and then generate
a runnable local app.

As of 2026-04-29, the product direction is a local Tauri desktop app with a
localhost-only FastAPI sidecar. Discord should become a lightweight remote
control and notification adapter, not the owner of the main workflow.

As of Stage 3 closeout, the architecture migration is considered MVP-complete.
The next work should finish the app surface, package it as a local desktop app,
and dogfood it on real personal development requests before final cleanup.
The detailed plan is in `STAGE4_APP_COMPLETION_PACKAGING_PLAN.md`.

As of version 8, Stage 4A and Stage 4B are usable for dogfooding: the Tauri
desktop app starts the local FastAPI sidecar, runs through plan approval,
implementation, mechanical QA, and QA approval, and shows a cleaner
agent-output-focused run timeline. Windows installer packaging remains the main
Stage 4C gap.

## Phase 1: Implemented

### Local Codex CLI Integration

- Python calls the local `codex` CLI with `subprocess.run`.
- Prompts are passed through stdin using `codex exec ... -`.
- Shell interpolation is not used.
- Windows Codex launchers such as `codex.cmd` are resolved.
- UTF-8 output handling is configured for Windows.
- Codex calls use:

```text
codex exec --skip-git-repo-check --sandbox workspace-write --color never -
```

### Original CLI MVP

- `main.py` accepts a user request from the terminal.
- Planner Agent creates a planning document.
- Developer Agent generates an app under `runs/<timestamp>/generated_app`.
- Mechanical QA runs language-neutral executable checks when a manifest or safe
  adapter is available, with Python syntax checks kept as one adapter.
- If mechanical QA fails, Developer Agent receives the error log and gets one or more fix attempts.

### Discord Human-in-the-loop MVP

- Discord bot entrypoint: `discord_bot.py`
- Slash command: `/dev`
- User can request a service/app from Discord.
- Bot posts progress updates to the Discord channel while controlling runs
  through the localhost FastAPI API.
- FastAPI worker runs Planner Agent A, optional Planner Agent B, and Planner
  Agent A finalization.
- The parallel route creates a contract bundle and task manifest after plan
  approval as part of the worker-owned implementation flow.
- Discord buttons allow the requester to:
  - Approve
  - Request changes
  - Cancel
- If approved, Discord calls the API and the FastAPI worker continues the
  selected route.
- QA result, generated app path, and executable QA screenshots are read through
  the API/artifact state and posted back to Discord when available.
- After QA, Discord asks the requester to approve the result or record a fix
  request.
- Discord exposes read-only `/runs` and `/status` commands backed by the local
  API. Status output includes active-step metadata and a short log tail from
  Stage 3C observation endpoints.
- A first routing core is implemented through `ROUTING_MODE` with `fast`,
  `balanced`, `parallel`, and `manual` modes. The default is `balanced`. Fast
  and balanced routes now use `CodeAgent(code_1)` directly instead of the
  legacy `DeveloperAgent`.

### Session and State Management

- Each run creates `runs/YYYYMMDD_HHMMSS`.
- Run state is saved to `state.json`.
- Events are appended to `events.jsonl`.
- Human-readable progress is saved to `transcript.md`.
- Planning artifacts are saved under `planning/`.
- Raw Codex prompt/stdout/stderr/meta logs are saved under `logs/`.
- Codex session IDs are parsed from CLI output and stored per agent.
- Follow-up calls try to resume each agent session with:

```text
codex exec resume <session_id> -
```

- If resume fails, the engine falls back to a fresh Codex call using the latest relevant artifact.
- The full transcript is not resent on every turn.
- Discord progress messages show a short agent session id and whether that call resumed an existing session.

### Current Main Files

- `main.py`: local CLI orchestrator
- `app_services.py`: UI-agnostic local service layer for run/config/event/artifact/action access
- `discord_api_client.py`: small localhost FastAPI client used by Discord
- `discord_api_engine.py`: Discord presentation adapter over the local API
- `local_api.py`: FastAPI adapter over the local service layer
- `run_local_api.py`: localhost-only API server runner
- `discord_bot.py`: Discord slash command entrypoint
- `dashboard.py`: Streamlit local run control panel for planning/contract/scaffold tests
- `debate_engine.py`: Planner A/B debate, contract approval, parallel development, QA routing
- `agents.py`: Planner, Architect, Scaffold, Code, Integrator, QA, and legacy Developer prompts
- `codex_runner.py`: Codex CLI subprocess wrapper and session parsing
- `parallel_workflow.py`: contract, task assignment, workspace, and merge helpers
- `local_dashboard_runner.py`: local non-Discord planning/contract/scaffold runner
- `state_store.py`: persistent run state and event/transcript storage
- `discord_ui.py`: approval buttons and revision modal
- `discord_reporter.py`: Discord message helpers
- `executable_qa.py`: generated app execution probes, screenshots, and runtime logs
- `qa.py`: mechanical QA result composition, including the Python syntax adapter
- `routing.py`: deterministic route selection for fast, balanced, parallel, and manual runs
- `reference_packs.py`: copies curated reference packs into each run and loads
  role-specific `pack/role` guidance for agent prompts
- `reference_packs/karpathy/`: curated lightweight coding discipline for Code
  Agents and the Integrator, based on andrej-karpathy-skills source material
- `reference_packs/gstack/`: curated role guidance distilled from gstack source
  skills without running the gstack installer or source scripts
- `workspace_manager.py`: run folder and generated app folder helpers
- `config.py`: environment variable configuration
- `ux/`: React/Vite UI connected to the local API, with a Tauri desktop shell scaffold

## Current Local App/API Snapshot

Completed so far:

- Added a UI-agnostic service layer in `app_services.py`:
  - `RunService` for creating/listing runs and recording approve/cancel/change actions.
  - `ArtifactService` for safe run artifact listing and file reads.
  - `EventService` for converting `events.jsonl` into timeline DTOs.
  - `ConfigService` for routing modes, defaults, provider display, Codex homes,
    model, reasoning effort, and reference profiles.
- Added `local_api.py` and `run_local_api.py` as the local-only FastAPI adapter.
- Added React/Vite entry files and replaced the prototype UX mock wiring with
  API calls for config, runs, events, artifacts, and approval actions.
- Added a Tauri scaffold under `ux/src-tauri/` for the future desktop shell.
- Hardened the Tauri shell into a usable local app wrapper:
  - prefers the repo-local `.venv` Python for `run_local_api.py`,
  - supports `ORCHESTRA_PYTHON` and `ORCHESTRA_REPO_ROOT` overrides,
  - chooses a localhost API port and waits for `/health`,
  - injects the API base URL into React,
  - captures sidecar stdout/stderr under `tmp/tauri_sidecar/`,
  - stops the sidecar on app close.
- Added local provider/account display:
  - `CODEX_HOME`
  - `PLANNER_*_CODEX_HOME`
  - `ARCHITECT_CODEX_HOME`
  - `SCAFFOLD_CODEX_HOME`
  - `CODE_AGENT_CODEX_HOMES`
  - `QA_AGENT_CODEX_HOMES`
- Added safe `.env` loading for non-secret local app defaults. Secret values
  such as Discord tokens are not loaded by this service helper.
- Created a local ignored `.env` on this machine that maps:
  - `account_1` to `D:\codex_profiles\account_1`
  - `account_2` to `D:\codex_profiles\account_2`
- The local API currently reports both Codex accounts through `/config`.
- The UI now shows the resolved Codex model and reasoning effort from env or
  Codex config instead of a hardcoded default label.
- The default prefilled request text was removed from the UI composer.
- Manual mode now supports local UI add/toggle/delete for agents and passes
  active Planner/Code/QA counts into `POST /runs`.
- Fixed the app root height bug that caused a white gap when the viewport grew.
- The React run monitor now defaults to a clean operator timeline that focuses
  on agent outputs, approvals, user actions, and errors. Internal worker/system
  events remain available through `System` and `All` filters.
- Agent output events now preview the generated markdown artifact content
  directly in the timeline.
- The latest checked validation passed:
  - `python -m py_compile app_services.py state_store.py tests\test_app_services.py`
  - `python -m unittest discover -s tests` (38 tests)
  - `npm run build` from `ux/`
  - `cargo check` from `ux/src-tauri/`

Still partial:

- `POST /runs` now creates run state quickly and enqueues planning through the
  FastAPI run worker. Plan approval now advances through the implementation and
  QA workflow from the app.
- Fast and balanced routes now run a single `CodeAgent(code_1)` against
  `generated_app`; parallel and manual multi-code routes run contract,
  scaffold, parallel Code Agents, integration, mechanical QA, optional LLM QA,
  and the automatic fix loop.
- QA approve is connected and moves `awaiting_qa_approval` to `completed`.
  Operator-requested QA fixes after that checkpoint are still recorded but not
  yet re-enqueued as a separate worker continuation.
- Manual mode agent cards currently affect supported role counts. They are not
  yet a full agent registry with per-agent prompts, models, accounts, and
  execution ownership.
- Tauri dev-mode app execution is verified, including sidecar startup. Windows
  installer packaging is not yet smoke-tested.
- The Python sidecar packaging strategy is still undecided for distributable
  builds: source + existing Python/`.venv` for local development, or a bundled
  sidecar executable for installer builds.

FastAPI run worker migration status:

- Added `run_worker.py` with an in-process `asyncio.Queue`, `RunJob`, active
  job registry, per-run locks, and job dispatch for planning, plan approval,
  plan revision, and cancellation.
- Added `workflow_engine.py` as the non-Discord workflow stage owner for local
  planning, route-aware implementation, QA, and automatic fix checkpoints.
- Extended `state_store.py` with `active_step`, `control`, and `workflow`
  helpers while keeping older run state readable.
- Changed local API run creation so `POST /runs` creates run state quickly,
  records routing/workflow/config, sets `planning_queued`, and enqueues
  background planning instead of blocking on Codex planning.
- Changed approve/request-changes/cancel service methods so they validate state,
  persist approval/control events, and enqueue the next worker job when the
  FastAPI worker is available.
- Added an async full-workflow path for plan approval. Route behavior is now:
  `fast` and `balanced` use a single Code Agent; `parallel` and manual routes
  with more than one Code Agent use contract/scaffold/code/integration.
- Shared local workflow helpers now pass stored Codex session ids into follow-up
  calls and fall back to a fresh call if resume fails with a Codex execution
  error.
- Added Stage 3C observation APIs:
  - `GET /runs/{run_id}/active-step`
  - `GET /runs/{run_id}/logs`
  - `GET /runs/{run_id}/logs/tail`
  - enriched artifact metadata with type, stage, role, existence, size, and
    updated time
- The React run monitor now shows active step metadata and recent log tails from
  the API instead of reading local files directly.
- Added worker-focused tests using a fake workflow engine.
- Verified on 2026-04-30 with Python compile checks, the unittest suite, and
  the React/Vite production build.

Stage 3 closeout:

- Stage 3 is complete for the local API workflow and Discord adapter MVP.
- Remaining Stage 3 hardening items should be carried as product backlog, not
  blockers for starting Stage 4.
- The project should now be used through the app on real development requests
  to discover practical UX, QA, recovery, and packaging issues.

## Known Limitations

- The local API now creates run state quickly, enqueues planning, and continues
  implementation/QA through the FastAPI run worker after plan approval.
  `discord_bot.py` now uses the API adapter instead of directly running the
  long workflow. The older `debate_engine.py` remains in the repository as a
  legacy implementation/reference path.
- Tauri scaffolding is present, but local packaging requires Rust/Cargo,
  Node dependencies, and FastAPI dependencies to be installed on the machine.
- The Discord approval path no longer always uses the full contract/scaffold/
  parallel-code/integrator/QA-agent pipeline. Route selection is currently
  explicit through configuration rather than a natural-language router.
- `DeveloperAgent` is still kept for the original single-developer CLI path.
  The newer routing design should reuse `CodeAgent(code_1)` for single-agent
  implementation so single and parallel code paths share the same prompts and
  manifest requirements.
- `/dev --medium` or similar per-request model/reasoning selection is not implemented yet.
- Global `CODEX_MODEL` and `CODEX_REASONING_EFFORT` defaults are supported, but Discord per-request model/reasoning selection is not implemented yet.
- Discord messages show planning and QA output, but generated app execution commands are not yet summarized as clearly as they could be.
- QA now has a first executable-probe slice for static HTML, Streamlit, CLI,
  and opt-in Windows launcher checks. Broader GUI automation and app-specific
  assertions are still limited.
- Executable QA now prefers a generated `codex_app_manifest.json` that declares
  safe setup, test, smoke, server, and browser checks in a language-neutral
  schema. Framework detection remains as a fallback when the manifest is
  missing.
- Codex-backed QA Agent review is implemented after mechanical QA. It can use
  the configured QA `CODEX_HOME`, model, reasoning effort, QA report, contract,
  generated app listing, and attached screenshots.
- Session resume is supported in the shared local workflow path, with fallback
  to a fresh call on Codex execution failure. Deeper long-term memory compaction
  is not implemented.
- Discord approval controls are requester-only, not role/team-policy based.
- `reference_packs/gstack_src/` and `reference_packs/karpathy_src/` are local
  ignored vendor caches. The orchestrator only attaches curated committed
  Markdown files to agent prompts; it does not run source scripts or installers.

## Immediate Priorities

### 0. Recommended Completion Sequence

Complete the product in this order:

1. Finish the desktop app surface and use it for real runs.
   - Make the React/Tauri UI the primary control surface.
   - Verify full run creation, plan approval, execution observation, QA review,
     and completion from the app.
   - Record dogfooding findings before doing broad cleanup.
2. Package the local desktop app.
   - Harden the Tauri sidecar lifecycle.
   - Decide how the Python FastAPI sidecar is bundled.
   - Build and smoke-test a Windows installer.
3. Harden cancel, retry, and recovery based on real failures.
   - Ensure cancelled runs are not overwritten by late worker exceptions.
   - Add explicit retry entry points for failed or cancelled stages where
     practical.
   - Re-enqueue operator-requested QA fixes after `awaiting_qa_approval`.
4. Strengthen generic executable QA where dogfooding shows gaps.
   - Expand the initial manifest runner with richer schema coverage and
     environment handling.
   - Use framework adapters for Python, Node/Vite/React, static HTML, and CLI
     projects when the manifest is missing.
   - Add Playwright browser checks for web apps: page load, blank screen,
     console errors, screenshot capture, and basic interaction probes.
5. Clean up legacy paths after the packaged app proves the main workflow.
   - Decide whether to remove or quarantine `debate_engine.py`.
   - Keep `main.py` legacy CLI only if it remains useful for diagnostics.
6. Polish app UX on top of the stable backend.
   - Run graph and stage controls.
   - Full artifact preview/editor.
   - Per-agent account/model/reasoning selection.
   - Real manual-mode agent registry.
   - Better run history and status filtering.

### 1. Routing Core Before More UI

Implemented a first routing decision layer before development starts. The first
version is deterministic and cheap rather than another Codex call.

Target run modes:

- `fast`: optional lightweight planning, `CodeAgent(code_1)` owns the whole
  `generated_app`, then mechanical QA.
- `balanced`: Planner A/B review, `CodeAgent(code_1)` owns implementation,
  mechanical QA, and one QA Agent review.
- `parallel`: current contract/scaffold/code-agent/integrator/QA workflow.
- `manual`: user-provided planner/code/QA counts and model/reasoning settings.

The selected route is recorded in `state.json` and a `route.json` artifact with
the mode, pipeline stages, agent counts, and a short reason. Remaining work:
expose route controls in Streamlit and Discord slash command options.

### 2. Unify Single-Code and Parallel-Code Agents

Keep `DeveloperAgent` only as a legacy compatibility path until it can be
removed. Fast and balanced routes now use `CodeAgent(code_1)` directly, with an
assignment that grants ownership of the whole generated app. Remaining work:
move the original local CLI path to the same route-aware `CodeAgent` flow.

### 3. Language-Neutral QA Manifest

Require final app-producing agents to create `codex_app_manifest.json` in the
app root:

- Fast/balanced route: `CodeAgent(code_1)` creates the final manifest.
- Parallel route: Scaffold may create a draft manifest, Code Agents may suggest
  checks, and Integrator must finalize the manifest for `generated_app`.

Mechanical QA should use this order:

1. Read and validate `codex_app_manifest.json`.
2. Execute safe manifest checks with `shell=False`, timeouts, captured logs, and
   allowlisted commands.
3. Fall back to README run-command parsing.
4. Fall back to language/framework adapters such as Python, Node, Go, Rust, and
   static web.
5. Mark executable QA as `SKIP` with a clear reason if no safe target is found.

QA Agent should review the manifest, mechanical QA report, screenshots, and
contract. It should not be responsible for launching arbitrary commands.

### 4. Repository Skills for Agent Quality

Reference guidance is now role-specific with `pack/role` profiles. Defaults:

- `planner_a`: none
- `planner_b`: none
- `code_agent`: `karpathy/code_agent`
- `integrator`: `karpathy/integrator`
- `qa_agent`: none

gstack remains available as an opt-in profile source, for example
`gstack/planner_a`, `gstack/planner_b`, or `gstack/qa_agent`. The orchestrator
copies only the selected curated packs into `runs/<run_id>/reference_packs/` and
records `reference_profiles.json`. Remaining work: expose profile selection in
Discord and the dashboard, then promote stable files into repo-scoped skills
under `.agents/skills` if the prompt-only pack proves useful.

Candidate repo-scoped skills:

- `planner-product`: small MVP planning, acceptance criteria, and route hints.
- `task-splitter`: `task_manifest.json`, file ownership, dependency, and
  integration-plan rules.
- `app-manifest`: `codex_app_manifest.json` schema and safe command examples.
- `qa-reviewer`: manifest/report/screenshot-based PASS/FAIL review format.
- `frontend-visual-qa`: screenshot review rules for blank pages, layout
  breakage, missing primary UI, and obvious interaction failures.

Use skills to improve agent reasoning and output formats. Keep actual app
execution, screenshots, command safety, logs, and timeouts in the Python QA
harness.

## Phase 2: Proposed Next Work

### Per-request Model and Reasoning Options

Add support for Discord command options such as:

```text
/dev request:"Build a CSV preview app" reasoning:medium model:gpt-5.5
```

or a lightweight text convention:

```text
/dev --medium Build a CSV preview app
```

Implementation notes:

- Implemented base support for `model` and `reasoning_effort` fields in `CodexResult`.
- Implemented config defaults `CODEX_MODEL` and `CODEX_REASONING_EFFORT`.
- Implemented explicit Codex CLI flags/config overrides in `codex_runner.py`.
- Implemented recording selected model/reasoning in agent session state and Discord status output.
- Remaining work: expose these as true per-request Discord slash command options.

### Better Discord Output

- Post the exact generated app execution command after QA.
- Upload or link `README.md` from `generated_app`.
- Add a `/status run_id` command.
- Add a `/runs` command for recent runs.
- Add a `/cancel run_id` command for long-running tasks.

### Stronger QA

- Add generated app file presence checks.
- Validate `codex_app_manifest.json` when present and surface schema errors in
  the QA report.
- Add a language-neutral manifest runner for safe local setup, test, CLI,
  server, and browser checks.
- Keep Python syntax checks as one adapter, not the whole QA model.
- Add README run-command parsing as a fallback when the manifest is missing.
- Expand app-specific browser assertions beyond the generic keyboard probe.
- Add Tkinter/Pygame-safe smoke test strategy where practical.
- Expand QA Agent prompts and routing for multiple specialized reviewers.

### Code Review Agent

- Reuse `CodeAgent(code_1)` for fast and balanced single-agent implementation.
- Keep `DeveloperAgent` as a legacy path until the router can replace it.
- Add Code Agent 2 or Reviewer Agent only when the selected route justifies it.
- Reviewer checks whether generated code matches the approved plan.
- Reviewer can request targeted Code Agent or Integrator revisions before QA.

## Phase 3: Parallel Agent Workflow

Detailed design is tracked in `PARALLEL_AGENT_PLAN.md`.

### Contract-first Parallel Development

- Implemented base Planner/Architect contract bundle before code starts:
  - `requirements.md`
  - `architecture.md`
  - `api_contract.md` or `openapi.yaml`
  - `data_model.md`
  - `task_manifest.json`
  - `file_ownership.md`
  - `acceptance_tests.md`
- Implemented human approval against the contract bundle.
- Implemented Scaffold Agent for the shared project skeleton.
- Implemented Code Agents for isolated task groups in parallel workspaces.
- Implemented Integrator Agent that merges code-agent outputs into the final `generated_app`.
- Implemented first mechanical QA split:
  - Python syntax check
  - executable probe for static HTML, Streamlit, CLI, and opt-in Windows launchers
  - screenshots and runtime logs under `runs/<run_id>/qa/`
  - Codex-backed QA Agent review after mechanical QA
  - targeted fix routing to the owning Code Agent or Integrator
  - Discord QA approval/fix request loop
- Remaining work: add richer app-specific QA agents and stronger structured
  plan-compliance scoring.

### Dynamic Agent and Account Pool

- Support Planner 2-3, Code 1-3, and QA 1-2 agents per run.
- Add an agent registry with:
  - `agent_id`
  - role
  - account assignment
  - `CODEX_HOME`
  - model
  - reasoning effort
  - system/developer prompt override
- Allow two or more local Codex accounts by assigning different `CODEX_HOME`
  directories per account.
- Use account-level concurrency limits so agents can be distributed across
  logged-in accounts.
- Record account/model/reasoning/session details in `state.json`.

### Team Collaboration

- Role-based approval in Discord.
- Multiple approvers.
- Approval audit trail.
- Git branch creation per run.
- Optional automatic commit after approval.

### Dashboard Direction

- Discord becomes a message integration and mobile approval/feedback channel.
- A web dashboard becomes the primary control surface after the core workflow is
  stable.
- Dashboard controls should include agent counts, account pool, model selection,
  reasoning effort, prompt overrides, task assignment, run graph, logs, and
  artifact review.

## Phase 4: Web Dashboard and Integrations

### Web Dashboard

- Build a local dashboard for creating and managing runs.
- Show each stage of a run:
  - planning
  - contract approval
  - scaffold
  - parallel code batches
  - integration
  - QA
  - completion
- Provide forms for:
  - agent count by role
  - model/reasoning per agent
  - account assignment
  - prompt override editing
  - contract review and approval
  - task reassignment before code starts

### Discord Adapter

- Keep `/dev`, `/status`, `/runs`, and approval buttons as a remote control
  layer.
- Send dashboard links or local run paths in Discord status updates.
- Do not make Discord the only place where detailed configuration is possible.

### Framework Evaluation

The current direct orchestrator fits the local Codex CLI constraint well.
AutoGen, LangGraph, or Microsoft Agent Framework can be revisited if:

- workflow state transitions become too complex,
- visual traces are needed,
- checkpointing and resumability exceed the simple `state.json` design,
- or custom Codex CLI model clients become worth maintaining.

LangGraph is the most likely candidate for future workflow orchestration, but
Phase 1 intentionally avoids that dependency.

## Git Sharing Notes

Commit source and documentation files.

Do not commit:

- `runs/`
- `__pycache__/`
- `.pyc` files
- local `.env` files
- Discord bot tokens
- Codex auth/cache directories

Use `.gitignore` to keep generated run artifacts and local caches out of Git.
