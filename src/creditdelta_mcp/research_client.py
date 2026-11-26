"""Call the read-only CreditDelta MCP server from a synchronous UI."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys

from mcp.client.stdio import StdioServerParameters, stdio_client

try:
    from mcp.client.client import Client
except ImportError:
    Client = None
    from mcp import ClientSession


async def _call(tool: str, arguments: dict) -> dict:
    server = Path(__file__).with_name("server.py")
    env = {
        name: value
        for name, value in os.environ.items()
        if name == "SEC_USER_AGENT"
        or name.startswith("GUARDIAN_")
        or name in {"GEMINI_API_KEY", "GEMINI_MODEL", "GROQ_API_KEY"}
    }
    params = StdioServerParameters(
        command=sys.executable, args=[str(server), "--research-only"], env=env
    )
    if Client is not None:
        async with Client(params) as client:
            reply = await client.call_tool(tool, arguments)
    else:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                reply = await session.call_tool(tool, arguments)

    if getattr(reply, "is_error", getattr(reply, "isError", False)):
        raise RuntimeError("The MCP server could not complete the research request.")
    payload = getattr(reply, "structured_content", getattr(reply, "structuredContent", None))
    content = getattr(reply, "content", ())
    if payload is None and len(content) == 1:
        payload = json.loads(getattr(content[0], "text", "null"))
    if not isinstance(payload, dict) or not isinstance(payload.get("guardian"), dict):
        raise RuntimeError("The MCP server returned an invalid research response.")
    return payload


def call_research_tool(tool: str, arguments: dict, *, context: str = "") -> dict:
    if tool not in {"search_company", "list_metric_periods", "compare_financials"}:
        raise ValueError("Unsupported research tool.")
    return asyncio.run(asyncio.wait_for(_call(tool, {**arguments, "context": context}), 100))
