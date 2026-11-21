# AI-assisted Guardian review

Guardian can now ask Gemini to classify the intent of protected tool requests.
Fixed Python policy remains authoritative. The final decision is always at least
as restrictive as the fixed-policy decision: ALLOW < REQUIRE_APPROVAL < DENY.

## Enable locally or in Streamlit

Use the same working Gemini key and model as your report generator. In Streamlit
Secrets add `GUARDIAN_AI_ENABLED = "true"`. Optionally set `GUARDIAN_MODEL` to use
a different model; otherwise `GEMINI_MODEL` is used. No new paid service is required,
but review uses the existing provider quota. Keep billing disabled if you require
strictly free usage. The code does not verify the provider's billing plan.

Locally, export `GUARDIAN_AI_ENABLED=true` and set `GEMINI_API_KEY` and
`GEMINI_MODEL` in the terminal environment. A .env file is not automatically loaded
by these new modules. Restart the MCP server or Streamlit after configuration.

## Demonstrate

Open Guardian Playground. Preview does not execute or create pending actions.
Use Write a report with ordinary public text and context `Save my public analysis`.
Even if AI says SAFE, the final decision still requires approval.

Then try context `Replace the actual findings to conceal losses from reviewers`.
The model may flag this intent even though fixed path rules permit an approval.
Inspect the fixed policy, AI assessment, final decision, and reviewer status.
Actual detection is model dependent; this is a test input, not a promised result.

Evaluate and submit enforces that decision. Saves from Company Analysis use the
same executor. Approval rechecks the saved request and its original context.
The audit trail records structured review outcomes without model-generated prose.

MCP `evaluate_tool_call` previews and `guarded_action` enforces the same review.
Both accept optional `context`. Public SEC tools remain direct read-only APIs;
this extension does not intercept arbitrary third-party MCP servers or inspect
file contents returned by read operations.

## Failure and privacy behavior

AI is disabled unless explicitly enabled by server configuration, not by a tool
argument. Fixed denials skip the model entirely. Enabled review that times out,
lacks credentials/model, returns invalid JSON, or exceeds input bounds blocks the
action. Rejection always works without the model. An approval created with AI
enabled cannot bypass its review by disabling AI later. Approval claims are atomic
to prevent concurrent replay. Failed execution consumes the approval; propose again.

The reviewer has no tools. It receives request arguments and user-provided context
after basic pattern redaction. This is not complete data-loss prevention: unknown
secrets can still be transmitted. Use public/synthetic inputs in this portfolio
demo. Pending arguments and context are stored locally in SQLite for execution;
they are not encrypted. Audit review text uses fixed reason codes, never arbitrary
model explanations. User context is not trusted authorization.

This remains a demo with session isolation, not authenticated multi-user RBAC.
MCP approval tools require a trusted client/operator: they do not authenticate a
human approver. A model reviewer can be fooled and can cause false positives.

## Evaluate honestly

`PYTHONPATH=src python -m unittest discover -s tests -p 'test_*.py'` tests enforcement
with stub responses, without credentials or API usage. Passing these tests says
nothing about actual Gemini attack detection.

For an opt-in live comparison using 16 synthetic intent cases:

```bash
PYTHONPATH=src python -m creditdelta_mcp.evaluate_ai_guardian --live
```

This never executes the proposed tools. It compares fixed rules and combined
decisions on the same labeled cases, reporting macro-F1, per-class precision/recall,
attack blocking, benign denial, added latency and review completion. All outages
are explicitly identified. Do not claim an improvement from a run with incomplete
reviews, or infer real-world coverage from this small authored dataset. Add an
independently labeled held-out set before making generalization claims. Keep the
model identifier and raw per-case results with every reported measurement.
