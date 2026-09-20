import tempfile
import unittest
from pathlib import Path

from creditdelta_mcp.enforcement import GuardedExecutor


class EnforcementTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.executor = GuardedExecutor(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_write_requires_approval_then_executes(self):
        report = self.executor.reports_directory / "apple.txt"
        proposed = self.executor.propose(
            "write_file", {"path": str(report), "content": "Revenue decreased 1.59%."}
        )
        self.assertEqual(proposed["status"], "REQUIRE_APPROVAL")
        self.assertFalse(report.exists())

        resolved = self.executor.resolve_approval(proposed["approval_id"], True)
        self.assertEqual(resolved["status"], "APPROVED_AND_EXECUTED")
        self.assertEqual(report.read_text(), "Revenue decreased 1.59%.")

    def test_rejected_action_never_executes(self):
        report = self.executor.reports_directory / "blocked.txt"
        proposed = self.executor.propose(
            "write_file", {"path": str(report), "content": "Do not write"}
        )
        resolved = self.executor.resolve_approval(proposed["approval_id"], False)
        self.assertEqual(resolved["status"], "REJECTED")
        self.assertFalse(report.exists())

    def test_sensitive_email_is_blocked_without_pending_action(self):
        proposed = self.executor.propose(
            "send_email", {"recipient": "outside@example.com", "message": "password secret123"}
        )
        self.assertEqual(proposed["status"], "DENY")
        self.assertIsNone(proposed["approval_id"])
        self.assertFalse(self.executor.outbox_path.exists())

    def test_delete_moves_file_to_recoverable_trash(self):
        report = self.executor.reports_directory / "old.txt"
        report.write_text("recover me")
        proposed = self.executor.propose("delete_file", {"path": str(report)})
        resolved = self.executor.resolve_approval(proposed["approval_id"], True)
        recovered = Path(resolved["result"]["recoverable_copy"])
        self.assertFalse(report.exists())
        self.assertEqual(recovered.read_text(), "recover me")

    def test_audit_redacts_sensitive_message(self):
        self.executor.propose(
            "send_email", {"recipient": "outside@example.com", "message": "password secret123"}
        )
        latest = self.executor.list_audit(1)[0]
        self.assertEqual(latest["arguments"]["message"], "[REDACTED SENSITIVE CONTENT]")


if __name__ == "__main__":
    unittest.main()
