# Security Policy and Threat Model

## Protected assets

- Files under the local CreditDelta reports directory
- Tool arguments that may contain credentials or personal data
- Approval state and audit history
- SEC-derived financial evidence

## Trust boundaries

The user and deterministic Guardian policy are trusted. Model-generated tool
requests, retrieved document text, unknown MCP tools, paths supplied as tool
arguments, and outbound recipients are untrusted.

## Current controls

| Threat | Control |
| --- | --- |
| Unknown or poisoned tool | Default-deny allowlist |
| Directory traversal | Canonical path validation and approved-directory boundary |
| Destructive file action | Explicit approval and recoverable local trash |
| Data exfiltration | Sensitive-pattern detection and outbound email blocking |
| Silent external action | Approval required for all simulated email |
| Audit leakage | Sensitive values redacted from audit views |
| Replayed approval | Approval IDs can be resolved only once |
| Policy changed after request | Policy is evaluated again before approved execution |
| LLM numerical hallucination | Calculations and verified SEC facts are produced by deterministic Python code |
| Unsupported LLM claims | Prompt restricts generation to supplied facts; authoritative evidence is appended separately |
| LLM/API unavailability | Deterministic report fallback |
| Cross-session data exposure | Separate temporary storage directory for each browser session |
| API key exposure | Gemini key stored only in server-side environment variables or deployment secrets |

## Assumptions and limitations

- The current policy engine detects selected structured patterns, not every
  possible encoding or obfuscation of sensitive information.
- The email tool is a local simulation; no real email service is connected.
- The benchmark is a fixed regression suite and is not proof of universal
  attack prevention.
- Public web sessions use isolated temporary report, approval, and audit
  directories, but the prototype does not provide authenticated user accounts,
  durable ownership, role-based access control, or remote MCP OAuth.
- Local users with direct filesystem access can bypass an application-layer
  policy gateway; operating-system permissions remain necessary.
- CreditDelta provides research assistance, not ratings or investment advice.

## Limitations

- Browser-session isolation is not authentication and should not be treated as
  a durable user identity.
- Free cloud instances may delete reports and audit history when they restart.
- The per-session LLM generation limit is a demonstration control, not robust
  distributed rate limiting.
- LLM-generated explanations may still contain misleading wording and must be
  reviewed by the user; deterministic SEC facts remain authoritative.
- Free-tier Gemini requests may be subject to quota limits, temporary
  unavailability, and the provider's data-use policies.