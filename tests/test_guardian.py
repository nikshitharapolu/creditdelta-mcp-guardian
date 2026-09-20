import tempfile
import unittest
from pathlib import Path

from creditdelta_mcp.guardian import Decision, PolicyEngine


class GuardianTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.reports = Path(self.temp_dir.name) / "reports"
        self.reports.mkdir()
        self.engine = PolicyEngine(str(self.reports))

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_allows_public_creditdelta_read(self):
        result = self.engine.evaluate("compare_financials", {"cik": "0000320193"})
        self.assertEqual(result.decision, Decision.ALLOW)

    def test_denies_unknown_tool(self):
        result = self.engine.evaluate("run_any_shell_command", {"command": "whoami"})
        self.assertEqual(result.decision, Decision.DENY)

    def test_denies_path_outside_approved_directory(self):
        result = self.engine.evaluate("read_file", {"path": "../../private.txt"})
        self.assertEqual(result.decision, Decision.DENY)

    def test_requires_approval_for_file_deletion(self):
        path = self.reports / "apple.txt"
        result = self.engine.evaluate("delete_file", {"path": str(path)})
        self.assertEqual(result.decision, Decision.REQUIRE_APPROVAL)

    def test_requires_approval_for_external_email(self):
        result = self.engine.evaluate(
            "send_email", {"recipient": "friend@example.com", "message": "Apple report"}
        )
        self.assertEqual(result.decision, Decision.REQUIRE_APPROVAL)

    def test_blocks_sensitive_email(self):
        result = self.engine.evaluate(
            "send_email",
            {"recipient": "unknown@example.com", "message": "password: correct-horse"},
        )
        self.assertEqual(result.decision, Decision.DENY)
        self.assertEqual(result.risk, "critical")


if __name__ == "__main__":
    unittest.main()
