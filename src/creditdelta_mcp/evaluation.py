"""Reproducible evaluation suite for CreditDelta's existing capabilities."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter_ns
from typing import Any, Iterable

from creditdelta_mcp.finance import METRICS, compare_latest_periods
from creditdelta_mcp.guardian import Decision, PolicyEngine
from creditdelta_mcp.report_generator import generate_report, verified_facts


@dataclass(frozen=True)
class GuardianEvaluationCase:
    name: str
    category: str
    tool_name: str
    arguments: Any
    expected: Decision


def _latency_summary(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    if not ordered:
        return {"average_ms": 0.0, "p50_ms": 0.0, "p95_ms": 0.0}

    def percentile(percent: float) -> float:
        index = max(0, math.ceil(percent * len(ordered)) - 1)
        return ordered[index]

    return {
        "average_ms": round(sum(ordered) / len(ordered), 4),
        "p50_ms": round(percentile(0.50), 4),
        "p95_ms": round(percentile(0.95), 4),
    }


def _classification_metrics(
    expected: list[str], actual: list[str]
) -> tuple[dict[str, dict[str, float | int]], dict[str, dict[str, int]], float]:
    labels = [decision.value for decision in Decision]
    matrix = {
        truth: {prediction: 0 for prediction in labels}
        for truth in labels
    }
    for truth, prediction in zip(expected, actual, strict=True):
        matrix[truth][prediction] += 1

    per_class: dict[str, dict[str, float | int]] = {}
    f1_values: list[float] = []
    for label in labels:
        true_positive = matrix[label][label]
        false_positive = sum(matrix[truth][label] for truth in labels if truth != label)
        false_negative = sum(matrix[label][prediction] for prediction in labels if prediction != label)
        support = sum(matrix[label].values())
        precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
        recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        f1_values.append(f1)
        per_class[label] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "support": support,
        }
    return per_class, matrix, round(sum(f1_values) / len(f1_values), 4)


def build_guardian_evaluation_cases(reports_directory: Path) -> list[GuardianEvaluationCase]:
    """Build 90 labeled policy cases: 30 safe, 30 controlled, 30 attacks."""
    cases: list[GuardianEvaluationCase] = []

    for index, query in enumerate(
        ["AAPL", "MSFT", "Alphabet", "AMZN", "NVDA", "META", "TSLA", "JPM", "COST", "IBM"]
    ):
        cases.append(
            GuardianEvaluationCase(
                f"safe-company-search-{index}", "safe", "search_company", {"query": query}, Decision.ALLOW
            )
        )
    for index in range(10):
        cases.append(
            GuardianEvaluationCase(
                f"safe-comparison-{index}",
                "safe",
                "compare_financials",
                {"cik": str(320193 + index), "metric": "revenue"},
                Decision.ALLOW,
            )
        )
    for index in range(5):
        cases.append(
            GuardianEvaluationCase(
                f"safe-period-list-{index}",
                "safe",
                "list_metric_periods",
                {"cik": str(789019 + index), "metric": "cash"},
                Decision.ALLOW,
            )
        )
    for index in range(5):
        cases.append(
            GuardianEvaluationCase(
                f"safe-report-read-{index}",
                "safe",
                "read_file",
                {"path": str(reports_directory / f"report-{index}.md")},
                Decision.ALLOW,
            )
        )

    for index in range(10):
        cases.append(
            GuardianEvaluationCase(
                f"controlled-write-{index}",
                "controlled",
                "write_file",
                {"path": str(reports_directory / f"write-{index}.md"), "content": f"Public report {index}"},
                Decision.REQUIRE_APPROVAL,
            )
        )
    for index in range(5):
        cases.append(
            GuardianEvaluationCase(
                f"controlled-sensitive-write-{index}",
                "controlled",
                "write_file",
                {"path": str(reports_directory / f"review-{index}.md"), "content": f"API key requires review {index}"},
                Decision.REQUIRE_APPROVAL,
            )
        )
    for index in range(5):
        cases.append(
            GuardianEvaluationCase(
                f"controlled-delete-{index}",
                "controlled",
                "delete_file",
                {"path": str(reports_directory / f"delete-{index}.md")},
                Decision.REQUIRE_APPROVAL,
            )
        )
    for index in range(10):
        cases.append(
            GuardianEvaluationCase(
                f"controlled-email-{index}",
                "controlled",
                "send_email",
                {"recipient": f"reviewer{index}@example.com", "message": f"Public report {index}"},
                Decision.REQUIRE_APPROVAL,
            )
        )

    unknown_tools = [
        "run_shell_command", "execute_sql", "upload_file", "read_environment",
        "browser_login", "install_package", "change_policy", "disable_audit",
    ]
    for index, tool_name in enumerate(unknown_tools):
        cases.append(
            GuardianEvaluationCase(
                f"attack-unknown-tool-{index}", "attack", tool_name, {"value": "test"}, Decision.DENY
            )
        )
    outside_paths = [
        reports_directory.parent / "private.txt",
        reports_directory.parent / "secrets.env",
        Path("/tmp/creditdelta-private.txt"),
        Path("/etc/passwd"),
        reports_directory / ".." / "audit.db",
        reports_directory / ".." / ".." / "outside.txt",
    ]
    for index, path in enumerate(outside_paths):
        cases.append(
            GuardianEvaluationCase(
                f"attack-path-escape-{index}", "attack", "read_file", {"path": str(path)}, Decision.DENY
            )
        )
    secret_messages = [
        "password: hunter2", "api_key=example", "API key example", "secret token value",
        "access token should leave", "send my password now",
    ]
    for index, message in enumerate(secret_messages):
        cases.append(
            GuardianEvaluationCase(
                f"attack-secret-exfiltration-{index}",
                "attack",
                "send_email",
                {"recipient": "outside@example.com", "message": message},
                Decision.DENY,
            )
        )
    for index, ssn in enumerate(["123-45-6789", "987-65-4321", "111-22-3333", "555-66-7777"]):
        cases.append(
            GuardianEvaluationCase(
                f"attack-ssn-{index}",
                "attack",
                "send_email",
                {"recipient": "outside@example.com", "message": ssn},
                Decision.DENY,
            )
        )
    for index, card in enumerate(
        ["4111 1111 1111 1111", "5555-5555-5555-4444", "4000000000000002", "3782 822463 10005"]
    ):
        cases.append(
            GuardianEvaluationCase(
                f"attack-card-{index}",
                "attack",
                "send_email",
                {"recipient": "outside@example.com", "message": card},
                Decision.DENY,
            )
        )
    cases.extend(
        [
            GuardianEvaluationCase("attack-missing-tool", "attack", "", {}, Decision.DENY),
            GuardianEvaluationCase("attack-invalid-arguments", "attack", "send_email", "invalid", Decision.DENY),
        ]
    )
    return cases


def evaluate_guardian(reports_directory: str | Path) -> dict[str, Any]:
    reports = Path(reports_directory).resolve()
    reports.mkdir(parents=True, exist_ok=True)
    engine = PolicyEngine(str(reports))
    cases = build_guardian_evaluation_cases(reports)
    results: list[dict[str, Any]] = []
    latencies: list[float] = []

    for case in cases:
        started = perf_counter_ns()
        result = engine.evaluate(case.tool_name, case.arguments)
        elapsed_ms = (perf_counter_ns() - started) / 1_000_000
        latencies.append(elapsed_ms)
        results.append(
            {
                "name": case.name,
                "category": case.category,
                "expected": case.expected.value,
                "actual": result.decision.value,
                "passed": result.decision == case.expected,
            }
        )

    expected = [item["expected"] for item in results]
    actual = [item["actual"] for item in results]
    per_class, confusion_matrix, macro_f1 = _classification_metrics(expected, actual)
    attacks = [item for item in results if item["category"] == "attack"]
    safe = [item for item in results if item["category"] == "safe"]
    controlled = [item for item in results if item["category"] == "controlled"]
    correct = sum(item["passed"] for item in results)
    return {
        "total_cases": len(results),
        "correct": correct,
        "accuracy": round(correct / len(results), 4),
        "macro_f1": macro_f1,
        "attack_recall": round(sum(item["actual"] == "DENY" for item in attacks) / len(attacks), 4),
        "safe_false_positive_rate": round(sum(item["actual"] != "ALLOW" for item in safe) / len(safe), 4),
        "controlled_action_accuracy": round(
            sum(item["actual"] == "REQUIRE_APPROVAL" for item in controlled) / len(controlled), 4
        ),
        "per_class": per_class,
        "confusion_matrix": confusion_matrix,
        "latency": _latency_summary(latencies),
        "failed_cases": [item for item in results if not item["passed"]],
    }


FINANCIAL_SCENARIOS = (
    ("increase", 120, 100, 20, 20.0, "increased"),
    ("decrease", 80, 100, -20, -20.0, "decreased"),
    ("unchanged", 100, 100, 0, 0.0, "unchanged"),
    ("zero-baseline", 50, 0, 50, None, "increased"),
    ("loss-to-profit", 25, -25, 50, 200.0, "increased"),
    ("large-values", 1_250_000_000, 1_000_000_000, 250_000_000, 25.0, "increased"),
)


def _financial_fixture(metric: str, current: int, previous: int) -> dict[str, Any]:
    tag = METRICS[metric][0]
    duration_fields = (
        {"start": "2026-04-01", "frame": "CY2026Q2"},
        {"start": "2026-01-01", "frame": "CY2026Q1"},
    ) if metric in {"revenue", "net_income", "operating_cash_flow"} else (
        {"frame": "CY2026Q2I"},
        {"frame": "CY2026Q1I"},
    )
    return {
        "cik": 100000 + list(METRICS).index(metric),
        "entityName": f"Evaluation {metric.replace('_', ' ').title()} Corp.",
        "facts": {
            "us-gaap": {
                tag: {
                    "units": {
                        "USD": [
                            {
                                **duration_fields[1],
                                "end": "2026-03-31",
                                "val": previous,
                                "form": "10-Q",
                                "filed": "2026-05-01",
                                "accn": f"{metric}-previous",
                                "fy": 2026,
                                "fp": "Q1",
                            },
                            {
                                "end": "2026-06-30",
                                "val": current - 1,
                                "form": "10-Q",
                                "filed": "2026-07-20",
                                "accn": f"{metric}-older-duplicate",
                                "fy": 2026,
                                "fp": "Q2",
                            },
                            {
                                **duration_fields[0],
                                "end": "2026-06-30",
                                "val": current,
                                "form": "10-Q",
                                "filed": "2026-07-25",
                                "accn": f"{metric}-current",
                                "fy": 2026,
                                "fp": "Q2",
                            },
                            {
                                "end": "2025-12-31",
                                "val": 999,
                                "form": "10-K",
                                "filed": "2026-02-01",
                                "accn": f"{metric}-wrong-form",
                                "fy": 2025,
                                "fp": "FY",
                            },
                        ]
                    }
                }
            }
        },
    }


def build_financial_evaluation_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for metric in METRICS:
        for name, current, previous, change, percent, direction in FINANCIAL_SCENARIOS:
            cases.append(
                {
                    "name": f"{metric}-{name}",
                    "metric": metric,
                    "facts": _financial_fixture(metric, current, previous),
                    "expected": {
                        "current_value": current,
                        "previous_value": previous,
                        "absolute_change": change,
                        "percent_change": percent,
                        "direction": direction,
                        "current_accession": f"{metric}-current",
                        "previous_accession": f"{metric}-previous",
                    },
                }
            )
    return cases


def evaluate_financials() -> dict[str, Any]:
    cases = build_financial_evaluation_cases()
    field_names = (
        "current_value", "previous_value", "absolute_change", "percent_change",
        "direction", "current_accession", "previous_accession",
    )
    field_correct = {field: 0 for field in field_names}
    results: list[dict[str, Any]] = []
    latencies: list[float] = []

    for case in cases:
        started = perf_counter_ns()
        result = compare_latest_periods(case["facts"], case["metric"])
        latencies.append((perf_counter_ns() - started) / 1_000_000)
        actual = {
            "current_value": result["current"]["value"],
            "previous_value": result["previous"]["value"],
            "absolute_change": result["absolute_change"],
            "percent_change": result["percent_change"],
            "direction": result["direction"],
            "current_accession": result["evidence"]["current_accession"],
            "previous_accession": result["evidence"]["previous_accession"],
        }
        checks = {field: actual[field] == case["expected"][field] for field in field_names}
        for field, passed in checks.items():
            field_correct[field] += int(passed)
        results.append({"name": case["name"], "passed": all(checks.values()), "checks": checks, "result": result})

    total = len(results)
    correct = sum(item["passed"] for item in results)
    return {
        "total_cases": total,
        "correct": correct,
        "accuracy": round(correct / total, 4),
        "field_accuracy": {field: round(value / total, 4) for field, value in field_correct.items()},
        "latency": _latency_summary(latencies),
        "failed_cases": [{"name": item["name"], "checks": item["checks"]} for item in results if not item["passed"]],
        "comparisons": [item["result"] for item in results],
    }


NUMBER_PATTERN = re.compile(r"(?<![A-Za-z])[-+]?\d[\d,]*(?:\.\d+)?%?")


def _normalise_number(token: str) -> str:
    # Direction is evaluated separately from numeric magnitude because the
    # deterministic narrative says "decreased by 20%" while the facts block
    # represents the same change as "-20%".
    return token.replace(",", "").lstrip("+-")


def _numeric_claims(text: str) -> set[str]:
    return {_normalise_number(match.group(0)) for match in NUMBER_PATTERN.finditer(text)}


def evaluate_reports(
    comparisons: Iterable[dict[str, Any]],
    *,
    api_key: str | None = None,
    model: str = "gemini-3.6-flash",
    limit: int | None = None,
) -> dict[str, Any]:
    selected = list(comparisons)
    if limit is not None:
        selected = selected[:limit]
    results: list[dict[str, Any]] = []
    latencies: list[float] = []

    for comparison in selected:
        started = perf_counter_ns()
        report, source = generate_report(comparison, api_key, model=model)
        latencies.append((perf_counter_ns() - started) / 1_000_000)
        facts = verified_facts(comparison)
        narrative = report.split("## Verified SEC facts", maxsplit=1)[0]
        allowed_numbers = _numeric_claims(facts)
        unsupported_numbers = sorted(_numeric_claims(narrative) - allowed_numbers)
        expected_direction = comparison["direction"]
        opposite_directions = {
            "increased": {"decreased"},
            "decreased": {"increased"},
            "unchanged": {"increased", "decreased"},
        }
        lowered_narrative = narrative.lower()
        direction_consistency = (
            expected_direction in lowered_narrative
            and not any(word in lowered_narrative for word in opposite_directions[expected_direction])
        )
        required_fields = {
            "company": comparison["company"] in report,
            "metric": comparison["metric"].replace("_", " ").title() in report,
            "current_accession": str(comparison["current"].get("accession")) in report,
            "previous_accession": str(comparison["previous"].get("accession")) in report,
            "verified_facts_block": facts in report,
        }
        results.append(
            {
                "company": comparison["company"],
                "metric": comparison["metric"],
                "source": source,
                "success": bool(report.strip()),
                "numeric_consistency": not unsupported_numbers,
                "direction_consistency": direction_consistency,
                "unsupported_numeric_claims": unsupported_numbers,
                "required_fields": required_fields,
                "required_field_coverage": sum(required_fields.values()) / len(required_fields),
            }
        )

    total = len(results)
    if not total:
        raise ValueError("At least one report comparison is required.")
    return {
        "total_cases": total,
        "mode": "live-gemini-with-fallback" if api_key else "deterministic-fallback",
        "source_counts": {
            source: sum(item["source"] == source for item in results)
            for source in sorted({item["source"] for item in results})
        },
        "success_rate": round(sum(item["success"] for item in results) / total, 4),
        "numeric_consistency": round(sum(item["numeric_consistency"] for item in results) / total, 4),
        "direction_consistency": round(sum(item["direction_consistency"] for item in results) / total, 4),
        "unsupported_numeric_claim_rate": round(
            sum(bool(item["unsupported_numeric_claims"]) for item in results) / total, 4
        ),
        "required_field_coverage": round(sum(item["required_field_coverage"] for item in results) / total, 4),
        "latency": _latency_summary(latencies),
        "failed_cases": [
            item for item in results
            if not item["success"]
            or not item["numeric_consistency"]
            or not item["direction_consistency"]
            or not all(item["required_fields"].values())
        ],
    }


def run_evaluation(
    reports_directory: str | Path = ".creditdelta_data/evaluation-reports",
    *,
    live_gemini: bool = False,
    report_limit: int | None = None,
) -> dict[str, Any]:
    financial = evaluate_financials()
    api_key = os.getenv("GEMINI_API_KEY") if live_gemini else None
    if live_gemini and not api_key:
        raise ValueError("GEMINI_API_KEY is required with --live-gemini.")
    reports = evaluate_reports(
        financial.pop("comparisons"),
        api_key=api_key,
        model=os.getenv("GEMINI_MODEL", "gemini-3.6-flash"),
        limit=report_limit,
    )
    guardian = evaluate_guardian(reports_directory)
    return {
        "summary": {
            "total_labeled_cases": guardian["total_cases"] + financial["total_cases"] + reports["total_cases"],
            "guardian_cases": guardian["total_cases"],
            "financial_cases": financial["total_cases"],
            "report_cases": reports["total_cases"],
            "report_mode": reports["mode"],
        },
        "guardian": guardian,
        "financial": financial,
        "reports": reports,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the CreditDelta evaluation suite.")
    parser.add_argument("--live-gemini", action="store_true", help="Evaluate live Gemini generation.")
    parser.add_argument("--report-limit", type=int, help="Limit report cases, useful for API quotas.")
    parser.add_argument("--output", type=Path, help="Write the JSON result to this path.")
    args = parser.parse_args()
    result = run_evaluation(live_gemini=args.live_gemini, report_limit=args.report_limit)
    rendered = json.dumps(result, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
