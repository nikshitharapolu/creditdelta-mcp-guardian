"""Human-facing Streamlit application for CreditDelta MCP Guardian."""

from __future__ import annotations

import os
import sys
from creditdelta_mcp.auth import show_account
from creditdelta_mcp.my_reports import save_report, show_my_reports
import uuid
from pathlib import Path
from typing import Any

SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

import streamlit as st

from creditdelta_mcp.benchmark import run_benchmark
from creditdelta_mcp.enforcement import GuardedExecutor
from creditdelta_mcp.ai_guardian import configured_reviewer
from creditdelta_mcp.finance import METRICS, compare_latest_periods, latest_periods
from creditdelta_mcp.report_generator import generate_report
from creditdelta_mcp.sec_client import SECClient
from creditdelta_mcp.report_workflow import report_save_context, report_snapshot, snapshot_matches

METRIC_LABELS = {
    "revenue": "Revenue",
    "cash": "Cash and cash equivalents",
    "current_debt": "Current debt",
    "net_income": "Net income",
    "operating_cash_flow": "Operating cash flow",
}


@st.cache_resource
def get_sec_client() -> SECClient:
    return SECClient()


def get_session_executor() -> GuardedExecutor:
    """Isolate reports, approvals, and audit events for each browser session."""
    if "guardian_session_id" not in st.session_state:
        st.session_state.guardian_session_id = uuid.uuid4().hex
    directory = Path(".creditdelta_data/sessions") / st.session_state.guardian_session_id
    return GuardedExecutor(directory, reviewer=configured_reviewer())


def configure_sec_identity() -> None:
    """Load deployment credentials from Streamlit secrets."""
    try:
        for setting in ("GROQ_API_KEY", "GUARDIAN_GROQ_MODEL", "REPORT_GROQ_MODEL",
                        "GUARDIAN_PROVIDERS", "GUARDIAN_OLLAMA_MODEL"):
            if setting in st.secrets:
                os.environ[setting] = str(st.secrets[setting])
    except (FileNotFoundError, KeyError):
        pass
    try:
        sec_identity = st.secrets.get("SEC_USER_AGENT")
        gemini_key = st.secrets.get("GEMINI_API_KEY")
        gemini_model = st.secrets.get("GEMINI_MODEL")
        for name in ("GUARDIAN_AI_ENABLED","GUARDIAN_MODEL","GUARDIAN_OLLAMA_MODEL",):
            if name in st.secrets:
                os.environ[name] = str(st.secrets[name])
    except Exception:
        sec_identity = gemini_key = gemini_model = None
    if sec_identity and not os.getenv("SEC_USER_AGENT"):
        os.environ["SEC_USER_AGENT"] = str(sec_identity)
    if gemini_key and not os.getenv("GEMINI_API_KEY"):
        os.environ["GEMINI_API_KEY"] = str(gemini_key)
    if gemini_model and not os.getenv("GEMINI_MODEL"):
        os.environ["GEMINI_MODEL"] = str(gemini_model)


def money(value: int | float | None) -> str:
    if value is None:
        return "N/A"
    sign, amount = ("-" if value < 0 else ""), abs(float(value))
    symbol = "$"
    if amount >= 1_000_000_000:
        return f"{sign}{symbol}{amount / 1_000_000_000:,.2f}B"
    if amount >= 1_000_000:
        return f"{sign}{symbol}{amount / 1_000_000:,.2f}M"
    return f"{sign}{symbol}{amount:,.0f}"


def show_result(result: dict[str, Any]) -> None:
    status = result.get("status", result.get("decision"))
    decision = result.get("final_decision", result.get("decision"))
    if status in {"EXECUTED", "APPROVED_AND_EXECUTED"}:
        st.success("Action completed.")
    elif status == "REJECTED":
        st.info("Action cancelled. Nothing was changed.")
    elif decision == "DENY" or status == "DENIED_BY_POLICY":
        st.error("This action was blocked.")
    elif decision == "REQUIRE_APPROVAL":
        st.warning("Your confirmation is required before this action can run.")
    else:
        st.success("This action is allowed.")
    review = result.get("ai_review", {})
    if review.get("status") == "unavailable":
        st.warning("AI review is temporarily unavailable. Fixed rules and approval requirements still apply.")
    elif review.get("status") == "completed":
        st.caption(review.get("explanation", "AI review completed."))
    if result.get("result") and "content" in result["result"]:
        st.text(result["result"]["content"])
    with st.expander("Security details"):
        for reason in result.get("reasons", []):
            st.write(reason)
        st.json(result)


