# Example Skills

This directory contains optional Skill / Guideline presets for demos and tests.

These files are not applied automatically. The default Code Agent still uses
the broad Karpathy Guidelines skill, while these example skills are only used
when the user selects one in the GUI prompt editor or saves a custom prompt
override.

Current examples:

- `data_analysis/common_checklist.md`: general data analysis checklist.
- `data_analysis/planning_skill.md`: Planner A skill for grounded analysis
  planning.
- `data_analysis/reviewer_skill.md`: Planner B / reviewer skill for checking
  whether the plan preserves user intent and source-data evidence.
- `data_analysis/qa_skill.md`: QA skill for evidence-based review of analysis
  outputs.
- `data_visualization/checklist.md`: general visualization checklist for
  truthful, readable, decision-oriented visual outputs.
- `data_visualization/planning_skill.md`: Planner / Reviewer skill for
  decision-oriented dashboard and visualization briefs.
- `data_visualization/implementation_skill.md`: Code Agent skill for building
  usable dashboard and chart interfaces.
- `data_visualization/qa_skill.md`: QA skill for visual correctness,
  interaction, accessibility, and interpretation risks.
