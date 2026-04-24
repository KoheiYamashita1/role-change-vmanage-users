# vManage RBAC User Group Permission Manager

A Python script that bulk-checks and updates RBAC task permissions (Read / Write) for user groups on Cisco SD-WAN vManage.

> 日本語版 README は [README.ja.md](./README.ja.md) を参照してください。

## Features

- Inspect the current permission state (`--check-only`)
- Bulk update every feature (`--mode all-write` / `--mode all-read`)
- Update a specific subset of features only (`--mode targeted`)
- Before / after comparison in `ERW` bits (Enabled, Read, Write)
- Dry run mode that does not apply changes (`--dry-run`)

## Requirements

- Python 3.8+
- A vManage account with administrator-level privileges
- Network reachability to the vManage REST API (`/dataservice/admin/usergroup`)

### Dependencies

```bash
pip install requests
```

A virtual environment is recommended:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install requests
```

## Usage

### 1. Check current permissions (recommended first step)

Display the permission state for every task in the target group without making any changes.

```bash
python3 rbac-change-vmanage-user.py \
  --host <vmanage-ip-or-fqdn> \
  --user <admin-username> \
  --password <password> \
  --group <group-name> \
  --check-only
```

Example:

```bash
python3 rbac-change-vmanage-user.py \
  --host <vmanage-ip> \
  --user <admin-username> \
  --password "$VMANAGE_PASSWORD" \
  --group basic \
  --check-only
```

> Tip: store the password in an environment variable (e.g. `export VMANAGE_PASSWORD='...'`) so it does not appear in your shell history or documentation.

### 2. Grant Write permission on every feature

```bash
python3 rbac-change-vmanage-user.py \
  --host <vmanage-ip> \
  --user <admin-username> \
  --password <password> \
  --group <group-name> \
  --mode all-write
```

### 3. Grant Read-only permission on every feature

```bash
python3 rbac-change-vmanage-user.py \
  --host <vmanage-ip> \
  --user <admin-username> \
  --password <password> \
  --group <group-name> \
  --mode all-read
```

### 4. Update specific features only (targeted mode)

`--targets` accepts one or more `feature` names returned by the vManage API. Quote any name containing spaces.

```bash
python3 rbac-change-vmanage-user.py \
  --host <vmanage-ip> \
  --user <admin-username> \
  --password <password> \
  --group <group-name> \
  --mode targeted \
  --targets "Application Monitoring" "Policy" \
  --write True \
  --read False
```

### 5. Dry run (preview changes only)

Skip the PUT request and print only the diff computed from the prepared payload.

```bash
python3 rbac-change-vmanage-user.py \
  --host <vmanage-ip> \
  --user <admin-username> \
  --password <password> \
  --group <group-name> \
  --mode all-write \
  --dry-run
```

## Options

| Option | Required | Description |
| --- | --- | --- |
| `--host` | Yes | vManage IP address or FQDN |
| `--user` | Yes | vManage user name |
| `--password` | Yes | vManage password |
| `--group` | Yes | Target user group name |
| `--mode` | Conditional | One of `all-write` / `all-read` / `targeted`. Not required with `--check-only` |
| `--targets` | Conditional | Feature names to update when using `targeted` mode |
| `--write` | Conditional | Write flag (`True`/`False`) for `targeted` mode |
| `--read` | Conditional | Read flag (`True`/`False`) for `targeted` mode |
| `--check-only` | No | Only display the current permissions; perform no updates |
| `--dry-run` | No | Only preview the changes based on the prepared payload |
| `--list-mode` | No | `changed` (default) or `all`. Scope of the before / after listing |

## Sample output (excerpt)

```
=== Permissions (Before -> After) ===
Legend: ERW bits (Enabled, Read, Write). '1'=True, '0'=False
List Mode : ALL
Total Feats in Group: 359
-----------------------------------------------
Feature                BEFORE  AFTER
-----------------------------------------------
Application Monitoring 110     110
Policy                 110     110
...
```

- `ERW` encodes (Enabled, Read, Write) as a 3-bit value
- Example: `110` means Enabled=True, Read=True, Write=False

## Security notes

- The script disables HTTPS certificate verification (`verify=False`) so it can talk to vManage instances that use self-signed certificates. For production use, consider switching to verification against a trusted CA.
- Passing the password on the command line leaves it in the shell history. Use environment variables or a secrets manager in real deployments.
- The script **overwrites every task of the target user group via PUT**. Always verify the intended change with `--check-only` and `--dry-run` first.

## License

Follow your internal policy when using this repository. If you plan to redistribute or use it commercially, consider adding a dedicated license file.
