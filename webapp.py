"""Streamlit Web UI for vManage RBAC user group management.

Run with::

    streamlit run webapp.py --server.address 127.0.0.1

Then open http://localhost:8501 in your browser.

Features
--------
- Sidebar: vManage host / user / password login form.
- Tab 1 (Groups):          list all user groups, pick one to edit.
- Tab 2 (Current Status):  view permissions of the selected group.
- Tab 3 (Edit Permissions): edit per-task enabled/read/write flags,
  apply presets (All Write / All Read / Reset), preview diff, and apply.
- Tab 4 (Raw JSON):        inspect the raw group dict returned by vManage.

Security notes
--------------
- Passwords are kept only in ``st.session_state`` for the lifetime of the
  browser session; they are never written to disk by this script.
- Default values for host / user are read from the environment variables
  ``VMANAGE_HOST`` / ``VMANAGE_USER``. Passwords are NOT read from env.
- Bind to 127.0.0.1 (as shown above) unless you deliberately want other
  machines on the network to reach this UI.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

import pandas as pd
import streamlit as st

from rbac_vmanage.core import (
    build_payload_all,
    build_payload_from_tasks,
    diff_maps,
    get_usergroup,
    list_usergroups,
    put_usergroup,
    summarize,
    to_pretty_json,
    vmanage_login,
)


# ---------------------------------------------------------------------------
# Page setup
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="vManage RBAC Manager",
    page_icon="🛡️",
    layout="wide",
)


# ---------------------------------------------------------------------------
# Session-state helpers
# ---------------------------------------------------------------------------
def _init_state() -> None:
    defaults = {
        "sess": None,
        "host": "",
        "user": "",
        "groups": [],
        "selected_group": None,
        "edit_tasks": None,  # list[dict] currently being edited
        "edit_group_name": None,  # name of the group that edit_tasks belongs to
        "pending_apply": False,  # two-step confirm for Apply Changes
        "last_put_result": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def _is_connected() -> bool:
    return st.session_state.get("sess") is not None


def _logout() -> None:
    st.session_state["sess"] = None
    st.session_state["host"] = ""
    st.session_state["user"] = ""
    st.session_state["groups"] = []
    st.session_state["selected_group"] = None
    st.session_state["edit_tasks"] = None
    st.session_state["edit_group_name"] = None
    st.session_state["pending_apply"] = False
    st.session_state["last_put_result"] = None


# ---------------------------------------------------------------------------
# Sidebar: connection form
# ---------------------------------------------------------------------------
def _render_sidebar() -> None:
    st.sidebar.title("🔐 vManage Connection")

    if _is_connected():
        st.sidebar.success(f"Connected: {st.session_state['host']}")
        st.sidebar.caption(f"User: {st.session_state['user']}")
        if st.sidebar.button("Logout", use_container_width=True):
            _logout()
            st.rerun()
        return

    st.sidebar.error("Disconnected")

    default_host = os.environ.get("VMANAGE_HOST", "")
    default_user = os.environ.get("VMANAGE_USER", "")

    with st.sidebar.form("login_form", clear_on_submit=False):
        host = st.text_input("Host / IP", value=default_host, placeholder="vmanage.example.com")
        user = st.text_input("Username", value=default_user, placeholder="admin")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login", use_container_width=True)

    if submitted:
        if not host or not user or not password:
            st.sidebar.warning("Host, user, and password are all required.")
            return
        with st.spinner(f"Logging in to {host}..."):
            try:
                sess = vmanage_login(host, user, password)
            except SystemExit as e:
                st.sidebar.error(f"Login failed: {e}")
                return
            except Exception as e:  # network, TLS, etc.
                st.sidebar.error(f"Login error: {e}")
                return

        st.session_state["sess"] = sess
        st.session_state["host"] = host
        st.session_state["user"] = user
        st.session_state["groups"] = []
        st.session_state["selected_group"] = None
        st.session_state["edit_tasks"] = None
        st.session_state["edit_group_name"] = None
        st.rerun()


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------
def _load_groups(force: bool = False) -> List[Dict[str, Any]]:
    if not _is_connected():
        return []
    if force or not st.session_state.get("groups"):
        try:
            st.session_state["groups"] = list_usergroups(
                st.session_state["sess"], st.session_state["host"]
            )
        except Exception as e:
            st.error(f"Failed to list user groups: {e}")
            st.session_state["groups"] = []
    return st.session_state["groups"]


def _get_current_group(groupname: str) -> Dict[str, Any]:
    """Fetch a single group from the in-memory list (no extra API call)."""
    for g in st.session_state.get("groups") or []:
        if g.get("groupName") == groupname:
            return g
    # Fallback: hit the API directly.
    return get_usergroup(st.session_state["sess"], st.session_state["host"], groupname)


def _reset_edit_buffer(current_group: Dict[str, Any]) -> None:
    """Copy the current group's tasks into the editable buffer."""
    tasks = current_group.get("tasks") or []
    st.session_state["edit_tasks"] = [
        {
            "feature": t.get("feature"),
            "enabled": bool(t.get("enabled", False)),
            "read": bool(t.get("read", False)),
            "write": bool(t.get("write", False)),
        }
        for t in tasks
        if t.get("feature")
    ]
    st.session_state["edit_group_name"] = current_group.get("groupName")
    st.session_state["pending_apply"] = False


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
def _tab_groups() -> None:
    st.subheader("User Groups")

    col_a, col_b = st.columns([1, 3])
    with col_a:
        if st.button("🔄 Reload groups", use_container_width=True):
            _load_groups(force=True)

    groups = _load_groups()
    if not groups:
        st.info("No user groups loaded yet. Click 'Reload groups'.")
        return

    rows = []
    for g in groups:
        rows.append(
            {
                "groupName": g.get("groupName", ""),
                "groupDesc": g.get("groupDesc", ""),
                "task_count": len(g.get("tasks") or []),
            }
        )
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)

    names = [g.get("groupName") for g in groups if g.get("groupName")]
    current = st.session_state.get("selected_group")
    try:
        idx = names.index(current) if current in names else 0
    except ValueError:
        idx = 0

    selected = st.selectbox(
        "Select a group to inspect / edit",
        options=names,
        index=idx if names else 0,
        key="selected_group_picker",
    )
    if selected and selected != st.session_state.get("selected_group"):
        st.session_state["selected_group"] = selected
        # Invalidate any stale edit buffer belonging to a different group.
        if st.session_state.get("edit_group_name") != selected:
            st.session_state["edit_tasks"] = None
            st.session_state["edit_group_name"] = None
            st.session_state["pending_apply"] = False
    elif selected:
        st.session_state["selected_group"] = selected


