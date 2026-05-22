---
id: data-visualization/implementation-skill
label: Data Visualization Implementation Skill
source: Orchestra example skills
description: Code Agent guidance for implementing clear, truthful, usable dashboards and chart interfaces.
license: Project
recommended_for: code_agent
variant: example
---

# Data Visualization Implementation Skill

Use this skill for dashboards, chart pages, visual reports, and interactive data
exploration tools.

Guidance:
- Inspect the actual source data first. Decide the primary user decision flow;
  do not merely execute a planner chart list.
- Build one clear reading path: overview, comparison or segmentation, then
  detail inspection.
- If more than two analysis modes are needed, use tabs, segmented views, or
  master-detail instead of one long chart gallery.
- Filters, sorting, tabs, and selected items must update the underlying data,
  metrics, charts, and tables.
- Preserve material time, category, group, quantity, denominator, unit,
  missingness, and outlier-sensitive fields.
- Make calculations inspectable with labels, metric definitions, tooltips, or
  evidence tables. Keep units and aggregation levels clear.
- Verify non-empty rendering and at least the key interactions.
