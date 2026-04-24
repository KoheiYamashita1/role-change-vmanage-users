#!/usr/bin/env python3
"""vManage RBAC Task Permission Modifier (CLI).

This script is a thin wrapper around :mod:`rbac_vmanage.core` so that the
CLI and the Streamlit Web UI (``webapp.py``) share the same underlying
logic. The public CLI contract (arguments, output format, exit codes) is
unchanged.
"""

import argparse
import json
import sys

from rbac_vmanage.core import (
    build_payload_all,
    build_payload_targeted,
    get_usergroup,
    print_side_by_side,
    put_usergroup,
    summarize,
    vmanage_login,
)


def main() -> None:
    ap = argparse.ArgumentParser(description="vManage RBAC Task Permission Modifier")
    ap.add_argument("--host", help="vManage IP or hostname")
    ap.add_argument("--user", help="vManage username")
    ap.add_argument("--password", help="vManage password")
    ap.add_argument("--group", help="Target user group name")
    ap.add_argument(
        "--mode",
        choices=["all-write", "all-read", "targeted"],
        help="Permission change mode",
    )
    ap.add_argument(
        "--targets",
        nargs="+",
        help="List of feature names to modify (for targeted mode)",
    )
    ap.add_argument(
        "--write", type=bool, default=None, help="Write flag for targeted mode"
    )
    ap.add_argument(
        "--read", type=bool, default=None, help="Read flag for targeted mode"
    )
    ap.add_argument(
        "--check-only",
        action="store_true",
        help="Only check current settings (no changes)",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Show planned changes but do not apply",
    )
    ap.add_argument(
        "--list-mode",
        choices=["changed", "all"],
        default="changed",
        help="List all tasks or only changed ones",
    )
    args = ap.parse_args()

    # Show usage example if insufficient arguments
    if not args.host or not args.user or not args.password or not args.group:
        print("Example usage:")
        print(
            "  python3 rbac-change-vmanage-user.py --host <vmanage-ip> "
            "--user <admin-username> --password <password> --group demogrp --check-only"
        )
        print(
            "  python3 rbac-change-vmanage-user.py --host <vmanage-ip> "
            "--user <admin-username> --password <password> --group demogrp --mode all-write"
        )
        print(
            "  python3 rbac-change-vmanage-user.py --host <vmanage-ip> "
            "--user <admin-username> --password <password> --group demogrp "
            "--mode targeted --targets 'Application Monitoring' 'Policy' --write True --read False"
        )
        sys.exit(1)

    sess = vmanage_login(args.host, args.user, args.password)

    # Fetch current group
    current_group = get_usergroup(sess, args.host, args.group)
    before_map = summarize(current_group.get("tasks", []))

    if args.check_only:
        # Always show ALL in check-only so the user sees everything
        lm = "all"
        print(
            json.dumps(
                {
                    "host": args.host,
                    "group": args.group,
                    "mode": "CHECK_ONLY",
                    "task_count": len(before_map),
                },
                indent=2,
            )
        )
        print_side_by_side(before_map, before_map, list_mode=lm)
        return

    # Build planned payload
    if args.mode == "all-write":
        payload = build_payload_all(current_group, args.group, "ALL_WRITE")
    elif args.mode == "all-read":
        payload = build_payload_all(current_group, args.group, "ALL_READ")
    elif args.mode == "targeted":
        if not args.targets or args.write is None or args.read is None:
            raise SystemExit(
                "Targeted mode requires --targets and both --write and --read flags."
            )
        payload = build_payload_targeted(
            current_group, args.group, args.targets, args.write, args.read
        )
    else:
        raise SystemExit("Must specify a mode unless using --check-only.")

    after_predicted_map = summarize(payload.get("tasks", []))

    if args.dry_run:
        changed_pred = [
            k for k in before_map if before_map.get(k) != after_predicted_map.get(k)
        ]
        lm = "all" if args.list_mode == "changed" and not changed_pred else args.list_mode
        print(
            json.dumps(
                {
                    "host": args.host,
                    "group": args.group,
                    "mode": f"DRY_RUN-{args.mode.upper()}",
                    "planned_task_count": len(after_predicted_map),
                    "predicted_changed_feature_count": len(changed_pred),
                },
                indent=2,
            )
        )
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
