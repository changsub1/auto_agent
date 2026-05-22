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
- Separate visual requirements by analytical purpose:
  - overview and headline indicators
  - ranking or category comparison
  - time trend
  - distribution and outliers
  - proportion or composition
  - relationship or correlation
  - drill-down and audit table
- For each required view, state what question it answers and what a good user
  should be able to conclude from it.
- Do not settle for KPI cards and rank tables when the data supports important
  time, distribution, or outlier analysis.
- Plan filters and presets in user language. Prefer understandable choices over
  forcing users to type exact thresholds.
- Include a validation path: users should be able to inspect the rows, metrics,
  or calculation logic behind important visual claims.
- Define acceptance criteria in terms of user-visible insight quality and
  visual correctness, not implementation mechanics.

## Reviewer Guidance

- Check whether the brief preserves the user's original visualization goal.
- Check whether the visual plan would help the target audience make a decision,
  not merely display data.
- Check whether important data dimensions were ignored: time, group, geography,
  category, distribution, denominator, or outlier-sensitive metrics.
- Check whether the brief distinguishes quantity from proportion.
- Check whether average-only summaries hide skew, outliers, or small sample
  groups.
- Check whether the proposed dashboard has a clear reading path.
- Check whether chart choices are justified by the analytical task.
- If the brief drifts into implementation mechanics, translate that content
  back into the underlying user-visible requirement.