def remember_report_edit() -> None:
    """Keep draft data separate from Streamlit's disposable widget state."""
    st.session_state.report_draft = st.session_state.report_editor


def resolve_report_action(executor, approval_id, approve):
    """Resolve once and retain the outcome for both pages."""
    outcome = executor.resolve_approval(approval_id, approve)
    if approval_id == st.session_state.get("report_approval_id"):
        snapshot = st.session_state.get("report_pending_snapshot", {})
        st.session_state.report_save_filename = snapshot.get("filename", "report")
        st.session_state.report_save_result = outcome
        for key in ("report_approval_id", "report_pending_snapshot", "report_pending_review"):
            st.session_state.pop(key, None)
    st.session_state.last_approval_result = outcome
    return outcome


def company_analysis(sec: SECClient, executor: GuardedExecutor) -> None:
    st.header("Explore Companies")
    st.caption("1. Find a company → 2. Compare numbers → 3. Review and download")
    st.caption("Compare public financial facts reported to the U.S. SEC.")
    if not os.getenv("SEC_USER_AGENT"):
        st.info("For responsible SEC access, set SEC_USER_AGENT to your name and email.")

    if "company_query_input" not in st.session_state:
        st.session_state.company_query_input = st.session_state.get(
            "company_query_saved", ""
        )

    with st.form("company_search"):
        query = st.text_input(
            "Company name or ticker",
            placeholder="AAPL or Apple",
            key="company_query_input",
        )
        search = st.form_submit_button("Search", type="primary")
    if search:
        st.session_state.company_query_saved = query
        try:
            with st.spinner("Searching SEC companies…"):
                st.session_state.company_matches = sec.search_company(query, 10)
        except Exception as exc:
            st.error(str(exc))

    matches = st.session_state.get("company_matches", [])
    if not matches:
        st.info("Search for a public company to begin.")
        return
    options = {f"{x['name']} ({x['ticker']})": x for x in matches}
    selected = options[st.selectbox("Company", options)]
    a, b, c = st.columns(3)
    a.metric("Ticker", selected["ticker"])
    b.metric("SEC CIK", selected["cik"])
    c.metric("Source", "SEC Company Facts")

    with st.form("financial_analysis"):
        metric = st.selectbox(
            "Financial metric", list(METRICS), format_func=lambda x: METRIC_LABELS[x]
        )
        form = st.radio("Report period", ["10-Q", "10-K"], horizontal=True,
                        format_func=lambda value: "Quarterly (10-Q)" if value == "10-Q" else "Annual (10-K)")
        analyze = st.form_submit_button("Analyze latest periods", type="primary")
    if analyze:
        try:
            with st.spinner("Loading and comparing SEC facts…"):
                facts = sec.company_facts(selected["cik"])
                st.session_state.financial_result = compare_latest_periods(facts, metric, form)
                st.session_state.financial_history = latest_periods(facts, metric, form, 4)
                st.session_state.pop("generated_report", None)
                st.session_state.pop("report_editor", None)
                st.session_state.pop("report_draft", None)
                st.session_state.pop("report_save_result", None)
        except Exception as exc:
            st.error(str(exc))

    result = st.session_state.get("financial_result")
    history = st.session_state.get("financial_history")
    if not result or result.get("cik") != selected["cik"]:
        return
    st.subheader(f"{result['company']} · {METRIC_LABELS[result['metric']]}")
    current, previous = result["current"], result["previous"]
    percent = result["percent_change"]
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Latest value", money(current["value"]), money(result["absolute_change"]))
    m2.metric("Previous value", money(previous["value"]))
    m3.metric("Change", "N/A" if percent is None else f"{percent:+.2f}%")
    m4.metric("Direction", result["direction"].title())
    if history:
        chart = [{"Period": x["end"], "Value": x["value"]} for x in reversed(history["periods"])]
        st.line_chart(chart, x="Period", y="Value")
        with st.expander("Period details and SEC evidence"):
            st.dataframe(history["periods"], use_container_width=True)
            st.json(result["evidence"])

    st.divider()
    st.subheader("Create your report")
    st.caption("Review and edit the draft, then download your report.")
    generation_count = st.session_state.get("generation_count", 0)
    if st.button("Generate AI report", type="primary", disabled=generation_count >= 5):
        api_key = os.getenv("GEMINI_API_KEY")
        model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        diagnostics = []
        with st.spinner("Generating grounded report…"):
            report, source = generate_report(
                result, api_key, model,
                groq_api_key=os.getenv("GROQ_API_KEY"),
                groq_model=os.getenv("REPORT_GROQ_MODEL", "openai/gpt-oss-20b"),
                diagnostics=diagnostics,
            )
        st.session_state.report_diagnostics = diagnostics
        st.session_state.generated_report = report
        st.session_state.report_editor = report
        st.session_state.report_draft = report
        st.session_state.report_source = source
        st.session_state.generation_count = generation_count + 1
    if generation_count >= 5:
        st.warning("This browser session has reached the five-report demo limit.")

    report = st.session_state.get("generated_report")
    if report:
        if st.session_state.get("report_source") in {"gemini", "groq"}:
            provider = st.session_state.report_source.title()
            st.success(f"AI draft generated with {provider}. Review it against the SEC facts below.")
        else:
            st.info("AI report providers were unavailable or not configured. A template report was created from the SEC facts.")
        if st.session_state.get("report_diagnostics"):
            with st.expander("Report generation status"):
                st.table(st.session_state.report_diagnostics)
                st.caption("Status codes only. No API keys, prompts, or raw provider errors are shown.")
        if "report_editor" not in st.session_state:
            st.session_state.report_editor = st.session_state.get("report_draft", report)
        edited = st.text_area("Review and edit report", height=420, key="report_editor",
                              on_change=remember_report_edit)
        st.session_state.report_draft = edited
        safe_name = "-".join(
            part for part in result["company"].lower().replace(".", "").split() if part.isalnum()
        ) or "company"
        filename = f"{safe_name}-{result['metric']}-report.md"

        # save_context = report_save_context(result, filename, edited)
        # save_col, download_col = st.columns(2)

        # # Option 1: Save inside the application using Guardian approval.
        # if save_col.button(
        #     "Save report",
        #     key="save_report",
        #     disabled="report_approval_id" in st.session_state or not edited.strip(),
        # ):
        #     outcome = executor.propose(
        #         "write_file",
        #         {
        #             "path": str(executor.reports_directory / filename),
        #             "content": edited,
        #         },
        #         context=save_context,
        #     )
        #     st.session_state.pop("report_save_result", None)

        #     if outcome["decision"] == "REQUIRE_APPROVAL":
        #         st.session_state.report_approval_id = outcome["approval_id"]
        #         st.session_state.report_pending_snapshot = report_snapshot(filename, edited, save_context)
        #         st.session_state.report_pending_review = outcome
        #     elif outcome["status"] == "EXECUTED":
        #         st.session_state.report_save_result = outcome
        #     else:
        #         st.session_state.report_save_blocked = outcome

        #     st.rerun()


        # # Option 2: Download directly without storing it in the application.
        # download_col.download_button(
        #     "Download report",
        #     data=edited,
        #     file_name=filename,
        #     mime="text/markdown",
        #     key="download_report",
        # )


        # if st.session_state.get("report_save_blocked"):
        #     show_result(st.session_state.pop("report_save_blocked"))
        # approval_id = st.session_state.get("report_approval_id")
        # if approval_id:
        #     snapshot = st.session_state.get("report_pending_snapshot", {})
        #     st.info("Report submitted. Open Pending Actions & History to review and approve or cancel this save.")
        #     st.caption(f"Pending file: {snapshot.get('filename', 'report')}")
        #     if not snapshot_matches(snapshot, filename, edited, save_context):
        #         st.warning("You edited the draft after submitting it. Cancel the old request in Pending Actions, then submit this version.")
        # save_result = st.session_state.get("report_save_result")
        # if save_result:
        #     status = save_result.get("status")
        #     saved_name = st.session_state.get("report_save_filename", filename)
        #     if status in {"APPROVED_AND_EXECUTED", "EXECUTED"}:
        #         st.success(f"Submitted report saved as {saved_name}. Later draft edits are not included in that saved copy.")
        #     elif status == "REJECTED":
        #         st.info("Save cancelled. Your draft is still available to edit or download.")
        #     else:
        #         show_result(save_result)
        st.download_button(
            "Download report",
            data=edited,
            file_name=filename,
            mime="text/markdown",
            key="download_report",
            type="primary",
            disabled=not edited.strip(),
        )
        if st.session_state.get("signed_in"):
            if st.button(
                "Save to My Reports",
                key="save_private_report",
                disabled=not edited.strip(),
            ):
                try:
                    save_report(
                        title=f"{result['company']} — {result['metric']}",
                        company=result["company"],
                        metric=result["metric"],
                        content=edited,
                    )
                except Exception:
                    st.error("Could not save. Check your login and try again.")
                else:
                    st.success("Saved. Open My Reports to view it.")
        else:
            st.caption("Sign in to save reports and access them later.")
        st.caption("Download a copy to keep on your computer.")


