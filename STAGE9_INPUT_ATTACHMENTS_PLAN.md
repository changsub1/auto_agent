# Stage9 Input Attachments Plan

## 목적

Stage9의 목표는 사용자가 GUI의 초기 프롬프트 입력창에서 데이터 파일을 첨부하고, 해당 파일이 새 run의 입력 자료로 보존되며, Planner, Code Agent, QA Agent가 같은 입력 파일을 근거로 작업하도록 만드는 것이다.

과제 시연 기준으로는 사용자가 CSV, XLSX, JSON 같은 데이터 파일을 첨부한 뒤 "브랜드 비교분석 대시보드 만들어줘"라고 요청했을 때 다음 흐름이 보여야 한다.

1. 첨부 파일이 새 `runs/<run_id>/inputs/`에 저장된다.
2. Planner가 파일 존재와 경로를 인식하고 데이터 기반 계획을 세운다.
3. Code Agent가 첨부 파일을 읽어 대시보드 앱을 구현한다.
4. QA Agent가 같은 입력 파일과 생성된 앱을 근거로 검토한다.
5. UI 타임라인에는 입력 파일, 주요 산출물, QA evidence가 간결하게 표시된다.

## 현재 상태

현재 GUI에는 `첨부` 버튼 UI가 있지만 실제 파일 첨부 흐름은 완성되어 있지 않다.

- run 생성 API는 텍스트 요청과 실행 설정 중심이다.
- 첨부 파일을 `runs/<run_id>/inputs/`로 저장하는 로직이 없다.
- Planner/Code/QA 프롬프트에 입력 파일 manifest가 자동 주입되지 않는다.
- QA workspace에 입력 파일을 전달하는 표준 경로가 없다.

따라서 현재 제출판에서 파일 기반 작업을 하려면 프로젝트 폴더 안에 데이터를 미리 두고, 프롬프트에 직접 경로를 적는 우회 방식이 필요하다.

## 설계 원칙

Stage9는 "파일 첨부를 지원하는 로컬 실행 프레임워크"를 목표로 하되, 과제 제출 일정에 맞춰 범위를 제한한다.

- 첨부 파일은 새 run 내부에 복사해서 보존한다.
- 에이전트에게는 원본 PC 경로가 아니라 run 내부 상대 경로를 알려준다.
- 첨부 파일은 읽기 입력 자료로 취급하고, 원본을 수정하지 않는다.
- 대용량 파일 전문을 프롬프트에 붙이지 않는다.
- manifest와 샘플 정보만 프롬프트에 주입한다.
- Code/QA workspace에는 필요한 경우 입력 파일 사본을 제공한다.
- 모든 manifest와 텍스트 산출물은 UTF-8로 기록한다.

## Stage9A: Run Input Attachment Pipeline

Status: implemented in the local codebase. Verification commands still need to be run in a normal terminal because the current Codex tool sandbox could not start local processes.

GUI에서 파일을 선택하고 새 run 생성 시 함께 전달하는 기본 파이프라인을 만든다.

작업 범위:

- 프롬프트 입력창의 `첨부` 버튼을 실제 파일 선택 동작에 연결한다.
- 여러 파일 선택을 지원한다.
- 선택된 파일을 chip/list 형태로 표시하고 제거할 수 있게 한다.
- run 생성 요청에 첨부 파일 metadata와 content를 포함한다.
- 백엔드에서 파일명을 sanitize하고 `runs/<run_id>/inputs/`에 저장한다.
- `runs/<run_id>/inputs/input_manifest.json`을 생성한다.
- 파일 저장 완료 이벤트를 타임라인에 표시한다.

1차 구현은 새 의존성을 줄이기 위해 JSON base64 전송 방식을 사용한다. 현재 제한은 파일당 25 MB, 전체 80 MB이다. 파일 크기 제한이 문제가 되면 Stage9 후속 작업에서 multipart upload 또는 Tauri 파일 경로 기반 복사 방식으로 확장한다.

## Stage9B: Input Manifest And Prompt Injection

Status: implemented in the local codebase. CSV/TSV, JSON, and XLSX receive lightweight schema previews in `inputs/input_manifest.json`; verification commands still need to be run in a normal terminal.

에이전트들이 첨부 파일을 안정적으로 인식하도록 run-level 입력 문맥을 구성한다.

작업 범위:

