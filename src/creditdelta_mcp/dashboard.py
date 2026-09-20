"""Human-facing Streamlit application for CreditDelta MCP Guardian."""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path
from typing import Any

SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

import streamlit as st

from creditdelta_mcp.benchmark import run_benchmark
from creditdelta_mcp.enforcement import GuardedExecutor
from creditdelta_mcp.finance import METRICS, compare_latest_periods, latest_periods
from creditdelta_mcp.report_generator import generate_report
from creditdelta_mcp.sec_client import SECClient

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
    return GuardedExecutor(directory)


def configure_sec_identity() -> None:
    """Load deployment credentials from Streamlit secrets."""
    try:
        sec_identity = st.secrets.get("SEC_USER_AGENT")
        gemini_key = st.secrets.get("GEMINI_API_KEY")
        gemini_model = st.secrets.get("GEMINI_MODEL")
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
    decision = result.get("decision", result.get("status", "UNKNOWN"))
    message = f"{decision} — {' '.join(result.get('reasons', []))}"
    if decision == "ALLOW" or result.get("status") == "EXECUTED":
        st.success(message)
    elif decision == "REQUIRE_APPROVAL":
        st.warning(message)
    else:
        st.error(message)
    st.json(result)


def company_analysis(sec: SECClient, executor: GuardedExecutor) -> None:
    st.header("Company analysis")
    st.caption("Compare public financial facts reported to the U.S. SEC.")
    if not os.getenv("SEC_USER_AGENT"):
        st.info("For responsible SEC access, set SEC_USER_AGENT to your name and email.")

    with st.form("company_search"):
        query = st.text_input("Company name or ticker", placeholder="AAPL or Apple")
        search = st.form_submit_button("Search", type="primary")
    if search:
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
        form = st.radio("Filing type", ["10-Q", "10-K"], horizontal=True)
        analyze = st.form_submit_button("Analyze latest periods", type="primary")
    if analyze:
        try:
            with st.spinner("Loading and comparing SEC facts…"):
                facts = sec.company_facts(selected["cik"])
                st.session_state.financial_result = compare_latest_periods(facts, metric, form)
                st.session_state.financial_history = latest_periods(facts, metric, form, 4)
                st.session_state.pop("generated_report", None)
                st.session_state.pop("report_editor", None)
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
    st.subheader("Generate report")
    generation_count = st.session_state.get("generation_count", 0)
    if st.button("Generate AI report", type="primary", disabled=generation_count >= 5):
        api_key = os.getenv("GEMINI_API_KEY")
        model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        with st.spinner("Generating grounded report…"):
            report, source = generate_report(result, api_key, model)
        st.session_state.generated_report = report
        st.session_state.report_editor = report
        st.session_state.report_source = source
        st.session_state.generation_count = generation_count + 1
    if generation_count >= 5:
        st.warning("This browser session has reached the five-report demo limit.")

    report = st.session_state.get("generated_report")
    if report:
        if st.session_state.get("report_source") == "gemini":
            st.success("AI-generated draft created from verified SEC facts.")
        else:
            st.info("Gemini was unavailable, so the deterministic template was used.")
        edited = st.text_area("Review and edit report", height=420, key="report_editor")
        safe_name = "-".join(
            part for part in result["company"].lower().replace(".", "").split() if part.isalnum()
        ) or "company"
        filename = f"{safe_name}-{result['metric']}-report.md"

        save_col, download_col = st.columns(2)

        # Option 1: Save inside the application using Guardian approval.
        if save_col.button(
            "Save securely to workspace",
            key="save_report",
            disabled="report_approval_id" in st.session_state,
        ):
            outcome = executor.propose(
                "write_file",
                {
                    "path": str(executor.reports_directory / filename),
                    "content": edited,
                },
            )

            if outcome["decision"] == "REQUIRE_APPROVAL":
                st.session_state.report_approval_id = outcome["approval_id"]
            elif outcome["status"] == "EXECUTED":
                st.session_state.report_save_result = outcome
            else:
                st.error("Guardian blocked the report save.")

            st.rerun()


        # Option 2: Download directly without storing it in the application.
        download_col.download_button(
            "Download report",
            data=edited,
            file_name=filename,
            mime="text/markdown",
            key="download_report",
        )


        # Show inline confirmation when Guardian requires approval.
        approval_id = st.session_state.get("report_approval_id")

        if approval_id:
            st.warning(
                "Saving this report changes stored application data. "
                "Do you want to approve this action?"
            )

            approve_col, reject_col, _ = st.columns([1, 1, 3])

            if approve_col.button(
                "Approve and save",
                type="primary",
                key="approve_report_save",
            ):
                try:
                    result = executor.resolve_approval(approval_id, True)

                    st.session_state.report_save_result = result
                    del st.session_state.report_approval_id

                    st.rerun()
                except Exception as exc:
                    st.error(f"Could not save the report: {exc}")

            if reject_col.button(
                "Reject",
                key="reject_report_save",
            ):
                try:
                    executor.resolve_approval(approval_id, False)

                    del st.session_state.report_approval_id
                    st.session_state.report_save_rejected = True

                    st.rerun()
                except Exception as exc:
                    st.error(f"Could not reject the request: {exc}")


        # Display the final outcome after the page reruns.
        save_result = st.session_state.get("report_save_result")

        if save_result and save_result.get("status") == "APPROVED_AND_EXECUTED":
            st.success(
                f"Report saved securely to the workspace as `{filename}`. "
                "The action was recorded in the audit trail."
            )

        if st.session_state.pop("report_save_rejected", False):
            st.info("Report save rejected. Nothing was written to the workspace.")


