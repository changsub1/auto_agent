---
id: data-analysis/common-checklist
label: Data Analysis Checklist
source: Orchestra example skills
description: General checklist for data structure, quality, statistical validity, visualization, and interpretation ethics.
license: Project
recommended_for: planner, planner_a, reviewer, planner_b, code_agent, qa_agent
variant: example
---

# Data Analysis Checklist

## Purpose

데이터 분석 작업에서 자료 구조, 품질, 통계적 타당성, 시각화, 해석 윤리를 점검하기 위한 일반 체크리스트다. 특정 도메인이나 산출물 형식에 고정하지 않는다.

## Prompt Engineering Frame

- Role: 데이터 분석 결과물을 설계, 구현, 검토하는 전문가 관점으로 판단한다.
- Audience: 결과를 보는 사용자가 어떤 결정을 내릴지 먼저 추정하고, 확실하지 않으면 가정으로 표시한다.
- Knowledge / Information: 첨부 원본 파일, 사용자 요청, 생성된 산출물, 실행 증거를 구분해서 사용한다.
- Task / Goal: 단순히 차트를 배치하는 것이 아니라, 데이터가 의사결정에 어떤 근거를 제공하는지 설명한다.
- Policy / Rules: 근거 없는 인과 주장, 과도한 추천, 표본 수 무시, 편향적 해석을 피한다.
- Format / Structure: 결론, 근거, 한계, 검증 경로가 사용자가 확인 가능한 형태로 남아야 한다.

## Core Guidelines

- 데이터의 분석 단위를 먼저 파악한다. 한 행이 사람, 거래, 기업, 지역, 시점, 문서, 제품 중 무엇을 의미하는지 확인한다.
- 열의 의미, 단위, 타입, 시간 범위, 식별자, 범주형 값의 불일치를 확인한다.
- 결측치, 중복, 비정상 값, 인코딩 문제, 파싱 실패를 분석 전 단계에서 기록한다.
- 시간 변수가 있으면 시간 흐름, 변화율, 계절성, 구조적 변화 가능성을 검토한다.
- 수치형 변수는 평균만 보지 말고 중앙값, 분위수, 분산, IQR, 최소/최대, 분포 형태를 함께 확인한다.
- 왜도가 큰 변수는 로그 변환, 분위수 비교, robust summary를 고려한다.
- 이상치는 무조건 삭제하지 않는다. 탐지 기준, 영향, 제외 전후 차이를 설명한다.
- 비교 분석에서는 분모, 노출량, 집단 크기, 관측 기간, 표본 수 차이를 확인한다.
- 상관관계와 인과관계를 구분한다. 관찰 데이터로 인과를 단정하지 않는다.
- 모델이나 점수를 만들 경우 학습/검증 분리, 누수, 과적합, 기준선 모델, 평가 지표를 점검한다.
- 민감한 집단, 지역, 성별, 연령, 소득 등 사회적 영향을 가질 수 있는 변수는 편향과 오용 가능성을 검토한다.
- 모든 결론에는 데이터 한계, 가정, 불확실성을 함께 적는다.
