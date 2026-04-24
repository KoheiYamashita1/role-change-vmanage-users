#!/usr/bin/env python3
import sys
import argparse
import requests
import json
from urllib.parse import urljoin

# Disable HTTPS warnings for self-signed certs on vManage
requests.packages.urllib3.disable_warnings()

def vmanage_login(vmanage_ip: str, username: str, password: str) -> requests.Session:
    """
    Login to vManage and return an authenticated requests.Session
    with XSRF token and JSON headers set.
    """
    base = f"https://{vmanage_ip}"
    sess = requests.Session()
    sess.verify = False
    sess.headers.update({"Accept": "application/json"})

    # Step 1: POST to j_security_check
    r = sess.post(urljoin(base, "/j_security_check"),
                  data={"j_username": username, "j_password": password}, timeout=30)
    if "JSESSIONID" not in sess.cookies:
        raise SystemExit(f"Login failed: status={r.status_code}")

    # Step 2: Fetch XSRF token
    t = sess.get(urljoin(base, "/dataservice/client/token"), timeout=15)
    if t.ok and t.text:
        sess.headers["X-XSRF-TOKEN"] = t.text.strip()

    # Default Content-Type
    sess.headers["Content-Type"] = "application/json"
    return sess

def get_usergroup(sess: requests.Session, vmanage_ip: str, groupname: str) -> dict:
    """
    Retrieve all user groups and return the one matching `groupname`.
    """
    url = f"https://{vmanage_ip}/dataservice/admin/usergroup"
    r = sess.get(url, timeout=30)
    r.raise_for_status()
    body = r.json() or {}
    for g in body.get("data", []):
        if g.get("groupName") == groupname:
            return g
    raise KeyError(f"usergroup '{groupname}' not found")

def put_usergroup(sess: requests.Session, vmanage_ip: str, groupname: str, payload: dict):
    """
    PUT updated user group payload to vManage.
    """
    url = f"https://{vmanage_ip}/dataservice/admin/usergroup/{groupname}"
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

def summarize(tasks: list) -> dict:
    """
    Convert list of task dicts into {feature: {enabled, read, write}}.
    """
    return {
        t["feature"]: {
            "enabled": t.get("enabled"),
            "read": t.get("read"),
            "write": t.get("write")
        }
        for t in tasks
    }

def print_side_by_side(before_map: dict, after_map: dict, list_mode: str = "changed"):
    """
    Print before/after in a table format.
    list_mode = "changed" or "all"
    """
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
        b_str = f"{int(bool(b.get('enabled')))}{int(bool(b.get('read')))}{int(bool(b.get('write')))}"
        a_str = f"{int(bool(a.get('enabled')))}{int(bool(a.get('read')))}{int(bool(a.get('write')))}"
        print(f"{feat:<22} {b_str:<6} {a_str}")
    if not changed_keys:
        print("(no rows to display)")

def build_payload_all(cur_group: dict, groupname: str, mode: str) -> dict:
    """
    Build payload modifying ALL tasks according to mode:
    mode = "ALL_WRITE" -> write=True, read=False, enabled=True
    mode = "ALL_READ"  -> read=True, write=False, enabled=True
    """
    tasks = []
    for t in cur_group.get("tasks", []):
        if mode == "ALL_WRITE":
            tasks.append({"feature": t.get("feature"), "enabled": True, "read": False, "write": True})
        elif mode == "ALL_READ":
            tasks.append({"feature": t.get("feature"), "enabled": True, "read": True, "write": False})
        else:
            raise ValueError("Unknown mode for build_payload_all")
    return {
        "groupName": groupname,
        "groupDesc": cur_group.get("groupDesc", "user group description"),
        "tasks": tasks
    }

def build_payload_targeted(cur_group: dict, groupname: str, targets: list, write: bool, read: bool) -> dict:
    """
    Build payload modifying ONLY specified target features.
    """
    tasks = []
    for t in cur_group.get("tasks", []):
        if t.get("feature") in targets:
            tasks.append({"feature": t.get("feature"), "enabled": True, "read": read, "write": write})
        else:
            tasks.append(t)
    return {
        "groupName": groupname,
        "groupDesc": cur_group.get("groupDesc", "user group description"),
        "tasks": tasks
    }