def _tab_current_status() -> None:
    st.subheader("Current Status")
    groupname = st.session_state.get("selected_group")
    if not groupname:
        st.info("Select a group in the 'Groups' tab first.")
        return

    try:
        group = _get_current_group(groupname)
    except Exception as e:
        st.error(f"Failed to load group: {e}")
        return

    tasks = group.get("tasks") or []
    summary = summarize(tasks)

    total = len(summary)
    enabled = sum(1 for v in summary.values() if v.get("enabled"))
    read_only = sum(
        1 for v in summary.values() if v.get("read") and not v.get("write")
    )
    write_enabled = sum(1 for v in summary.values() if v.get("write"))

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total features", total)
    m2.metric("Enabled", enabled)
    m3.metric("Read-only", read_only)
    m4.metric("Write-enabled", write_enabled)

    rows = [
        {
            "Feature": feat,
            "Enabled": bool(v.get("enabled")),
            "Read": bool(v.get("read")),
            "Write": bool(v.get("write")),
        }
        for feat, v in sorted(summary.items())
    ]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def _tab_edit_permissions() -> None:
    st.subheader("Edit Permissions")
    groupname = st.session_state.get("selected_group")
    if not groupname:
        st.info("Select a group in the 'Groups' tab first.")
        return

    try:
        current_group = _get_current_group(groupname)
    except Exception as e:
        st.error(f"Failed to load group: {e}")
        return

    # Initialize the edit buffer on first entry / group change.
    if (
        st.session_state.get("edit_tasks") is None
        or st.session_state.get("edit_group_name") != groupname
    ):
        _reset_edit_buffer(current_group)

    # Preset buttons ----------------------------------------------------------
    st.markdown("**Presets**")
    c1, c2, c3 = st.columns(3)
    if c1.button("All Write", use_container_width=True):
        payload = build_payload_all(current_group, groupname, "ALL_WRITE")
        st.session_state["edit_tasks"] = [
            {
                "feature": t["feature"],
                "enabled": bool(t.get("enabled")),
                "read": bool(t.get("read")),
                "write": bool(t.get("write")),
            }
            for t in payload["tasks"]
        ]
        st.session_state["pending_apply"] = False
    if c2.button("All Read", use_container_width=True):
        payload = build_payload_all(current_group, groupname, "ALL_READ")
        st.session_state["edit_tasks"] = [
            {
                "feature": t["feature"],
                "enabled": bool(t.get("enabled")),
                "read": bool(t.get("read")),
                "write": bool(t.get("write")),
            }
            for t in payload["tasks"]
        ]
        st.session_state["pending_apply"] = False
    if c3.button("Reset to Current", use_container_width=True):
        _reset_edit_buffer(current_group)

    st.divider()

    # Row-level editor --------------------------------------------------------
    edit_df = pd.DataFrame(st.session_state["edit_tasks"])
    if edit_df.empty:
        st.warning("This group has no tasks.")
        return

    edited = st.data_editor(
        edit_df,
        use_container_width=True,
        hide_index=True,
        num_rows="fixed",
        disabled=["feature"],
        column_config={
            "feature": st.column_config.TextColumn("Feature"),
            "enabled": st.column_config.CheckboxColumn("Enabled"),
            "read": st.column_config.CheckboxColumn("Read"),
            "write": st.column_config.CheckboxColumn("Write"),
        },
        key=f"editor_{groupname}",
    )

    # Persist edits back into session state so they survive reruns triggered
    # by the Apply / preset buttons below.
    st.session_state["edit_tasks"] = edited.to_dict(orient="records")

    # Diff preview ------------------------------------------------------------
    st.divider()
    st.markdown("**Diff Preview (changed rows only)**")
    before_map = summarize(current_group.get("tasks") or [])
    after_map = summarize(st.session_state["edit_tasks"])
    all_rows = diff_maps(before_map, after_map)
    changed_rows = [r for r in all_rows if r["changed"]]

    if not changed_rows:
        st.info("No changes vs. current state.")
    else:
        st.caption(
            f"{len(changed_rows)} of {len(all_rows)} features changed. "
            "ERW = Enabled / Read / Write (1=True, 0=False)."
        )
        st.dataframe(
            pd.DataFrame(changed_rows)[["feature", "before_ERW", "after_ERW"]],
            use_container_width=True,
            hide_index=True,
        )

    # Apply ------------------------------------------------------------------
    st.divider()
    dry_run = st.checkbox(
        "Dry-run (validate only, do not PUT to vManage)",
        value=True,
        help="When checked, the Apply button will only show the planned diff.",
    )

    apply_col, status_col = st.columns([1, 3])
    apply_clicked = apply_col.button(
        "Apply Changes", type="primary", use_container_width=True
    )

    if apply_clicked:
        if not changed_rows:
            status_col.info("Nothing to apply — no changes detected.")
        elif dry_run:
            status_col.success(
                f"Dry-run OK: {len(changed_rows)} feature(s) would change. "
                "No PUT was sent."
            )
        else:
            if not st.session_state.get("pending_apply"):
                st.session_state["pending_apply"] = True
                status_col.warning(
                    "⚠️ Click **Apply Changes** again to confirm and PUT to vManage."
                )
            else:
                # Second click — actually send the PUT.
                payload = build_payload_from_tasks(
                    groupname,
                    current_group.get("groupDesc"),
                    st.session_state["edit_tasks"],
                )
                try:
                    with st.spinner("Applying changes to vManage..."):
                        result = put_usergroup(
                            st.session_state["sess"],
                            st.session_state["host"],
                            groupname,
                            payload,
                        )
                    st.session_state["last_put_result"] = result
                    st.session_state["pending_apply"] = False
                    # Refresh the cached group list so Current Status reflects reality.
                    _load_groups(force=True)
                    refreshed = _get_current_group(groupname)
                    _reset_edit_buffer(refreshed)
                    status_col.success(f"Applied. Server response: {result}")
                except Exception as e:
                    st.session_state["pending_apply"] = False
                    status_col.error(f"PUT failed: {e}")

    if st.session_state.get("last_put_result") is not None:
        with st.expander("Last PUT response"):
            st.write(st.session_state["last_put_result"])


def _tab_raw_json() -> None:
    st.subheader("Raw JSON")
    groupname = st.session_state.get("selected_group")
    if not groupname:
        st.info("Select a group in the 'Groups' tab first.")
        return

    try:
        group = _get_current_group(groupname)
    except Exception as e:
        st.error(f"Failed to load group: {e}")
        return

    st.caption(
        "Raw dictionary returned by vManage. Useful for debugging — this is "
        "exactly what the API sees."
    )
    st.code(to_pretty_json(group), language="json")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    _init_state()
    _render_sidebar()

    st.title("🛡️ vManage RBAC Manager")
    st.caption(
        "Manage Cisco vManage user group permissions from your browser. "
        "All API calls are made from this machine only."
    )

    if not _is_connected():
        st.info(
            "Enter your vManage host, username, and password in the sidebar "
            "and click **Login** to get started."
        )
        return

    tab_groups, tab_status, tab_edit, tab_raw = st.tabs(
        ["Groups", "Current Status", "Edit Permissions", "Raw JSON"]
    )
    with tab_groups:
        _tab_groups()
    with tab_status:
        _tab_current_status()
    with tab_edit:
        _tab_edit_permissions()
    with tab_raw:
        _tab_raw_json()


if __name__ == "__main__":
    main()
