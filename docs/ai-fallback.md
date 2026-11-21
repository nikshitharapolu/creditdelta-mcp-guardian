# AI availability fallback

This policy supersedes the earlier AI extension's block-on-outage behavior.
Deterministic denials remain denials. Valid AI BLOCK decisions remain denials.
Unavailable or malformed model responses are NOT_RUN, never SAFE or a model detection.
Safe reads follow the fixed policy; writes/deletes/simulated emails still require
explicit approval. The original arguments and policy are checked again at approval.
Invalid or oversized review input remains denied. Audit details record unavailable review.
When all models fail, suspicious intent beyond fixed rules may go undetected.

## Apply and test
Apply CreditDelta-AI-Fallback.patch from the project root, then run:
python -m pytest

Restart Streamlit. In Guardian Playground, use a report inside the approved directory:
- Read a report during a simulated outage: allowed.
- Propose a write during an outage: requires approval; no file written yet.
- Approve the pending write: writes the file under the fixed policy.
- Unknown tool or outside path: denied.
Automated tests simulate outages; they do not spend Gemini quota.

## Optional local Ollama fallback
Gemini remains first. Set GUARDIAN_OLLAMA_MODEL in the terminal to an already
installed Ollama model name (see ollama list), then launch Streamlit from that
same terminal. Keep GUARDIAN_AI_ENABLED=true as before.
Example, replacing YOUR_INSTALLED_MODEL with the exact local model name:

export GUARDIAN_OLLAMA_MODEL="YOUR_INSTALLED_MODEL"
PYTHONPATH=src python -m streamlit run src/creditdelta_mcp/dashboard.py

Ollama must be running locally. This code does not install or download models.
It calls only http://127.0.0.1:11434/api/chat, with a 30-second timeout,
no proxy or redirects, and no model tools. A valid first-provider verdict stops
the chain; only an unavailable review tries the next provider.
The existing dashboard displays the review explanation and status. Provider attempts
are included in structured inspection and audit results.

On Streamlit Community Cloud, localhost means the cloud server, not your Mac.
Do not set GUARDIAN_OLLAMA_MODEL there unless Ollama actually runs on that server.
The deployed app still works using fixed policy and human approval when Gemini fails.
No new paid provider is configured. Report generation is unchanged.

The evaluation CLI still evaluates its directly selected Gemini reviewer; it is
not a benchmark of the optional Ollama fallback chain. Existing evaluation results
are not comparable without recording this policy change.
