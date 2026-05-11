# Orchestra: 로컬 CLI 기반 멀티 에이전트 개발 앱

Orchestra는 사용자가 자연어로 앱/기능 개발을 요청하면 여러 LLM 에이전트가
기획, 구현, QA를 나누어 수행하는 로컬 데스크톱 MVP입니다.

핵심 목표는 OpenAI API 비용을 매 요청마다 쓰는 서비스가 아니라, 사용자가
이미 로그인한 Codex CLI 구독 환경을 활용해 개인 PC에서 동작하는 개발 보조
앱을 만드는 것입니다.

## 현재 구현 요약

- Tauri 데스크톱 앱 + localhost FastAPI sidecar
- Codex CLI 기반 Planner, Code Agent, Integrator, QA Agent
- `fast`, `balanced`, `parallel`, `manual` 실행 모드
- Human-in-the-loop 승인 흐름
  - 계획 승인
  - QA 결과 승인
  - 변경 요청
  - 중지
- Codex 계정, 모델, reasoning effort GUI 선택
- Codex 5시간/주간 사용량 GUI 표시
- manual 모드에서 에이전트 추가 및 workflow graph 편집
- mechanical QA
  - syntax check
  - generated app 실행 probe
  - Playwright screenshot
  - console/page error 수집
- LLM QA Agent
  - mechanical QA report
  - screenshot
  - contract/plan
  - generated app listing
  - 사용자 지정 QA guideline/system prompt
  를 보고 PASS/FAIL 판단
- QA Prompt / Skill Editor
  - Default QA
  - Ethics & Bias QA
  - Accessibility QA
  - Strict Safety QA

## 실행 전 준비물

### 필수

- Windows 10/11
- Python 3.10 이상
- Node.js / npm
- Codex CLI 설치 및 로그인
- Git

### 데스크톱 앱 개발 실행에 필요

- Rust / Cargo
- Tauri CLI는 `ux/package.json`의 devDependency로 설치됩니다.

### 권장

- repo 내부 `.venv` 사용
- Playwright Chromium 설치

## 처음 설치

PowerShell에서 저장소 루트로 이동합니다.

```powershell
cd D:\curs\auto\multi_codex_dev_mvp
```

Python 의존성을 설치합니다.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Playwright 브라우저를 설치합니다. 브라우저 앱을 QA할 때 screenshot과
실행 probe에 필요합니다.

```powershell
.\.venv\Scripts\python.exe -m playwright install chromium
```

프론트엔드 의존성을 설치합니다.

```powershell
cd D:\curs\auto\multi_codex_dev_mvp\ux
npm install
```

Codex CLI 로그인을 확인합니다.

```powershell
codex login status
codex --version
```

## 데스크톱 앱 실행

가장 권장하는 실행 방식입니다. Tauri 앱이 FastAPI sidecar를 자동으로
띄웁니다.

```powershell
cd D:\curs\auto\multi_codex_dev_mvp\ux
$env:ORCHESTRA_REPO_ROOT="D:\curs\auto\multi_codex_dev_mvp"
$env:ORCHESTRA_PYTHON="D:\curs\auto\multi_codex_dev_mvp\.venv\Scripts\python.exe"
npm run tauri:dev
```

주의: `npm run tauri dev`가 아니라 `npm run tauri:dev`입니다.

## 브라우저 개발 모드 실행

Tauri 없이 웹 UI와 FastAPI를 따로 띄워 확인할 수 있습니다.

터미널 1: FastAPI 실행

```powershell
cd D:\curs\auto\multi_codex_dev_mvp
.\.venv\Scripts\python.exe run_local_api.py --host 127.0.0.1 --port 8765
```

터미널 2: React 실행

```powershell
cd D:\curs\auto\multi_codex_dev_mvp\ux
npm run dev
```

브라우저에서 다음 주소로 접속합니다.

```text
http://127.0.0.1:5173
```

## 기본 사용법

