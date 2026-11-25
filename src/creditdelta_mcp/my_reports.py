from datetime import datetime, timezone

import streamlit as st

from creditdelta_mcp.auth import get_user_client
from creditdelta_mcp.guardian import Decision, PolicyEngine


def save_report(title, company, metric, content):
    client = get_user_client()
    user = client.auth.get_user().user

    if not user:
        raise ValueError("Please sign in first.")

    client.table("reports").insert({
        "user_id": user.id,
        "title": title,
        "company": company,
        "metric": metric,
        "content": content,
    }).execute()


def change_trash_status(report_id, move_to_trash, *, confirmed=False):
    client = get_user_client()
    user = client.auth.get_user().user
    if not user:
        raise ValueError("Please sign in again.")

    # Fetch ownership from the database, never from a form field.
    reports = (
        client.table("reports")
        .select("id,user_id")
        .eq("id", report_id)
        .eq("user_id", user.id)
        .limit(1)
        .execute()
        .data
    )

    owner_id = reports[0]["user_id"] if reports else None
    action = "trash_report" if move_to_trash else "restore_report"

    decision = PolicyEngine().evaluate_report_action(
        action,
        authenticated_user_id=user.id,
        report_owner_id=owner_id,
    )

    if decision.decision == Decision.DENY:
        raise ValueError("Report unavailable.")

    if (
        decision.decision == Decision.REQUIRE_APPROVAL
        and confirmed is not True
    ):
        raise ValueError("Please confirm before moving this report to Trash.")

    deleted_at = (
        datetime.now(timezone.utc).isoformat()
        if move_to_trash
        else None
    )

    result = (
        client.table("reports")
        .update({"deleted_at": deleted_at})
        .eq("id", report_id)
        .eq("user_id", user.id)
        .execute()
    )

    if not result.data:
        raise ValueError("Report unavailable.")

def show_report_history(client, user_id):
    with st.expander("Your recent activity"):
        try:
            events = (
                client.table("report_activity")
                .select("report_id,action,created_at")
                .eq("user_id", user_id)
                .order("created_at", desc=True)
                .limit(30)
                .execute()
                .data
            )
        except Exception:
            st.warning("Could not load activity history. Please try again.")
            return

        if not events:
            st.caption("New saves, moves to Trash, and restores will appear here.")
            return

        labels = {
            "saved": "Report saved",
            "trashed": "Moved to Trash",
            "restored": "Report restored",
        }

        st.dataframe(
            [
                {
                    "Action": labels.get(event["action"], event["action"]),
                    "Time (UTC)": event["created_at"],
                    "Report ID": event["report_id"],
                }
                for event in events
            ],
            hide_index=True,
            use_container_width=True,
        )
def show_my_reports():
    st.header("My Reports")
    client = get_user_client()

    try:
        user = client.auth.get_user().user
    except Exception:
        user = None

    if not user:
        st.info("Sign in using the sidebar to view your reports.")
        return
    show_report_history(client, user.id)

    # Clear the previous confirmation before rendering its widget again.
    confirmation_key = st.session_state.pop(
        "report_confirmation_to_clear", None
    )
    if confirmation_key:
        st.session_state.pop(confirmation_key, None)

    notice = st.session_state.pop("my_reports_notice", None)
    if notice:
        st.success(notice)

    show_trash = st.checkbox("Show Trash", key="show_report_trash")

    try:
        query = (
            client.table("reports")
            .select("id,title,company,metric,content,created_at")
            .eq("user_id", user.id)
        )

        if show_trash:
            query = query.not_.is_("deleted_at", "null")
        else:
            query = query.is_("deleted_at", "null")

        reports = (
            query.order("created_at", desc=True)
            .limit(50)
            .execute()
            .data
        )
    except Exception:
        st.error("Could not load reports. Please try again.")
        return

    if not reports:
        st.info(
            "Trash is empty."
            if show_trash
            else "No saved reports yet. Create one in Explore Companies."
        )
        return

    st.caption(
        "Showing up to 50 trashed reports."
        if show_trash
        else "Showing your 50 most recent reports."
    )

    for report in reports:
        report_id = report["id"]
        confirmation_key = f"confirm-trash-{report_id}"

        with st.expander(report["title"]):
            st.caption(f"Saved: {report['created_at']}")
            st.text(report["content"])

            st.download_button(
                "Download",
                data=report["content"],
                file_name=f"report-{report_id}.md",
                mime="text/markdown",
                key=f"download-{report_id}",
            )

            if show_trash:
                if st.button("Restore", key=f"restore-{report_id}"):
                    try:
                        change_trash_status(report_id, False)
                    except Exception:
                        st.error(
                            "Could not restore the report. "
                            "Check your login and try again."
                        )
                    else:
                        st.session_state.my_reports_notice = (
                            "Report restored. Turn off Show Trash to view it."
                        )
                        st.session_state.report_confirmation_to_clear = (
                            confirmation_key
                        )
                        st.rerun()
            else:
                confirmed = st.checkbox(
                    "Move this report to Trash? You can restore it later.",
                    key=confirmation_key,
                )

                if st.button(
                    "Move to Trash",
                    key=f"trash-{report_id}",
                    disabled=not confirmed,
                ):
                    try:
                        change_trash_status(report_id, True, confirmed=confirmed)
                    except Exception:
                        st.error(
                            "Could not move the report to Trash. "
                            "Check your login and try again."
                        )
                    else:
                        st.session_state.my_reports_notice = (
                            "Report moved to Trash. You can restore it later."
                        )
                        st.session_state.report_confirmation_to_clear = (
                            confirmation_key
                        )
                        st.rerun()