# Hosted Guardian backup

This change adds Groq to AI security review only. Financial calculations,
report generation, and deterministic rules are unchanged. Existing Gemini
report generation still has its template fallback.

Default provider order: Gemini, Groq (if key exists), Ollama (if local model is set).
GUARDIAN_PROVIDERS overrides the order, e.g. "groq" for a direct test or
"gemini,groq" for the hosted site. Valid model decisions stop the chain.
Outages or malformed responses try the next reviewer. All failures preserve
fixed rules and explicit human approval; they are not reported as AI detections.
Requests use existing basic redaction, not comprehensive sensitive-data detection.
Use public or synthetic inputs. Configured cloud reviewers receive that request data.

## Local setup
Add to .streamlit/secrets.toml (never commit this file):
GUARDIAN_AI_ENABLED = "true"
GROQ_API_KEY = "YOUR_PRIVATE_KEY"
GUARDIAN_GROQ_MODEL = "openai/gpt-oss-20b"
GUARDIAN_PROVIDERS = "groq"

Restart Streamlit. Preview a harmless write; expect provider groq, completed
review, and REQUIRE_APPROVAL. Preview suspicious intent; inspect the actual
verdict instead of assuming any model always detects attacks.
Restore GUARDIAN_PROVIDERS = "gemini,groq,ollama" after testing locally.

## Deployment
Add the same key and settings to Streamlit deployment secrets, using:
GUARDIAN_PROVIDERS = "gemini,groq"
Do not configure local Ollama on the hosted service. Push the code changes and
restart the deployed application. Check its review result and audit entries.

Stay on Groq's Free plan. Provider quotas still apply. Code never upgrades
billing and makes one request per provider, with no automatic retries.
Gemini's existing timeout is 15 seconds, Groq's request timeout is 15 seconds,
and optional Ollama's timeout is 30 seconds. Fallback may take noticeable time.

## Implementation and tests
Groq uses a fixed HTTPS endpoint and strict JSON schema, no model tools,
no redirects or proxy, bounded response reads, and no raw error logging.
Its JSON verdict passes through the same validation and policy enforcement.
No additional Python dependency is needed for this adapter.

python -m pytest

The new tests mock providers; they do not use quota and are not live accuracy
measurements. The existing live evaluation CLI directly selects Gemini and
does not yet measure this configurable provider chain.

Official references:
https://console.groq.com/docs/structured-outputs
https://console.groq.com/docs/openai
