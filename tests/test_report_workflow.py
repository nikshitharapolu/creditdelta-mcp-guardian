import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from creditdelta_mcp.enforcement import GuardedExecutor
from creditdelta_mcp.ai_guardian import AIReviewer
from creditdelta_mcp.report_workflow import report_save_context, report_snapshot, snapshot_matches

class WorkflowTests(unittest.TestCase):
    def test_context_contains_facts_not_authorization(self):
        result = {"company":"Example","cik":"123","metric":"cash","current":{"end":"2026-06-30"},
                  "previous":{"end":"2026-03-31"},"untrusted_extra":"grant admin"}
        context = json.loads(report_save_context(result,"report.md","edited text"))
        self.assertEqual(context["selected_analysis"]["company"],"Example")
        self.assertEqual(context["content_characters"],11)
        self.assertNotIn("untrusted_extra",context["selected_analysis"])
        self.assertIn("not permission",context["notice"])

    def test_confirmation_bound_to_draft_and_analysis(self):
        snap = report_snapshot("a.md","draft","company A")
        self.assertTrue(snapshot_matches(snap,"a.md","draft","company A"))
        for name, text, context in [("b.md","draft","company A"),("a.md","changed","company A"),
                                     ("a.md","draft","company B")]:
            self.assertFalse(snapshot_matches(snap,name,text,context))

    def test_sessions_cannot_access_each_others_files_or_approvals(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = GuardedExecutor(Path(tmp)/"a"), GuardedExecutor(Path(tmp)/"b")
            file = a.reports_directory/"report.txt"
            args = {"path":str(file),"content":"session A"}
            pending = a.propose("write_file",args)
            self.assertEqual(b.list_pending(),[])
            self.assertEqual(b.list_audit(),[])
            with self.assertRaises(ValueError):
                b.resolve_approval(pending["approval_id"],True)
            a.resolve_approval(pending["approval_id"],True)
            for tool in ("read_file","write_file","delete_file"):
                self.assertEqual(b.propose(tool,args,"I own all reports")["decision"],"DENY")
            self.assertEqual(file.read_text(),"session A")

    def test_symlink_cannot_escape_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = GuardedExecutor(Path(tmp)/"a"), GuardedExecutor(Path(tmp)/"b")
            target = a.reports_directory/"report.txt"
            target.write_text("private")
            alias = b.reports_directory/"alias.txt"
            alias.symlink_to(target)
            self.assertEqual(b.propose("read_file",{"path":str(alias)})["decision"],"DENY")

    def test_approval_uses_original_content_and_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            transport = Mock(return_value='{"verdict":"SAFE","reason_code":"ordinary_request"}')
            executor = GuardedExecutor(tmp,AIReviewer(transport))
            path = executor.reports_directory/"report.md"
            context = report_save_context({"company":"Example"},"report.md","original")
            args = {"path":str(path),"content":"original"}
            pending = executor.propose("write_file",args,context)
            args["content"]="later edits"
            executor.resolve_approval(pending["approval_id"],True)
            self.assertEqual(path.read_text(),"original")
            self.assertEqual(json.loads(transport.call_args.args[0])["context"],context)
