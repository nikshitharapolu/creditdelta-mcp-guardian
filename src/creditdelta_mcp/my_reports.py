from datetime import datetime, timezone

import streamlit as st

from creditdelta_mcp.auth import get_user_client


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


def change_trash_status(report_id, move_to_trash):
    client = get_user_client()

    # Recheck authentication when performing the action.
    user = client.auth.get_user().user
    if not user:
        raise ValueError("Please sign in again.")

    deleted_at = (
        datetime.now(timezone.utc).isoformat()
        if move_to_trash else None
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
                        change_trash_status(report_id, True)
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