1. 앱을 실행합니다.
2. 왼쪽에서 실행 모드를 고릅니다.
   - `fast`: 빠른 단일 구현, mechanical QA 중심
   - `balanced`: Planner A/B + Code Agent + mechanical QA + LLM QA 가능
   - `parallel`: 계약/스캐폴드/병렬 Code Agent/Integrator/QA
   - `manual`: 에이전트와 workflow graph를 직접 구성
3. Codex account/model/reasoning을 선택합니다.
4. 아래 입력창에 만들 앱이나 기능을 설명합니다.
5. `실행 시작`을 누릅니다.
6. Planner 결과를 확인하고 승인합니다.
7. 구현과 QA가 끝나면 QA 결과를 승인하거나 수정 요청합니다.

## LLM QA Agent 시연 방법

제출/발표 시에는 `fast`가 아니라 `balanced` 또는 `manual`을 권장합니다.
`fast`는 기본적으로 mechanical QA만 돌 수 있습니다.

앱 왼쪽 실행 모드 영역에 다음처럼 표시됩니다.

```text
QA route: LLM QA Agent enabled
```

또는

```text
QA route: mechanical QA only
```

LLM QA Agent가 실제로 돈 run은 `qa_report.md`에 다음 섹션이 생깁니다.

```text
## Codex QA Agent Reviews
```

QA Agent는 직접 코드를 수정하지 않습니다. 먼저 mechanical QA가 앱을 실행하고
스크린샷, 콘솔 로그, syntax check, 실행 probe 결과를 만듭니다. 그 다음 LLM
QA Agent가 그 증거와 plan/contract를 검토해 `QA_STATUS: PASS` 또는 `FAIL`을
판단합니다.

## QA Prompt / Skill Editor

각 agent 카드의 `skill` 행 또는 설정 아이콘을 클릭하면 오른쪽 큰 패널이
열립니다.

탭은 다음과 같습니다.

- `Skill / Guideline`
- `System Prompt`
- `Effective Prompt Preview`

QA Agent에는 다음 preset이 있습니다.

- `Default QA`
- `Ethics & Bias QA`
- `Accessibility QA`
- `Strict Safety QA`

저장한 prompt는 로컬 파일 `local_prompt_overrides.json`에 저장됩니다. 이 파일은
Git에 올라가지 않습니다.

run 시작 시 사용된 prompt는 다음 위치에 artifact로 저장됩니다.

```text
runs/<run_id>/prompts/
  qa_1_skill.md
  qa_1_system.md
  qa_1_effective_preview.md
  prompt_settings.json
```

수업 프로젝트에서는 같은 결과물을 두고 QA guideline만 바꾸어 QA Agent의
판단이 달라지는 것을 시연할 수 있습니다. 예를 들어 `Default QA`에서는 통과한
앱이 `Ethics & Bias QA` 또는 `Strict Safety QA`에서는 개인정보/편향 위험 때문에
실패할 수 있습니다.

## API Key Provider에 대한 현재 방침

현재 제출판은 Codex CLI 중심입니다.

OpenAI API key 기반 provider는 구조상 확장 가능하도록 provider abstraction을
두고 있지만, 전체 과정을 API provider로 바꾸는 것은 별도 runner adapter,
message history/state 관리, tool executor 설계가 필요합니다. 14일 제출판에서는
범위가 커지므로 후순위입니다.

## Discord 봇 실행

Discord는 선택 기능입니다. 현재 데스크톱 앱이 메인 사용 경로입니다.

환경 변수를 설정합니다.

```powershell
$env:DISCORD_BOT_TOKEN="your_bot_token"
$env:DISCORD_GUILD_ID="your_test_guild_id"
```

FastAPI를 먼저 실행합니다.

```powershell
cd D:\curs\auto\multi_codex_dev_mvp
.\.venv\Scripts\python.exe run_local_api.py --host 127.0.0.1 --port 8765
```

다른 터미널에서 Discord bot을 실행합니다.

```powershell
cd D:\curs\auto\multi_codex_dev_mvp
.\.venv\Scripts\python.exe discord_bot.py
```

Discord 명령 예시:

```text
/dev 간단한 쇼핑몰 사이트 만들어줘
/runs limit:10
/status run_id:20260505_010000
```

## 테스트와 빌드

Python 테스트:

