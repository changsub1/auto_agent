# Language-Neutral Orchestration Plan

## Goal

Remove Python-first assumptions from the multi-agent orchestration layer so
Codex CLI, Claude CLI, and future coding tools can choose the right language,
framework, file layout, and run strategy for each user request.

The orchestrator should coordinate work, preserve safety, record artifacts, and
verify results. It should not narrow capable coding agents into Python apps
unless the user request, existing project, or accepted plan calls for Python.

## Current Implementation Status

First implementation pass added:

- Agent prompts no longer prefer Python by default.
- Scaffold and Integrator prompts no longer require `app.py` or
  `requirements.txt`.
- `docs/CODEX_APP_MANIFEST.md` is the repo-level manifest contract. Agent
  prompts now use short references to that document instead of embedding a long
  schema in every prompt.
- Fallback contract generation is stack-neutral and asks for
  `codex_app_manifest.json`.
- Legacy CLI QA now reports "mechanical QA" and combines Python syntax checks
  with executable QA.
- `executable_qa.py` checks `codex_app_manifest.json` before framework
  heuristics, validates command arrays, enforces generated-app working
  directory boundaries, runs allowlisted commands with `shell=False`, and stores
  stdout/stderr evidence.

## Audit Findings That Drove This Pass

Before this implementation pass, the system contained Python-first defaults in
prompts, fallback contracts, and QA.

Examples:

- `agents.py` tells Planner A to "Prefer Python".
- `agents.py` asks final planning to stay within a "Python MVP".
- `agents.py` tells Architect to "Prefer Python".
- `agents.py` asks Scaffold to create a "runnable Python project skeleton".
- `agents.py` asks Integrator to produce a "final runnable Python app".
- Legacy `DeveloperAgent` asks for `app.py`, `requirements.txt`, and
  `README.md`.
- `parallel_workflow.py` fallback contract creates Python-oriented files and
  task ownership.
- `qa.py` is centered on `python -m py_compile`.
- `executable_qa.py` detected `index.html`, `app.py`, Streamlit, Python CLI,
  and Windows launchers, but did not prefer a language-neutral manifest.

These are useful for the original MVP, but they are now a bottleneck.

## Principle

Use language-neutral coordination and language-specific adapters.

Bad default:

```text
Create a runnable Python app with app.py and requirements.txt.
```

Better default:

```text
Choose the simplest local implementation approach that fits the user request.
Explain the chosen runtime, entrypoint, setup command, run command, and test or
smoke-check command in codex_app_manifest.json.
```

## Prompt Changes

### Planner

Remove:

- "Prefer Python."
- "small executable Python MVP"
- framework hints such as Streamlit unless explicitly requested.

Replace with:

- Choose the simplest local app shape that fits the request.
- Prefer standard project conventions for the chosen language/framework.
- If the user does not specify a stack, pick one and state why.
- Keep the scope small and runnable locally.
- Include expected runtime, entrypoint, and verification approach.

### Architect

Remove:

- "Prefer Python."
- Python-specific fallback architecture.

Replace with:

- Select or preserve the implementation stack from the approved plan.
- Define task boundaries using paths that match the chosen stack.
- Require `codex_app_manifest.json`.
- Keep command examples as JSON arrays, not shell strings.

### Scaffold

Remove:

- "Create a runnable Python project skeleton."
- "Include app.py, requirements.txt..."
- "Keep imports valid so Python syntax QA can run..."

Replace with:

- Create the minimal project skeleton for the chosen stack.
- Include conventional dependency/config files only when needed.
- Include `README.md`.
- Include or draft `codex_app_manifest.json`.
- Keep the skeleton runnable or clearly mark placeholder commands.

### Code Agent

Keep:

- owned paths,
- forbidden paths,
- manifest requirement,
- local runnable constraint.

Add:

- Follow the stack and conventions declared by the plan/contract unless the
  user feedback changes them.
- Do not change the chosen stack without explaining the reason in the summary.

### Integrator

Remove:

- "final runnable Python app"
- `app.py` and `requirements.txt` default.

Replace with:

- Ensure `integration/merged_app` is the final runnable local project.
- Preserve the chosen stack's conventional entrypoints and dependency files.
- Ensure `codex_app_manifest.json` is present and accurate.

### Legacy DeveloperAgent

Best option:

- Retire it from active routes.
- Route the original CLI path through `CodeAgent(code_1)` with a whole-project
  assignment.

Interim option:

- Rewrite its prompt to be language-neutral.
- Rename docs and comments so it is not treated as the preferred path.

## Manifest-First QA

`codex_app_manifest.json` should become the primary execution contract.

The canonical repo documentation is `docs/CODEX_APP_MANIFEST.md`. Prompts
should reference that file briefly instead of repeating the whole schema.

Proposed minimum schema:

