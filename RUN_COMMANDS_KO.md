# 실행 명령어 모음

이 파일은 Windows 기준 로컬 실행 명령어만 모아둔 문서입니다.
PowerShell에서 `codex`가 막히면 `codex.cmd`를 사용하세요.

## 1. 작업 폴더 이동

PowerShell:

```powershell
cd D:\curs\auto\multi_codex_dev_mvp
```

명령 프롬프트(cmd.exe):

```bat
cd /d D:\curs\auto\multi_codex_dev_mvp
```

## 2. 의존성 설치

```powershell
python -m pip install -r requirements.txt
```

이제 실행형 브라우저 QA는 Playwright를 사용합니다. 최초 1회 Chromium을 설치하세요.

```powershell
python -m playwright install chromium
```

현재 PC에서 Streamlit이 Miniconda Python에만 잡혀 있으면 아래처럼 실행할 수 있습니다.

```powershell
D:\miniconda3\python.exe -m pip install -r requirements.txt
D:\miniconda3\python.exe -m playwright install chromium
```

## 3. Codex 로그인 상태 확인

기본 계정:

```powershell
codex.cmd login status
```

1번 계정:

```powershell
$env:CODEX_HOME = "D:\codex_profiles\account_1"
codex.cmd login status
```

2번 계정:

```powershell
$env:CODEX_HOME = "D:\codex_profiles\account_2"
codex.cmd login status
```

## 4. Codex 계정 로그인

```powershell
$env:CODEX_HOME = "D:\codex_profiles\account_1"
codex.cmd login
codex.cmd login status
```

```powershell
$env:CODEX_HOME = "D:\codex_profiles\account_2"
codex.cmd login
codex.cmd login status
```

각 계정 폴더의 `config.toml`에는 아래 값을 넣어두는 것을 권장합니다.

```toml
cli_auth_credentials_store = "file"
```

## 5. Discord 봇 환경 변수

PowerShell:

```powershell
$env:DISCORD_BOT_TOKEN = "봇_토큰"
$env:DISCORD_GUILD_ID = "테스트_서버_ID"
```

cmd.exe:

```bat
set DISCORD_BOT_TOKEN=봇_토큰
set DISCORD_GUILD_ID=테스트_서버_ID
```

선택 설정:

```powershell
$env:DISCORD_ALLOWED_CHANNEL_ID = "채널_ID"
$env:DISCORD_ALLOWED_USER_IDS = "사용자ID_1,사용자ID_2"
```

## 6. 에이전트 계정 배분

PowerShell:

```powershell
$env:PLANNER_A_CODEX_HOME = "D:\codex_profiles\account_1"
$env:PLANNER_B_CODEX_HOME = "D:\codex_profiles\account_1"
$env:ARCHITECT_CODEX_HOME = "D:\codex_profiles\account_2"
$env:SCAFFOLD_CODEX_HOME = "D:\codex_profiles\account_2"
$env:CODE_AGENT_CODEX_HOMES = "D:\codex_profiles\account_2"
$env:CODE_AGENT_COUNT = "2"
$env:QA_AGENT_CODEX_HOMES = "D:\codex_profiles\account_2"
$env:QA_AGENT_COUNT = "1"
$env:INTEGRATOR_CODEX_HOME = "D:\codex_profiles\account_2"
$env:DEVELOPER_CODEX_HOME = "D:\codex_profiles\account_2"
```

cmd.exe:

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

모델과 추론 강도:

```powershell
$env:CODEX_MODEL = "gpt-5.4"
$env:CODEX_REASONING_EFFORT = "medium"
```

## 7. QA 설정

기본값은 실행형 QA 켜짐입니다.

```powershell
$env:EXECUTABLE_QA_ENABLED = "1"
$env:EXECUTABLE_QA_TIMEOUT_SECONDS = "90"
```

`.bat` 또는 `.cmd` 실행은 기본적으로 꺼져 있습니다. 신뢰하는 산출물에서만 켜세요.

```powershell
$env:EXECUTABLE_QA_ALLOW_LOCAL_COMMANDS = "1"
```

cmd.exe:

```bat
set EXECUTABLE_QA_ENABLED=1
set EXECUTABLE_QA_TIMEOUT_SECONDS=90
set EXECUTABLE_QA_ALLOW_LOCAL_COMMANDS=0
```

## 8. Discord 봇 실행

PowerShell:

```powershell
python discord_bot.py
```

cmd.exe:

```bat
python discord_bot.py
```

Discord에서:

```text
/dev index.html로 실행되는 테트리스 게임을 만들어줘
```

현재 흐름:

```text
Planner A
-> Planner B
-> Planner A final
-> Architect contract bundle
-> Discord 계약 승인
-> Scaffold
-> code_1/code_2 병렬 구현
-> Integrator merge
-> Python syntax QA
-> Executable QA, screenshot, keyboard probe
-> Discord 결과 승인 또는 수정 요청
```

## 9. 대시보드 실행

```powershell
python -m streamlit run dashboard.py
```

현재 PC에서 Miniconda Python을 써야 하면:

```powershell
D:\miniconda3\python.exe -m streamlit run dashboard.py
```

현재 대시보드는 `planning_only`, `contract_only`, `scaffold_only` 테스트용입니다.
전체 병렬 개발과 QA 승인 루프는 Discord 경로가 담당합니다.

## 10. 로컬 CLI 실행

```powershell
python main.py "CSV 파일 업로드 후 미리보기와 결측치 요약을 보여주는 앱"
```

계정과 모델 지정:

```powershell
python main.py --planner-codex-home "D:\codex_profiles\account_1" --developer-codex-home "D:\codex_profiles\account_2" --model gpt-5.4 --reasoning-effort medium "작은 할 일 관리 앱"
```

## 11. 문법 검사

```powershell
python -m py_compile main.py agents.py codex_runner.py workspace_manager.py parallel_workflow.py local_dashboard_runner.py executable_qa.py qa.py state_store.py config.py discord_reporter.py discord_ui.py debate_engine.py discord_bot.py dashboard.py
```

## 12. 최근 실행 로그 확인

최근 run 목록:

```powershell
Get-ChildItem .\runs -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 5 Name,LastWriteTime
```

상태 확인:

```powershell
Get-Content -Raw .\runs\RUN_ID\state.json
```

QA 리포트 확인:

```powershell
Get-Content -Raw .\runs\RUN_ID\qa_report.md
```

QA 스크린샷 확인:

```powershell
Get-ChildItem .\runs\RUN_ID\qa -Recurse -Filter *.png
```

생성 앱 확인:

```powershell
Get-ChildItem .\runs\RUN_ID\generated_app
```

## 13. 생성 앱 직접 실행

각 run의 `generated_app\README.md`를 우선 확인하세요.

Python 앱:

```powershell
cd .\runs\RUN_ID\generated_app
python app.py
```

Streamlit 앱:

```powershell
cd .\runs\RUN_ID\generated_app
python -m streamlit run app.py
```

HTML 앱:

```powershell
cd .\runs\RUN_ID\generated_app
start index.html
```

## 14. 자주 보는 문제

`DISCORD_BOT_TOKEN is required`가 나오면 봇을 실행하는 같은 터미널에서 토큰을 설정해야 합니다.

PowerShell:

```powershell
$env:DISCORD_BOT_TOKEN
```

cmd.exe:

```bat
echo %DISCORD_BOT_TOKEN%
```

`codex.ps1` 실행 정책 오류가 나오면 `codex.cmd`를 사용하세요.

```powershell
codex.cmd login status
codex.cmd exec --help
```
