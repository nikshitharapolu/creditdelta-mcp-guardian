# Simplified report workflow

The default navigation shows Explore Companies and Pending Actions & History.
Show security demos reveals Security Demo and Test Results. Technical decisions,
JSON, audit records, and individual test cases are expandable.

Normal report saves collect company, CIK, metric, period ends, destination, and
content length from the selected analysis and actual report. These details are
descriptive, not authorization; editable report content is still untrusted.
The optional explanation field remains only in Security Demo and is labeled
untrusted. No existing tool restriction or approval requirement is relaxed.
MCP callers still supply untrusted context as before.

The exact submitted draft is shown before inline approval. If its content,
filename, or selected analysis changes, confirmation is disabled until the
pending save is cancelled and the updated report is submitted. Approval still
executes the stored snapshot and rechecks policy. A pending action resolved
on the History page is cleared from the report page on its next run.

Session boundary regression tests cover reads, writes, deletion, approval IDs,
audit/pending lists, and a symlink pointing outside the session report directory.
This is not authenticated multi-user authorization. Self-confirmation does not
prevent a malicious user from approving their own otherwise-permitted action.
An application-generated description cannot reveal hidden intentions.
Server administrators with direct filesystem access remain outside this boundary.

Apply the patch from the project root, run python -m pytest, restart Streamlit.
Test a report save locally: inspect its pending draft, change the editor, verify
confirmation is disabled, cancel, submit again, and confirm the updated draft.
Test Security Demo and Test Results using the sidebar toggle.
No provider settings or secrets change; no live API calls were used in testing.
