"""Minimal, testable client for the public SEC JSON APIs."""

from __future__ import annotations

import json
import os
from typing import Any, Callable
from urllib.request import Request, urlopen


SEC_DATA_BASE = "https://data.sec.gov"
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"


class SECClientError(RuntimeError):
    """Raised when SEC data cannot be fetched or interpreted."""


JsonFetcher = Callable[[str], dict[str, Any]]


class SECClient:
    """Fetch company identifiers and XBRL facts from SEC endpoints.

    The SEC asks automated clients to identify themselves. Set SEC_USER_AGENT
    to a value such as "Your Name your.email@example.com" before live use.
    """

    def __init__(self, fetch_json: JsonFetcher | None = None) -> None:
        self._fetch_json = fetch_json or self._default_fetch_json

    @staticmethod
    def _default_fetch_json(url: str) -> dict[str, Any]:
        user_agent = os.getenv(
            "SEC_USER_AGENT", "CreditDelta educational-project contact@example.com"
        )
        request = Request(
            url,
            headers={
                "User-Agent": user_agent,
                "Host": "data.sec.gov" if url.startswith(SEC_DATA_BASE) else "www.sec.gov",
            },
        )
        try:
            with urlopen(request, timeout=20) as response:  # noqa: S310 - fixed trusted URLs
                return json.load(response)
        except Exception as exc:  # urllib exposes several transport exceptions
            raise SECClientError(f"Could not fetch SEC data: {exc}") from exc

    def search_company(self, query: str, limit: int = 5) -> list[dict[str, str]]:
        """Return ticker matches ordered by exact ticker/name relevance."""
        cleaned = query.strip().lower()
        if not cleaned:
            raise ValueError("Company query cannot be empty.")
        if not 1 <= limit <= 20:
            raise ValueError("Limit must be between 1 and 20.")

        payload = self._fetch_json(SEC_TICKERS_URL)
        matches: list[tuple[int, dict[str, str]]] = []
        for record in payload.values():
            ticker = str(record["ticker"])
            title = str(record["title"])
            ticker_lower = ticker.lower()
            title_lower = title.lower()
            if cleaned not in ticker_lower and cleaned not in title_lower:
                continue
            if cleaned == ticker_lower:
                rank = 0
            elif cleaned == title_lower:
                rank = 1
            elif ticker_lower.startswith(cleaned):
                rank = 2
            elif title_lower.startswith(cleaned):
                rank = 3
            else:
                rank = 4
            matches.append(
                (
                    rank,
                    {
                        "name": title,
                        "ticker": ticker,
                        "cik": str(record["cik_str"]).zfill(10),
                    },
                )
            )
        matches.sort(key=lambda item: (item[0], item[1]["name"]))
        return [match for _, match in matches[:limit]]

    def company_facts(self, cik: str) -> dict[str, Any]:
        """Return all standardized XBRL facts for one company."""
        digits = str(cik).strip()
        if not digits.isdigit() or len(digits) > 10:
            raise ValueError("CIK must contain at most 10 digits.")
        padded = digits.zfill(10)
        return self._fetch_json(f"{SEC_DATA_BASE}/api/xbrl/companyfacts/CIK{padded}.json")