```json
{
  "version": 1,
  "app_type": "web | cli | desktop | library | game | unknown",
  "runtime": "python | node | bun | go | rust | java | dotnet | static | other",
  "working_directory": ".",
  "setup": [
    {
      "name": "install dependencies",
      "command": ["npm", "install"],
      "timeout_seconds": 120
    }
  ],
  "checks": [
    {
      "name": "unit tests",
      "command": ["npm", "test"],
      "timeout_seconds": 120
    }
  ],
  "run": {
    "command": ["npm", "run", "dev", "--", "--host", "127.0.0.1"],
    "timeout_seconds": 120,
    "ready_url": "http://127.0.0.1:5173",
    "stop": "process_tree"
  },
  "browser_checks": [
    {
      "url": "http://127.0.0.1:5173",
      "expect_visible_text": [],
      "interactions": []
    }
  ]
}
```

Rules:

- Commands must be arrays.
- No shell strings.
- Working directory must stay inside the generated app directory.
- Timeouts are required.
- Network access should be off by default unless explicitly allowed.
- Environment variables must be explicit and should not include secrets.

## How to Execute Many Languages Safely

It is not practical to hardcode every language, framework, and app shape.
However, it is also not safe to let an LLM freely execute arbitrary commands.

Use a three-layer strategy.

### Layer 1: Manifest Runner

If `codex_app_manifest.json` exists:

1. Validate schema.
2. Validate command arrays.
3. Validate allowed executables.
4. Validate working directory boundaries.
5. Run setup/check/run/browser probes with timeouts.
6. Store stdout, stderr, screenshots, and process metadata.

This should handle most successful agent outputs.

### Layer 2: Framework Adapters

If the manifest is missing or invalid, use conservative detection:

- static web: `index.html`
- Node/Vite/React: `package.json` scripts
- Python: `.py`, `pyproject.toml`, `requirements.txt`
- Go: `go.mod`
- Rust: `Cargo.toml`
- .NET: `.csproj` or `.sln`
- Java/Kotlin: `pom.xml`, `build.gradle`, `gradlew`

Adapters should only run safe, known commands with `shell=False`.

### Layer 3: QA Execution Plan Agent

If adapters cannot infer a safe command, ask a QA planning agent to produce a
machine-readable execution plan, not to execute it directly.

The prompt should ask for JSON only:

```text
Inspect the generated app listing and README. Propose a safe local execution
plan as JSON. Commands must be arrays. Do not include destructive commands. Do
not request secrets. Do not use shell-specific syntax. If there is no safe
command, return status "skip" with a reason.
```

Then the Python harness validates and executes the proposed plan.

## Why Not Let the QA Agent Execute Directly?

Letting Codex CLI or Claude CLI run the generated app directly from a broad
prompt sounds simple, but it creates avoidable risk and weak evidence.

Problems:

- The generated app or README can contain prompt-injection-like instructions.
- The QA agent may choose unsafe commands.
- The run may depend on undeclared local state.
- Logs, screenshots, ports, and process cleanup become inconsistent.
- Cancellation is harder because the orchestrator does not own every child
  process.
- Re-running the same QA becomes nondeterministic.
- It blurs responsibility between "decide what to run" and "execute safely".

Better model:

- Let the QA agent reason about what should be run.
- Let the harness decide what is allowed.
- Let the harness execute and capture evidence.
- Let the QA agent review the evidence and produce PASS/FAIL findings.

This keeps powerful coding agents useful without giving them uncontrolled local
execution authority.

## Browser and Visual QA

For web/game/desktop-like outputs:

1. The manifest starts the server or opens a static file.
2. The harness uses Playwright to load the target.
3. The harness captures:
   - initial screenshot,
   - console logs,
   - page errors,
   - basic blank-screen checks,
   - optional interactions from the manifest or QA execution plan.
4. The QA agent reviews screenshots and logs after execution.

Optional future improvement:

- Let a QA agent propose browser interactions as JSON.
- Validate selectors/actions.
- Execute them through Playwright.
- Feed screenshots/logs back to the QA agent.

## Refactor Sequence

1. Update prompt text in `agents.py` to remove Python-first defaults.
2. Update `parallel_workflow.py` fallback contract to be stack-neutral.
3. Add `docs/CODEX_APP_MANIFEST.md` as the manifest contract.
4. Keep prompt references to the manifest short.
5. Rename "Python syntax QA" in docs/status to "mechanical QA".
6. Make `codex_app_manifest.json` the first executable QA path.
7. Add a manifest validator and runner.
8. Keep Python syntax checks as one adapter, not the default QA identity.
9. Add conservative adapters for Node/static web later as a fallback.
10. Add QA execution plan agent only after manifest runner safety is in place.
11. Retire or rewrite `DeveloperAgent`.
12. Update README and project status.

## Acceptance Criteria

- A user request for React, Node, Go, Rust, static HTML, or Python is not pushed
  back toward Python by the planner or architect.
- Generated task manifests can own stack-appropriate paths.
- Scaffold and integrator prompts do not require `app.py`.
- Mechanical QA first checks `codex_app_manifest.json`.
- Python syntax QA still works for Python projects.
- Missing manifest results in safe adapter fallback or a clear SKIP reason.
- No generated app command is executed with `shell=True`.
