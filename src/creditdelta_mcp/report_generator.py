"""Grounded financial report generation with a deterministic fallback."""

from __future__ import annotations

from typing import Any
import time

def _money(value: int | float) -> str:
    sign = "-" if value < 0 else ""
    amount = abs(float(value))
    if amount >= 1_000_000_000:
        return f"{sign}$" + f"{amount / 1_000_000_000:,.3f} billion"
    if amount >= 1_000_000:
        return f"{sign}$" + f"{amount / 1_000_000:,.3f} million"
    return f"{sign}$" + f"{amount:,.0f}"


def verified_facts(comparison: dict[str, Any]) -> str:
    """Render the facts that Python, rather than the LLM, controls."""
    current, previous = comparison["current"], comparison["previous"]
    percent = comparison.get("percent_change")
    percent_text = "not available" if percent is None else f"{percent:+.2f}%"
    return (
        "## Verified SEC facts\n\n"
        f"- **Company:** {comparison['company']}\n"
        f"- **Metric:** {comparison['metric'].replace('_', ' ').title()}\n"
        f"- **Current period ({current['end']}):** {_money(current['value'])}\n"
        f"- **Previous period ({previous['end']}):** {_money(previous['value'])}\n"
        f"- **Absolute change:** {_money(comparison['absolute_change'])}\n"
        f"- **Percentage change:** {percent_text}\n"
        f"- **Direction:** {comparison['direction']}\n"
        f"- **Current filing accession:** {current.get('accession', 'N/A')}\n"
        f"- **Previous filing accession:** {previous.get('accession', 'N/A')}\n"
        "- **Source:** SEC XBRL Company Facts API\n"
    )


def deterministic_report(comparison: dict[str, Any]) -> str:
    """Always-available report that contains no model-generated claims."""
    percent = comparison.get("percent_change")
    change = "an unavailable percentage" if percent is None else f"{abs(percent):.2f}%"
    narrative = (
        f"## Summary\n\n{comparison['company']}'s "
        f"{comparison['metric'].replace('_', ' ')} {comparison['direction']} by {change} "
        "between the two most recent comparable reporting periods. This summary is generated "
        "directly from the verified facts below.\n\n"
    )
    return (
        f"# CreditDelta Report: {comparison['company']}\n\n"
        f"{narrative}{verified_facts(comparison)}\n"
        "## Disclaimer\n\nThis report is for educational and research purposes only. "
        "It is not a credit rating or investment advice."
    )


def build_prompt(comparison: dict[str, Any]) -> str:
    """Create a tightly grounded prompt from verified public facts."""
    return (
        "Write a concise financial-change narrative using ONLY the verified facts below. "
        "Do not introduce any new number, cause, forecast, recommendation, credit opinion, "
        "or investment advice. Explain what changed in 2-3 short paragraphs for a general "
        "reader. Use the heading '## AI-generated interpretation'. Do not repeat the full "
        "facts list or add a disclaimer.\n\n"
        + verified_facts(comparison)
    )


def generate_report(
    comparison: dict[str, Any], api_key: str | None, model: str = "gemini-2.5-flash"
) -> tuple[str, str]:
    """Return (report, source), falling back safely when Gemini is unavailable."""
    fallback = deterministic_report(comparison)
    if not api_key:
        return fallback, "template"
    try:
        from google import genai

        client = genai.Client(api_key=api_key)
        response = None

        for attempt in range(3):
            try:
                response = client.models.generate_content(
                model=model,
                contents=build_prompt(comparison),
                )
                break
            except Exception as exc:
                is_temporary = "503" in str(exc) or "UNAVAILABLE" in str(exc)

                if is_temporary and attempt < 2:
                    wait_seconds = 2 ** attempt  # waits 1 second, then 2 seconds
                    print(
                        f"Gemini temporarily unavailable. "
                        f"Retrying in {wait_seconds} second(s)..."
                    )
                    time.sleep(wait_seconds)
                    continue

                raise

        if response is None:
            raise RuntimeError("Gemini did not return a response.")
        narrative = (response.text or "").strip()
        if len(narrative) < 80 or len(narrative) > 4000:
            raise ValueError("Model response length was outside the safe range.")
        report = (
            f"# CreditDelta Report: {comparison['company']}\n\n"
            f"{narrative}\n\n{verified_facts(comparison)}\n"
            "## Disclaimer\n\nThis AI-generated draft is for educational and research purposes "
            "only. It is not a credit rating or investment advice."
        )
        return report, "gemini"
    except Exception as exc:
        print(f"Gemini report generation failed: {type(exc).__name__}: {exc}")
        return fallback, "template"
