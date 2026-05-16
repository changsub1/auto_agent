# Stage8 Artifact / Token Budget Hardening Plan

최종 갱신: 2026-05-17

## 목적

Stage8의 목표는 실행 결과 폴더와 UI 산출물 목록을 발표와 실사용 관점에서 정리하는 것이다.

기본 모드에서는 사용자가 이해해야 하는 핵심 결과만 남긴다.

- 최종 실행 결과물
- 각 에이전트의 입력 프롬프트
- 각 에이전트의 출력
- 계획/계약/QA 보고서
- 첨부 파일 manifest
- QA verdict, findings, screenshots

디버그 모드에서만 내부 runner 진단용 파일을 남긴다.

- Codex 호출 meta
- 빈 stderr
- `prompts/final/*` 중복 prompt 복사본
- QA workspace의 복사된 app/tools/context/scratch
- probe 내부 result/preview/stdout 파일
- 브라우저 실행 내부 console/result 파일

## Debug Artifact Mode

기본값은 slim mode다.

```env
ORCHESTRA_DEBUG_ARTIFACTS=0
```

내부 동작을 추적해야 할 때만 다음처럼 켠다.

```env
ORCHESTRA_DEBUG_ARTIFACTS=1
```

`stdout/stderr`만으로는 완전한 입출력 세트가 아니다. `stdout`은 에이전트 출력이고, 에이전트 입력은 별도로 생성한 prompt 파일이다. 따라서 기본 보존 단위는 `*_prompt.txt`와 `*_stdout.txt`이며, `*_stderr.txt`는 내용이 있을 때만 남긴다.

## Stage8A: Host Browser QA Runner

브라우저 실행과 스크린샷 수집은 Codex QA Agent 내부가 아니라 Orchestra host process에서 수행한다.

흐름:

```text
Code Agent 완료
-> QA workspace 생성
-> QA Agent가 app/context를 읽고 browser action file 작성
-> Orchestra host runner가 trusted browser_probe.py 실행
-> screenshots/result/console evidence 저장
-> 같은 QA Agent 세션에 host evidence 전달
-> QA Agent가 verdict.json, qa_findings.md 최종 갱신
```

현재 상태: 구현 완료.

## Stage8B: Prompt Snapshot Deduplication

실제 route에 쓰인 agent만 prompt snapshot 대상으로 삼는다. 기본 모드에서는 `logs/*_prompt.txt`를 `prompts/final/*`로 다시 복사하지 않는다.

현재 상태: 구현 완료.

## Stage8C: Evidence Manifest 중심 구조

QA 산출물은 기본적으로 다음 핵심 파일 중심으로 노출한다.

```text
evidence/
  evidence_manifest.json
  verdict.json
  qa_findings.md
  command_log.jsonl
  host_browser_evidence.json
screenshots/
  *.png
```

probe preview, command stdout 전문, browser console 세부 파일은 debug mode에서만 보존한다.

현재 상태: 구현 완료.

## Stage8D: Scratch Cleanup

QA 중 생기는 브라우저 profile/cache/crashpad 파일은 자동 정리한다.

대상 예:

- `scratch/chrome-profile*`
- `scratch/playwright-profile*`
- `scratch/*Crashpad*`
- browser cache/profile 임시 폴더

현재 상태: 구현 완료.

## Stage8E: Large File Read Guard

QA Agent가 큰 파일 전문을 prompt나 findings에 붙여 넣지 않도록 제한한다.

- 큰 파일은 `file_probe`로 size, preview, contains evidence를 먼저 기록한다.
- 긴 command 출력은 `command_probe --max-output-chars`로 제한한다.
- 다음 agent context에는 전체 로그가 아니라 핵심 evidence path와 요약만 전달한다.

현재 상태: 구현 완료.

## Stage8F: UTF-8 Hardening

새 run에서 깨진 한글이 생기지 않도록 state, events, transcript, artifact, subprocess stdout/stderr 저장을 UTF-8 중심으로 통일한다.

이미 깨진 문자열을 추정 복구하는 방식은 적용하지 않는다. 잘못 복구하면 정상 텍스트까지 손상될 수 있으므로, 새로 생성되는 데이터의 인코딩 경로를 고정하는 데 집중한다.

현재 상태: 구현 완료.

## Stage8G: Presentation-Friendly Artifact Mode

기본 UI와 산출물 목록은 발표용으로 정리한다.

기본 노출:

- 계획/계약/최종 plan
- prompt 설정과 에이전트별 prompt 입력 파일
- 에이전트별 stdout 출력 파일
- 최종 generated app
- QA report, verdict, findings, screenshot
- 첨부 파일 manifest

기본 숨김 또는 삭제:

- 빈 stderr
- Codex meta 파일
- final prompt 중복 복사본
- QA workspace 내부 복사본
- QA tools 복사본
- scratch/context/probe 내부 파일

현재 상태: 구현 완료.
