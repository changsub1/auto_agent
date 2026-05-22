# Orchestra

Orchestra는 Codex CLI를 여러 에이전트처럼 조합해, 비전문가 사용자의 개발 요청을 기획, 검토, 구현, QA, 사용자 승인 단계로 나누어 실행하는 로컬 데스크톱 개발 보조 도구입니다.

핵심 목표는 사용자가 완벽한 프롬프트를 쓰지 않아도 Planner와 Reviewer가 전문가 관점에서 요구사항을 구체화하고, Code Agent가 승인된 계획을 바탕으로 구현하며, QA Agent가 evidence를 남겨 검토하는 흐름을 만드는 것입니다. 외부 API를 매번 호출하는 서비스가 아니라 사용자가 이미 로그인한 Codex CLI 구독 환경을 활용하는 개인용 로컬 앱을 지향합니다.

## 현재 버전

- 버전: 14
- 실행 형태: Tauri 데스크톱 앱 + 로컬 FastAPI sidecar
- 주 대상: Windows 로컬 환경
- 기본 provider: Codex CLI
- API key provider: 구조상 확장 가능하지만 현재 제출판은 Codex CLI 중심

## 주요 기능

- 실행 모드
  - `fast`: 빠른 단일 Code Agent 중심 실행
  - `balanced`: Planner A/B 기획, 사용자 승인, Code Agent, QA Workspace Agent
  - `parallel`: 계약/스캐폴드/복수 Code Agent/Integrator/QA 흐름
  - `manual`: 사용자가 에이전트 흐름을 직접 구성
- GUI 기반 에이전트 로스터
  - 에이전트별 계정, 모델, reasoning effort 설정
  - manual 모드에서 에이전트 추가, 비활성화, 순서 조정
- Human-in-the-loop 승인
  - Planner 결과 승인/수정 요청
  - QA 결과 승인/수정 요청
  - 타임라인 카드에서 주요 결과와 승인 액션 확인
- Prompt / Skill 편집
  - 에이전트별 System Prompt 확인 및 수정
  - Skill / Guideline 선택 및 수정
  - Effective Prompt Preview 확인
  - run 시작 시 사용된 prompt snapshot 저장
- Skill Registry
  - Code Agent 기본값: Karpathy Guidelines
  - 예시 스킬: Data Analysis, Data Visualization, QA Skill
  - rules-books 계열 mini/nano 스킬 등록
  - gstack 등 원본 reference pack은 참고 자료로 보관 가능
- 첨부 파일 기반 작업
  - 최초 프롬프트 입력 시 파일 첨부
  - run 폴더의 `inputs/` 아래에 파일 저장
  - `input_manifest.json`으로 첨부 파일 정보 제공
- QA Workspace Agent
  - 각 QA attempt마다 격리된 `qa_workspace` 생성
  - generated app 복사 후 QA Agent가 evidence 수집
  - `verdict.json`, `qa_findings.md`, `command_log.jsonl`, screenshot evidence 저장
- Run Monitor
  - Clean timeline 중심 UI
  - 에이전트 출력, approval, error, QA evidence 표시
  - 상세 로그/파일 패널은 필요할 때만 확인

## 멀티에이전트 설계 의도

Orchestra의 목적은 사용자가 세밀한 개발 프롬프트를 직접 완성하지 않아도 되는 구조입니다.

```text
비전문가 요청
-> Planner A가 전문가 관점의 제품 요구사항 초안 작성
-> Planner B가 누락, 축소, 근거 부족, 사용자 가치 검토
-> 사용자가 계획 승인 또는 수정 요청
-> Code Agent가 승인된 계획과 원본 요청을 바탕으로 구현
-> QA Agent가 evidence 기반으로 결과 검토
-> 사용자가 최종 승인 또는 수정 요청
```

Planner A는 사용자의 원문을 그대로 반복하지 않고, 모호한 요청을 전문가 수준 product brief로 끌어올리도록 설계되어 있습니다. Reviewer B는 Planner가 실제로 전문가 관점을 더했는지, 사용자 목적을 축소하지 않았는지, 데이터와 근거가 충분한지 검토합니다.

## QA 구조

