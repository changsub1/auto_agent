# Stage 3 FastAPI Full Workflow Plan

Stage 3 moves the full execution workflow out of Discord-owned control paths
and into the FastAPI + RunWorker execution engine.

The target architecture is:

- FastAPI owns run creation, state transitions, queueing, cancellation, and
  workflow execution.
- RunWorker owns the active local execution lifecycle.
- WorkflowEngine owns stage execution.
- Discord becomes one client surface, not the execution engine.
- Web UI, Discord, and future CLI clients all observe and control the same run
  state through the API.

## Current Baseline

Completed before Stage 3:

- FastAPI run service can create runs and enqueue planning.
- RunWorker has an in-process queue.
- StateStore is the durable source of truth for status, events, artifacts,
  active step, and control requests.
- Codex async runner streams stdout/stderr to log files while the process is
  running.
- Active Codex subprocesses can be cancelled through process handles.
- Planning runs through the async runner and records active planner PID.
- Planning success reaches `awaiting_plan_approval`.
- Planning approval currently stops at `development_queued`.

Stage 3 starts from that checkpoint.

## Stage 3A: Full Workflow Engine Migration

Status: complete in this branch.

- `continue_after_plan_approval` now starts `WorkflowEngine.run_development_async`
  when available.
- FastAPI/RunWorker development execution now runs contract and scaffold.
- Architect and Scaffold agents have async Codex runner paths.
- Contract/scaffold subprocesses are registered for active process cancel.
- Code agents, integration, and mechanical QA now run through the
  FastAPI/RunWorker path.
- Multiple active Codex subprocesses can be registered per run, so parallel code
  agent cancellation can stop every active child process.
- LLM QA now runs through the FastAPI/RunWorker path when `qa_agent_count` is
  greater than zero.
- Targeted fix loop now runs through the FastAPI/RunWorker path for code-agent
  fixes and integrator repair.
- The workflow now reaches `awaiting_qa_approval` after mechanical QA.
- Final completion after QA approval remains handled by the existing
  `approve_qa` service action.
- QA approve and QA fix requests are accepted only from
  `awaiting_qa_approval`.

Goal: move planning-after-approval execution into `WorkflowEngine` and
`RunWorker`.

Stages to migrate:

- contract
- scaffold
- code agents
- integration
- mechanical QA
- LLM QA
- fix loop

Implementation tasks:

1. Add workflow methods after planning approval. Done:
   `run_development_async(...)` exists for contract, scaffold, code agents,
   integration, mechanical QA, LLM QA, and targeted fix loop.
   - `run_development_async(...)`
   - narrower internal methods such as `_run_contract_async`,
     `_run_scaffold_async`, `_run_code_agents_async`, `_run_integration_async`,
     `_run_mechanical_qa`, `_run_llm_qa_async`, and `_run_fix_loop_async`.
2. Reuse the existing local workflow functions where possible, but route Codex
   calls through async runner wrappers.
3. Register every active Codex subprocess with RunWorker.
4. Persist `active_step` for each stage and agent:
   - stage
   - agent_id
   - pid
   - interruptible
5. Keep artifact paths and event names compatible with current UI readers.
6. Ensure `continue_after_plan_approval` starts development instead of only
   marking `development_queued`. Done for Stage 3A-1.
7. Preserve the existing manifest-first executable QA behavior.

Completed Stage 3A-2 scope:

- migrate code agents,
- migrate integration,
- migrate mechanical QA.

Completed additional Stage 3A scope:

- migrate LLM QA,
- migrate targeted fix loop,
- define final completion status after QA approval.

Stage 3A-1 verified with:

- `python -m py_compile main.py agents.py codex_runner.py workspace_manager.py parallel_workflow.py local_dashboard_runner.py executable_qa.py qa.py state_store.py config.py discord_reporter.py discord_ui.py debate_engine.py discord_bot.py dashboard.py app_services.py local_api.py run_local_api.py run_worker.py workflow_engine.py`
- `python -m unittest discover -s tests`
- `npm run build`
- `git diff --check`

Stage 3A-2 verified with:

- `python -m py_compile agents.py local_dashboard_runner.py workflow_engine.py run_worker.py tests\test_app_services.py`
- `python -m unittest discover -s tests -p test_app_services.py`
- `python -m py_compile main.py agents.py codex_runner.py workspace_manager.py parallel_workflow.py local_dashboard_runner.py executable_qa.py qa.py state_store.py config.py discord_reporter.py discord_ui.py debate_engine.py discord_bot.py dashboard.py app_services.py local_api.py run_local_api.py run_worker.py workflow_engine.py`
- `python -m unittest discover -s tests`
- `npm run build`
- `git diff --check`

LLM QA and fix loop verified with:

