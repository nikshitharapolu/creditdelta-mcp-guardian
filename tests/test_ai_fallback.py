import tempfile
import unittest
from unittest.mock import Mock
from creditdelta_mcp.ai_guardian import AIReviewer, FallbackReviewer, assess
from creditdelta_mcp.enforcement import GuardedExecutor

SAFE = '{"verdict":"SAFE","reason_code":"ordinary_request"}'
BLOCK = '{"verdict":"BLOCK","reason_code":"instruction_override"}'

class FallbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.offline = AIReviewer(Mock(side_effect=TimeoutError()))
        self.ex = GuardedExecutor(self.tmp.name, reviewer=self.offline)
        self.path = self.ex.reports_directory / "report.md"

    def test_outage_read_write_and_replay(self):
        self.path.write_text("old")
        self.assertEqual(self.ex.propose("read_file", {"path": str(self.path)})["result"]["content"], "old")
        pending = self.ex.propose("write_file", {"path": str(self.path), "content": "new"})
        self.assertEqual(pending["decision"], "REQUIRE_APPROVAL")
        self.assertEqual(self.path.read_text(), "old")
        self.assertEqual(self.ex.resolve_approval(pending["approval_id"], True)["status"], "APPROVED_AND_EXECUTED")
        self.assertEqual(self.path.read_text(), "new")
        self.assertEqual(self.ex.list_audit()[0]["review"]["ai_review"]["status"], "unavailable")
        with self.assertRaises(ValueError):
            self.ex.resolve_approval(pending["approval_id"], True)

    def test_outage_delete_rejection(self):
        self.path.write_text("keep")
        pending = self.ex.propose("delete_file", {"path": str(self.path)})
        self.ex.resolve_approval(pending["approval_id"], False)
        self.assertTrue(self.path.exists())

    def test_unknown_tool_blocks_without_model(self):
        self.assertEqual(self.ex.propose("shell", {})["decision"], "DENY")
        self.offline.transport.assert_not_called()

    def test_provider_fallback(self):
        second = Mock(return_value=SAFE)
        chain = FallbackReviewer([("gemini", self.offline), ("ollama", AIReviewer(second))])
        result, details = assess(self.ex.policy, chain, "write_file", {"path": str(self.path), "content": "public"})
        self.assertEqual(result.decision, "REQUIRE_APPROVAL")
        self.assertEqual(details["ai_review"]["provider"], "ollama")
        self.assertEqual(len(details["ai_review"]["attempts"]), 2)

    def test_block_never_tries_next(self):
        second = Mock(return_value=SAFE)
        chain = FallbackReviewer([("first", AIReviewer(lambda _: BLOCK)), ("second", AIReviewer(second))])
        result, _ = assess(self.ex.policy, chain, "search_company", {"query": "AAPL"})
        self.assertEqual(result.decision, "DENY")
        second.assert_not_called()

    def test_all_unavailable(self):
        chain = FallbackReviewer([("first", self.offline), ("second", self.offline)])
        result, details = assess(self.ex.policy, chain, "search_company", {"query": "AAPL"})
        self.assertEqual(result.decision, "ALLOW")
        self.assertEqual(details["ai_review"]["verdict"], "NOT_RUN")
