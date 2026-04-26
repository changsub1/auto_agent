# Parallel Agent Development Plan

## Goal

Evolve the current Discord-first MVP into a contract-first, parallel Codex CLI
orchestrator.

The target workflow is:

```text
User request
  -> planner/architect agents produce a contract bundle and task manifest
  -> human approves the contract
  -> scaffold agent creates a shared skeleton
  -> code agents implement isolated task slices in parallel
  -> integrator merges slices
  -> QA agents validate mechanics and plan compliance
  -> Discord reports status and handles approval/feedback
```

Discord remains useful for mobile approval and feedback. The later dashboard
should become the primary control surface for agent counts, model selection,
prompt overrides, account pools, run status, and artifact review.

## Design Principles

- Contract-first before parallel code: planners must define boundaries before
  code agents write files.
- Isolated write spaces: code agents should not edit the same directory at the
  same time.
- Explicit file ownership: each task declares owned files, allowed shared files,
  and forbidden files.
- Deterministic orchestration: Python code decides agent assignment and merge
  order; Codex agents execute bounded prompts.
- Account-aware scheduling: each agent invocation receives the `CODEX_HOME`
  assigned by the orchestrator.
- Human approval stays before expensive or broad write phases.
- Every agent output is saved as a run artifact, not only sent to Discord.

## Relevant Codex CLI Facts

The local orchestrator can rely on these Codex CLI behaviors:

- `codex exec` supports `--model` and repeatable `-c key=value` config
  overrides, including `model_reasoning_effort`.
- `codex login` supports browser/device login and `--with-api-key`.
- Codex caches credentials locally. Official docs state file-based credentials
  are stored as `auth.json` under `CODEX_HOME` when
  `cli_auth_credentials_store = "file"` is configured.
- Codex subagent documentation confirms parallel agents are useful for bounded
  work, but write-heavy parallel work needs careful coordination.
- Codex app worktree documentation uses Git worktrees to let Codex work in
  parallel without interfering with the foreground checkout. The local MVP can
  implement the same isolation idea with per-agent workspace copies first, and
  optionally move to Git worktrees later.

Sources:

- https://developers.openai.com/codex/auth
- https://developers.openai.com/codex/cli/reference
- https://developers.openai.com/codex/config-reference
- https://developers.openai.com/codex/subagents
- https://developers.openai.com/codex/app/worktrees

## Local Two-account Login Strategy

Use one Codex home directory per account.

Recommended local directories:

```text
D:\codex_profiles\account_1
D:\codex_profiles\account_2
```

Put this `config.toml` in each directory:

```toml
cli_auth_credentials_store = "file"
```

This keeps each account's `auth.json` under its own `CODEX_HOME`. Treat those
files like passwords. Do not commit them, paste them into tickets, or send them
to chat.

PowerShell login flow:

```powershell
$env:CODEX_HOME = "D:\codex_profiles\account_1"
codex.cmd login
codex.cmd login status

$env:CODEX_HOME = "D:\codex_profiles\account_2"
codex.cmd login
codex.cmd login status
```

Device-code login, useful when browser callback is awkward:

```powershell
$env:CODEX_HOME = "D:\codex_profiles\account_1"
codex.cmd login --device-auth

$env:CODEX_HOME = "D:\codex_profiles\account_2"
codex.cmd login --device-auth
```

API-key login is also available, but it changes billing/data-handling to the
API organization path. The current MVP goal is local Codex CLI login rather than
direct OpenAI SDK/API-key usage, so ChatGPT login should be the default unless
there is a specific automation reason.

```powershell
$env:CODEX_HOME = "D:\codex_profiles\account_1"
$env:OPENAI_API_KEY | codex.cmd login --with-api-key
```

## Agent/account Assignment

Introduce explicit account and agent specs.

Example future config:

```json
{
  "accounts": [
    {
      "id": "account_1",
      "codex_home": "D:/codex_profiles/account_1",
      "max_concurrent_agents": 3
    },
    {
      "id": "account_2",
      "codex_home": "D:/codex_profiles/account_2",
      "max_concurrent_agents": 3
    }
  ],
  "agents": [
    {
      "id": "planner_a",
      "role": "product_planner",
      "account_id": "account_1",
      "model": "gpt-5.4",
      "reasoning_effort": "high"
    },
    {
      "id": "planner_b",
      "role": "technical_architect",
      "account_id": "account_1",
      "model": "gpt-5.4",
      "reasoning_effort": "high"
    },
    {
      "id": "code_1",
      "role": "developer",
      "account_id": "account_1",
      "model": "gpt-5.4",
      "reasoning_effort": "medium"
    },
    {
      "id": "code_2",
      "role": "developer",
      "account_id": "account_2",
      "model": "gpt-5.4",
      "reasoning_effort": "medium"
    },
    {
      "id": "qa_1",
      "role": "mechanical_qa",
      "account_id": "account_2",
      "model": "gpt-5.4-mini",
      "reasoning_effort": "medium"
    },
    {
      "id": "qa_2",
      "role": "plan_reviewer",
      "account_id": "account_2",
      "model": "gpt-5.4",
      "reasoning_effort": "high"
    }
  ]
}
```