`balanced`와 `manual`에서 QA Agent가 포함된 경로는 QA Workspace Agent를 사용합니다.

```text
Code Agent 결과물
-> QA attempt 생성
-> qa_workspace/app에 generated_app 복사
-> qa_workspace/qa_tools에 안전한 probe 도구 복사
-> QA Agent가 필요한 command/file/browser probe 선택
-> host browser evidence 또는 screenshot 수집
-> evidence/verdict.json 작성
-> 타임라인에서 QA 결과 확인
```

대표 산출물:

```text
runs/<run_id>/qa/attempt_00/qa_workspace/evidence/verdict.json
runs/<run_id>/qa/attempt_00/qa_workspace/evidence/qa_findings.md
runs/<run_id>/qa/attempt_00/qa_workspace/evidence/command_log.jsonl
runs/<run_id>/qa/attempt_00/qa_workspace/screenshots/*.png
runs/<run_id>/qa_report.md
```

QA hard policy:

- `verdict.json`이 없거나 형식이 잘못되면 FAIL
- `qa_findings.md`가 없으면 PASS 금지
- `command_log.jsonl`에 실제 probe/evidence 기록이 없으면 PASS 금지
- visual/browser/game/dashboard 유형은 screenshot evidence 없이 PASS 금지
- desktop GUI는 기본적으로 OS 전체 마우스/키보드 조작을 하지 않고 `--self-test`, unit test, import check 중심으로 검토

## 요구 사항

- Windows 권장
- Python 3.10 이상
- Node.js / npm
- Rust / Cargo
- Codex CLI 설치 및 로그인
- Playwright Chromium

## 최초 설치

CMD 기준:

아래 명령어의 첫 줄에서 `C:\path\to\multi_codex_dev_mvp`는 사용자가 실제로 이 프로젝트를 내려받은 폴더로 바꾸어야 합니다.

```cmd
set PROJECT_DIR=C:\path\to\multi_codex_dev_mvp
cd /d "%PROJECT_DIR%"
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
```

프론트엔드 의존성:

```cmd
cd /d "%PROJECT_DIR%\ux"
npm install
```

Codex CLI 확인:

```cmd
codex --version
codex
```

Codex CLI가 Windows sandbox 설정을 요구하면 기본적으로 `Set up default sandbox`를 선택하는 것을 권장합니다. 특정 프로필에서 `CreateProcessWithLogonW failed: 1326`이 반복되면 해당 Codex profile의 sandbox cache가 꼬인 상태일 수 있습니다.

## 데스크톱 앱 실행

Tauri 앱은 FastAPI sidecar를 자동으로 실행합니다.

CMD 기준:

```cmd
set PROJECT_DIR=C:\path\to\multi_codex_dev_mvp
cd /d "%PROJECT_DIR%\ux"
set ORCHESTRA_REPO_ROOT=%PROJECT_DIR%
set ORCHESTRA_PYTHON=%PROJECT_DIR%\.venv\Scripts\python.exe
npm run tauri:dev
```

주의:

```cmd
npm run tauri:dev
```

가 맞습니다. `npm run tauri dev`가 아닙니다.

## 브라우저 개발 모드

터미널 1:

```cmd
set PROJECT_DIR=C:\path\to\multi_codex_dev_mvp
cd /d "%PROJECT_DIR%"
.\.venv\Scripts\python.exe run_local_api.py --host 127.0.0.1 --port 8765
```

터미널 2:

```cmd
set PROJECT_DIR=C:\path\to\multi_codex_dev_mvp
cd /d "%PROJECT_DIR%\ux"
npm run dev
```

브라우저:

```text
http://127.0.0.1:5173
```

## 앱 빌드

프론트엔드 빌드:

```cmd
set PROJECT_DIR=C:\path\to\multi_codex_dev_mvp
cd /d "%PROJECT_DIR%\ux"
npm run build
```

Tauri 앱 빌드:

```cmd
set PROJECT_DIR=C:\path\to\multi_codex_dev_mvp
cd /d "%PROJECT_DIR%\ux"
npm run tauri:build
```

빌드 결과는 보통 다음 경로 아래에 생성됩니다.

```text
ux/src-tauri/target/release/bundle/
```

## 기본 사용법

