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
- For entity-comparison dashboards (brands, products, regions, customers,
  documents, etc.), prefer a stable product frame: filters and KPIs, one
  primary comparison area, a persistent selected-entity detail panel, and an
  evidence table.
- Treat ranked rows, chart marks, suggestions, and search results as selection
  controls when entities are comparable. Selecting an entity should update the
  detail panel and, when useful, related charts.
- If more than two analysis modes are needed, use tabs, segmented views, or
  master-detail instead of one long chart gallery.
- Filters, sorting, tabs, and selected items must update the underlying data,
  metrics, charts, and tables.
- If time exists, avoid market-only trends as the only longitudinal view when
  entities can be selected. Prefer selected entity vs filtered/all comparison,
  or make the market-level basis unmistakable.
- Scores, grades, recommendations, and rankings are allowed when they help the
  user decide, but expose the formula, weights, scale, missing-data treatment,
  and small-sample caveats in concise user-facing language.
- Before coding the layout, define the main user action loop: narrow the data,
  compare candidates, select one, inspect evidence, then revise filters.
- Design for first-time non-technical users. Labels and captions should make
  each view's purpose clear without requiring knowledge of the data pipeline.
- Do not rely on free-text search alone for large entity lists. Provide a
  discoverable selection path such as autocomplete, datalist, searchable select,
  chips, clickable ranked rows, or a filtered suggestion list.
- Make each chart's current basis visible: all filtered data, selected entity,
  selected year range, or comparison group. If no entity is selected, avoid
  showing charts that look entity-specific unless they are clearly labeled as
  overall or market-level views.
- Use plain product language for primary UI labels. Keep analyst/internal terms
  such as raw data, source row, missingness, and outlier out of prominent labels
  unless translated into user-facing language.
- Every tab should answer "what am I looking at?" with a short subtitle, badge,
  empty state, or caption.
- Keep the first screen decision-oriented. Prefer a clear next click over a
  broad collection of charts.
- Preserve material time, category, group, quantity, denominator, unit,
  missingness, and outlier-sensitive fields.
- Make calculations inspectable with labels, metric definitions, tooltips, or
  evidence tables. Keep units and aggregation levels clear.
- Verify non-empty rendering and at least the key interactions.
