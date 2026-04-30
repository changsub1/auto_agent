# Codex App Manifest

Generated runnable apps must include `codex_app_manifest.json` in the app root.
The local QA harness reads this file, validates it, runs safe commands, and
stores logs, screenshots, and reports.

The manifest is an execution contract. It is not a prompt.

## Required Rules

- Use valid JSON.
- Put the file at `generated_app/codex_app_manifest.json` or the final app root.
- Commands must be JSON arrays of strings.
- Do not use shell strings.
- Do not use shell control syntax such as `&&`, `||`, `;`, `|`, redirects,
  command substitution, or newlines inside command arguments.
- Keep `working_directory` inside the app root.
- Use local commands only.
- Do not require secrets.
- Include timeouts for commands that may run longer than a few seconds.
- Keep setup/check/run commands minimal and reproducible.

## Minimal Shape

```json
{
  "version": 1,
  "app_type": "web",
  "runtime": "node",
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
      "name": "build",
      "command": ["npm", "run", "build"],
      "timeout_seconds": 120
    }
  ],
  "run": {
    "command": ["npm", "run", "dev", "--", "--host", "127.0.0.1"],
    "ready_url": "http://127.0.0.1:5173",
    "timeout_seconds": 120
  }
}
```

## Fields

- `version`: manifest schema version. Use `1`.
- `app_type`: short app category, such as `web`, `cli`, `server`, `desktop`,
  `game`, `library`, or `unknown`.
- `runtime`: main runtime or stack, such as `node`, `python`, `go`, `rust`,
  `static`, `java`, `dotnet`, `bun`, or `other`.
- `working_directory`: relative path from the app root. Use `.` unless the
  runnable project lives in a subdirectory.
- `setup`: optional list of setup commands.
- `checks`: optional list of build, test, lint, typecheck, or validation
  commands.
- `smoke`: optional list of quick smoke commands.
- `run`: optional command for launching a server or app.
- `run.ready_url`: local URL the harness should wait for and inspect. Use
  `http://127.0.0.1:<port>`, `http://localhost:<port>`, or a `file://` URL.

## Command Step Shape

```json
{
  "name": "unit tests",
  "command": ["python", "-m", "pytest"],
  "timeout_seconds": 120
}
```

Use the most conventional command for the chosen stack. Examples:

- Python check: `["python", "-m", "py_compile", "app.py"]`
- Python tests: `["python", "-m", "pytest"]`
- Node install: `["npm", "install"]`
- Node build: `["npm", "run", "build"]`
- Node dev server: `["npm", "run", "dev", "--", "--host", "127.0.0.1"]`
- Static web smoke: use `app_type: "web"`, `runtime: "static"`, and a `run`
  command only when a server is needed.
- Go tests: `["go", "test", "./..."]`
- Rust tests: `["cargo", "test"]`

## Web App Guidance

For a web app, prefer:

1. setup command if dependencies are required,
2. build or test command,
3. run command with a stable local host/port,
4. `ready_url` for browser QA.

Use `127.0.0.1` instead of a public host.

## CLI App Guidance

For a CLI app, include at least one smoke command:

```json
{
  "version": 1,
  "app_type": "cli",
  "runtime": "python",
  "smoke": [
    {
      "name": "help command",
      "command": ["python", "app.py", "--help"],
      "timeout_seconds": 30
    }
  ]
}
```

## When Unsure

If there is no safe automatic execution command, still create the manifest and
document that fact with no commands. The harness will mark executable QA as
`SKIP` rather than inventing unsafe commands.
