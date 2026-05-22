from __future__ import annotations

import unittest
from types import SimpleNamespace

from local_dashboard_runner import extract_code_brief_from_plan, render_single_code_context


class CodeBriefExtractionTests(unittest.TestCase):
    def test_extracts_only_code_brief_section(self) -> None:
        plan = """# Final Plan

## Code Brief
- Outcome: build the app.
- Done when: it runs locally.

## Planner Notes
- Data inspection detail that should not reach the Code Agent.
"""

        brief = extract_code_brief_from_plan(plan)

        self.assertIn("## Code Brief", brief)
        self.assertIn("Outcome: build the app", brief)
        self.assertNotIn("Planner Notes", brief)
        self.assertNotIn("Data inspection detail", brief)

    def test_falls_back_to_full_plan_without_code_brief(self) -> None:
        plan = "# Final Plan\n\n- Legacy compact plan."

        self.assertEqual(extract_code_brief_from_plan(plan), plan)

    def test_single_code_context_uses_code_brief_only(self) -> None:
        plan = """# Final Plan

## Code Brief
- Outcome: build the app.

## Planner Notes
- Internal rationale.
"""
        route = SimpleNamespace(mode="balanced", reason="test route")

        context = render_single_code_context(plan, route)

        self.assertIn("# Planner Brief", context)
        self.assertIn("not as an approved specification", context)
        self.assertIn("Outcome: build the app", context)
        self.assertNotIn("Internal rationale", context)
        self.assertIn("- mode: balanced", context)


if __name__ == "__main__":
    unittest.main()
