"""Hosted Groq review adapter; no tool execution or arbitrary destination."""
import json
import os
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
from urllib.error import URLError, HTTPError

from creditdelta_mcp.ai_guardian import REASONS, SYSTEM_PROMPT, ReviewFailure

SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["SAFE", "REVIEW", "BLOCK"]},
        "reason_code": {"type": "string", "enum": list(REASONS)},
    },
    "required": ["verdict", "reason_code"],
    "additionalProperties": False,
}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ReviewFailure("invalid_api_request")


def groq_transport(payload: str) -> str:
    key = os.getenv("GROQ_API_KEY", "").strip()
    if not key:
        raise ReviewFailure("configuration_missing")
    model = os.getenv("GUARDIAN_GROQ_MODEL", "openai/gpt-oss-20b").strip()
    if not model:
        raise ReviewFailure("configuration_missing")
    body = {
        "model": model,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                     {"role": "user", "content": payload}],
        "temperature": 0,
        "max_completion_tokens": 1024,
        "stream": False,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "guardian_review", "strict": True, "schema": SCHEMA},
        },
    }
    if model in {"openai/gpt-oss-20b", "openai/gpt-oss-120b"}:
        body["reasoning_effort"] = "low"
    request = Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 "User-Agent": "CreditDelta-Guardian/1.0"},
        method="POST",
    )
    # No retries, redirects, proxies, tools, or raw error logging.
    opener = build_opener(ProxyHandler({}), NoRedirect())
    try:
        with opener.open(request, timeout=15) as response:
            raw = response.read(65537)
    except HTTPError:
        raise
    except URLError as exc:
        category = "timeout" if isinstance(exc.reason, TimeoutError) else "network_error"
        raise ReviewFailure(category) from None
    if len(raw) > 65536:
        raise ReviewFailure("response_too_large")
    try:
        obj = json.loads(raw)
        choice = obj["choices"][0]
        finish = choice.get("finish_reason")
        if finish == "length":
            raise ReviewFailure("output_truncated")
        if finish == "content_filter" or choice["message"].get("refusal"):
            raise ReviewFailure("provider_content_block")
        if finish != "stop" or choice["message"].get("tool_calls"):
            raise ReviewFailure("invalid_schema")
        content = choice["message"]["content"]
        if not isinstance(content, str):
            raise ReviewFailure("invalid_schema")
        return content
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        raise ReviewFailure("invalid_schema") from None
