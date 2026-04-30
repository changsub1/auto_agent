# Local Codex Multi-Agent Development MVP

This project is a local technical MVP for multi-agent development automation.
It does not use an OpenAI API key directly and does not use the OpenAI SDK.
All LLM work is delegated to the locally installed and logged-in Codex CLI
through Python `subprocess`.

The original CLI flow is still available:

```text
User request -> Planner Agent -> Developer Agent -> Python syntax QA
```

The new Discord flow adds human-in-the-loop planning approval:

```text
/dev request
  -> Planner Agent A draft
  -> Planner Agent B review
  -> Planner Agent A final plan
  -> Architect Agent contract bundle
  -> Discord contract approve / request changes / cancel
  -> Scaffold Agent creates scaffold_app
  -> Code Agents implement isolated workspaces in parallel
  -> Integrator Agent merges generated_app
  -> Python syntax QA
```

## Requirements

- Python 3.10 or newer
- Codex CLI installed and logged in locally
- For Discord mode: a Discord bot token

Check Codex CLI first:

```bash
codex --help
codex exec --help
codex login status
```

## Install Python Dependencies

```bash
cd multi_codex_dev_mvp
python -m pip install -r requirements.txt
```

`requirements.txt` contains the local API, dashboard, Discord bot, and QA
dependencies. Codex itself must be installed separately and available as
`codex` on PATH.

## Local CLI Usage

```bash
python main.py "CSV file upload app that previews rows and shows missing value counts."
```

Planner and Developer can use different `CODEX_HOME` values:

```bash
python main.py --planner-codex-home "C:\Users\USER\.codex_planner" --developer-codex-home "C:\Users\USER\.codex_developer" "Build a simple todo app."
```

Set syntax-fix retries:

```bash
python main.py --max-fix-iterations 1 "Build a CSV analysis app."
```

## Discord Bot Usage

Set environment variables:

```bat
set DISCORD_BOT_TOKEN=your_bot_token
set DISCORD_GUILD_ID=your_test_guild_id
```

Optional controls:

```bat
set DISCORD_ALLOWED_CHANNEL_ID=channel_id
set DISCORD_ALLOWED_USER_IDS=user_id_1,user_id_2
set PLANNER_A_CODEX_HOME=C:\Users\USER\.codex_planner_a
set PLANNER_B_CODEX_HOME=C:\Users\USER\.codex_planner_b
set ARCHITECT_CODEX_HOME=C:\Users\USER\.codex_architect
set SCAFFOLD_CODEX_HOME=C:\Users\USER\.codex_developer
set DEVELOPER_CODEX_HOME=C:\Users\USER\.codex_developer
set INTEGRATOR_CODEX_HOME=C:\Users\USER\.codex_developer
set CODE_AGENT_CODEX_HOMES=C:\Users\USER\.codex_developer_1,C:\Users\USER\.codex_developer_2
set CODE_AGENT_COUNT=2
set QA_AGENT_CODEX_HOMES=C:\Users\USER\.codex_qa
set QA_AGENT_COUNT=1
set ROUTING_MODE=balanced
set REFERENCE_PACK_ENABLED=1
set PLANNER_A_REFERENCE=
set PLANNER_B_REFERENCE=
set CODE_AGENT_REFERENCE=karpathy/code_agent
set INTEGRATOR_REFERENCE=karpathy/integrator
set QA_AGENT_REFERENCE=
set CODEX_MODEL=gpt-5.4
set CODEX_REASONING_EFFORT=medium
set MAX_FIX_ITERATIONS=1
set CODEX_TIMEOUT_SECONDS=900
```

Run the bot:

```bash
python discord_bot.py
```

In Discord:

```text
/dev CSV file upload app that previews data and shows missing value counts.
```

The bot posts Planner A's draft, Planner B's review, Planner A's final plan,
and the Architect contract bundle summary. The requesting user then gets
buttons:

- Approve
- Request changes
- Cancel

Approval starts the selected routing pipeline. Fast and balanced routes use one
`CodeAgent`; the parallel route starts scaffold, parallel Code Agents,
integration, and QA. A contract or plan revision request sends the feedback
back into the planning loop. After QA, the
bot posts the report and any screenshots, then asks the requester to approve
the result or request implementation fixes. Fixes are routed to the owning
`code_N` session when QA identifies an owned path or suspected owner; shared,
cross-agent, or unknown issues go to the Integrator. `DeveloperAgent` remains
only for the legacy single-developer CLI path.

`ROUTING_MODE` controls the development pipeline. The default is `balanced`:

