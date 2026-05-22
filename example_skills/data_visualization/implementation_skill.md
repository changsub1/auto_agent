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

## Purpose

Use this skill when implementing dashboards, chart pages, visual reports, or
interactive data exploration tools. Choose the implementation approach that best
satisfies the user's requested deliverable and the approved product brief.

## Implementation Guidance

- Build the visualization around the user's main decision flow, not around a
  gallery of unrelated charts.
- Provide an immediate overview, then let users segment, compare, and inspect
  details.
- Preserve important data dimensions from the source: time, group, category,
  quantity, denominator, unit, and outlier-sensitive fields.
- When time variables exist and matter, include a time-oriented view unless the
  brief explicitly excludes it.
- When distributions or outliers matter, provide robust summaries, filters,
  or comparison modes so extreme values do not silently dominate the page.
- Use user-friendly filter presets when possible, and allow direct input only
  when it adds real value.
- Keep exact values available through tables, tooltips, or detail panels.
- Make calculations inspectable: label metrics, units, aggregation levels,
  denominators, and filter effects.
- Sort rankings by meaningful metrics and make the current sorting clear.
- Avoid chart clutter. Use tabs, sections, or small multiples when many views
  are needed.
- Use accessible colors and readable text. Do not rely on color alone to encode
  critical status.
- Keep visual styling restrained. Emphasize data hierarchy, not decoration.
- Verify that filters, tabs, sorting, and chart interactions update the actual
  data shown, not only the UI labels.

## Visual Integrity

- Use zero baselines for bar charts unless there is a clearly justified reason.
- Do not use 3D charts or decorative effects that distort comparisons.
- Avoid pie or donut charts for many categories or precise comparisons.
- Use log scales or robust summaries only when they are labeled clearly.
- Do not hide missing values, excluded rows, or threshold filters when they
  materially change conclusions.

