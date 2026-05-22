---
id: data-visualization/checklist
label: Data Visualization Checklist
source: Orchestra example skills
description: General checklist for truthful, readable, decision-oriented data visualization.
license: Project
recommended_for: planner, planner_a, reviewer, planner_b, code_agent, qa_agent
variant: example
---

# Data Visualization Checklist

## Purpose

Use this checklist when a task involves charts, dashboards, visual reports, or
interactive visual analysis. The goal is not to decorate data, but to help the
audience understand the meaning of the data accurately and make better
decisions.

## Core Principles

- Start from the audience and decision. Identify who will read the visualization
  and what decision, comparison, or question it should support.
- Choose the chart from the analytical task, not from visual novelty.
- Separate quantity, ratio, time, distribution, relationship, ranking,
  composition, and hierarchy. They need different visual encodings.
- Prefer direct, familiar encodings when possible: position and length are
  usually easier to compare than angle, area, or color intensity.
- Preserve units, denominators, time ranges, sample sizes, and aggregation
  levels. A clean chart is not useful if the meaning is unclear.
- Show uncertainty, missingness, extreme values, or filtering rules when they
  materially affect interpretation.
- Avoid visual effects that distort judgment: 3D charts, decorative gradients,
  unnecessary icons, overloaded colors, misleading axes, and excessive labels.
- Use color as information. Do not use many colors when ordering, grouping,
  highlighting, or status can be shown more clearly another way.
- Make the important comparison visible without requiring the user to inspect
  every mark manually.
- A dashboard should have a reading path: overview, filter or segment,
  comparison, detail, and validation path back to source rows or summary tables.

## Chart Selection

- Use bars or dot plots for category comparison and ranking.
- Use lines for time-series trends. Keep time ordering clear.
- Use histograms, density plots, box plots, or quantile summaries for
  distributions and outliers.
- Use scatter plots for relationships between two quantitative variables.
- Use grouped or small-multiple views when comparing trends across groups.
- Use stacked bars carefully. They are better for part-to-whole composition
  than for precise comparison of internal segments.
- Use pie or donut charts only for a small number of parts of one whole where
  rough proportion is enough.
- Use treemaps only when part-to-whole hierarchy matters and precise comparison
  is not the main task.
- Use tables when users need exact values, auditability, or many dimensions.

## Integrity Checks

- Check whether the baseline matters. Bar charts normally need a meaningful
  zero baseline.
- Check whether a log scale, robust summary, or filtering option is needed when
  values span orders of magnitude.
- Check whether the chosen denominator is comparable across groups.
- Check whether average values hide skew, outliers, or group-size differences.
- Check whether the latest value alone hides an important time trend.
- Check whether sorting makes the intended comparison easier.
- Check whether labels, units, legends, and tooltip values make the calculation
  transparent.
- Check whether the visualization supports accessibility: sufficient contrast,
  colorblind-safe palettes, keyboard-reachable controls, and readable text.