1. 앱을 실행합니다.
2. 왼쪽에서 실행 모드를 선택합니다.
3. 에이전트별 account, model, reasoning effort를 확인합니다.
4. 필요한 경우 에이전트 카드에서 Skill 또는 System Prompt를 조정합니다.
5. 하단 입력창에 만들 앱이나 기능을 적고, 필요하면 파일을 첨부합니다.
6. 실행을 시작합니다.
7. Planner 결과를 읽고 승인하거나 수정 요청합니다.
8. Code Agent 구현과 QA evidence를 확인합니다.
9. 최종 승인하거나 추가 수정 요청합니다.

## 데이터 분석 대시보드 시연 예시

예시 입력:

```text
데이터셋을 분석해서 HTML 대시보드를 만들어줘.
사용자가 핵심 인사이트를 빠르게 이해할 수 있게 구성하고,
필터와 차트, 요약 지표, 이상치/주의점도 포함해줘.
```

권장 구성:

- 실행 모드: `balanced`
- Planner A: Data Analysis Planning Skill 또는 Data Visualization Planning Skill
- Planner B: Data Analysis Reviewer Skill 또는 Data Visualization Planning Skill
- Code Agent: Karpathy Guidelines 또는 Data Visualization Implementation Skill
- QA Agent: Data Analysis QA Skill 또는 Data Visualization QA Skill

시연 포인트:

- 사용자가 짧은 요청과 데이터 파일만 제공
- Planner가 데이터 구조와 사용자 의사결정 맥락을 고려한 계획 생성
- Reviewer가 계획의 누락, 근거, 이상치/통계 해석 리스크 검토
- 사용자가 계획 승인
- Code Agent가 구현
- QA Agent가 screenshot/evidence 기반으로 결과 판정

## 프롬프트 엔지니어링 반영점

본 프로젝트는 강의에서 다룬 프롬프트 엔지니어링 요소를 다음 방식으로 적용합니다.

- role, audience, task, knowledge/evidence, policy/rules, style, output format을 에이전트별 System Prompt에 분리
- 비전문가의 짧은 요청을 Planner가 전문가 수준 product brief로 확장
- Reviewer가 Planner의 추론 요구사항과 사용자 명시 요구사항을 검토
- Skill / Guideline을 GUI에서 선택, 확인, 수정 가능
- Effective Prompt Preview로 실제 투입 프롬프트 확인 가능
- run마다 prompt snapshot 저장
- QA guideline preset을 바꾸어 같은 결과물도 다른 기준으로 평가 가능

## 주요 폴더

```text
agent_prompts/       # 에이전트별 기본 system prompt 템플릿
example_skills/      # 수업/시연용 예시 skill
docs/                # manifest 등 개발 문서
ux/                  # Tauri + React GUI
runs/                # 실행 결과, 입력 파일, 에이전트 출력, QA evidence
tests/               # Python unittest
```

## 테스트

백엔드:

```cmd
set PROJECT_DIR=C:\path\to\multi_codex_dev_mvp
cd /d "%PROJECT_DIR%"
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

프론트엔드:

```cmd
set PROJECT_DIR=C:\path\to\multi_codex_dev_mvp
cd /d "%PROJECT_DIR%\ux"
npm run build
```

Tauri Rust:

```cmd
set PROJECT_DIR=C:\path\to\multi_codex_dev_mvp
cd /d "%PROJECT_DIR%\ux\src-tauri"
cargo check
```

## 알려진 주의점

- Codex CLI account별 Windows sandbox 상태가 다를 수 있습니다.
- 특정 account에서 `CreateProcessWithLogonW failed: 1326`이 반복되면 해당 profile의 sandbox 설정을 다시 구성해야 합니다.
- 기존 run은 prompt snapshot을 보존하므로 System Prompt를 수정해도 과거 run에는 반영되지 않습니다.
- GUI에서 System Prompt를 커스텀 저장한 경우 기본 템플릿 변경을 반영하려면 해당 에이전트 Prompt 패널에서 Reset이 필요합니다.
- `fast` 모드는 속도 중심이라 LLM QA가 생략될 수 있습니다. 제출/시연용 검증은 `balanced` 또는 `manual`을 권장합니다.
