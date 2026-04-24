"""Core logic for vManage RBAC user group management.

All HTTPS calls to Cisco vManage REST endpoints are implemented here so
that both the CLI and the Streamlit Web UI can share the exact same
behavior.

Security notes:
- vManage deployments frequently use self-signed certificates, so
  ``requests.Session.verify`` is set to False and urllib3 warnings are
  suppressed. This matches the original CLI behavior. If you run against
  a vManage with a trusted CA chain, override ``sess.verify`` yourself.
- Passwords are never logged or persisted by this module; callers are
  responsible for handling credential storage.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urljoin

import requests

# Disable HTTPS warnings for self-signed certs on vManage (matches CLI).
requests.packages.urllib3.disable_warnings()


# ---------------------------------------------------------------------------
# Authentication / session
# ---------------------------------------------------------------------------
def vmanage_login(vmanage_ip: str, username: str, password: str) -> requests.Session:
    """Authenticate to vManage and return a ready-to-use ``requests.Session``.

    The returned session has the ``JSESSIONID`` cookie set, the
    ``X-XSRF-TOKEN`` header populated, and ``Content-Type: application/json``
    so subsequent GET/PUT/POST calls can be made directly.

    Raises ``SystemExit`` if login fails (keeps CLI parity).
    """
    base = f"https://{vmanage_ip}"
    sess = requests.Session()
    sess.verify = False
    sess.headers.update({"Accept": "application/json"})

    # Step 1: POST to j_security_check
    r = sess.post(
        urljoin(base, "/j_security_check"),
        data={"j_username": username, "j_password": password},
        timeout=30,
    )
    if "JSESSIONID" not in sess.cookies:
        raise SystemExit(f"Login failed: status={r.status_code}")

    # Step 2: Fetch XSRF token (some vManage versions require it for writes)
    t = sess.get(urljoin(base, "/dataservice/client/token"), timeout=15)
    if t.ok and t.text:
        sess.headers["X-XSRF-TOKEN"] = t.text.strip()

    sess.headers["Content-Type"] = "application/json"
    return sess


# ---------------------------------------------------------------------------
# User group retrieval
# ---------------------------------------------------------------------------
def list_usergroups(sess: requests.Session, vmanage_ip: str) -> List[Dict[str, Any]]:
    """Return the full list of user groups from ``/dataservice/admin/usergroup``.

    Each item is the raw dict as returned by vManage (contains at minimum
    ``groupName``, optionally ``groupDesc``, and a ``tasks`` list).
    """
    url = f"https://{vmanage_ip}/dataservice/admin/usergroup"
    r = sess.get(url, timeout=30)
    r.raise_for_status()
    body = r.json() or {}
    data = body.get("data", [])
    if not isinstance(data, list):
        return []
    return data


def get_usergroup(
    sess: requests.Session, vmanage_ip: str, groupname: str
) -> Dict[str, Any]:
    """Return the user group matching ``groupname``.

    Raises ``KeyError`` if the group does not exist (keeps CLI parity).
    """
    for g in list_usergroups(sess, vmanage_ip):
        if g.get("groupName") == groupname:
            return g
    raise KeyError(f"usergroup '{groupname}' not found")


# ---------------------------------------------------------------------------
# User group update
# ---------------------------------------------------------------------------
def put_usergroup(
    sess: requests.Session,
    vmanage_ip: str,
    groupname: str,
    payload: Dict[str, Any],
) -> Any:
    """PUT an updated user group payload to vManage.

    Returns the parsed JSON response if available, otherwise the raw text
    (or the literal string ``"OK"`` on empty 2xx responses). Raises for
    non-2xx responses after printing status + body (matches CLI behavior).
    """
    url = f"https://{vmanage_ip}/dataservice/admin/usergroup/{groupname}"
    payload = dict(payload)  # shallow copy so we do not mutate the caller's dict
    payload["groupName"] = groupname
    r = sess.put(url, json=payload, timeout=60)
    if not r.ok:
        print("STATUS:", r.status_code)
        print("BODY  :", r.text)
        r.raise_for_status()
    try:
        return r.json()
    except ValueError:
        return r.text or "OK"


# ---------------------------------------------------------------------------
# Summarization helpers
# ---------------------------------------------------------------------------
def summarize(tasks: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Optional[bool]]]:
    """Convert a list of task dicts into ``{feature: {enabled, read, write}}``."""
    return {
        t["feature"]: {
            "enabled": t.get("enabled"),
            "read": t.get("read"),
            "write": t.get("write"),
        }
        for t in tasks
        if "feature" in t
    }


def _erw_bits(entry: Optional[Dict[str, Any]]) -> str:
    """Return the 3-char ``ERW`` bit string for a permission entry."""
    e = entry or {}
    return (
        f"{int(bool(e.get('enabled')))}"
        f"{int(bool(e.get('read')))}"
        f"{int(bool(e.get('write')))}"
    )


def diff_maps(
    before_map: Dict[str, Dict[str, Optional[bool]]],
    after_map: Dict[str, Dict[str, Optional[bool]]],
) -> List[Dict[str, Any]]:
    """Return a row-per-feature diff suitable for table display.

    Each row has the shape::

        {
            "feature": str,
            "before_ERW": "101",
            "after_ERW":  "111",
            "changed":    bool,
        }

    The union of features in ``before_map`` and ``after_map`` is returned,
    sorted alphabetically.
    """
    features = sorted(set(before_map.keys()) | set(after_map.keys()))
    rows: List[Dict[str, Any]] = []
    for feat in features:
        b = before_map.get(feat)
        a = after_map.get(feat)
        rows.append(
            {
                "feature": feat,
                "before_ERW": _erw_bits(b) if b is not None else "---",
                "after_ERW": _erw_bits(a) if a is not None else "---",
                "changed": b != a,
            }
        )
    return rows


def print_side_by_side(
    before_map: Dict[str, Dict[str, Optional[bool]]],
    after_map: Dict[str, Dict[str, Optional[bool]]],
    list_mode: str = "changed",
) -> None:
    """Print before/after in the same table format used by the original CLI."""
    print("\n=== Permissions (Before -> After) ===")
    print("Legend: ERW bits (Enabled, Read, Write). '1'=True, '0'=False")
    print(f"List Mode : {list_mode.upper()}")
    print(f"Total Feats in Group: {len(before_map)}")

    if list_mode == "changed":
        changed_keys = [k for k in before_map if before_map.get(k) != after_map.get(k)]
        print(f"Changed Feats        : {len(changed_keys)}")
    else:
        changed_keys = list(before_map.keys())

    print("-----------------------------------------------")
    print(f"{'Feature':<22} BEFORE  AFTER")
    print("-----------------------------------------------")
    for feat in sorted(changed_keys):
        b = before_map.get(feat, {})
        a = after_map.get(feat, {})
        print(f"{feat:<22} {_erw_bits(b):<6} {_erw_bits(a)}")
    if not changed_keys:
        print("(no rows to display)")


# ---------------------------------------------------------------------------
# Payload builders
# ---------------------------------------------------------------------------
def build_payload_all(
    cur_group: Dict[str, Any], groupname: str, mode: str
) -> Dict[str, Any]:
    """Build a payload modifying ALL tasks according to ``mode``.

    ``mode`` must be one of:
    - ``"ALL_WRITE"`` -> ``enabled=True, read=False, write=True``
    - ``"ALL_READ"``  -> ``enabled=True, read=True,  write=False``
    """
    tasks: List[Dict[str, Any]] = []
    for t in cur_group.get("tasks", []):
        feature = t.get("feature")
        if mode == "ALL_WRITE":
            tasks.append(
                {"feature": feature, "enabled": True, "read": False, "write": True}
            )
        elif mode == "ALL_READ":
            tasks.append(
                {"feature": feature, "enabled": True, "read": True, "write": False}
            )
        else:
            raise ValueError("Unknown mode for build_payload_all")
    return {
        "groupName": groupname,
        "groupDesc": cur_group.get("groupDesc", "user group description"),
        "tasks": tasks,
    }


def build_payload_targeted(
    cur_group: Dict[str, Any],
    groupname: str,
    targets: Iterable[str],
    write: bool,
    read: bool,
) -> Dict[str, Any]:
    """Build a payload modifying ONLY the specified target features."""
    target_set = set(targets)
    tasks: List[Dict[str, Any]] = []
    for t in cur_group.get("tasks", []):
        if t.get("feature") in target_set:
            tasks.append(
                {
                    "feature": t.get("feature"),
                    "enabled": True,
                    "read": read,
                    "write": write,
                }
            )
        else:
            tasks.append(t)
    return {
        "groupName": groupname,
        "groupDesc": cur_group.get("groupDesc", "user group description"),
        "tasks": tasks,
    }


def build_payload_from_tasks(
    groupname: str,
    group_desc: Optional[str],
    tasks: Iterable[Dict[str, Any]],
) -> Dict[str, Any]:
    """Build a payload directly from an edited list of task dicts.

    Used by the Web UI where the user edits tasks row-by-row.
    Each task dict must contain ``feature`` and may contain
    ``enabled`` / ``read`` / ``write`` (booleans). Missing flags
    default to False.
    """
    normalized: List[Dict[str, Any]] = []
    for t in tasks:
        feature = t.get("feature")
        if not feature:
            continue
        normalized.append(
            {
                "feature": feature,
                "enabled": bool(t.get("enabled", False)),
                "read": bool(t.get("read", False)),
                "write": bool(t.get("write", False)),
            }
        )
    return {
        "groupName": groupname,
        "groupDesc": group_desc or "user group description",
        "tasks": normalized,
    }


# ---------------------------------------------------------------------------
# Convenience for JSON pretty printing (used by CLI)
# ---------------------------------------------------------------------------
def to_pretty_json(obj: Any) -> str:
    """Return pretty-printed JSON for debug/log output."""
    return json.dumps(obj, indent=2, ensure_ascii=False)
