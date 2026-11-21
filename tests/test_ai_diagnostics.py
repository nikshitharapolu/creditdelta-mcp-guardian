import json
import tempfile
import unittest
from unittest.mock import Mock

from creditdelta_mcp.ai_guardian import AIReviewer, ReviewFailure, assess
from creditdelta_mcp.guardian import PolicyEngine
from creditdelta_mcp.evaluate_ai_guardian import run


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.policy = PolicyEngine(self.directory.name)

    def review(self, transport):
        return AIReviewer(transport).review("search_company", {"query": "AAPL"}, "", self.policy)

    def test_response_categories(self):
        for text, expected in (
            ("", "empty_response"), ("{", "invalid_json"),
            ('{}', "invalid_schema"),
            ('{"verdict":[],"reason_code":"ordinary_request"}', "invalid_schema"),
            ('{"verdict":"SAFE","reason_code":"uncertain"}', "inconsistent_verdict"),
        ):
            with self.subTest(expected=expected):
                result = self.review(lambda _: text)
                self.assertEqual(result.error_category, expected)
                self.assertEqual(result.verdict, "NOT_RUN")

    def test_http_categories_and_no_exception_leak(self):
        for status, expected in ((429, "rate_limited"), (403, "authentication_or_permission"),
                                 (404, "model_or_endpoint_not_found"), (503, "provider_unavailable"),
                                 (400, "invalid_api_request"), (504, "timeout")):
            exc = RuntimeError("PRIVATE-KEY-AND-REQUEST")
            exc.code = status
            result = self.review(Mock(side_effect=exc))
            self.assertEqual(result.error_category, expected)
            self.assertNotIn("PRIVATE", repr(result))

    def test_timeout_category(self):
        self.assertEqual(self.review(Mock(side_effect=TimeoutError())).error_category, "timeout")

    def test_truncated_category(self):
        self.assertEqual(self.review(Mock(side_effect=ReviewFailure("output_truncated"))).error_category,
                         "output_truncated")

    def test_failure_uses_fixed_read_policy(self):
        result, details = assess(self.policy, AIReviewer(Mock(side_effect=TimeoutError())),
                                 "search_company", {"query": "AAPL"})
        self.assertEqual(result.decision, "ALLOW")
        self.assertEqual(details["ai_review"]["error_category"], "timeout")

    def test_progress_and_separate_completion_counts(self):
        progress = []
        result = run(AIReviewer(lambda _: "bad json"), progress.append)
        self.assertEqual(len(progress), 32)
        self.assertEqual(result["error_counts"], {"invalid_json": 15})
        self.assertEqual(result["completed_review_cases"], 0)
        self.assertIsNone(result["completed_review_accuracy"])
        self.assertEqual(result["rows"][-1]["ai_status"], "skipped")
