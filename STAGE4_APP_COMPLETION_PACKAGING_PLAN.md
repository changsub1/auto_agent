# Stage 4 App Completion And Packaging Plan

Stage 3 is considered complete at the MVP architecture level:

- FastAPI + RunWorker own workflow execution.
- Discord is an API client and notification surface.
- The React monitor reads active step, logs, events, and artifacts through API
  endpoints.
- The main remaining risks are product fit, packaging reliability, and
  operational polish discovered by actual use.

Stage 4 shifts the project from architecture migration to a usable local
desktop product.

## Version 8 Implementation Status

Stage 4A and 4B are usable for dogfooding:

- The React/Tauri app can create a run, approve the plan, observe execution,
  review QA, approve QA, and complete a run through the localhost API.
- The Tauri shell starts the FastAPI sidecar, waits for `/health`, injects the
  API URL into React, and writes sidecar stdout/stderr under
  `tmp/tauri_sidecar/`.
- Fast mode has been smoke-tested through the desktop app on a real request and
  produced a completed generated app.
- The run monitor now defaults to a clean operator timeline: agent outputs,
  approvals, user actions, and errors are shown by default; internal worker
  events remain available under the `System` or `All` filters.
- Agent output events preview the generated markdown artifact directly in the
  timeline.

Remaining Stage 4 work:

- Build and smoke-test a packaged Windows installer.
- Decide whether packaged builds use source + existing `.venv` Python or a
  bundled sidecar executable.
- Continue dogfooding across `fast`, `balanced`, `parallel`, and `manual` modes
  and record the highest-priority UX, QA, and recovery issues.

## Product Direction

Complete the app enough to use it on real personal development requests, then
dogfood it before making final architectural cleanup decisions.

The immediate goal is not to add every planned agent feature. The goal is to
make the local app installable, observable, recoverable, and comfortable enough
to run repeatedly on real tasks.

## Stage 4A: App Completion

Goal: make the React/Tauri app the primary control surface.

Tasks:

1. Finish the run lifecycle in the UI:
   - create run
   - approve plan
   - request plan changes
   - cancel run
   - review QA
   - approve QA
   - record QA fix request
2. Make run observation useful:
   - active step panel
   - recent log tail
   - event timeline
   - artifacts and QA evidence
   - generated app path and run directory
3. Add practical run controls:
   - refresh
   - open generated app folder where supported
   - clear error state
   - show failed/cancelled state clearly
4. Keep Discord as a secondary remote approval/status channel.

Acceptance:

- A user can complete a full request from the app without using the Streamlit
  dashboard or Discord.
- The UI makes it clear when the system is planning, coding, testing, waiting
  for approval, failed, cancelled, or completed.

## Stage 4B: Sidecar Runtime Hardening

Goal: make the FastAPI sidecar reliable under Tauri.

Initial implementation status:

- Tauri now prefers the repo-local `.venv` Python for `run_local_api.py`.
- `ORCHESTRA_PYTHON` can override the Python executable.
- `ORCHESTRA_REPO_ROOT` can override repository root detection.
- The sidecar waits for `/health` before setup completes.
- Sidecar stdout/stderr are written under `tmp/tauri_sidecar/`.

Tasks:

1. Start the local API sidecar from Tauri. Initial implementation done.
2. Choose a free localhost port. Initial implementation done.
3. Inject the API URL into React. Initial implementation done.
4. Wait for `/health` before showing the app as ready. Initial implementation
   done.
5. Stop the sidecar when the app exits. Initial implementation exists; verify
   under real `tauri:dev` and packaged app runs.
6. Capture sidecar stdout/stderr into app logs. Initial implementation done.
7. Keep the API localhost-only. Initial implementation done.
8. Install Rust/Cargo on the development machine and run `cargo fmt`,
   `cargo check`, `npm run tauri:dev`, and `npm run tauri:build`.
   Version 8 status: Rust/Cargo are installed, `cargo fmt`, `cargo check`,
   `npm run build`, and `npm run tauri:dev` have been verified. Packaged
   `npm run tauri:build` smoke testing is still pending.

Acceptance:

- `npm run tauri:dev` starts the UI and sidecar together.
- Closing the app stops the sidecar.
- Sidecar startup failures are visible to the user.

## Stage 4C: Windows Packaging

Goal: produce an installable Windows desktop build.

Tasks:

1. Decide the Python sidecar packaging strategy:
   - source + existing Python for dev, or
   - PyInstaller-built sidecar executable for packaged app.
2. Configure Tauri bundle metadata:
   - app name
   - icon
   - version
   - Windows NSIS target
3. Bundle or document runtime prerequisites:
   - Codex CLI installed and logged in
   - Python dependencies or sidecar executable
   - Playwright browser dependency when executable QA is enabled
4. Verify install, launch, run creation, sidecar shutdown, and uninstall.

Acceptance:

- A Windows install artifact can launch the local app.
- The app can connect to a local Codex CLI profile and create a run.
- The app does not require exposing the API beyond localhost.

## Stage 4D: Dogfooding And Feedback Capture

Goal: use the app on real tasks before final cleanup.

Dogfooding checklist:

- Run at least several real development requests in `fast`, `balanced`, and
  `parallel` modes.
- Record time to plan, time to code, failure rate, fix-loop usefulness, and QA
  signal quality.
- Note where the UI is unclear or slow.
- Note where agent prompts produce weak contracts, bad manifests, or noisy
  outputs.
- Verify Codex session resume behavior over repeated runs.
- Verify Discord `/dev`, `/runs`, and `/status` on a real bot token if Discord
  remains part of the workflow.

Dogfooding output:

- a short issue list grouped by severity,
- a UX friction list,
- a QA gap list,
- a packaging/setup issue list,
- a decision on whether legacy paths such as `debate_engine.py` should be
  removed, archived, or kept as compatibility references.

## Stage 4E: Stabilization

Goal: close the top dogfooding issues without broad redesign.

Tasks:

1. Fix high-severity run failures.
2. Improve the most confusing UI states.
3. Add regression tests for discovered failures.
4. Harden cancel/retry/recovery where real use shows it matters.
5. Decide whether operator QA fix re-enqueue belongs in Stage 4 or a later
   Stage 5 agent-control pass.

Acceptance:

- The app can be used repeatedly without manual file inspection for normal
  runs.
- Known limitations are documented clearly.
- The next stage can focus on advanced agent registry, richer QA, or broader
  distribution rather than core workflow plumbing.

## Non-Goals For Stage 4

- No cloud service backend.
- No multi-user hosted approval system.
- No external queue such as Redis/Celery unless local worker limits become a
  proven blocker.
- No full generalized agent registry unless dogfooding proves it is needed
  before packaging.
- No broad prompt rewrite unless real outputs show consistent failures.

## Stage 4 Exit Criteria

Stage 4 is complete when:

- The desktop app can run the local API sidecar.
- A real user can create, approve, observe, QA-review, and complete a run from
  the app.
- A Windows package has been built and smoke-tested.
- Dogfooding findings have been recorded and the highest-priority issues have
  either been fixed or moved to a clearly named follow-up stage.
