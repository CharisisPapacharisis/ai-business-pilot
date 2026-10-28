"""Conversational Streamlit interface for AI Business Pilot."""

import streamlit as st

from ai_business_pilot.approval import LinearIssueDraft
from ai_business_pilot.ui.runtime import (
    load_thread_state,
    resume_action,
    run_question,
)
from ai_business_pilot.ui.threads import (
    create_thread,
    list_threads,
    title_from_question,
    update_thread,
)

st.set_page_config(page_title="AI Business Pilot", page_icon="📊", layout="wide")


def ensure_selected_thread() -> str:
    """Return a valid selected thread, creating the first one when needed."""
    threads = list_threads()
    known_ids = {thread["thread_id"] for thread in threads}
    selected = st.session_state.get("thread_id")
    if selected not in known_ids:
        selected = threads[0]["thread_id"] if threads else create_thread()
        st.session_state.thread_id = selected
    return selected


def render_sidebar(selected_thread_id: str) -> None:
    """Render new-thread and persistent-thread controls."""
    with st.sidebar:
        st.title("AI Business Pilot")
        if st.button("＋ New conversation", use_container_width=True):
            st.session_state.thread_id = create_thread()
            st.rerun()

        st.caption("Conversations")
        for thread in list_threads():
            selected = thread["thread_id"] == selected_thread_id
            label = f"{'●' if selected else '○'} {thread['title']}"
            if st.button(
                label,
                key=f"thread-{thread['thread_id']}",
                use_container_width=True,
                disabled=selected,
            ):
                st.session_state.thread_id = thread["thread_id"]
                st.rerun()

        st.divider()
        st.caption("Local development UI · persisted with SQLite")


def history_messages(history: list[str]) -> list[tuple[str, str]]:
    """Convert the current string history into renderable chat messages."""
    messages = []
    for entry in history:
        if entry.startswith("User: "):
            messages.append(("user", entry.removeprefix("User: ")))
        elif entry.startswith("Assistant: "):
            messages.append(("assistant", entry.removeprefix("Assistant: ")))
    return messages


def render_history(state: dict) -> None:
    """Render saved messages from the selected graph thread."""
    messages = history_messages(state.get("history", []))
    if not messages:
        st.info(
            "Ask a business question. The planner will choose DuckDB, Linear, "
            "or both, and any external write will pause for approval."
        )
    for role, content in messages:
        with st.chat_message(role):
            st.markdown(content)


def render_activity(state: dict) -> None:
    """Show compact persisted routing and tool activity for the latest turn."""
    if not state.get("route") and not state.get("tool_calls"):
        return
    with st.expander("Latest run activity", expanded=False):
        columns = st.columns(3)
        columns[0].metric("Source route", state.get("route", "—"))
        columns[1].metric("Action", state.get("action", "none"))
        columns[2].metric("Status", state.get("status", "—"))
        calls = state.get("tool_calls", [])
        if calls:
            st.markdown("**Tool calls**")
            for call in calls:
                st.code(call, language=None)
        else:
            st.caption("No MCP tools were called in the latest turn.")


def render_created_issue(state: dict) -> None:
    """Show the latest verified external action outcome."""
    issue = state.get("created_issue")
    if state.get("status") != "created_verified" or not isinstance(issue, dict):
        return
    reference = issue.get("identifier") or issue.get("id") or "Created issue"
    st.success(f"Linear issue {reference} was created and verified.")
    if issue.get("url"):
        st.link_button("Open in Linear", issue["url"])


def render_approval(thread_id: str, state: dict) -> bool:
    """Render and handle the exact checkpointed issue draft when interrupted."""
    draft_data = state.get("draft")
    status = state.get("status")
    if not isinstance(draft_data, dict) or status not in {
        "pending_approval",
        "approved",
        "created_pending_verification",
    }:
        return False

    draft = LinearIssueDraft.model_validate(draft_data)
    st.warning("Human approval required")
    with st.container(border=True):
        st.subheader(draft.title)
        left, right = st.columns(2)
        left.markdown(f"**Team:** {draft.team}")
        right.markdown(f"**Priority:** {draft.proposed_priority}")
        st.markdown(draft.description)
        st.markdown("**Supporting evidence**")
        for item in draft.supporting_evidence:
            st.markdown(f"- {item}")
        st.caption(f"Request ID: {draft.request_id}")

        retry = state.get("approved") is True
        if retry:
            st.info(
                "This draft was already approved. Retry continues the saved action."
            )
            if st.button("Retry approved action", type="primary"):
                with st.status("Resuming approved action…", expanded=True):
                    result = resume_action(thread_id, True, retry=True)
                update_thread(thread_id, status=result.get("status", "completed"))
                st.rerun()
            return True

        approve_column, reject_column = st.columns(2)
        if approve_column.button(
            "Approve and create",
            type="primary",
            use_container_width=True,
        ):
            update_thread(thread_id, status="running")
            with st.status("Creating and verifying the Linear issue…", expanded=True):
                result = resume_action(thread_id, True)
            update_thread(thread_id, status=result.get("status", "completed"))
            st.rerun()
        if reject_column.button("Reject", use_container_width=True):
            update_thread(thread_id, status="running")
            with st.status("Recording rejection…", expanded=True):
                result = resume_action(thread_id, False)
            update_thread(thread_id, status=result.get("status", "completed"))
            st.rerun()
    return True


def submit_question(thread_id: str, question: str, has_history: bool) -> None:
    """Run one user turn and update thread display metadata."""
    update_thread(thread_id, status="running")
    with st.status("Investigating with current business data…", expanded=True):
        result = run_question(thread_id, question)
    update_thread(
        thread_id,
        title=None if has_history else title_from_question(question),
        status=result.get("status", "completed"),
    )
    st.rerun()


def main() -> None:
    """Render the selected conversation and dispatch user interactions."""
    selected_thread_id = ensure_selected_thread()
    render_sidebar(selected_thread_id)

    try:
        state = load_thread_state(selected_thread_id)
    except Exception as error:  # noqa: BLE001 - UI boundary surfaces runtime failures.
        st.error("The saved conversation could not be loaded.")
        st.exception(error)
        return

    st.header("Business analysis")
    st.caption(f"Thread: {selected_thread_id}")
    render_history(state)
    render_created_issue(state)
    render_activity(state)

    try:
        approval_pending = render_approval(selected_thread_id, state)
    except Exception as error:  # noqa: BLE001 - preserve checkpoint and show failure.
        st.error(
            "The approval action failed. Its checkpoint remains available to retry."
        )
        st.exception(error)
        return

    if approval_pending:
        st.chat_input("Resolve the pending approval before continuing", disabled=True)
        return

    if question := st.chat_input("Ask about your business data or initiatives"):
        with st.chat_message("user"):
            st.markdown(question)
        try:
            submit_question(
                selected_thread_id,
                question,
                has_history=bool(state.get("history")),
            )
        except Exception as error:  # noqa: BLE001 - preserve thread and show failure.
            update_thread(selected_thread_id, status="error")
            st.error("The graph run failed. The saved thread was not discarded.")
            st.exception(error)


if __name__ == "__main__":
    main()