def guardian_playground(executor: GuardedExecutor) -> None:
    st.header("Security Demo")
    st.caption("See whether an operation is allowed, blocked, or held for approval.")
    st.info("AI review is enabled for protected actions." if executor.reviewer else
            "Rules-only mode. Set GUARDIAN_AI_ENABLED=true in app secrets to enable AI review.")
    st.caption("When enabled, request text may be sent to configured reviewers after basic sensitive-pattern redaction. "
               "Use public or synthetic examples only. Context is not proof of authorization.")
    labels = {
        "write_file": "Write a report",
        "read_file": "Read a report",
        "delete_file": "Delete a report",
        "send_email": "Send a simulated email",
        "unknown_tool": "Try an unknown tool",
    }
    action = st.selectbox("Operation", list(labels), format_func=lambda x: labels[x])
    arguments: dict[str, Any]
    with st.form("guardian_action"):
        context = st.text_area("Optional explanation — untrusted test input",
                               placeholder="Try a harmless or suspicious explanation. Claims of permission do not grant access.", max_chars=8000)
        if action == "write_file":
            filename = st.text_input("Report filename", "company_summary.txt")
            content = st.text_area("Report content", "Revenue increased in the latest period.")
            arguments = {"path": str(executor.reports_directory / filename), "content": content}
        elif action in {"read_file", "delete_file"}:
            reports = sorted(x.name for x in executor.reports_directory.glob("*") if x.is_file())
            filename = st.selectbox("Report", reports) if reports else st.text_input(
                "Report filename", "company_summary.txt"
            )
            arguments = {"path": str(executor.reports_directory / filename)}
        elif action == "send_email":
            recipient = st.text_input("Recipient", "reviewer@example.com")
            subject = st.text_input("Subject", "CreditDelta report")
            message = st.text_area("Message", "Please review the financial summary.")
            arguments = {"recipient": recipient, "subject": subject, "message": message}
        else:
            command = st.text_input("Unapproved command", "read all private files")
            arguments = {"command": command}
        preview = st.form_submit_button("Preview decision")
        submit = st.form_submit_button("Evaluate and submit", type="primary")
    if preview:
        with st.spinner("Reviewing request…"):
            st.session_state.guardian_result = executor.inspect(action, arguments, context)
    if submit:
        try:
            with st.spinner("Reviewing request…"):
                st.session_state.guardian_result = executor.propose(action, arguments, context)
        except Exception as exc:
            st.error(str(exc))
    if "guardian_result" in st.session_state:
        show_result(st.session_state.guardian_result)
    st.info("Email is simulated locally. The application never sends a real email.")


