# Stage 2 Implementation Tasks

This is the implementation checklist for `STAGE2_STREAMING_RUNNER_PLAN.md`.
Keep this file task-oriented. Update it as each slice lands.

## Stage 2A: Async Runner + Streaming

Status: implemented in this branch.

Goal: add a Codex runner that can stream stdout/stderr to log files while the
process is still running.

Files:

- `codex_runner.py`
- `tests/test_codex_runner_async.py`

Implementation steps:

1. Add `run_codex_result_async(...)` returning the existing `CodexResult`.
2. Reuse existing command construction, env cleanup, prompt logging, session
   parsing, metadata rendering, sandbox checks, and error behavior.
3. Use `asyncio.create_subprocess_exec`.
4. Pass prompts through stdin.
5. Stream stdout and stderr concurrently into:
   - `<call_id>_stdout.txt`
   - `<call_id>_stderr.txt`
6. Preserve partial logs on timeout or failure.
7. Keep the existing synchronous `run_codex_result(...)` unchanged for current
   production paths.

Tests:

- Fake subprocess streams stdout before exit and the log file grows while the
  process is active.
- Stderr is streamed and parsed for session id and sandbox headers.
- Non-zero exit raises `CodexExecutionError` with captured stdout/stderr.
- Timeout raises `CodexExecutionError` and keeps partial stdout/stderr logs.

Acceptance:

- Async runner returns a `CodexResult` compatible with the sync runner.
- Logs are written incrementally.
- Existing tests still pass.

Verified:

- `python -m py_compile main.py agents.py codex_runner.py workspace_manager.py parallel_workflow.py local_dashboard_runner.py executable_qa.py qa.py state_store.py config.py discord_reporter.py discord_ui.py debate_engine.py discord_bot.py dashboard.py app_services.py local_api.py run_local_api.py run_worker.py workflow_engine.py`
- `python -m unittest discover -s tests`

## Stage 2B: Active Process Cancel

Status: implemented in this branch.

Goal: let the worker stop an active child process.

Files:

- `codex_runner.py`
- `run_worker.py`
- `workflow_engine.py`
- `tests/`

Implementation steps:

1. Add a small process handle/observer API around the async runner. Done:
   `CodexProcessHandle` is emitted through `process_started`.
2. Store active process handles by `run_id`. Done: `RunWorker.active_processes`.
3. Record PID in `state.json.active_step.pid`. Done when
   `RunWorker.register_process(...)` is called.
4. Add hard cancel. Done:
   - use `psutil` when available,
   - fall back to Windows `taskkill /T /F /PID <pid>`,
   - fall back to `process.terminate()` and `process.kill()`.
5. Emit process cancellation events. Done:
   `active_process_cancel_started` and `active_process_cancelled`.
6. Clear `active_step` after success, failure, timeout, and cancel. Done for
   worker-level active cancel; Stage 2C will wire per-agent async calls into
   this registry.

Tests:

- Queued cancel marks the run cancelled.
- Active cancel terminates a fake long-running process.
- `active_step` is cleared after cancel.
- Logs and events capture the cancellation.

Acceptance:

- Cancel stops an active child process.
- No orphaned active job remains in `RunWorker`.

Verified:

- `python -m py_compile main.py agents.py codex_runner.py workspace_manager.py parallel_workflow.py local_dashboard_runner.py executable_qa.py qa.py state_store.py config.py discord_reporter.py discord_ui.py debate_engine.py discord_bot.py dashboard.py app_services.py local_api.py run_local_api.py run_worker.py workflow_engine.py`
- `python -m unittest discover -s tests -p test_codex_runner_async.py`
- `python -m unittest discover -s tests -p test_app_services.py`
- `python -m unittest discover -s tests`
- `npm run build`
- `git diff --check`

## Stage 2C: Planning Integration

Status: implemented in this branch.

Goal: move planning execution onto the async runner.

Files:

- `agents.py`
- `workflow_engine.py`
- `run_worker.py`
- `tests/`

Implementation steps:

1. Add async planning methods or async agent call wrappers. Done:
   Planner A, Planner B, and Planner C planning calls have async paths.
2. Let `RunWorker` dispatch planning jobs without `asyncio.to_thread`. Done
   for engines that expose `run_planning_async`; sync fallback remains for
   lightweight tests and compatibility.
3. Persist `planning_running` and `active_step` before each planner call.
   Done through `WorkflowEngine.run_planning_async(...)` and the worker
   process registry.
4. Keep plan approval and plan revision behavior unchanged. Done:
   successful planning still reaches `awaiting_plan_approval`.
5. Leave `continue_after_plan_approval` at the `development_queued`
   checkpoint. Done.

Tests:

- `POST /runs` still returns quickly.
- Planning writes streaming logs.
- Planning reaches `awaiting_plan_approval`.
- Planning failure records `failed`.
- Cancel during planning works after Stage 2B.

Acceptance:

- UI polling can observe planning status, active step, and growing logs.
- Existing Stage 1 API and service behavior remains compatible.

Verified:

- `python -m py_compile agents.py local_dashboard_runner.py workflow_engine.py run_worker.py tests\test_app_services.py`
- `python -m unittest discover -s tests -p test_app_services.py`
- `python -m py_compile main.py agents.py codex_runner.py workspace_manager.py parallel_workflow.py local_dashboard_runner.py executable_qa.py qa.py state_store.py config.py discord_reporter.py discord_ui.py debate_engine.py discord_bot.py dashboard.py app_services.py local_api.py run_local_api.py run_worker.py workflow_engine.py`
- `python -m unittest discover -s tests`
- `npm run build`
- `git diff --check`

## Non-Goals For Stage 2

- Do not migrate contract, scaffold, code, integration, QA, or fixes into the
  worker yet.
- Do not add SSE yet.
- Do not broaden generated-app execution beyond the manifest-first QA work.
- Do not remove the synchronous Codex runner until all callers are migrated.
