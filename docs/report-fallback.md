# Report generation fallback

Reports try Gemini, then Groq, then the deterministic template. Existing security
review provider settings are separate and unchanged. Only the selected public
SEC comparison facts are sent to report providers; edited report text, audit
records, and private files are not included. AI prose can still be inaccurate;
the Python-rendered facts appendix is preserved but does not validate that prose.

Keep your existing GEMINI_API_KEY and GEMINI_MODEL. The dashboard reuses
GROQ_API_KEY from Streamlit secrets (or the environment). Optionally set:

```toml
REPORT_GROQ_MODEL = "openai/gpt-oss-20b"
```

No new dependency or paid service is required by this change. Provider quotas
still apply. Use your existing free-tier accounts. Do not commit secrets.
Each provider is attempted once, with a 15-second transport timeout. Network
behavior may make total wall-clock duration longer; no whole-workflow deadline
is claimed. Incomplete or invalid outputs fall through to the next provider.

Run `python -m pytest`. Automated tests mock providers; they do not measure model
quality or consume quota. For a local live backup check, temporarily remove the
Gemini key from both local secrets and the terminal environment, keep the Groq
key, and restart Streamlit. Generate a new report and expect a Groq label. Restore
the Gemini key afterward. Never expose keys in screenshots or commits.
