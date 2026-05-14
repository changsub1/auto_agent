# Orchestra

Orchestra는 로컬 Codex CLI를 여러 에이전트처럼 조합해 기획, 구현, QA, 사용자 승인을 진행하는 데스크톱 개발 보조 앱입니다.

목표는 API 호출마다 비용이 드는 외부 서비스가 아니라, 사용자가 이미 로그인한 Codex CLI 구독 환경을 활용해 개인 PC에서 실행되는 멀티 에이전트 개발 워크플로를 제공하는 것입니다.

## 현재 기능

- Tauri 데스크톱 앱 + localhost FastAPI sidecar
- 실행 모드: `fast`, `balanced`, `parallel`, `manual`
- Planner A/B 기반 기획과 사용자 승인
- Code Agent 기반 구현
- Integrator 기반 병합
- QA Workspace Agent 기반 LLM QA
- QA 결과 승인, 변경 요청, 중지
- Codex 계정, 모델, reasoning effort GUI 설정
- Codex 5시간/주간 사용량 표시
- Manual 모드에서 에이전트 추가, 비활성화, 순서 재배치
- Agent별 System Prompt / Skill / Effective Prompt 편집
- Skill Registry
  - Code Agent 기본값: Karpathy Guidelines
  - 선택 옵션: ciembor agent-rules-books mini/nano
  - gstack 원본은 reference archive로 보관
- Run Monitor
  - 주요 agent output, approval, error 중심 타임라인
  - 승인 버튼을 관련 결과 카드 안에 표시
  - QA evidence, screenshot, report를 타임라인에서 직접 확인
  - 우측 패널은 선택 이벤트와 파일 preview 중심으로 단순화

## QA 구조

제출판 QA는 Stage7D 기준으로 다음 흐름을 사용합니다.

```text
Code Agent 결과물
-> QA Workspace Agent 실행
-> qa_workspace/app에 generated_app 복사
-> qa_workspace/qa_tools에 안전한 검사 도구 복사
-> QA Agent가 command_probe/file_probe/browser_probe 중 필요한 도구 선택
-> Windows에서는 qa_tools\*.cmd launcher로 Orchestra Python/.venv 환경에서 실행
-> evidence 기반 verdict.json 작성
-> 사용자 QA 승인
```

`balanced`와 `manual`에서 QA Agent가 있는 경로는 더 이상 `LLM QA scenario plan -> Mechanical QA scenario run`을 선행하지 않습니다. QA Agent가 전용 작업공간 안에서 직접 검사 전략을 정하고, 제공된 도구로 증거를 수집합니다.

QA Workspace는 매 attempt마다 생성됩니다.

```text
runs/<run_id>/qa/attempt_00/qa_workspace/
  app/                         # generated_app 복사본
  context/                     # 요청, 계약, 파일 목록, QA baseline report
  qa_tools/                    # 안전한 evidence 수집 도구
  evidence/
    command_log.jsonl
    qa_findings.md
    verdict.json
  screenshots/
  scratch/
```

Hard policy:

- `evidence/verdict.json`이 없거나 형식이 잘못되면 FAIL
- `evidence/qa_findings.md`가 없으면 PASS 금지
- `evidence/command_log.jsonl`에 실제 probe 기록이 없으면 PASS 금지
- visual/browser/game/dashboard 앱은 screenshot evidence 없이 PASS 금지
- desktop GUI는 기본적으로 마우스/키보드 자동 조작을 하지 않고 `--self-test`, unit test, import check 중심으로 검토
- browser/canvas 게임은 OS 전체 입력이 아니라 Playwright page-scoped click/drag/wait/screenshot으로 상호작용 검증

## 요구 사항

- Windows 권장
- Python 3.10 이상
- Node.js / npm
- Rust / Cargo
- Codex CLI 설치 및 로그인
- Playwright Chromium

## 최초 설치

PowerShell 기준:

```powershell
cd D:\curs\auto\multi_codex_dev_mvp
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
```

프론트엔드:

```powershell
cd D:\curs\auto\multi_codex_dev_mvp\ux
npm install
```