- `input_manifest.json`에 파일명, 저장 경로, 크기, 확장자, MIME type, sha256을 기록한다.
- CSV/TSV는 컬럼명과 앞부분 샘플을 가볍게 추출한다.
- XLSX는 시트명, 행/열 수, 상위 컬럼명을 추출한다.
- Planner 프롬프트에 "첨부 파일은 `inputs/` 아래에 있다"는 섹션을 자동 추가한다.
- Code Agent 프롬프트에도 같은 manifest 요약을 전달한다.
- 대용량 파일 전문 출력 금지 규칙을 함께 주입한다.

목표는 파일 내용을 프롬프트에 전부 붙이는 것이 아니라, 에이전트가 직접 파일을 읽어 분석하도록 안내하는 것이다.

## Stage9C: Workspace Propagation

Status: implemented in the local codebase. Run inputs are copied into code workspaces, `generated_app/inputs`, and QA workspaces as local `inputs/` folders; verification commands still need to be run in a normal terminal.

Code Agent와 QA Agent가 같은 입력 파일을 안정적으로 읽을 수 있도록 workspace 복사 규칙을 정한다.

작업 범위:

- `runs/<run_id>/inputs/`를 canonical input source로 둔다.
- Code Agent가 `generated_app/`에서 작업할 경우 `generated_app/inputs/`에도 사본을 제공한다.
- QA workspace 생성 시 `qa_workspace/inputs/`에도 같은 입력 파일을 복사한다.
- 각 workspace에 `input_manifest.json`을 함께 둔다.
- 에이전트 프롬프트에는 현재 cwd 기준으로 읽을 수 있는 경로를 명시한다.

이렇게 하면 Planner, Code, QA가 서로 다른 cwd에서 실행되더라도 동일한 입력 데이터에 접근할 수 있다.

## Stage9D: Data Dashboard Demo Path

과제 시연에 바로 쓸 수 있는 데이터 대시보드 흐름을 안정화한다.

작업 범위:

- CSV/XLSX 기반 대시보드 요청을 balanced/manual 모드에서 테스트한다.
- Planner가 데이터 구조 확인 단계를 계획에 포함하는지 확인한다.
- Code Agent가 파일을 읽고 필터/차트/테이블이 있는 대시보드를 생성하는지 확인한다.
- QA Agent가 입력 데이터와 UI 결과를 근거로 검토하는지 확인한다.
- 타임라인에는 입력 파일, 생성 앱, 스크린샷, QA verdict만 핵심적으로 표시한다.

시연 예시 프롬프트:

```text
첨부한 프랜차이즈 가맹사업 데이터 파일을 기반으로 브랜드 비교분석 대시보드를 만들어줘.
브랜드별 가맹점 수, 평균 매출, 지역 분포, 연도별 변화 추이를 비교할 수 있어야 해.
```

## Stage9E: Safety And Limits

로컬 파일 첨부 기능이기 때문에 기본 안전장치를 둔다.

작업 범위:

- 파일명 path traversal 방지
- 파일당 크기 제한
- 전체 첨부 크기 제한
- 허용 확장자 기본값: `.csv`, `.tsv`, `.json`, `.xlsx`, `.xls`, `.txt`, `.md`
- 실행 파일 첨부는 기본 비허용
- 첨부 파일은 read-only input으로 취급
- manifest에는 원본 절대 경로를 저장하지 않거나 UI 표시용으로만 제한한다.

## 우선순위

제출 일정 기준 우선순위는 다음과 같다.

1. Stage9A: GUI 첨부와 run inputs 저장
2. Stage9B: manifest 생성과 Planner/Code prompt injection
3. Stage9C: generated app과 QA workspace로 입력 파일 전달
4. Stage9D: 프랜차이즈 데이터 대시보드 시연 검증
5. Stage9E: 파일 크기/확장자 제한과 안전장치 정리

## 완료 기준

Stage9는 다음 조건을 만족하면 완료로 본다.

- GUI에서 파일을 첨부한 상태로 run을 시작할 수 있다.
- 첨부 파일이 `runs/<run_id>/inputs/`에 저장된다.
- `input_manifest.json`이 생성된다.
- Planner 산출물에 첨부 파일을 기반으로 한 분석 계획이 나타난다.
- Code Agent가 첨부 파일을 읽어 앱을 생성한다.
- QA Agent가 입력 파일과 생성 앱을 근거로 verdict를 작성한다.
- 타임라인에서 사용자는 "어떤 파일을 넣었고, 어떤 결과가 나왔고, QA가 무엇을 확인했는지"를 한눈에 볼 수 있다.