The runner should resolve this to:

```text
agent_id -> account_id -> CODEX_HOME
agent_id -> model -> codex exec --model <model>
agent_id -> reasoning_effort -> codex exec -c model_reasoning_effort="<value>"
```

Session IDs remain per agent:

```json
{
  "agent_sessions": {
    "code_1": {
      "session_id": "...",
      "account_id": "account_1",
      "codex_home": "D:/codex_profiles/account_1",
      "model": "gpt-5.4",
      "reasoning_effort": "medium",
      "last_step": "implement_task_group"
    }
  }
}
```

## Contract Bundle

Planner/architect output should become a structured bundle under:

```text
runs/<run_id>/contract/
  requirements.md
  architecture.md
  api_contract.md
  data_model.md
  task_manifest.json
  file_ownership.md
  acceptance_tests.md
  integration_plan.md
```

For HTTP services, `api_contract.md` should be replaced or supplemented by
`openapi.yaml`. For event/message-based apps, use `asyncapi.yaml` later.

The contract is the approval boundary. Code agents should not start until the
requester approves this bundle.

## Task Manifest Schema

Minimum useful shape:

```json
{
  "version": 1,
  "tasks": [
    {
      "id": "T1",
      "title": "CSV upload and parsing",
      "summary": "Implement upload, encoding handling, and preview extraction.",
      "assigned_role": "developer",
      "dependencies": [],
      "owned_paths": [
        "src/csv_loader.py",
        "tests/test_csv_loader.py"
      ],
      "allowed_shared_paths": [
        "src/app.py",
        "README.md"
      ],
      "forbidden_paths": [
        "contract/",
        "runs/"
      ],
      "interfaces": [
        "load_csv(path: Path) -> CsvPreview"
      ],
      "acceptance_criteria": [
        "Handles UTF-8 and CP949 CSV files.",
        "Returns row count and column names.",
        "Includes unit tests for empty and malformed CSV files."
      ]
    }
  ]
}
```

## Run Directory Layout

Target layout:

```text
runs/<run_id>/
  state.json
  events.jsonl
  transcript.md
  contract/
  scaffold_app/
  agent_workspaces/
    code_1/
    code_2/
    code_3/
  agent_outputs/
    code_1_summary.md
    code_1_patch.diff
    code_2_summary.md
    code_2_patch.diff
  integration/
    merged_app/
    conflict_report.md
    integration_report.md
  generated_app/
  qa/
    mechanical_report.md
    plan_review.md
  logs/
```

`generated_app/` should only represent the final merged output. Parallel code
agents should write to `agent_workspaces/<agent_id>/`.

## Implementation Sequence

### Phase 3A: Agent Registry and Account Pool

- Add `AgentSpec` and `AccountSpec` dataclasses.
- Load a JSON config file path from `AGENT_ROSTER_PATH`.
- Keep current env vars as backward-compatible defaults.
- Store selected account, model, reasoning, and prompt override in `state.json`.
- Extend `codex_runner.py` to accept:
  - `model`
  - `reasoning_effort`
  - extra config overrides
  - `account_id`
- Log the effective command without exposing credentials.

### Phase 3B: Contract Planner

- Replace the current final-plan-only artifact with a contract bundle.
- Planner A drafts product requirements and feature groups.
- Planner B drafts architecture, API/module contracts, data model, task split,
  and acceptance criteria.
- Planner A or a new Architect Agent reconciles both into final contract files.
- Discord approval references the contract bundle, not a single final plan.

### Phase 3C: Scaffold Agent

- Add a scaffold step after contract approval.
- Scaffold agent creates:
  - project structure
  - route/module stubs
  - shared dataclasses/types
  - dependency file
  - test skeletons
  - README run command
- Scaffold agent must not implement feature-specific logic beyond minimal
  placeholders.

### Phase 3D: Parallel Code Agents

