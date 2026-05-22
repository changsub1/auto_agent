---
id: data-analysis/reviewer-skill
label: Data Analysis Reviewer Skill
source: Orchestra example skills
description: Reviewer guidance for checking whether a data analysis plan preserves user intent and is grounded in source data.
license: Project
recommended_for: reviewer, planner_b
variant: example
---

# Data Analysis Reviewer Skill

## Purpose

Planner A의 데이터 분석 계획이 사용자 의도, 원본 데이터, 분석 타당성, 구현 가능성을 충분히 반영했는지 검토한다. 이 스킬은 Planner B처럼 리뷰 역할을 하는 에이전트에게 맞춘다.

## Shared Data Analysis Checklist

- 데이터의 분석 단위, 열 의미, 단위, 타입, 시간 범위, 식별자, 범주형 값의 불일치를 확인한다.
- 결측치, 중복, 비정상 값, 인코딩 문제, 파싱 실패가 계획에 반영되었는지 본다.
- 시간 변수가 있으면 시간 흐름, 변화율, 계절성, 구조적 변화 가능성이 계획에 반영되었는지 본다.
- 수치형 변수는 평균뿐 아니라 중앙값, 분위수, 분산, IQR, 최소/최대, 분포 형태를 함께 확인해야 한다.
- 왜도가 큰 변수와 이상치가 결과를 지배할 수 있는지 확인한다.
- 비교 분석에서는 분모, 노출량, 집단 크기, 관측 기간, 표본 수 차이를 확인한다.
- 관찰 데이터로 인과를 단정하지 않는지 확인한다.
- 결론에 데이터 한계, 가정, 불확실성이 포함되는지 확인한다.

## Reviewer Guidelines

- 계획이 사용자의 원래 목적을 축소하지 않았는지 확인한다.
- Planner A가 원본 파일을 직접 확인했는지 확인한다. 데이터 기반 작업인데 `Data Inspection Notes`가 없거나 preview만 사용했다면 수정 요구한다.
- 필요한 경우 직접 원본 파일을 열어 핵심 주장만 검산한다:
  - 실제 컬럼명과 시간 범위
  - 행/열 수
  - 주요 수치 변수의 분포와 이상치 후보
  - 집단 크기 차이
  - 결측률 또는 파싱 문제
- 데이터가 제공하는 중요한 축을 누락하지 않았는지 확인한다.
- 평균, 합계, 최신값 같은 쉬운 지표에 과도하게 의존하지 않았는지 확인한다.
- 이상치, 결측치, 집단 크기 차이를 무시하지 않았는지 확인한다.
- 분석 결과가 행동 가능한 판단으로 이어지는지 확인한다.
- 과도한 모델링이나 불필요한 복잡성이 들어갔는지 확인하되, 필요한 EDA를 MVP 축소 명목으로 제거하지 않는다.
- 산출물이 대시보드라면 기본 필터, 프리셋, 시간 흐름, 상세 검산 경로, 탭/탐색 구조가 충분한지 확인한다.
- acceptance criteria가 “실행됨”뿐 아니라 분석 타당성, 데이터 검산, 시각화 품질, 해석 한계를 포함하는지 확인한다.
- 리뷰는 단순 반대가 아니라 최종 계획을 더 좋게 만드는 필수 수정사항과 선택 개선사항을 분리해서 제시한다.
