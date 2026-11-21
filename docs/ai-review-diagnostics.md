# Review diagnostics

Apply this update after the original AI Guardian extension. It does not relax
policy, change model prompts, increase retries, or execute evaluation tools.

Run from the project root (Python 3.11+ for TOML loading):

```bash
PYTHONPATH=src python -u -m creditdelta_mcp.evaluate_ai_guardian --live \
  --secrets-file .streamlit/secrets.toml \
  --output evaluation/results/ai-review-diagnostics.json
```

The explicitly selected secrets file overrides the corresponding environment
settings. Keys and file contents are never printed. Progress is printed to stderr
before and after each case. Results remain JSON on stdout and in the output file.
The live run consumes the existing provider quota, with one attempt per review.

`error_counts` groups failures; each row includes `error_category`.

| Category | Meaning |
| --- | --- |
| rate_limited | Provider returned 429; quota or rate limit, not an attack detection |
| timeout | Timeout exception, HTTP 408 or 504 |
| provider_unavailable | Other HTTP 5xx provider failure |
| authentication_or_permission | HTTP 401 or 403 |
| model_or_endpoint_not_found | HTTP 404 |
| invalid_api_request | Other HTTP 4xx rejection |
| network_error | Connection/transport failure |
| configuration_missing | Key or model missing |
| dependency_missing | Required Python dependency unavailable |
| output_truncated | Provider finish reason MAX_TOKENS |
| provider_content_block | Provider safety/content refusal |
| empty_response | No usable text returned |
| invalid_json | Text could not be parsed as JSON |
| invalid_schema | Fields, types, or enum values did not match expected schema |
| inconsistent_verdict | SAFE/reason-code combination contradicted itself |
| invalid_input / input_too_large | Local request validation failure |
| response_too_large | Returned text exceeded the local limit |
| unexpected_error | Unclassified failure; raw exception details intentionally omitted |

The safe category also appears in the dashboard explanation and structured audit.
Completed-review counts and accuracy exclude unavailable/skipped reviews; they are
conditional metrics on a potentially biased subset. Operational scores still
include fail-closed blocking. Keep the earlier run for comparison and do not claim
100% model detection from blocking caused by outages.