- Copy `scaffold_app/` into one workspace per code agent.
- Assign task groups by dependency and file ownership:
  - independent tasks run in parallel
  - dependent tasks wait for prerequisites
  - same owned file cannot be assigned to two agents in the same batch
- Run developer agents with `asyncio.gather`, bounded by account concurrency.
- Each code agent writes only inside its workspace and returns:
  - summary
  - files changed
  - tests added
  - unresolved questions
  - patch/diff against scaffold

### Phase 3E: Integrator

- Integrator merges code-agent patches into `integration/merged_app`.
- Detect overlapping path changes before applying patches.
- If conflicts exist, ask Integrator Agent to resolve with the contract and
  code-agent summaries.
- Run mechanical QA after each merge batch if cheap enough.
- Copy the final merged result to `generated_app/`.

### Phase 3F: QA Split

- Mechanical QA:
  - Python syntax
  - executable target detection
  - browser launch and screenshots for `index.html` and Streamlit apps
  - generic keyboard probe for browser apps: arrows, Space, and R
  - browser console and page error capture
  - import check
  - required files
  - requirements file validation
  - CLI `--help` smoke test when available
  - opt-in `.bat`/`.cmd` execution for trusted local launchers
  - framework-specific smoke tests where practical
- Plan Review QA:
  - compare contract acceptance criteria to implementation
  - use Codex-backed QA Agent sessions assigned through `QA_AGENT_CODEX_HOMES`
  - attach executable QA screenshots through Codex CLI `--image`
  - flag missing or extra behavior
  - emit suspected owners and affected paths for targeted fixes
  - request the owning Code Agent or Integrator revision before completion

### Phase 3G: Discord Controls

- `/dev` remains the start command.
- Add visible status for:
  - contract planning
  - awaiting contract approval
  - scaffold
  - code batch progress
  - integration
  - QA
- Add commands:
  - `/status run_id`
  - `/runs`
  - `/cancel run_id`
- Discord should show account labels such as `account_1`, never secrets or
  auth paths unless explicitly configured to do so.
- After mechanical QA, Discord posts screenshots and the QA report, then shows
  result approval controls:
  - approve result
  - request fixes
  - cancel

### Phase 4: Web Dashboard

- Treat Discord as a notification and mobile-control adapter.
- Dashboard becomes the primary control plane for:
  - agent count per stage
  - account pool and concurrency limits
  - model/reasoning selection
  - prompt override editing
  - contract artifact review
  - task assignment editing
  - live run graph
  - logs and QA reports
  - approval history

## Implemented First Code Milestone

The first vertical slice is now implemented in the Discord workflow:

- `codex_runner.py` supports model and reasoning effort options.
- Architect Agent creates the contract bundle.
- Scaffold Agent creates `scaffold_app`.
- Code Agents receive task groups from `task_manifest.json`.
- Each Code Agent works in `agent_workspaces/<agent_id>/`.
- Code Agents run concurrently with `asyncio.gather`.
- Integrator Agent merges into `integration/merged_app`.
- The merged app is copied to `generated_app` before QA.
- Mechanical QA now combines Python syntax checks with executable probes.
- Static HTML and Streamlit apps can be opened through Playwright, screenshotted,
  and tested with a generic keyboard probe.
- Codex-backed QA Agent reviews the contract, mechanical QA report, generated
  app listing, and screenshots after each QA cycle.
- QA failures are routed by suspected owner and affected paths. The owning
  `code_N` session resumes for owned-path fixes; Integrator handles shared,
  cross-agent, or unknown failures.
- Discord now supports a post-QA approval/fix loop before marking a run
  completed.

Remaining work is to replace the current env-var based agent assignment with a
full `AgentSpec`/`AccountSpec` registry and add richer app-specific QA agents.

## Open Risks

- Multiple logged-in ChatGPT accounts may be awkward if the OS credential store
  ignores `CODEX_HOME`. Use `cli_auth_credentials_store = "file"` for each
  profile to avoid that ambiguity.
- Parallel writes can create low-quality merges if task boundaries are weak.
  The contract bundle and file ownership checks are mandatory, not optional.
- Token usage will increase with every parallel agent. Account pools should have
  configurable concurrency limits.
- Generated apps without clear module boundaries will not parallelize well.
  For small apps, the orchestrator should fall back to one developer plus one
  reviewer.
- Windows support is workable here through `codex.cmd`, but PowerShell execution
  policy blocks `codex.ps1`; the runner should continue resolving `.cmd` first
  on Windows.
