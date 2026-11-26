import json
from types import SimpleNamespace

import pytest

from creditdelta_mcp import ask_creditdelta as ask


def test_valid_plan():
    plan = {
        "supported": True,
        "company": "AAPL",
        "metric": "revenue",
        "form": "10-Q",
    }
    assert ask.validate_plan(json.dumps(plan)) == plan


@pytest.mark.parametrize(
    "changes",
    [
        {"supported": False},
        {"company": ""},
        {"metric": "invented_metric"},
        {"form": "invalid_form"},
        {"command": "delete_all_reports"},
    ],
)
def test_rejects_unsupported_or_invalid_plans(changes):
    plan = {
        "supported": True,
        "company": "AAPL",
        "metric": "revenue",
        "form": "10-Q",
    }
    plan.update(changes)

    with pytest.raises(ValueError):
        ask.validate_plan(json.dumps(plan))


@pytest.mark.parametrize(
    "decision,should_stop",
    [
        ("ALLOW", False),
        ("DENY", True),
        ("REQUIRE_APPROVAL", True),
        ("UNEXPECTED", True),
    ],
)
def test_guardian_gate(monkeypatch, decision, should_stop):
    state = SimpleNamespace()
    monkeypatch.setattr(ask, "st", SimpleNamespace(session_state=state))

    calls = []
    matches = [{"ticker": "AAPL"}]

    def call_research_tool(tool, arguments, *, context):
        calls.append((tool, arguments, context))
        return {
            "guardian": {"final_decision": decision},
            "result": None if should_stop else matches,
        }

    monkeypatch.setattr(ask, "call_research_tool", call_research_tool)

    arguments = {"query": "AAPL"}
    request = "Compare Apple's revenue"

    if should_stop:
        with pytest.raises(ValueError, match="Guardian did not allow"):
            ask.run_research("search_company", arguments, request)
    else:
        assert ask.run_research("search_company", arguments, request) == matches

    assert calls == [("search_company", arguments, request)]
    assert state.ask_check["final_decision"] == decision