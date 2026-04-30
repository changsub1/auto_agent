# Project Status

## Purpose

This repository is a local Codex CLI multi-agent development automation MVP.
It verifies that a Python orchestrator can call the locally logged-in Codex CLI
instead of using an OpenAI API key or OpenAI SDK directly.

The current system can receive a development request, let multiple Codex-backed
agents discuss the plan, ask a human for approval in Discord, and then generate
a runnable Python app locally.

As of 2026-04-29, the product direction is a local Tauri desktop app with a
localhost-only FastAPI sidecar. Discord should become a lightweight remote
control and notification adapter, not the owner of the main workflow.

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
- QA runs `python -m py_compile` against generated Python files.
- If syntax QA fails, Developer Agent receives the error log and gets one or more fix attempts.

### Discord Human-in-the-loop MVP

- Discord bot entrypoint: `discord_bot.py`
- Slash command: `/dev`
- User can request a service/app from Discord.
- Bot posts progress updates to the Discord channel.
- Planner Agent A creates an initial plan.
- Planner Agent B reviews the plan.
- Planner Agent A creates a final plan.
- Architect Agent creates a contract bundle and task manifest.
- Discord buttons allow the requester to:
  - Approve
  - Request changes
  - Cancel
- If approved, Scaffold Agent creates `scaffold_app`.
- Code Agents implement assigned task groups in isolated workspaces in parallel.
- Integrator Agent merges the work into `generated_app`.
- QA result, generated app path, and executable QA screenshots are posted back
  to Discord when the probe can run.
- After QA, Discord asks the requester to approve the result or request fixes.
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
- `qa.py`: mechanical QA result composition and Python syntax QA
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
- The latest checked validation passed:
  - `python -m py_compile app_services.py local_dashboard_runner.py local_api.py run_local_api.py run_worker.py workflow_engine.py state_store.py`
  - `python -m unittest discover -s tests`
  - `npm run build` from `ux/`

Still partial:

- `POST /runs` is connected to the existing local dashboard runner, so it is
  useful for planning/contract/scaffold-stage testing but is not yet the final
  long-running workflow engine.
- Approve, request changes, QA approve, QA fix, and cancel are persisted through
  the API, but approve/fix actions do not yet advance the full implementation
  pipeline from the app.
- Manual mode agent cards currently affect supported role counts. They are not
  yet a full agent registry with per-agent prompts, models, accounts, and
  execution ownership.
- Tauri scaffolding exists, but Windows `.exe` packaging is not verified because
  Rust/Cargo and the Python sidecar packaging path still need to be installed
  and finalized.

FastAPI run worker Stage 1 is complete for the first worker slice:

- Added `run_worker.py` with an in-process `asyncio.Queue`, `RunJob`, active
  job registry, per-run locks, and job dispatch for planning, plan approval,
  plan revision, and cancellation.
- Added `workflow_engine.py` as the non-Discord workflow stage owner for local
  planning execution and development-queued checkpoints.
- Extended `state_store.py` with `active_step`, `control`, and `workflow`
  helpers while keeping older run state readable.
- Changed local API run creation so `POST /runs` creates run state quickly,
  records routing/workflow/config, sets `planning_queued`, and enqueues
  background planning instead of blocking on Codex planning.
- Changed approve/request-changes/cancel service methods so they validate state,
  persist approval/control events, and enqueue the next worker job when the
  FastAPI worker is available.
- Added worker-focused tests using a fake workflow engine.
- Verified on 2026-04-30 with Python compile checks, the unittest suite, and
  the React/Vite production build.

## Known Limitations

- The new local API now creates run state quickly and enqueues planning through
  the FastAPI run worker. Contract/scaffold/full code/integration/QA execution
  is still not fully owned by the worker; those deeper orchestration methods
  still need to be decoupled from Discord channel/interaction objects.
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
- Executable QA still relies mostly on detection heuristics. It should prefer a
  generated `codex_app_manifest.json` that declares safe setup, test, smoke,
  server, and browser checks in a language-neutral schema.
- Codex-backed QA Agent review is implemented after mechanical QA. It can use
  the configured QA `CODEX_HOME`, model, reasoning effort, QA report, contract,
  generated app listing, and attached screenshots.
- Session resume is supported, but deeper long-term memory compaction is not implemented.
- Discord approval controls are requester-only, not role/team-policy based.
- `reference_packs/gstack_src/` and `reference_packs/karpathy_src/` are local
  ignored vendor caches. The orchestrator only attaches curated committed
  Markdown files to agent prompts; it does not run source scripts or installers.

## Immediate Priorities

### 0. Recommended Completion Sequence

Complete the product in this order:

1. Build the Stage 2 streaming and interruptible Codex runner.
   - Add an async Codex process runner that streams stdout/stderr to log files.
   - Track PID/process handles in `active_step` so cancel can stop active Codex
     subprocesses.
   - Emit heartbeat/progress events while long-running Codex calls execute.
   - Support soft interrupt by storing feedback for the next safe checkpoint.
   - Support hard interrupt by terminating the active process tree and marking
     the run interrupted or cancelled.
2. Decouple full code, revision, and QA flows from Discord.
   - Move Discord-owned orchestration code into shared service methods.
   - Keep Discord as an adapter that calls the same service layer used by the
   app and future CLI.
   - Preserve Discord buttons and text summaries, but make the app capable of
   the same approve/request-change/cancel/QA-fix actions.
3. Finish the remaining worker migration.
   - Persist state transitions for contract, scaffold, code, integration, QA,
     fix, and completion.
   - Add worker jobs for starting/continuing after approval and running fixes
     after change requests.
   - Reuse the Stage 2 process runner for all Codex-backed stages.
4. Strengthen generic executable QA.
   - Prefer `codex_app_manifest.json` when present.
   - Add safe manifest validation and command execution with timeouts and logs.
   - Use framework adapters for Python, Node/Vite/React, static HTML, and CLI
     projects when the manifest is missing.
   - Add Playwright browser checks for web apps: page load, blank screen,
     console errors, screenshot capture, and basic interaction probes.
5. Finish the desktop app packaging path.
   - Install Rust/Cargo for Tauri builds.
   - Decide whether the Python API sidecar runs from source in dev and from a
     PyInstaller-built executable in production.
   - Make Tauri choose a free local port, inject it into the UI, and stop the
     sidecar on app exit.
   - Verify Windows `.exe` packaging after the backend worker is stable.
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
