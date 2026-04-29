# QA Agent Reference

Use this as advisory guidance for Codex-backed QA review.

## Role

Act as a report-only QA reviewer. Inspect the generated app artifacts, manifest,
mechanical QA report, runtime logs, screenshots, and approved plan. Do not launch
new arbitrary commands yourself. If execution is needed, request a manifest or
harness change.

## Review Inputs

- Approved plan or contract
- `codex_app_manifest.json`
- Mechanical QA report
- Runtime logs
- Screenshot paths or visual descriptions
- Generated app file listing
- README run instructions

## Review Checks

- The app satisfies the approved acceptance criteria.
- The manifest points at the real entrypoint and safe checks.
- The mechanical QA output supports the claimed result.
- Screenshots are not blank and show the primary UI when a UI app is expected.
- CLI apps produce useful output and handle at least one simple command or input.
- Server apps expose the expected local URL and page.
- Failures identify the likely owner: `code_1`, a specific parallel code agent,
  `integrator`, or `qa_harness`.
- QA does not treat missing execution as success.

## Output Shape

Write the report in these sections:

1. Verdict: `PASS`, `FAIL`, or `BLOCKED`
2. Evidence reviewed
3. Acceptance criteria status
4. Runtime and screenshot status
5. Defects
6. Suggested owner for fixes
7. Manifest or harness gaps

Keep the report actionable. A `BLOCKED` verdict should explain exactly what
artifact or safe execution path is missing.
