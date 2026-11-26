"""CreditDelta MCP server."""

from __future__ import annotations

import sys
from pathlib import Path

# MCP Inspector loads this file directly. Make the src-layout package visible
# even when the development launcher creates an isolated process.
SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

try:
    from mcp.server import MCPServer
except ImportError:
    from mcp.server.fastmcp import FastMCP as MCPServer

from creditdelta_mcp.benchmark import run_benchmark
from creditdelta_mcp.enforcement import GuardedExecutor
from creditdelta_mcp.ai_guardian import assess, configured_reviewer
from creditdelta_mcp.finance import METRICS, compare_latest_periods, latest_periods
from creditdelta_mcp.guardian import Decision, PolicyEngine
from creditdelta_mcp.sec_client import SECClient


mcp = MCPServer("CreditDelta")
research_mcp = MCPServer("CreditDelta Research")
sec = SECClient()
guardian = PolicyEngine()
reviewer = configured_reviewer()


def get_executor() -> GuardedExecutor:
    return GuardedExecutor(reviewer=reviewer)


def _research(tool, arguments, context, operation) -> dict:
    """Authorize and execute within one MCP call."""
    if len(context) > 1000:
        raise ValueError("Research context must be at most 1000 characters.")
    decision, review = assess(guardian, reviewer, tool, arguments, context)
    result = operation() if decision.decision == Decision.ALLOW else None
    return {"result": result, "guardian": {**decision.to_dict(), **review}}


@research_mcp.tool()
@mcp.tool()
def search_company(query: str, limit: int = 5, context: str = "") -> dict:
    """Find public SEC company matches, subject to Guardian review."""
    return _research(
        "search_company", {"query": query, "limit": limit}, context,
        lambda: sec.search_company(query, limit),
    )


@research_mcp.tool()
@mcp.tool()
def list_metric_periods(
    cik: str, metric: str, form: str = "10-Q", count: int = 4, context: str = ""
) -> dict:
    """List recent SEC values for a supported metric."""
    return _research(
        "list_metric_periods",
        {"cik": cik, "metric": metric, "form": form, "count": count},
        context, lambda: latest_periods(sec.company_facts(cik), metric, form, count),
    )


@research_mcp.tool()
@mcp.tool()
def compare_financials(cik: str, metric: str, form: str = "10-Q", context: str = "") -> dict:
    """Compare two recent SEC values, subject to Guardian review."""
    return _research(
        "compare_financials", {"cik": cik, "metric": metric, "form": form},
        context, lambda: compare_latest_periods(sec.company_facts(cik), metric, form),
    )


@mcp.tool()
def evaluate_tool_call(tool_name: str, arguments: dict, context: str = "") -> dict:
    """Ask MCP Guardian whether a proposed tool call is safe to execute."""
    return get_executor().inspect(tool_name, arguments, context)


@mcp.tool()
def guarded_action(tool_name: str, arguments: dict, context: str = "") -> dict:
    """Evaluate and safely execute, block, or queue a protected local action."""
    return get_executor().propose(tool_name, arguments, context)


@mcp.tool()
def resolve_approval(approval_id: str, approve: bool) -> dict:
    """Approve or reject one pending guarded action."""
    return get_executor().resolve_approval(approval_id, approve)


@mcp.tool()
def list_pending_actions() -> list[dict]:
    """List actions waiting for explicit user approval."""
    return get_executor().list_pending()


@mcp.tool()
def list_audit_events(limit: int = 20) -> list[dict]:
    """Return recent redacted Guardian decisions and execution outcomes."""
    return get_executor().list_audit(limit)


@mcp.tool()
def run_security_benchmark() -> dict:
    """Measure Guardian correctness and decision latency on adversarial cases."""
    return run_benchmark(get_executor().reports_directory)


@mcp.resource("creditdelta://metrics")
def supported_metrics() -> dict[str, list[str]]:
    """Return the financial metrics understood by this starter server."""
    return {"metrics": sorted(METRICS)}


@mcp.prompt()
def analyze_company(company: str, metric: str = "revenue") -> str:
    """Create instructions for analyzing a company's financial change."""
    return (
        f"Analyze {company}'s latest {metric} change. First use search_company to find its CIK. "
        "Then use compare_financials with form 10-Q. Explain the current value, previous value, "
        "percentage change, direction, and SEC filing evidence in simple language."
    )


@mcp.prompt()
def security_review(tool_name: str, arguments: str) -> str:
    """Create instructions for reviewing an action with MCP Guardian."""
    return (
        f"Review the proposed tool call '{tool_name}' with arguments: {arguments}. "
        "Use evaluate_tool_call and explain why the action is ALLOW, DENY, or "
        "REQUIRE_APPROVAL. Do not execute it."
    )


def main() -> None:
    (research_mcp if "--research-only" in sys.argv else mcp).run()


if __name__ == "__main__":
    main()
