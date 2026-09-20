"""Extract comparable financial periods from SEC company facts."""

from __future__ import annotations

from datetime import date
from typing import Any


METRICS: dict[str, tuple[str, ...]] = {
    "revenue": (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ),
    "cash": (
        "CashAndCashEquivalentsAtCarryingValue",
    ),
    "current_debt": (
        "LongTermDebtAndFinanceLeaseObligationsCurrent",
        "LongTermDebtCurrent",
    ),
    "net_income": (
        "NetIncomeLoss",
    ),
    "operating_cash_flow": (
        "NetCashProvidedByUsedInOperatingActivities",
    ),
}

# These metrics represent activity measured over a period of time.
# Their reporting durations must be comparable before calculating changes.
DURATION_METRICS = {
    "revenue",
    "net_income",
    "operating_cash_flow",
}


def _find_metric_facts(
    company_facts: dict[str, Any],
    metric: str,
) -> tuple[str, list[dict[str, Any]]]:
    """Find the first supported XBRL tag containing USD values."""

    if metric not in METRICS:
        raise ValueError(
            f"Unsupported metric: {metric}. "
            f"Choose from {sorted(METRICS)}"
        )

    us_gaap = company_facts.get("facts", {}).get("us-gaap", {})

    for tag in METRICS[metric]:
        concept = us_gaap.get(tag)

        if not concept:
            continue

        units = concept.get("units", {})
        values = units.get("USD")

        if values:
            return tag, values

    raise ValueError(
        f"No comparable SEC fact was found for metric '{metric}'."
    )


def _period_duration(fact: dict[str, Any], metric: str) -> int:
    """Return the reporting duration in days for one SEC fact."""

    start = fact.get("start")
    end = fact.get("end")

    if not start or not end:
        raise ValueError(
            f"SEC duration information is missing for '{metric}', "
            "so the period cannot be compared safely."
        )

    try:
        return (
            date.fromisoformat(end) - date.fromisoformat(start)
        ).days
    except ValueError as exc:
        raise ValueError(
            f"Invalid SEC reporting dates for '{metric}'."
        ) from exc


def _validate_comparable_durations(
    selected: list[dict[str, Any]],
    metric: str,
) -> None:
    """Reject duration facts covering materially different time spans."""

    if metric not in DURATION_METRICS or len(selected) < 2:
        return

    durations = [
        _period_duration(fact, metric)
        for fact in selected
    ]

    # Fiscal quarters and years can differ slightly because of calendar layout.
    # A difference greater than 20 days usually indicates quarterly versus
    # year-to-date data, which should not be compared directly.
    if max(durations) - min(durations) > 20:
        raise ValueError(
            f"The available '{metric}' periods cover different durations "
            f"({durations} days) and are not directly comparable."
        )


def latest_periods(
    company_facts: dict[str, Any],
    metric: str,
    form: str = "10-Q",
    count: int = 2,
) -> dict[str, Any]:
    """Return recent, comparable facts with one value per reporting end date.

    Amendments and repeated facts are deduplicated by period end date. The
    strongest quarterly candidate is preferred for duration metrics, followed
    by the most recently filed value.
    """

    if form not in {"10-Q", "10-K"}:
        raise ValueError(
            "Form must be either '10-Q' or '10-K'."
        )

    if not 1 <= count <= 8:
        raise ValueError(
            "Count must be between 1 and 8."
        )

    tag, raw_facts = _find_metric_facts(company_facts, metric)
    by_end: dict[str, dict[str, Any]] = {}

    def candidate_rank(
        fact: dict[str, Any],
    ) -> tuple[int, int, str]:
        """Prefer quarterly duration facts, then the newest filing.

        A 10-Q can contain both a three-month quarterly value and a
        year-to-date value with the same period end date. For duration metrics,
        a 60–120 day value or SEC quarterly frame is preferred.

        Instant metrics such as cash and current debt do not use duration.
        """

        quarterly = 0

        if metric in DURATION_METRICS and form == "10-Q":
            frame = str(fact.get("frame", ""))

            # SEC quarterly frames commonly look like CY2026Q1.
            # Instant frames often end with I.
            if "Q" in frame and not frame.endswith("I"):
                quarterly = 2

            start = fact.get("start")
            end = fact.get("end")

            if start and end:
                try:
                    days = (
                        date.fromisoformat(end)
                        - date.fromisoformat(start)
                    ).days

                    if 60 <= days <= 120:
                        quarterly = max(quarterly, 1)
                except ValueError:
                    pass

        has_frame = 1 if fact.get("frame") else 0
        filed_date = str(fact.get("filed", ""))

        return quarterly, has_frame, filed_date

    for fact in raw_facts:
        if fact.get("form") != form:
            continue

        if not fact.get("end"):
            continue

        if "val" not in fact:
            continue

        period_end = fact["end"]
        existing = by_end.get(period_end)

        if (
            existing is None
            or candidate_rank(fact) >= candidate_rank(existing)
        ):
            by_end[period_end] = fact

    selected = sorted(
        by_end.values(),
        key=lambda value: value["end"],
        reverse=True,
    )[:count]

    if len(selected) < count:
        raise ValueError(
            f"Only {len(selected)} usable {form} period(s) "
            f"found for '{metric}'."
        )

    _validate_comparable_durations(selected, metric)

    return {
        "company": company_facts.get(
            "entityName",
            "Unknown company",
        ),
        "cik": str(
            company_facts.get("cik", "")
        ).zfill(10),
        "metric": metric,
        "xbrl_tag": tag,
        "unit": "USD",
        "periods": [
            {
                "start": fact.get("start"),
                "end": fact["end"],
                "value": fact["val"],
                "filed": fact.get("filed"),
                "form": fact.get("form"),
                "accession": fact.get("accn"),
                "fiscal_year": fact.get("fy"),
                "fiscal_period": fact.get("fp"),
            }
            for fact in selected
        ],
    }


def compare_latest_periods(
    company_facts: dict[str, Any],
    metric: str,
    form: str = "10-Q",
) -> dict[str, Any]:
    """Compare the two most recent comparable reporting periods."""

    result = latest_periods(
        company_facts,
        metric,
        form=form,
        count=2,
    )

    current, previous = result["periods"]

    change = current["value"] - previous["value"]

    percent_change = None

    if previous["value"] != 0:
        percent_change = round(
            (change / abs(previous["value"])) * 100,
            2,
        )

    if change > 0:
        direction = "increased"
    elif change < 0:
        direction = "decreased"
    else:
        direction = "unchanged"

    return {
        **{
            key: value
            for key, value in result.items()
            if key != "periods"
        },
        "current": current,
        "previous": previous,
        "absolute_change": change,
        "percent_change": percent_change,
        "direction": direction,
        "evidence": {
            "source": "SEC XBRL Company Facts API",
            "current_accession": current.get("accession"),
            "previous_accession": previous.get("accession"),
        },
    }