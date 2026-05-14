# QA Tools

These tools are copied into each QA workspace as `qa_tools/`. They are intended
for the QA Agent to collect evidence without using global desktop automation.

Use them from the QA workspace root:

```powershell
qa_tools\file_probe.cmd --name readme --path app/README.md --contains "Usage"
qa_tools\command_probe.cmd --name self-test --cwd app -- python calculator.py --self-test
qa_tools\browser_probe.cmd --name initial --entry app/index.html --expect-text "Products"
```

Evidence is written under:

- `evidence/command_log.jsonl`
- `evidence/commands/`
- `evidence/browser/`
- `evidence/files/`
- `screenshots/`

Rules:

- Do not use OS-wide screenshots, desktop mouse/keyboard automation, or
  pyautogui-style global input.
- Browser screenshots must be of the generated app page only.
- On Windows, prefer the `.cmd` launchers. They use the same Python environment
  as Orchestra, so Playwright and other installed QA dependencies resolve
  consistently.
- Desktop GUI apps should be tested through `--self-test`, unit tests, imports,
  or CLI smoke checks unless a bounded GUI test hook is explicitly provided.

## Browser Actions

For games and other interactive browser apps, create a small action file and
pass it to `browser_probe.cmd`.

```json
{
  "actions": [
    {"action": "screenshot", "name": "before-shot"},
    {
      "action": "drag",
      "selector": "canvas#gameCanvas",
      "from": {"x": 210, "y": 520},
      "to": {"x": 120, "y": 590},
      "steps": 16
    },
    {"action": "wait", "ms": 1200},
    {"action": "screenshot", "name": "after-shot"}
  ]
}
```

```powershell
qa_tools\browser_probe.cmd --name slingshot --entry app/index.html --expect-selector "canvas#gameCanvas" --action-file scratch/slingshot_actions.json
```

Supported actions are `wait`, `screenshot`, `expect_text`, `expect_visible`,
`click`, `press`, `fill`, and `drag`. Drag coordinates are relative to the
selected element, so this can test canvas slingshot interactions without using
global mouse control.