- `python -m py_compile agents.py local_dashboard_runner.py workflow_engine.py run_worker.py tests\test_app_services.py`
- `python -m unittest discover -s tests -p test_app_services.py`
- `python -m py_compile main.py agents.py codex_runner.py workspace_manager.py parallel_workflow.py local_dashboard_runner.py executable_qa.py qa.py state_store.py config.py discord_reporter.py discord_ui.py debate_engine.py discord_bot.py dashboard.py app_services.py local_api.py run_local_api.py run_worker.py workflow_engine.py`
- `python -m unittest discover -s tests`
- `npm run build`
- `git diff --check`

Final QA approval policy verified with:

- `python -m py_compile app_services.py tests\test_app_services.py`
- `python -m unittest discover -s tests -p test_app_services.py`
- `python -m py_compile main.py agents.py codex_runner.py workspace_manager.py parallel_workflow.py local_dashboard_runner.py executable_qa.py qa.py state_store.py config.py discord_reporter.py discord_ui.py debate_engine.py discord_bot.py dashboard.py app_services.py local_api.py run_local_api.py run_worker.py workflow_engine.py`
- `python -m unittest discover -s tests`
- `npm run build`
- `git diff --check`

Acceptance:

- Approving a plan starts the remaining workflow without Discord owning the
  execution.
- Generated app artifacts are produced through the FastAPI/worker path.
- UI polling can see each active stage and agent.
- Cancel works during contract, scaffold, code, integration, and LLM QA Codex
  calls.
- Mechanical QA results remain attached to the run.
- LLM QA results are attached when QA agents are enabled.
- QA fix loop runs up to `max_fix_iterations` before the run waits for
  operator QA approval.
- Operator QA approval moves `awaiting_qa_approval` to `completed`.

## Stage 3B: Discord As API Client

Goal: remove long-running workflow execution from Discord bot code.

Implementation tasks:

1. Identify Discord paths that directly call local workflow execution.
2. Replace direct execution with FastAPI client calls:
   - create run
   - approve plan
   - request plan changes
   - cancel run
   - fetch run detail
   - fetch events/artifacts
3. Keep Discord messages as presentation only.
4. Do not let Discord hold the authoritative workflow state.
5. Add a small API client module for Discord instead of spreading HTTP calls
   across handlers.

Acceptance:

- Restarting Discord does not kill an active workflow.
- Discord can create, approve, revise, cancel, and inspect runs through API.
- Web UI and Discord show the same status because both read FastAPI state.

## Stage 3C: Execution State And Logs API

Goal: expose enough execution evidence for web UI, Discord, and QA review.

Implementation tasks:

1. Add or finalize API endpoints for:
   - active step
   - stage status
   - event timeline
   - artifact list and content
   - stdout/stderr log file list
   - log tail by file
2. Keep polling first. SSE/WebSocket can be added later only if polling is not
   enough.
3. Include process metadata where useful:
   - pid
   - agent_id
   - stage
   - started_at
   - interruptible
4. Ensure log endpoints never allow path traversal outside the run directory.

Acceptance:

- UI can show running stage, active agent, and recent logs.
- Discord can summarize progress without reading local files directly.
- QA evidence can point to concrete logs, artifacts, screenshots, and reports.

## Stage 3D: Cancel, Retry, And Recovery

Goal: make full workflow control predictable after migration.

Implementation tasks:

1. Apply active process cancellation to every async Codex-backed stage.
2. Define how cancellation behaves between subprocess calls.
3. Prevent cancelled runs from being overwritten as `failed`.
4. Add retry entry points for failed or cancelled stages where practical.
5. Keep retries explicit; do not automatically rerun expensive Codex calls
   without operator action.
6. Record clear events for:
   - cancel requested
   - active process cancel started
   - active process cancelled
   - stage skipped because cancelled
   - retry requested

Acceptance:

- Cancel does not leave orphan active jobs or active process handles.
- Cancelled status is stable and not overwritten by late worker exceptions.
- Operators can understand what was cancelled and where.

## Non-Goals

- Do not replace FastAPI with a distributed worker system yet.
- Do not add external queues such as Redis/Celery unless local worker limits
  become a real blocker.
- Do not remove the synchronous legacy CLI path until full FastAPI workflow is
  proven.
- Do not make Discord the state authority again.
- Do not broaden app execution beyond the manifest-first QA contract unless a
  concrete generated app requires it.

## Suggested Implementation Order

1. Stage 3A first: full workflow after plan approval.
2. Stage 3C next: expose logs and state needed to observe full workflow.
3. Stage 3B next: convert Discord to API client once API behavior is stable.
4. Stage 3D throughout: cancellation and recovery should be added as each stage
   is migrated, then hardened at the end.

## Completion Criteria

Stage 3 is complete when:

- A run can be created through FastAPI.
- Planning runs asynchronously and waits for approval.
- Plan approval triggers the full implementation and QA workflow through
  RunWorker.
- Discord can operate the same run through API calls only.
- Web UI and Discord read the same run state.
- Cancelling an active run stops the current child process and leaves durable
  cancelled state.
- Full test suite and frontend build pass.
