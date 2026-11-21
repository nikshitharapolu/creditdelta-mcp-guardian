import json
import tempfile
import sqlite3
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock

from creditdelta_mcp.ai_guardian import AIReviewer, assess
from creditdelta_mcp.enforcement import GuardedExecutor
from creditdelta_mcp.guardian import PolicyEngine
from creditdelta_mcp.evaluate_ai_guardian import run

SAFE = '{"verdict":"SAFE","reason_code":"ordinary_request"}'
BLOCK = '{"verdict":"BLOCK","reason_code":"instruction_override"}'
REVIEW = '{"verdict":"REVIEW","reason_code":"uncertain"}'


class AIReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.call = Mock(return_value=SAFE)
        self.executor = GuardedExecutor(self.tmp.name, reviewer=AIReviewer(self.call))
        self.path = self.executor.reports_directory / "report.md"
        self.args = {"path": str(self.path), "content": "Public financial summary"}

    def test_rule_denial_skips_provider(self):
        outcome = self.executor.propose("run_shell", {})
        self.assertEqual(outcome["decision"], "DENY")
        self.call.assert_not_called()

    def test_safe_model_cannot_waive_write_approval(self):
        outcome = self.executor.propose("write_file", self.args)
        self.assertEqual(outcome["decision"], "REQUIRE_APPROVAL")
        self.assertFalse(self.path.exists())

    def test_ai_block_creates_no_pending_action(self):
        self.call.return_value = BLOCK
        outcome = self.executor.propose("write_file", self.args)
        self.assertEqual(outcome["decision"], "DENY")
        self.assertEqual(self.executor.list_pending(), [])
        self.assertFalse(self.path.exists())

    def test_review_escalates_read(self):
        self.call.return_value = REVIEW
        self.path.write_text("public")
        outcome = self.executor.propose("read_file", {"path": str(self.path)})
        self.assertEqual(outcome["decision"], "REQUIRE_APPROVAL")
        self.assertIsNone(outcome["result"])

    def test_invalid_output_requires_human_approval(self):
        for value in ("", "not JSON", '{}', '{"verdict":"ALLOW","reason_code":"ordinary_request"}',
                      '{"verdict":"SAFE","reason_code":"instruction_override"}',
                      '{"verdict":"SAFE","reason_code":"ordinary_request","execute":true}'):
            with self.subTest(value=value):
                self.call.return_value = value
                self.assertEqual(self.executor.inspect("write_file", self.args)["decision"], "REQUIRE_APPROVAL")

    def test_timeout_blocks_and_does_not_leak_exception(self):
        self.call.side_effect = TimeoutError("private provider details")
        result = self.executor.propose("write_file", self.args)
        self.assertEqual(result["ai_review"]["status"], "unavailable")
        self.assertNotIn("private provider details", json.dumps(result))

    def test_context_preserved_and_approval_rechecked(self):
        pending = self.executor.propose("write_file", self.args, "Save public analysis")
        self.call.return_value = BLOCK
        result = self.executor.resolve_approval(pending["approval_id"], True)
        self.assertEqual(result["status"], "DENIED_BY_POLICY")
        self.assertEqual(json.loads(self.call.call_args.args[0])["context"], "Save public analysis")
        self.assertFalse(self.path.exists())

    def test_replay_rejected(self):
        pending = self.executor.propose("write_file", self.args)
        self.executor.resolve_approval(pending["approval_id"], True)
        with self.assertRaises(ValueError):
            self.executor.resolve_approval(pending["approval_id"], True)

    def test_disabled_reviewer_still_requires_explicit_approval(self):
        pending = self.executor.propose("write_file", self.args)
        restarted = GuardedExecutor(self.tmp.name)
        result = restarted.resolve_approval(pending["approval_id"], True)
        self.assertEqual(result["status"], "APPROVED_AND_EXECUTED")
        self.assertEqual(result["ai_review"]["status"], "unavailable")
        self.assertTrue(self.path.exists())

    def test_sensitive_data_redacted_before_provider(self):
        self.executor.inspect("write_file", {**self.args, "content": "password example-value"})
        self.assertNotIn("example-value", self.call.call_args.args[0])

    def test_oversize_request_skips_provider(self):
        result = self.executor.inspect("write_file", {**self.args, "content": "x" * 17000})
        self.assertEqual(result["decision"], "DENY")
        self.call.assert_not_called()

    def test_preview_has_no_side_effects(self):
        self.executor.inspect("write_file", self.args)
        self.assertFalse(self.path.exists())
        self.assertEqual(self.executor.list_pending(), [])
        self.assertEqual(self.executor.list_audit(), [])

    def test_audit_contains_structured_review(self):
        self.executor.propose("write_file", self.args)
        review = self.executor.list_audit()[0]["review"]
        self.assertEqual(review["ai_review"]["verdict"], "SAFE")
        self.assertEqual(review["rule_decision"], "REQUIRE_APPROVAL")

    def test_all_combinations_never_lower_policy_restrictions(self):
        rank = {"ALLOW": 0, "REQUIRE_APPROVAL": 1, "DENY": 2}
        policy = PolicyEngine(str(self.executor.reports_directory))
        for tool, args in (("search_company", {"query": "AAPL"}), ("write_file", self.args), ("unknown", {})):
            for response in (SAFE, BLOCK, REVIEW, "invalid"):
                final, details = assess(policy, AIReviewer(lambda _: response), tool, args)
                self.assertGreaterEqual(rank[final.decision.value], rank[details["rule_decision"]])

    def test_concurrent_approval_executes_once(self):
        pending = self.executor.propose("write_file", self.args)
        self.executor._execute = Mock(return_value={"saved": True})
        def approve():
            try:
                return self.executor.resolve_approval(pending["approval_id"], True)["status"]
            except ValueError:
                return "already-resolved"
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: approve(), range(2)))
        self.assertEqual(results.count("APPROVED_AND_EXECUTED"), 1)
        self.executor._execute.assert_called_once()

    def test_existing_database_migration(self):
        with tempfile.TemporaryDirectory() as directory:
            with sqlite3.connect(Path(directory)/"guardian.db") as connection:
                connection.executescript('''
                    CREATE TABLE approvals(id TEXT PRIMARY KEY, tool_name TEXT NOT NULL,
                    arguments_json TEXT NOT NULL, arguments_redacted_json TEXT NOT NULL,
                    status TEXT NOT NULL, created_at TEXT NOT NULL, resolved_at TEXT);
                    CREATE TABLE audit_events(id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL, tool_name TEXT NOT NULL,
                    arguments_redacted_json TEXT NOT NULL, decision TEXT NOT NULL,
                    risk TEXT NOT NULL, status TEXT NOT NULL);
                    INSERT INTO audit_events VALUES(1, 'old', 'test', '{}', 'DENY', 'high', 'DENY');
                ''')
            upgraded = GuardedExecutor(directory, reviewer=AIReviewer(self.call))
            self.assertEqual(upgraded.list_audit()[0]["created_at"], "old")
            self.assertEqual(upgraded.list_audit()[0]["review"], {})
            self.assertEqual(upgraded.propose("unknown", {})["decision"], "DENY")

    def test_evaluation_distinguishes_outage_from_detection(self):
        result = run(AIReviewer(lambda _: "invalid"))
        self.assertEqual(result["review_completion_rate"], 0)
        self.assertEqual(result["combined_operational"]["benign_denial_rate"], 0)
