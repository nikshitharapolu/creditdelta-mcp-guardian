"""Deterministic policy engine for MCP tool calls."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any


class Decision(StrEnum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"


@dataclass(frozen=True)
class PolicyResult:
    decision: Decision
    risk: str
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["decision"] = self.decision.value
        value["reasons"] = list(self.reasons)
        return value


class PolicyEngine:
    """Apply least-privilege rules before an MCP tool executes.

    This first version is intentionally deterministic: an LLM may later explain
    a result, but it cannot override the security decision.
    """

    SAFE_READ_TOOLS = {
        "search_company",
        "list_metric_periods",
        "compare_financials",
    }
    SENSITIVE_PATTERNS = (
        ("secret", re.compile(r"\b(?:api[_ -]?key|password|secret|token)\b", re.I)),
        ("social security number", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
        ("credit card number", re.compile(r"\b(?:\d[ -]*?){13,19}\b")),
    )

    def __init__(self, allowed_directory: str = "reports") -> None:
        self.allowed_directory = Path(allowed_directory).resolve()

    def evaluate(self, tool_name: str, arguments: dict[str, Any]) -> PolicyResult:
        if not isinstance(tool_name, str) or not tool_name.strip():
            return PolicyResult(Decision.DENY, "critical", ("Tool name is missing.",))
        if not isinstance(arguments, dict):
            return PolicyResult(Decision.DENY, "critical", ("Tool arguments must be an object.",))

        name = tool_name.strip()
        sensitive = self._find_sensitive_data(arguments)

        if name in self.SAFE_READ_TOOLS:
            if sensitive:
                return PolicyResult(
                    Decision.DENY,
                    "high",
                    (f"Unexpected sensitive data detected: {', '.join(sensitive)}.",),
                )
            return PolicyResult(
                Decision.ALLOW,
                "low",
                ("Read-only CreditDelta operation using public SEC data.",),
            )

        if name in {"read_file", "write_file", "delete_file"}:
            path_value = arguments.get("path")
            if not isinstance(path_value, str) or not path_value.strip():
                return PolicyResult(Decision.DENY, "high", ("A valid file path is required.",))
            requested = Path(path_value).expanduser().resolve()
            if not self._is_within_allowed_directory(requested):
                return PolicyResult(
                    Decision.DENY,
                    "critical",
                    ("File path is outside the approved reports directory.",),
                )
            if name == "read_file":
                return PolicyResult(Decision.ALLOW, "low", ("Read is limited to the approved directory.",))
            if name == "write_file":
                if sensitive:
                    return PolicyResult(
                        Decision.REQUIRE_APPROVAL,
                        "high",
                        (f"Content may contain {', '.join(sensitive)}.", "Writing changes local data."),
                    )
                return PolicyResult(
                    Decision.REQUIRE_APPROVAL,
                    "medium",
                    ("Writing changes local data and requires confirmation.",),
                )
            return PolicyResult(
                Decision.REQUIRE_APPROVAL,
                "high",
                ("Deleting a file is a destructive action.",),
            )

        if name == "send_email":
            if sensitive:
                return PolicyResult(
                    Decision.DENY,
                    "critical",
                    (f"Possible data exfiltration: {', '.join(sensitive)} detected.",),
                )
            return PolicyResult(
                Decision.REQUIRE_APPROVAL,
                "high",
                ("Email sends information outside the system.",),
            )

        return PolicyResult(
            Decision.DENY,
            "critical",
            ("Unknown tools are denied by default.",),
        )

    def _is_within_allowed_directory(self, requested: Path) -> bool:
        try:
            requested.relative_to(self.allowed_directory)
            return True
        except ValueError:
            return False

    def _find_sensitive_data(self, value: Any) -> list[str]:
        text = self._flatten(value)
        return [label for label, pattern in self.SENSITIVE_PATTERNS if pattern.search(text)]

    def _flatten(self, value: Any) -> str:
        if isinstance(value, dict):
            return " ".join(f"{key} {self._flatten(item)}" for key, item in value.items())
        if isinstance(value, (list, tuple, set)):
            return " ".join(self._flatten(item) for item in value)
        return str(value)