def guardian_playground(executor: GuardedExecutor) -> None:
    st.header("Guardian playground")
    st.caption("See whether an operation is allowed, blocked, or held for approval.")
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
        submit = st.form_submit_button("Evaluate and submit", type="primary")
    if submit:
        try:
            st.session_state.guardian_result = executor.propose(action, arguments)
        except Exception as exc:
            st.error(str(exc))
    if "guardian_result" in st.session_state:
        show_result(st.session_state.guardian_result)
    st.info("Email is simulated locally. The application never sends a real email.")


def approvals_and_audit(executor: GuardedExecutor) -> None:
    st.header("Approvals and audit")
    approvals_tab, audit_tab = st.tabs(["Pending approvals", "Audit trail"])
    with approvals_tab:
        pending = executor.list_pending()
        if not pending:
            st.success("No actions are waiting for approval.")
        for item in pending:
            with st.container(border=True):
                st.subheader(item["tool_name"])
                st.caption(f"Requested {item['created_at']}")
                st.json(item["arguments"])
                yes, no, _ = st.columns([1, 1, 4])
                if yes.button("Approve", key="yes-" + item["approval_id"], type="primary"):
                    executor.resolve_approval(item["approval_id"], True)
                    st.rerun()
                if no.button("Reject", key="no-" + item["approval_id"]):
                    executor.resolve_approval(item["approval_id"], False)
                    st.rerun()
    with audit_tab:
        audit = executor.list_audit(100)
        if audit:
            st.dataframe(audit, use_container_width=True)
            st.caption("Sensitive values are redacted before display.")
        else:
            st.info("No audit events yet. Try an operation in Guardian Playground.")


def security_benchmark(executor: GuardedExecutor) -> None:
    st.header("Security benchmark")
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
        page = st.radio(
            "Navigate",
            ["Company Analysis", "Guardian Playground", "Approvals & Audit", "Security Benchmark"],
            label_visibility="collapsed",
        )
        st.divider()
        
        st.caption("Reports and approvals are isolated to this browser session.")
    if page == "Company Analysis":
        company_analysis(sec, executor)
    elif page == "Guardian Playground":
        guardian_playground(executor)
    elif page == "Approvals & Audit":
        approvals_and_audit(executor)
    else:
        security_benchmark(executor)


if __name__ == "__main__":
    main()
