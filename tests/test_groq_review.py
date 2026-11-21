import json
import os
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from creditdelta_mcp.ai_guardian import AIReviewer, configured_reviewer, assess
from creditdelta_mcp.groq_review import groq_transport
from creditdelta_mcp.guardian import PolicyEngine

SAFE = '{"verdict":"SAFE","reason_code":"ordinary_request"}'
BLOCK = '{"verdict":"BLOCK","reason_code":"instruction_override"}'

class GroqTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"GUARDIAN_AI_ENABLED":"true", "GROQ_API_KEY":"test-only",
                                          "GUARDIAN_OLLAMA_MODEL":"local-test"}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.policy = PolicyEngine(self.tmp.name)

    def response(self, content=SAFE, finish="stop"):
        return json.dumps({"choices":[{"finish_reason":finish,"message":{"content":content}}]}).encode()

    def test_http_request_and_schema(self):
        with patch("creditdelta_mcp.groq_review.build_opener") as factory:
            factory.return_value.open.return_value.__enter__.return_value.read.return_value = self.response()
            self.assertEqual(groq_transport("{}"), SAFE)
            request = factory.return_value.open.call_args.args[0]
            body = json.loads(request.data)
            self.assertEqual(request.full_url, "https://api.groq.com/openai/v1/chat/completions")
            self.assertTrue(body["response_format"]["json_schema"]["strict"])
            self.assertNotIn("tools", body)
            self.assertEqual(factory.return_value.open.call_args.kwargs["timeout"], 15)

    def test_429_diagnostics_no_key_leak(self):
        with patch("creditdelta_mcp.groq_review.build_opener") as factory:
            factory.return_value.open.side_effect = HTTPError("url",429,"private-key",{},None)
            result = AIReviewer(groq_transport).review("search_company",{"query":"AAPL"},"",self.policy)
            self.assertEqual(result.error_category, "rate_limited")
            self.assertNotIn("private-key", str(result))

    def test_bad_response_and_truncation(self):
        for body, expected in [(b'{}',"invalid_schema"), (self.response(finish="length"),"output_truncated")]:
            with self.subTest(expected=expected), patch("creditdelta_mcp.groq_review.build_opener") as factory:
                factory.return_value.open.return_value.__enter__.return_value.read.return_value = body
                result = AIReviewer(groq_transport).review("search_company",{"query":"AAPL"},"",self.policy)
                self.assertEqual(result.error_category, expected)

    def test_network_error(self):
        with patch("creditdelta_mcp.groq_review.build_opener") as factory:
            factory.return_value.open.side_effect = URLError("private details")
            result = AIReviewer(groq_transport).review("search_company",{"query":"AAPL"},"",self.policy)
            self.assertEqual(result.error_category, "network_error")

    def test_gemini_failure_uses_groq(self):
        with patch("creditdelta_mcp.ai_guardian.gemini_transport",side_effect=TimeoutError()), \
             patch("creditdelta_mcp.groq_review.groq_transport",return_value=BLOCK), \
             patch("creditdelta_mcp.ai_guardian.ollama_transport") as local:
            result, details = assess(self.policy,configured_reviewer(),"search_company",{"query":"AAPL"})
            self.assertEqual(result.decision,"DENY")
            self.assertEqual(details["ai_review"]["provider"],"groq")
            local.assert_not_called()

    def test_groq_only_still_requires_approval(self):
        os.environ["GUARDIAN_PROVIDERS"]="groq"
        with patch("creditdelta_mcp.groq_review.groq_transport",return_value=SAFE):
            result, details = assess(self.policy,configured_reviewer(),"write_file",
                                     {"path":self.tmp.name+"/report.txt","content":"public"})
            self.assertEqual(result.decision,"REQUIRE_APPROVAL")
            self.assertEqual(len(details["ai_review"]["attempts"]),1)

    def test_missing_key_and_invalid_config(self):
        os.environ.pop("GROQ_API_KEY")
        self.assertEqual([name for name,_ in configured_reviewer().reviewers],["gemini","ollama"])
        os.environ["GUARDIAN_PROVIDERS"]="untrusted-provider"
        with self.assertRaises(ValueError):
            configured_reviewer()
