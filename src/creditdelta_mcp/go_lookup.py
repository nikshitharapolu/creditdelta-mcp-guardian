"""Optional loopback company search for the MCP server."""

import json
import os
from urllib.parse import urlencode
from urllib.request import ProxyHandler, build_opener, HTTPRedirectHandler


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def search_company(sec, query: str, limit: int):
    if os.getenv("CREDITDELTA_GO_LOOKUP") != "1":
        return sec.search_company(query, limit)
    if not query.strip() or len(query.encode("utf-8")) > 400 or not 1 <= limit <= 20:
        raise ValueError("Enter a company name or ticker and a limit from 1 to 20.")
    params = urlencode({"q": query, "limit": limit})
    opener = build_opener(ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(f"http://127.0.0.1:8787/companies?{params}", timeout=10) as response:
            rows = json.loads(response.read(65537))
    except (OSError, ValueError) as exc:
        raise RuntimeError("Go company lookup is unavailable. Check the local service.") from exc
    if not isinstance(rows, list) or len(rows) > limit or any(
        not isinstance(row, dict)
        or set(row) != {"name", "ticker", "cik"}
        or not all(isinstance(value, str) for value in row.values())
        for row in rows
    ):
        raise RuntimeError("Go company lookup returned an invalid response.")
    return rows