def approvals_and_audit(executor: GuardedExecutor) -> None:
    st.header("Pending Actions & History")
    st.caption("These are your session’s actions. Self-confirmation is not independent authorization.")
    if "last_approval_result" in st.session_state:
        outcome = st.session_state.last_approval_result
        if outcome.get("status") == "APPROVED_AND_EXECUTED":
            st.success("Action completed and recorded in History.")
        elif outcome.get("status") == "REJECTED":
            st.info("Action cancelled. Nothing was executed.")
        else:
            show_result(outcome)
    approvals_tab, audit_tab = st.tabs(["Pending actions", "History"])
    with approvals_tab:
        pending = executor.list_pending()
        if not pending:
            st.success("No actions are waiting for approval.")
        for item in pending:
            with st.container(border=True):
                st.subheader({"write_file": "Save report", "delete_file": "Delete report",
                              "read_file": "Read report", "send_email": "Simulated email"}.get(item["tool_name"], item["tool_name"]))
                st.caption(f"Requested {item['created_at']}")
                args = item["arguments"]
                if "path" in args:
                    st.write("File:", Path(args["path"]).name)
                is_report = item["approval_id"] == st.session_state.get("report_approval_id")
                changed = False
                if is_report:
                    snapshot = st.session_state.get("report_pending_snapshot", {})
                    st.caption("Exact submitted draft — this is the version the action will save.")
                    st.text(snapshot.get("content", "Preview unavailable"))
                    changed = st.session_state.get("report_draft") != snapshot.get("content")
                    if changed:
                        st.warning("Your current draft differs from this request. Cancel it and submit the updated draft from Explore Companies.")
                    if st.session_state.get("report_pending_review", {}).get("ai_review", {}).get("status") == "unavailable":
                        st.warning("AI review was unavailable. Check the submitted draft yourself before approving.")
                elif "content" in args:
                    st.text(args["content"])
                with st.expander("Action details (sensitive values redacted)"):
                    st.json(args)
                yes, no, _ = st.columns([1, 1, 4])
                if yes.button("Approve", key="yes-" + item["approval_id"], type="primary", disabled=changed):
                    resolve_report_action(executor, item["approval_id"], True)
                    st.rerun()
                if no.button("Cancel save" if is_report else "Reject", key="no-" + item["approval_id"]):
                    resolve_report_action(executor, item["approval_id"], False)
                    st.rerun()
    with audit_tab:
        audit = executor.list_audit(100)
        if audit:
            st.dataframe([{"Time": x["created_at"], "Action": x["tool_name"], "Outcome": x["status"]} for x in audit], use_container_width=True)
            with st.expander("Technical audit records"):
                st.json(audit)
            st.caption("Sensitive values are redacted before display.")
        else:
            st.info("No audit events yet. Try an operation in Guardian Playground.")