```powershell
cd D:\curs\auto\multi_codex_dev_mvp
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

프론트엔드 빌드:

```powershell
cd D:\curs\auto\multi_codex_dev_mvp\ux
npm run build
```

Tauri 개발 실행:

```powershell
cd D:\curs\auto\multi_codex_dev_mvp\ux
npm run tauri:dev
```

Tauri 패키징:

```powershell
cd D:\curs\auto\multi_codex_dev_mvp\ux
npm run tauri:build
```

## 주요 폴더

```text
app_services.py              FastAPI와 GUI가 공유하는 서비스 계층
local_api.py                 localhost FastAPI adapter
run_worker.py                background run worker
workflow_engine.py           route/manual graph 실행 엔진
local_dashboard_runner.py    실제 agent stage 실행 helper
agents.py                    Planner/Code/Integrator/QA agent prompt 정의
executable_qa.py             앱 실행 probe, screenshot, browser QA
qa.py                        mechanical QA 결과 결합
ux/                          React + Tauri GUI
reference_packs/             agent skill/reference pack
runs/                        실행 결과물, Git 제외
```

## Run 결과물 구조

각 실행은 `runs/<run_id>/`에 저장됩니다.

```text
runs/<run_id>/
  state.json
  events.jsonl
  transcript.md
  route.json
  workflow_graph.json
  planning/
  contract/
  scaffold_app/
  agent_workspaces/
  agent_outputs/
  integration/
  generated_app/
  qa/
    attempt_00/
      syntax_report.md
      executable_qa_report.md
      screenshot_initial.png
      screenshot_after_keys.png
      browser_console.json
      qa_1_review.md
  prompts/
    prompt_settings.json
    qa_1_skill.md
    qa_1_system.md
    qa_1_effective_preview.md
  qa_report.md
  logs/
```

## 자주 나는 문제

### `npm run tauri dev`가 실패함

명령어가 다릅니다.

```powershell
npm run tauri:dev
```

### Tauri 빌드에서 Rust 관련 오류가 남

Rust/Cargo가 설치되어 있어야 합니다. Windows에서는 Rustup 설치 후 새 터미널을
열어 다시 실행하세요.

```powershell
rustc --version
cargo --version
```

### Playwright browser가 없다고 나옴

```powershell
cd D:\curs\auto\multi_codex_dev_mvp
.\.venv\Scripts\python.exe -m playwright install chromium
```

### LLM QA가 안 돈 것 같음

- `fast` 모드인지 확인합니다.
- GUI에서 `QA route: LLM QA Agent enabled`인지 확인합니다.
- `balanced` 또는 `manual`에서 QA Agent가 enabled인지 확인합니다.
- run 결과의 `qa_report.md`에 `## Codex QA Agent Reviews`가 있는지 확인합니다.

### Codex 사용량이 부족함

앱의 `Resources` 패널에서 5시간/주간 limit을 확인합니다. Codex CLI에서도 직접
확인할 수 있습니다.

```text
/status
```

## Git에 올리지 않는 파일

다음 파일/폴더는 로컬 실행 결과 또는 개인 설정이라 Git에서 제외됩니다.

```text
.venv/
.env
runs/
local_app_settings.json
local_prompt_overrides.json
ux/node_modules/
ux/dist/
ux/src-tauri/target/
```

## 발표 포인트

- 프롬프트 엔지니어링:
  - Planner/Code/QA Agent별 역할 프롬프트 분리
  - QA Prompt / Skill Editor에서 guideline 변경 가능
  - 사용 prompt를 run artifact로 보존
- AI 윤리:
  - `Ethics & Bias QA` preset
  - 개인정보, 차별, 편향, 민감정보 수집 위험 검토
  - 같은 결과물도 guideline에 따라 다른 QA 판단 가능
- Human-in-the-loop:
  - 계획 승인 후 구현
  - QA 결과 승인 또는 수정 요청
- 비용/실용성:
  - API key 중심 SaaS가 아니라 사용자의 로컬 Codex CLI 구독 환경 활용
  - 개인 사용자를 위한 CLI/desktop 중심 멀티 에이전트 개발 앱