- `fast`: Planner A, one `CodeAgent`, and mechanical QA.
- `balanced`: Planner A/B, one `CodeAgent`, mechanical QA, and one QA Agent when configured.
- `parallel`: contract, scaffold, parallel Code Agents, Integrator, and QA.
- `manual`: use configured code/QA counts; more than one code agent uses the parallel route.

Set `QA_AGENT_COUNT=0` to run only mechanical QA for routes that would otherwise
include Codex-backed QA review.

Reference profiles are role-specific and use `pack/role` syntax. By default,
only Code Agents and the Integrator receive the lightweight Karpathy-inspired
coding guidance:

```text
CODE_AGENT_REFERENCE=karpathy/code_agent
INTEGRATOR_REFERENCE=karpathy/integrator
```

Planner and QA references are empty by default. They can be customized, for
example:

```text
PLANNER_A_REFERENCE=gstack/planner_a
PLANNER_B_REFERENCE=gstack/planner_b
QA_AGENT_REFERENCE=gstack/qa_agent
```

At run start, the orchestrator copies only the selected curated packs into
`runs/<run_id>/reference_packs/` and attaches the matching role file to each
agent prompt. The ignored `reference_packs/gstack_src/` and
`reference_packs/karpathy_src/` directories are local vendor source caches;
their installers and source scripts are not run by this project.

Executable browser QA uses Playwright when it is installed. Install the Python
package through `requirements.txt`, then install Chromium once:

```bash
python -m playwright install chromium
```

## Local Dashboard Usage

The Streamlit dashboard is a local run control panel for testing the
contract-first workflow without Discord.

```bash
python -m streamlit run dashboard.py
```

If Streamlit is installed in the local Miniconda Python on this machine, use:

```bash
D:\miniconda3\python.exe -m streamlit run dashboard.py
```

The dashboard supports:

- `planning_only`
- `contract_only`
- `scaffold_only`

`full_run` is shown but disabled for now because the Discord approval workflow
still owns full scaffold/code/integration/QA execution. The dashboard reuses the
same environment variable defaults as the Discord bot, including `CODEX_HOME`,
model, reasoning effort, timeouts, and code-agent counts.

The dashboard displays:

- run id and local run path
- `state.json`
- `events.jsonl`
- `transcript.md`
- `contract/*`
- `qa_report.md` when available

It never reads or displays `auth.json`.

## Local API Usage

The local desktop/web UI uses a FastAPI adapter over the shared Python service
layer. The API is local-only and must bind to `127.0.0.1` or `localhost`.

Install the API dependencies:

```bash
python -m pip install -r requirements.txt
```

Run the API:

```bash
python run_local_api.py --host 127.0.0.1 --port 8765
```

Available local endpoints include:

- `GET /config`
- `POST /runs`
- `GET /runs`
- `GET /runs/{run_id}`
- `GET /runs/{run_id}/events`
- `GET /runs/{run_id}/artifacts`
- `GET /runs/{run_id}/artifacts/content?path=...`
- `POST /runs/{run_id}/approve`
- `POST /runs/{run_id}/request-changes`
- `POST /runs/{run_id}/cancel`
- `POST /runs/{run_id}/qa/approve`
- `POST /runs/{run_id}/qa/request-fix`

`POST /runs` creates run state quickly, records the selected route/workflow, and
enqueues background planning through the local FastAPI run worker. The UI can
poll run detail, events, and artifacts while planning is in progress. Approval,
revision, and cancel actions are persisted through the same service layer and
enqueue worker jobs when possible.

The current worker stops at a `development_queued` checkpoint after plan or
contract approval. Full contract/scaffold/code/integration/QA execution still
needs to be moved out of the Discord-owned orchestration path before the app can
run the complete implementation pipeline by itself.

## React/Tauri App Usage

The `ux/` folder is now a Vite React app that reads the local FastAPI API
instead of static mock data.

Development mode:

```bash
cd ux
pnpm install
pnpm dev
```

In a separate terminal:

```bash
python run_local_api.py --host 127.0.0.1 --port 8765
```

Tauri desktop mode:

```bash
cd ux
pnpm tauri:dev
```

The Tauri shell chooses a free local port, starts `run_local_api.py` as a
sidecar process, and gives the React UI the API URL through the `api_base_url`
Tauri command. The first packaging target is Windows NSIS.

## Run Output

Each run creates a timestamped directory:

```text
runs/YYYYMMDD_HHMMSS/
  state.json
  events.jsonl
  transcript.md
  reference_packs/
    karpathy/
      reference_pack_manifest.json
      code_agent.md
      integrator.md
    gstack/
      reference_pack_manifest.json
      planner_a.md
      planner_b.md
      code_agent.md
      integrator.md
      qa_agent.md
  plan.md
  planning/
    01_planner_a_draft.md
    02_planner_b_review.md
    03_final_plan.md
  contract/
    requirements.md
    architecture.md
    api_contract.md
    data_model.md
    task_manifest.json
    file_ownership.md
    acceptance_tests.md
    integration_plan.md
  scaffold_app/
  agent_workspaces/
    code_1/
    code_2/
  agent_outputs/
    assignment_summary.md
    code_1_summary.md
    code_2_summary.md
  integration/
    merged_app/
    merge_seed_report.md
  generated_app/
    app.py
    requirements.txt
    README.md
  qa/
    attempt_00/
      syntax_report.md
      executable_qa_report.md
      screenshot_initial.png
      screenshot_after_keys.png
  qa_report.md
  logs/
    *_prompt.txt
    *_stdout.txt
    *_stderr.txt
    *_meta.txt
```

## Session and Memory Design

The Discord workflow is session-oriented.

- Each agent has its own Codex session id in `state.json`.
- New agent calls use `codex exec ... -`.
- Follow-up calls try `codex exec resume <session_id> -`.
- Prompts are sent through stdin, not shell interpolation.
- If resume fails, the engine falls back to a fresh Codex call using the latest
  relevant artifact instead of the full transcript.

Local files are still written for audit and recovery:

- `state.json`: current run status, Discord ids, artifact paths, agent session ids
- `events.jsonl`: append-only machine-readable event log
- `transcript.md`: human-readable conversation and artifact log
- `planning/*.md`: planning artifacts
- `contract/*`: Architect-created contract bundle and task manifest
- `scaffold_app/`: shared skeleton copied into each code-agent workspace
- `agent_workspaces/*`: isolated parallel code-agent workspaces
- `integration/merged_app`: Integrator output before it is copied to `generated_app`
- `qa/`: syntax reports, executable QA reports, screenshots, and runtime logs
- `logs/*`: raw Codex prompt/stdout/stderr/meta logs

The engine intentionally avoids sending the full transcript on every turn. It
prefers Codex session resume and only sends the new feedback, review, or latest
artifact needed for that turn.

## Multi-account Codex CLI Setup

Use one `CODEX_HOME` directory per local Codex account. Configure file-based
credential storage in each profile so each account keeps its own `auth.json`:

```toml
cli_auth_credentials_store = "file"
```

Example PowerShell login flow:

```powershell
$env:CODEX_HOME = "D:\codex_profiles\account_1"
codex.cmd login
codex.cmd login status

$env:CODEX_HOME = "D:\codex_profiles\account_2"
codex.cmd login
codex.cmd login status
```

Then assign those profile paths through the existing agent environment
variables, such as `PLANNER_A_CODEX_HOME`, `PLANNER_B_CODEX_HOME`, and
`DEVELOPER_CODEX_HOME`. The Phase 3 plan in `PARALLEL_AGENT_PLAN.md` describes
the future generalized account and agent registry.

Current assignment example with Planner A/B on account 1 and the remaining
agents on account 2:

```bat
set PLANNER_A_CODEX_HOME=D:\codex_profiles\account_1
set PLANNER_B_CODEX_HOME=D:\codex_profiles\account_1
set ARCHITECT_CODEX_HOME=D:\codex_profiles\account_2
set SCAFFOLD_CODEX_HOME=D:\codex_profiles\account_2
set CODE_AGENT_CODEX_HOMES=D:\codex_profiles\account_2
set CODE_AGENT_COUNT=2
set QA_AGENT_CODEX_HOMES=D:\codex_profiles\account_2
set QA_AGENT_COUNT=1
set INTEGRATOR_CODEX_HOME=D:\codex_profiles\account_2
set DEVELOPER_CODEX_HOME=D:\codex_profiles\account_2
```

## Safety Notes

- User requests are never executed as shell commands.
- User requests are passed only as Codex prompt text through stdin.
- `subprocess.run` uses list arguments and `shell=False`.
- Codex calls use `--skip-git-repo-check`.
- New Codex exec calls use `--sandbox workspace-write`.
- Generated apps are created under each run's `generated_app` directory.
- Generated `.bat` and `.cmd` files are normalized to CRLF line endings.

## Syntax Check

```bash
python -m py_compile main.py agents.py codex_runner.py workspace_manager.py parallel_workflow.py local_dashboard_runner.py executable_qa.py qa.py state_store.py config.py discord_reporter.py discord_ui.py debate_engine.py discord_bot.py dashboard.py
```
