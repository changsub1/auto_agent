# Project Status

최종 갱신: 2026-05-14

## 요약

Orchestra는 로컬 Codex CLI를 멀티 에이전트처럼 호출해 기획, 구현, QA, 사용자 승인을 진행하는 Tauri 데스크톱 앱입니다. 현재 제출용 MVP는 Codex CLI 중심으로 동작하며, API key provider는 후순위 확장 항목입니다.

## 제품 방향

- 개인 사용자용 로컬 데스크톱 앱
- 사용자가 로그인한 Codex CLI 구독 환경 활용
- localhost FastAPI sidecar + React/Tauri UI
- Discord bot 경로는 보조/레거시 경로로 유지
- 과제 관점에서는 프롬프트 엔지니어링, 멀티 에이전트 역할 분리, QA guideline, evidence 기반 판단을 강조

## 주요 기능

- 실행 모드
  - `fast`: 빠른 단일 Code Agent 구현, mechanical QA 중심
  - `balanced`: Planner A/B, Code Agent, QA Workspace Agent
  - `parallel`: 계약, 스캐폴드, 복수 Code Agent, Integrator, QA
  - `manual`: 사용자가 에이전트와 워크플로 그래프를 직접 구성
- GUI 설정
  - Codex 계정 선택
  - 모델 선택
  - reasoning effort 선택
  - Codex 5시간/주간 사용량 표시
  - agent별 계정/모델/reasoning override
- Prompt/Skill 설정
  - `agent_prompts/` 기반 System Prompt 템플릿
  - GUI에서 agent별 System Prompt 수정 가능
  - Skill / Guideline과 System Prompt 분리
  - Code Agent 기본 skill은 Karpathy Guidelines
  - ciembor agent-rules-books mini/nano 선택 가능
  - run 시작 시 prompt snapshot 저장
- Human-in-the-loop
  - Planner 결과 승인
  - 변경 요청
  - QA 결과 승인
  - QA 수정 요청 기록
  - 중지
- QA
  - balanced/manual에서 QA Agent가 있으면 QA Workspace Agent 직접 실행
  - `qa_workspace/app`에 산출물 복사
  - `qa_workspace/qa_tools`에 command/file/browser probe 도구 복사
  - `qa_tools\*.cmd` launcher로 Orchestra Python/.venv 환경에서 QA 도구 실행
  - QA Agent가 필요한 도구를 선택해 evidence 수집
  - browser/canvas 앱은 action file 기반 page-scoped drag/click/screenshot 검증 가능
  - `evidence/verdict.json`, `evidence/qa_findings.md`, `evidence/command_log.jsonl` 강제
  - visual/browser app은 screenshot evidence 없이 PASS 불가
  - desktop GUI는 기본적으로 OS-wide mouse/keyboard automation 비활성화
- Run Monitor
  - 타임라인을 agent output, approval, error 중심으로 정리
  - 승인 버튼을 관련 결과 카드 안에 표시
  - QA evidence를 타임라인 카드에서 직접 확인
  - 우측 패널은 선택 이벤트 상세와 파일 preview 중심

## Stage별 상태

### Stage 3

FastAPI run worker 기반 전체 workflow MVP가 완료되었습니다. 기존 Discord-owned flow는 보조 경로로 남았고, 주 실행 경로는 로컬 API입니다.

### Stage 4

Tauri 데스크톱 앱이 FastAPI sidecar를 실행하고 React UI와 연결합니다. Windows installer 패키징은 후순위이지만 dev 실행은 가능합니다.

### Stage 5

GUI 설정과 manual graph MVP가 구현되었습니다.

- provider health/status
- Codex 모델/reasoning 설정
- Codex 사용량 표시
- per-agent provider config
- manual 모드 agent 추가/삭제/비활성화
- 제한된 workflow graph 저장/검증

### Stage 6

Prompt/Skill 설정 분리가 구현되었습니다.

- `agent_prompts/` 기반 System Prompt 템플릿
- `prompt_templates.py` 로더
- GUI Prompt Editor
- Skill Registry
- prompt snapshot
- final prompt log artifact 저장

### Stage 7

QA 구조와 Run Monitor 정리가 진행되었습니다.

- Stage7A: LLM QA scenario plan 기반 동적 QA 초안
- Stage7B-1: UTF-8 subprocess/env hardening
- Stage7B-2: 타임라인 action card로 승인 UI 이동
- Stage7B-3: 타임라인 QA evidence preview 추가
- Stage7B-4: 우측 패널 단순화
- Stage7C: QA Workspace Agent 구현
- Stage7D: scenario plan/mechanical QA 선행을 제거하고 QA Workspace Agent가 직접 evidence 도구를 선택하는 구조로 전환

Stage7D 기준 QA 흐름:

```text
Code 완료
-> QA Workspace 생성
-> generated_app 복사
-> qa_tools 복사
-> QA Agent가 command_probe/file_probe/browser_probe.cmd 선택 실행
-> verdict.json, qa_findings.md, command_log.jsonl 작성
-> hard policy 검증
-> 사용자 QA 승인
```

## 주요 파일

- `app_services.py`: UI-agnostic service layer
- `local_api.py`: FastAPI API adapter
- `run_worker.py`: background run worker
- `workflow_engine.py`: route별 workflow 실행
- `local_dashboard_runner.py`: agent stage 실행 함수
- `agents.py`: Planner/Code/QA agent prompt 구성
- `codex_runner.py`: Codex CLI subprocess wrapper
- `qa_tools/`: QA Workspace Agent에게 제공되는 안전한 evidence 수집 도구
- `executable_qa.py`: fast/no-LLM 경로에서 사용하는 manifest, Playwright, CLI 기반 mechanical QA
- `qa.py`: QA result composition
- `prompt_templates.py`: System Prompt template loader
- `skill_registry.py`: Skill / Guideline catalog
- `state_store.py`: run state, events, artifacts
- `ux/`: React/Tauri UI

## 현재 검증 상태

최근 확인:

```text
.\.venv\Scripts\python.exe -m unittest discover -s tests
npm run build
```

통과했습니다.

## 제출 전 확인 항목

1. `balanced` 또는 `manual` 모드에서 실제 성공 run 확보
2. LLM QA 산출물 확인
   - `qa_workspace/evidence/verdict.json`
   - `qa_workspace/evidence/qa_findings.md`
   - `qa_workspace/evidence/command_log.jsonl`
   - screenshots
   - `qa_report.md`
3. 앱 화면에서 타임라인과 우측 패널이 QA evidence를 제대로 보여주는지 시각 확인
4. 과제 발표용 비교 시연 준비
   - 단일 Codex 방식 결과물
   - Orchestra 멀티 에이전트 방식 결과물
   - QA guideline 변경에 따른 판단 차이

## 후순위

- OpenAI API key provider
- Claude Code provider
- 더 자유로운 DAG executor
- QA 도구 확장
- 강한 OS 격리 기반 QA sandbox
- Windows installer packaging
