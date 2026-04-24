"""rbac_vmanage core package.

Shared logic for Cisco vManage RBAC user group management.
Used by both the CLI (`rbac-change-vmanage-user.py`) and the Streamlit
Web UI (`webapp.py`).
"""

from .core import (
    vmanage_login,
    get_usergroup,
    put_usergroup,
    list_usergroups,
    summarize,
    diff_maps,
    print_side_by_side,
    build_payload_all,
    build_payload_targeted,
    build_payload_from_tasks,
)

__all__ = [
    "vmanage_login",
    "get_usergroup",
    "put_usergroup",
    "list_usergroups",
    "summarize",
    "diff_maps",
    "print_side_by_side",
    "build_payload_all",
    "build_payload_targeted",
    "build_payload_from_tasks",
]