def main():
    ap = argparse.ArgumentParser(description="vManage RBAC Task Permission Modifier")
    ap.add_argument("--host", help="vManage IP or hostname")
    ap.add_argument("--user", help="vManage username")
    ap.add_argument("--password", help="vManage password")
    ap.add_argument("--group", help="Target user group name")
    ap.add_argument("--mode", choices=["all-write", "all-read", "targeted"], help="Permission change mode")
    ap.add_argument("--targets", nargs="+", help="List of feature names to modify (for targeted mode)")
    ap.add_argument("--write", type=bool, default=None, help="Write flag for targeted mode")
    ap.add_argument("--read", type=bool, default=None, help="Read flag for targeted mode")
    ap.add_argument("--check-only", action="store_true", help="Only check current settings (no changes)")
    ap.add_argument("--dry-run", action="store_true", help="Show planned changes but do not apply")
    ap.add_argument("--list-mode", choices=["changed", "all"], default="changed", help="List all tasks or only changed ones")
    args = ap.parse_args()

    # Show usage example if insufficient arguments
    if not args.host or not args.user or not args.password or not args.group:
        print("Example usage:")
        print("  python3 rbac-change-vmanage-user.py --host <vmanage-ip> --user <admin-username> --password <password> --group demogrp --check-only")
        print("  python3 rbac-change-vmanage-user.py --host <vmanage-ip> --user <admin-username> --password <password> --group demogrp --mode all-write")
        print("  python3 rbac-change-vmanage-user.py --host <vmanage-ip> --user <admin-username> --password <password> --group demogrp --mode targeted --targets 'Application Monitoring' 'Policy' --write True --read False")
        sys.exit(1)

    sess = vmanage_login(args.host, args.user, args.password)

    # Fetch current group
    current_group = get_usergroup(sess, args.host, args.group)
    before_map = summarize(current_group.get("tasks", []))

    if args.check_only:
        # Always show ALL in check-only so user sees everything
        lm = "all"
        print(json.dumps({
            "host": args.host,
            "group": args.group,
            "mode": "CHECK_ONLY",
            "task_count": len(before_map)
        }, indent=2))
        print_side_by_side(before_map, before_map, list_mode=lm)
        return

    # Build planned payload
    if args.mode == "all-write":
        payload = build_payload_all(current_group, args.group, "ALL_WRITE")
    elif args.mode == "all-read":
        payload = build_payload_all(current_group, args.group, "ALL_READ")
    elif args.mode == "targeted":
        if not args.targets or args.write is None or args.read is None:
            raise SystemExit("Targeted mode requires --targets and both --write and --read flags.")
        payload = build_payload_targeted(current_group, args.group, args.targets, args.write, args.read)
    else:
        raise SystemExit("Must specify a mode unless using --check-only.")

    after_predicted_map = summarize(payload.get("tasks", []))

    if args.dry_run:
        changed_pred = [k for k in before_map if before_map.get(k) != after_predicted_map.get(k)]
        lm = "all" if args.list_mode == "changed" and not changed_pred else args.list_mode
        print(json.dumps({
            "host": args.host,
            "group": args.group,
            "mode": f"DRY_RUN-{args.mode.upper()}",
            "planned_task_count": len(after_predicted_map),
            "predicted_changed_feature_count": len(changed_pred)
        }, indent=2))
        print_side_by_side(before_map, after_predicted_map, list_mode=lm)
        return

    # Apply changes
    put_res = put_usergroup(sess, args.host, args.group, payload)
    print("PUT result:", put_res)

    # Fetch after state
    after_group = get_usergroup(sess, args.host, args.group)
    after_map = summarize(after_group.get("tasks", []))

    # Decide listing mode (if no change, force all)
    changed_after = [k for k in before_map if before_map.get(k) != after_map.get(k)]
    lm = "all" if args.list_mode == "changed" and not changed_after else args.list_mode

    print_side_by_side(before_map, after_map, list_mode=lm)

if __name__ == "__main__":
    main()

