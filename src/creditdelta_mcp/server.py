"""CreditDelta MCP server."""

from __future__ import annotations

import sys
from pathlib import Path

# MCP Inspector loads this file directly. Make the src-layout package visible
# even when the development launcher creates an isolated process.
SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from mcp.server import MCPServer

from creditdelta_mcp.benchmark import run_benchmark
from creditdelta_mcp.enforcement import GuardedExecutor
from creditdelta_mcp.finance import METRICS, compare_latest_periods, latest_periods
from creditdelta_mcp.guardian import PolicyEngine
from creditdelta_mcp.sec_client import SECClient


mcp = MCPServer("CreditDelta")
sec = SECClient()
guardian = PolicyEngine()
executor = GuardedExecutor()


@mcp.tool()
def search_company(query: str, limit: int = 5) -> list[dict[str, str]]:
    """Find a public company and its SEC CIK using a name or ticker."""
    return sec.search_company(query, limit)


@mcp.tool()
def list_metric_periods(
    cik: str, metric: str, form: str = "10-Q", count: int = 4
) -> dict:
    """List recent SEC values for a supported financial metric.

    Supported metrics: revenue, cash, current_debt, net_income,
    operating_cash_flow.
    """
    facts = sec.company_facts(cik)
    return latest_periods(facts, metric, form, count)


@mcp.tool()
def compare_financials(cik: str, metric: str, form: str = "10-Q") -> dict:
    """Compare the two most recent SEC values for one financial metric."""
    facts = sec.company_facts(cik)
    return compare_latest_periods(facts, metric, form)


@mcp.tool()
def evaluate_tool_call(tool_name: str, arguments: dict) -> dict:
    """Ask MCP Guardian whether a proposed tool call is safe to execute."""
    return guardian.evaluate(tool_name, arguments).to_dict()


@mcp.tool()
def guarded_action(tool_name: str, arguments: dict) -> dict:
    """Evaluate and safely execute, block, or queue a protected local action."""
    return executor.propose(tool_name, arguments)


@mcp.tool()
def resolve_approval(approval_id: str, approve: bool) -> dict:
    """Approve or reject one pending guarded action."""
    return executor.resolve_approval(approval_id, approve)


@mcp.tool()
def list_pending_actions() -> list[dict]:
    """List actions waiting for explicit user approval."""
    return executor.list_pending()


@mcp.tool()
def list_audit_events(limit: int = 20) -> list[dict]:
    """Return recent redacted Guardian decisions and execution outcomes."""
    return executor.list_audit(limit)


@mcp.tool()
def run_security_benchmark() -> dict:
    """Measure Guardian correctness and decision latency on adversarial cases."""
    return run_benchmark(executor.reports_directory)


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
    mcp.run()


if __name__ == "__main__":
    main()