Codex CLI 확인:

```powershell
codex --version
codex login status
```

## 데스크톱 앱 실행

Tauri 앱이 FastAPI sidecar를 자동으로 실행합니다.

```powershell
cd D:\curs\auto\multi_codex_dev_mvp\ux
$env:ORCHESTRA_REPO_ROOT="D:\curs\auto\multi_codex_dev_mvp"
$env:ORCHESTRA_PYTHON="D:\curs\auto\multi_codex_dev_mvp\.venv\Scripts\python.exe"
npm run tauri:dev
```

주의: 스크립트 이름은 `tauri:dev`입니다. `npm run tauri dev`가 아닙니다.

## 브라우저 개발 모드

터미널 1:

```powershell
cd D:\curs\auto\multi_codex_dev_mvp
.\.venv\Scripts\python.exe run_local_api.py --host 127.0.0.1 --port 8765
```

터미널 2:

```powershell
cd D:\curs\auto\multi_codex_dev_mvp\ux
npm run dev
```

브라우저:

```text
http://127.0.0.1:5173
```

## 기본 사용법

1. 앱을 실행합니다.
2. 왼쪽에서 실행 모드를 고릅니다.
   - `fast`: 빠른 단일 Code Agent 구현, mechanical QA 중심
   - `balanced`: Planner A/B, Code Agent, QA Workspace Agent
   - `parallel`: 계약/스캐폴드/복수 Code Agent/Integrator/QA
   - `manual`: 사용자가 에이전트와 워크플로 그래프를 직접 구성
3. 계정, 모델, reasoning effort를 선택합니다.
4. 하단 입력창에 만들 앱이나 기능을 설명합니다.
5. `실행 시작`을 누릅니다.
6. Planner 결과 카드에서 기획을 승인하거나 수정 요청합니다.
7. 구현과 QA가 끝나면 QA 카드에서 evidence를 확인하고 최종 승인합니다.

## LLM QA 시연 방법

과제 시연에서는 `fast`보다 `balanced` 또는 `manual`을 권장합니다. `fast`는 빠른 실행을 위해 LLM QA가 생략될 수 있습니다.

성공 run에서 보통 다음 산출물을 확인할 수 있습니다.

```text
runs/<run_id>/qa/attempt_00/qa_workspace/evidence/verdict.json
runs/<run_id>/qa/attempt_00/qa_workspace/evidence/qa_findings.md
runs/<run_id>/qa/attempt_00/qa_workspace/evidence/command_log.jsonl
runs/<run_id>/qa/attempt_00/qa_workspace/screenshots/*.png
runs/<run_id>/qa_report.md
```

Run Monitor에서 QA 이벤트를 펼치면 screenshot, findings, verdict를 바로 확인할 수 있습니다.

## 과제 설명 포인트

이 프로젝트는 수업의 프롬프트 엔지니어링과 AI 윤리 주제를 다음 방식으로 반영합니다.

- Agent별 System Prompt를 GUI에서 확인하고 수정할 수 있습니다.
- Skill / Guideline을 Agent별로 선택하거나 직접 수정할 수 있습니다.
- QA guideline preset을 바꾸면 같은 결과물도 다른 기준으로 평가할 수 있습니다.
- LLM QA는 무제한 실행 권한을 갖지 않고, 제한된 workspace와 evidence 정책 안에서 판단합니다.
- visual/browser 앱은 screenshot evidence 없이 PASS가 되지 않습니다.

## API Key Provider 상태

제출판은 Codex CLI 중심입니다. OpenAI API key 기반 provider는 구조적으로 확장 가능하도록 남겨두었지만, 별도 message history/state 관리와 tool executor adapter가 필요하므로 후순위입니다.

## 테스트

백엔드:

```powershell
cd D:\curs\auto\multi_codex_dev_mvp
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

프론트엔드:

```powershell
cd D:\curs\auto\multi_codex_dev_mvp\ux
npm run build
```

Tauri Rust:

```powershell
cd D:\curs\auto\multi_codex_dev_mvp\ux\src-tauri
cargo check
```
