import unittest

from creditdelta_mcp.report_generator import build_prompt, deterministic_report, generate_report


SAMPLE = {
    "company": "Example Inc.",
    "metric": "revenue",
    "current": {"end": "2026-06-30", "value": 120, "accession": "current-1"},
    "previous": {"end": "2026-03-31", "value": 100, "accession": "previous-1"},
    "absolute_change": 20,
    "percent_change": 20.0,
    "direction": "increased",
}


class ReportGeneratorTests(unittest.TestCase):
    def test_template_contains_verified_evidence(self):
        report = deterministic_report(SAMPLE)
        self.assertIn("Example Inc.", report)
        self.assertIn("current-1", report)
        self.assertIn("20.00%", report)

    def test_prompt_prohibits_unsupported_claims(self):
        prompt = build_prompt(SAMPLE)
        self.assertIn("ONLY", prompt)
        self.assertIn("Do not introduce", prompt)

    def test_missing_key_uses_template(self):
        report, source = generate_report(SAMPLE, None)
        self.assertEqual(source, "template")
        self.assertIn("Verified SEC facts", report)


if __name__ == "__main__":
    unittest.main()
