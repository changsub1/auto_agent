---
id: data-visualization/planning-skill
label: Data Visualization Planner Skill
source: Orchestra example skills
description: Planner and reviewer guidance for designing decision-oriented visualization and dashboard briefs.
license: Project
recommended_for: planner, planner_a, reviewer, planner_b
variant: example
---

# Data Visualization Planner Skill

## Purpose

Use this skill when planning a dashboard, visual analysis tool, or report. The
planner should define the audience, decision context, analytical questions, and
visual quality criteria. Do not prescribe the implementation stack, files,
scripts, libraries, or technical pipeline.

## Planner Guidance

- Rewrite the user request as a decision-oriented visualization goal.
- Identify the target audience and what they need to compare, diagnose, select,
  monitor, or explain.
- Inspect attached data when available and record the visual implications:
  analysis unit, time variables, categorical fields, quantitative fields,
  missingness, skew, outliers, and group-size differences.
- Select the 2-4 highest-value analytical purposes for the Code Brief. Do not
  promote every possible purpose into mandatory scope.
- Consider these purposes, then choose only the ones that matter most:
  overview/headline indicators, ranking/category comparison, time trend,
  distribution/outliers, proportion/composition, relationship/correlation, and
  drill-down/audit table.
- Phrase the Code Brief as core questions and guardrails, not as a fixed chart
  inventory. Let the Code Agent choose the exact layout and chart count.
- Keep optional visual ideas in Planner Notes unless omitting them would make
  the result fail the user's goal.
- Plan filters and presets in user language. Prefer understandable choices over
  forcing users to type exact thresholds.
- Include a lightweight validation path: users should be able to inspect the
  rows, metrics, or calculation logic behind important visual claims.
- Define acceptance criteria in terms of user-visible insight quality and
  visual correctness, not implementation mechanics.

## Reviewer Guidance

- Check whether the brief preserves the user's original visualization goal.
- Check whether the visual plan would help the target audience make a decision,
  not merely display data.
- Check whether important data dimensions were ignored, but recommend adding
  only dimensions that are essential to the user's main decision.
- Check whether the brief distinguishes quantity from proportion.
- Check whether average-only summaries hide skew, outliers, or small sample
  groups.
- Check whether the proposed dashboard has a clear reading path without
  becoming a gallery of loosely related charts.
- Check whether the brief leaves chart and layout mechanics to the Code Agent.
- If the brief drifts into implementation mechanics, translate that content
  back into the underlying user-visible requirement.
