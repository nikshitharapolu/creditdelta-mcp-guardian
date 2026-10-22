import tempfile
import unittest
from pathlib import Path

from creditdelta_mcp.evaluation import (
    build_financial_evaluation_cases,
    build_guardian_evaluation_cases,
    evaluate_financials,
    evaluate_reports,
    run_evaluation,
)


class EvaluationTests(unittest.TestCase):
    def test_guardian_dataset_has_balanced_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            cases = build_guardian_evaluation_cases(Path(directory))
        self.assertEqual(len(cases), 90)
        self.assertEqual(sum(case.category == "safe" for case in cases), 30)
        self.assertEqual(sum(case.category == "controlled" for case in cases), 30)
        self.assertEqual(sum(case.category == "attack" for case in cases), 30)

    def test_financial_dataset_has_six_cases_per_metric(self):
        cases = build_financial_evaluation_cases()
        self.assertEqual(len(cases), 30)

    def test_financial_evaluation_passes(self):
        result = evaluate_financials()
        self.assertEqual(result["total_cases"], 30)
        self.assertEqual(result["accuracy"], 1.0)

    def test_report_evaluation_detects_grounded_template(self):
        financial = evaluate_financials()
        result = evaluate_reports(financial["comparisons"], limit=3)
        self.assertEqual(result["total_cases"], 3)
        self.assertEqual(result["numeric_consistency"], 1.0)
        self.assertEqual(result["required_field_coverage"], 1.0)

    def test_full_evaluation_counts_all_cases(self):
        with tempfile.TemporaryDirectory() as directory:
            result = run_evaluation(directory)
        self.assertEqual(result["summary"]["total_labeled_cases"], 150)
        self.assertEqual(result["guardian"]["macro_f1"], 1.0)


if __name__ == "__main__":
    unittest.main()
