# 실행 명령어 모음

Windows 기준 명령어입니다. PowerShell을 기본으로 사용합니다.

## 작업 폴더 이동

PowerShell:

```powershell
cd D:\curs\auto\multi_codex_dev_mvp
```

cmd.exe:

```bat
cd /d D:\curs\auto\multi_codex_dev_mvp
```

## Python 의존성 설치

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
```

## 프론트엔드 의존성 설치

```powershell
cd D:\curs\auto\multi_codex_dev_mvp\ux
npm install
```

## Codex CLI 로그인 확인

```powershell
codex --version
codex login status
```

별도 Codex 프로필을 확인하려면:

```powershell
$env:CODEX_HOME="D:\codex_profiles\account_1"
codex login status
```

```powershell
$env:CODEX_HOME="D:\codex_profiles\account_2"
codex login status
```

## 데스크톱 앱 실행

```powershell
cd D:\curs\auto\multi_codex_dev_mvp\ux
$env:ORCHESTRA_REPO_ROOT="D:\curs\auto\multi_codex_dev_mvp"
$env:ORCHESTRA_PYTHON="D:\curs\auto\multi_codex_dev_mvp\.venv\Scripts\python.exe"
npm run tauri:dev
```

주의: `npm run tauri dev`가 아니라 `npm run tauri:dev`입니다.

## 브라우저 개발 모드 실행

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

Rust/Tauri:

```powershell
cd D:\curs\auto\multi_codex_dev_mvp\ux\src-tauri
cargo check
```

## LLM QA 테스트 팁

`fast` 모드는 LLM QA가 생략될 수 있습니다. QA Agent 동작을 확인하려면 `balanced` 또는 `manual` 모드를 사용하세요.

성공 run에서 확인할 주요 파일:

```text
runs\<run_id>\qa\attempt_00\qa_scenarios.json
runs\<run_id>\qa\attempt_00\scenario_results.json
runs\<run_id>\qa\attempt_00\qa_workspace\evidence\verdict.json
runs\<run_id>\qa\attempt_00\qa_workspace\evidence\qa_findings.md
runs\<run_id>\qa_report.md
```