def security_benchmark(executor: GuardedExecutor) -> None:
    st.header("Test Results")
    st.caption("Repeatable safe, controlled, and adversarial policy tests.")
    if st.button("Run benchmark", type="primary") or "benchmark_result" not in st.session_state:
        st.session_state.benchmark_result = run_benchmark(executor.reports_directory)
    result = st.session_state.benchmark_result
    a, b, c, d = st.columns(4)
    a.metric("Pass rate", f"{result['pass_rate_percent']}%")
    b.metric("Attack block rate", f"{result['attack_block_rate_percent']}%")
    c.metric("Safe false positives", f"{result['safe_false_positive_rate_percent']}%")
    d.metric("Policy latency", f"{result['average_policy_latency_ms']} ms")
    st.progress(result["pass_rate_percent"] / 100)
    with st.expander("Individual test cases"):
        st.dataframe(result["cases"], use_container_width=True)
    st.caption("Results cover the included cases; they do not prove protection from every attack.")


def main() -> None:
    st.set_page_config(page_title="CreditDelta Guardian", page_icon="🛡️", layout="wide")
    configure_sec_identity()
    st.markdown(
        """
        <style>
        :root { color-scheme: dark; }
        html, body, #root, .stApp {
            -webkit-text-size-adjust: 100%;
            text-size-adjust: 100%;
            font-synthesis: none;
            font-size: 18px !important;
        }
        .block-container {
            width: calc(100% - 72px) !important;
            max-width: 1320px !important;
            margin: 0 auto !important;
            padding: 34px 0 72px !important;
        }
        .app-hero {
            padding: 30px 34px;
            margin-bottom: 32px;
            border: 1px solid #303b52;
            border-radius: 18px;
            background: linear-gradient(135deg, #171f33 0%, #111722 55%, #171b2b 100%);
            box-shadow: 0 16px 45px rgba(0,0,0,.22);
        }
        .hero-badge {
            display: inline-block;
            padding: 6px 12px;
            margin-bottom: 13px;
            border-radius: 999px;
            background: rgba(124,140,255,.15);
            border: 1px solid rgba(124,140,255,.38);
            color: #b8c1ff;
            font-size: 14px;
            font-weight: 700;
            letter-spacing: .07em;
            text-transform: uppercase;
        }
        .app-hero h1 {
            margin: 0 0 10px;
            color: #f8f9ff;
            font-size: 46px !important;
            line-height: 1.08 !important;
            letter-spacing: -.035em;
        }
        .app-hero p {
            max-width: 820px;
            margin: 0;
            color: #b9c1d3;
            font-size: 18px !important;
            line-height: 1.55 !important;
        }
        h1 { font-size: 46px !important; line-height: 1.1 !important; }
        h2 { margin-top: 4px !important; font-size: 31px !important; line-height: 1.25 !important; }
        h3 { font-size: 23px !important; line-height: 1.3 !important; }
        p, li, .stMarkdown p {
            font-size: 18px !important;
            line-height: 1.6 !important;
        }
        label, [data-testid="stWidgetLabel"] p {
            font-size: 17px !important;
            font-weight: 650 !important;
            color: #e7eaf3 !important;
        }
        [data-testid="stCaptionContainer"] p {
            color: #aeb6c8 !important;
            font-size: 16px !important;
            line-height: 1.55 !important;
        }
        [data-testid="stSidebar"] {
            min-width: 300px !important;
            max-width: 300px !important;
            background: #151c2b !important;
            border-right: 1px solid #2c3549 !important;
        }
        [data-testid="stSidebar"] > div:first-child { padding: 34px 22px !important; }
        [data-testid="stSidebar"] h2 { font-size: 25px !important; }
        [data-testid="stSidebar"] label,
        [data-testid="stSidebar"] p {
            font-size: 16px !important;
            line-height: 1.45 !important;
        }
        [data-testid="stSidebar"] [role="radiogroup"] label {
            min-height: 46px;
            padding: 9px 10px !important;
            margin: 3px 0;
            border-radius: 9px;
        }
        [data-testid="stMetric"] {
            min-height: 138px;
            background: linear-gradient(145deg, #192132, #141a26);
            padding: 22px !important;
            border: 1px solid #303a4e;
            border-radius: 14px;
            box-shadow: 0 8px 24px rgba(0,0,0,.14);
        }
        [data-testid="stMetricLabel"] p { font-size: 16px !important; }
        [data-testid="stMetricValue"] { font-size: 34px !important; line-height: 1.2 !important; }
        [data-testid="stForm"] {
            padding: 24px !important;
            border: 1px solid #303a4e !important;
            border-radius: 14px !important;
            background: #111722 !important;
        }
        .stButton > button, .stFormSubmitButton > button {
            min-height: 50px;
            padding: 10px 22px;
            font-size: 17px !important;
            font-weight: 700 !important;
            border-radius: 10px;
        }
        input, textarea, button, select, [data-baseweb="select"], [role="radiogroup"] {
            font: inherit !important;
        }
        .stTextInput input, .stTextArea textarea, [data-baseweb="select"] {
            font-size: 18px !important;
            min-height: 52px;
        }
        .stTextInput input, .stTextArea textarea {
            padding: 12px 14px !important;
        }
        [data-testid="stAlert"] {
            padding: 17px 19px !important;
            border-radius: 12px !important;
        }
        [data-testid="stAlert"] p { font-size: 17px !important; }
        [data-testid="stTabs"] button p { font-size: 17px !important; font-weight: 650 !important; }
        [data-testid="stDataFrame"] {
            font-size: 16px !important;
            border: 1px solid #303a4e;
            border-radius: 12px;
            overflow: hidden;
        }
        hr { border-color: #30394d !important; }
        @media (max-width: 900px) {
            .block-container { width: calc(100% - 32px) !important; padding-top: 20px !important; }
            .app-hero { padding: 24px; margin-bottom: 24px; }
            .app-hero h1, h1 { font-size: 36px !important; }
            .app-hero p, p, li, .stMarkdown p { font-size: 17px !important; }
            [data-testid="stHorizontalBlock"] { flex-wrap: wrap; gap: .75rem; }
            [data-testid="column"] { min-width: 260px !important; flex: 1 1 260px !important; }
        }
        @media (max-width: 600px) {
            .block-container { width: calc(100% - 24px) !important; }
            .app-hero h1, h1 { font-size: 32px !important; }
            h2 { font-size: 27px !important; }
            [data-testid="column"] { min-width: 100% !important; flex-basis: 100% !important; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        """
        <section class="app-hero">
          <span class="hero-badge">Secure financial intelligence</span>
          <h1>CreditDelta Guardian</h1>
          <p>Explore evidence-backed SEC financial changes while a deterministic security
          layer controls sensitive actions, approvals, and audit records.</p>
        </section>
        """,
        unsafe_allow_html=True,
    )
    sec, executor = get_sec_client(), get_session_executor()
    with st.sidebar:
        st.header("CreditDelta")
        user = show_account()
        st.divider()
        advanced = st.checkbox("Show security demos", value=False)
        pages = ["Explore Companies", "My Reports", "Pending Actions & History"]
        if advanced:
            pages += ["Security Demo", "Test Results"]
        page = st.radio("Navigate", pages, label_visibility="collapsed")
        st.divider()
        st.caption("Files and history belong to this browser session. Download reports to keep them.")
        st.caption("Demo session separation; no user accounts or independent approver.")
    if page == "Explore Companies":
        company_analysis(sec, executor)
    elif page == "Security Demo":
        guardian_playground(executor)
    elif page == "Pending Actions & History":
        approvals_and_audit(executor)
    elif page == "My Reports":
        show_my_reports()
    else:
        security_benchmark(executor)



if __name__ == "__main__":
    main()
