---
id: data-visualization/qa-skill
label: Data Visualization QA Skill
source: Orchestra example skills
description: QA guidance for checking dashboard usefulness, visual correctness, and interpretation risks.
license: Project
recommended_for: qa_agent
variant: example
---

# Data Visualization QA Skill

## Purpose

Use this skill when reviewing generated dashboards, chart pages, visual reports,
or interactive data tools. Passing QA requires more than successful execution:
the visualization must support truthful interpretation and the user's intended
decision.

## QA Checklist

- Confirm the app runs and the primary visual views render with non-empty data.
- Check whether the dashboard answers the user's stated decision problem.
- Check whether the source data dimensions are represented appropriately:
  time, category, group, quantity, denominator, unit, and relevant outliers.
- If time variables are present and important, flag missing time-trend analysis.
- If group comparison is present, check sample size, denominator, and time range
  comparability.
- If values are skewed or outlier-sensitive, check whether average-only views
  mislead the user.
- Verify that filters, presets, tabs, sorting, search, and drill-down controls
  update the displayed charts and tables correctly.
- For entity-comparison dashboards, interact with the product flow: filter the
  data, choose an entity from a row/chart/suggestion/search result, verify the
  detail panel changes, switch views, and verify the selected or filtered basis
  remains clear.
- Check whether the first screen gives a clear next action, not just a
  collection of metrics and charts.
- If a score, grade, recommendation, or ranking is shown, check that the
  formula, weights or basis, scale, and missing/small-sample caveats are visible
  enough for a user to trust but not overread it.
- If time fields exist and entities can be selected, check whether trend views
  show selected entity vs filtered/all context, or clearly state that the trend
  is market-level only.
- For large entity lists, fail or warn when the only discovery path is exact
  free-text search and no clickable list, suggestion list, autocomplete,
  searchable select, or equivalent path is available.
- Check whether chart types fit the analytical task:
  - bars or dot plots for comparison
  - lines for time trends
  - histograms, box plots, or quantile summaries for distribution
  - scatter plots for relationships
  - stacked bars or treemaps only when part-to-whole structure matters
- Check for visual distortion: truncated axes, 3D effects, overloaded colors,
  unlabeled units, unclear legends, unreadable labels, or misleading ordering.
- Check whether important calculations can be audited through labels, tooltips,
  tables, or documented metric definitions.
- Check accessibility: readable text, contrast, colorblind-safe choices,
  keyboard-accessible controls where practical, and no color-only critical
  meaning.
- Check whether conclusions overclaim beyond what the data supports.

## Verdict Guidance

- PASS only when the app runs, key charts render, interactions work, and the
  visual design supports the intended decision without major distortion.
- PASS_WITH_WARNINGS when the core result works but has minor visual,
  accessibility, or interpretation issues.
- FAIL when the app does not run, data does not load, key visual requirements
  are missing, or the visualization materially misleads the user.
- INCONCLUSIVE when evidence is insufficient to judge visual behavior.
