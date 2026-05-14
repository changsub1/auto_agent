# Stage7 QA Workspace Plan

## Goal

Stage7의 최종 방향은 고정된 머신 QA 시나리오에 결과물을 억지로 맞추는 것이 아니라, QA Agent가 전용 작업공간에서 산출물을 분석하고 필요한 evidence 도구를 직접 선택해 검증하는 구조다.

최종 흐름:

```text
Code Agent
-> QA Workspace 생성
-> generated_app을 qa_workspace/app으로 복사
-> qa_tools를 qa_workspace/qa_tools로 복사
-> QA Agent가 command/file/browser probe 중 필요한 도구 선택
-> evidence/verdict.json, qa_findings.md, command_log.jsonl 작성
-> hard policy 검증
-> 사용자 QA 승인
```

## Rationale

이전 Stage7A 구조는 다음 흐름이었다.

```text
LLM QA scenario plan
-> Mechanical QA scenario run
-> same-session LLM QA verdict
```

이 방식은 웹 페이지의 간단한 상호작용에는 유용하지만, 결과물이 HTML이 아닐 수도 있고, desktop GUI나 CLI, Python 앱일 수도 있다는 문제가 있었다. 또한 제한된 머신 QA가 약간만 의도와 다르게 조작해도 LLM QA가 실제 결함과 harness 결함을 구분하기 어려웠다.

Stage7D에서는 QA Agent가 Codex CLI처럼 직접 판단하되, 안전한 도구와 전용 workspace만 제공한다. 즉, “머신 QA가 판단”하는 구조가 아니라 “QA Agent가 판단하고, 도구는 evidence 수집만 담당”하는 구조다.

## QA Workspace Layout

```text
runs/<run_id>/qa/attempt_00/qa_workspace/
  app/                         # completed generated_app copy
  context/
    user_request.md
    contract_bundle.md
    generated_app_listing.txt
    mechanical_qa_report.md    # Stage7D에서는 agentic QA baseline report
  qa_tools/
    command_probe.py
    file_probe.py
    browser_probe.py
  evidence/
    command_log.jsonl
    qa_findings.md
    verdict.json
  screenshots/
  scratch/
```

`generated_app/`는 최종 산출물 원본이며 QA가 수정하지 않는다. QA Agent는 `qa_workspace/app` 복사본을 대상으로만 검사하고, 임시 실험은 `scratch/`에 둔다.

## QA Tools

### command_probe.py

로컬 명령을 shell 없이 실행하고 UTF-8 stdout/stderr, result JSON, command log를 남긴다.

예:

```powershell
python qa_tools/command_probe.py --name self-test --cwd app -- python calculator.py --self-test
```

주 용도:

- unit test
- `--self-test`
- import check
- build/check/smoke command

### file_probe.py

파일 존재와 텍스트 포함 여부를 검사하고 preview와 result JSON을 남긴다.

예:

```powershell
python qa_tools/file_probe.py --name readme --path app/README.md --contains "Usage"
```

### browser_probe.py

로컬 `file://`, `localhost`, `127.0.0.1` 대상만 열고 Playwright page screenshot, console log, result JSON을 남긴다. 데스크톱 화면 전체를 캡처하지 않는다.

예:

```powershell
python qa_tools/browser_probe.py --name initial --entry app/index.html --expect-text "Products"
```

## Safety Policy

- QA Agent는 현재 QA workspace 밖에 쓰지 않는다.
- `pyautogui`, OS-wide screenshot, 전역 마우스/키보드 조작, Alt+Tab, Win-key shortcut, 데스크톱 window control은 기본 금지다.
- desktop GUI는 `--self-test`, unit test, import check, CLI smoke check를 우선한다.
- browser screenshot은 generated app page에 한정한다.
- 외부 네트워크, secret, 사용자 PC의 다른 폴더 접근은 사용하지 않는다.

## Hard PASS Policy

QA Agent가 `PASS`를 출력해도 Orchestra가 다음 조건을 강제한다.

- `evidence/verdict.json` 누락 또는 invalid JSON이면 FAIL
- `evidence/qa_findings.md` 누락이면 PASS 금지
- `evidence/command_log.jsonl` 누락 또는 실제 probe 기록 없음이면 PASS 금지
- visual/browser/game/dashboard 앱은 screenshot evidence 없으면 PASS 금지

Verdict schema:

```json
{
  "status": "PASS | FAIL | INCONCLUSIVE | UNSUPPORTED",
  "summary": "one paragraph",
  "findings": ["concrete issue or none"],
  "evidence": ["relative evidence path or observation"],
  "affected_paths": ["app-relative path or none"],
  "suspected_owners": ["code_1", "code_2", "integrator", "unknown", "none"]
}
```

## Implemented

- Stage7B-1: UTF-8 subprocess/env hardening
- Stage7B-2: approval action을 타임라인 결과 카드 안으로 이동
- Stage7B-3: QA evidence와 screenshot을 타임라인에서 preview
- Stage7B-4: 우측 패널을 기본적으로 선택 이벤트/파일 preview 중심으로 단순화
- Stage7C: QA Workspace Agent 도입
- Stage7D:
  - balanced/manual의 LLM QA 경로에서 scenario plan -> mechanical QA 선행 제거
  - `qa_tools/` 복사
  - QA workspace에 `.cmd` launcher를 생성해 Orchestra의 Python/.venv 환경으로 QA 도구 실행
  - QA Agent prompt에 안전한 도구 사용 규칙 추가
  - PASS hard policy에 실제 probe 기록 요구 추가
  - `command_probe.py`, `file_probe.py`, `browser_probe.py` 추가
  - `browser_probe.py`에 action file 기반 page-scoped click/press/drag/wait/screenshot 지원 추가

## Remaining Work

- 실제 balanced/manual run으로 QA Workspace Agent가 웹, CLI, desktop GUI self-test를 잘 구분하는지 시각 검증
- 타임라인에서 `qa_tools` 결과를 더 읽기 쉬운 카드 형태로 요약
- desktop GUI self-test convention을 Code Agent prompt에 더 명확히 반영
- 필요 시 `qa_tools`에 서버 실행 helper, image comparison helper, canvas pixel probe 추가
- 장기적으로 Windows Sandbox 또는 Docker 기반 강한 격리 검토

## Submission Narrative

이 단계는 프롬프트 엔지니어링과 harness engineering을 함께 보여준다.

- Prompt engineering: QA Agent의 System Prompt와 Skill/Guideline을 GUI에서 수정할 수 있다.
- Harness engineering: QA Agent에게 무제한 OS 조작을 주지 않고, workspace와 evidence 도구만 제공한다.
- AI reliability: PASS는 LLM 판단만으로 허용하지 않고, verdict, findings, command log, screenshot 같은 증거를 요구한다.
- AI ethics: QA guideline preset을 바꾸면 같은 산출물도 접근성, 편향, 안전성 기준으로 다르게 평가할 수 있다.
