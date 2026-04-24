# vManage RBAC ユーザーグループ権限マネージャ

Cisco SD-WAN vManage のユーザーグループ (User Group) に対して、RBAC タスク権限 (Read / Write) を一括で確認・変更するための Python スクリプトです。

> The English README is the primary documentation. See [README.md](./README.md).

## 機能

- 現在の権限状態の確認 (`--check-only`)
- 全機能に対する一括変更 (`--mode all-write` / `--mode all-read`)
- 特定機能のみを対象とした変更 (`--mode targeted`)
- 変更前後の比較表示 (ERW bits 形式: Enabled, Read, Write)
- 実際には適用しないドライラン (`--dry-run`)

## 前提条件

- Python 3.8 以上
- vManage 管理ユーザー相当の権限を持つアカウント
- vManage の REST API (`/dataservice/admin/usergroup`) に到達可能なネットワーク

### 依存ライブラリ

```bash
pip install requests
```

仮想環境の利用を推奨します。

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install requests
```

## 使い方

### 1. 現在の権限を確認する (推奨: 最初の動作確認)

変更は行わず、対象グループの全タスクの権限状態を一覧表示します。

```bash
python3 rbac-change-vmanage-user.py \
  --host <vmanage-ip-or-fqdn> \
  --user <admin-username> \
  --password <password> \
  --group <group-name> \
  --check-only
```

例:

```bash
python3 rbac-change-vmanage-user.py \
  --host <vmanage-ip> \
  --user <admin-username> \
  --password "$VMANAGE_PASSWORD" \
  --group basic \
  --check-only
```

> 補足: パスワードは環境変数 (例: `export VMANAGE_PASSWORD='...'`) に格納して渡すことで、シェル履歴やドキュメントに残らないようにできます。

### 2. 全機能に対して Write 権限を付与する

```bash
python3 rbac-change-vmanage-user.py \
  --host <vmanage-ip> \
  --user <admin-username> \
  --password <password> \
  --group <group-name> \
  --mode all-write
```

### 3. 全機能に対して Read 権限のみ付与する

```bash
python3 rbac-change-vmanage-user.py \
  --host <vmanage-ip> \
  --user <admin-username> \
  --password <password> \
  --group <group-name> \
  --mode all-read
```

### 4. 特定機能のみを対象に変更する (targeted モード)

`--targets` には vManage API が返す `feature` 名を指定します。スペースを含む場合はクォートで囲みます。

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

### 5. ドライラン (変更内容の事前確認)

実際には PUT せず、送信予定のペイロードによる変更点のみ表示します。

```bash
python3 rbac-change-vmanage-user.py \
  --host <vmanage-ip> \
  --user <admin-username> \
  --password <password> \
  --group <group-name> \
  --mode all-write \
  --dry-run
```

## オプション一覧

| オプション | 必須 | 説明 |
| --- | --- | --- |
| `--host` | ○ | vManage の IP アドレスまたは FQDN |
| `--user` | ○ | vManage ユーザー名 |
| `--password` | ○ | vManage パスワード |
| `--group` | ○ | 対象のユーザーグループ名 |
| `--mode` | △ | `all-write` / `all-read` / `targeted` のいずれか。`--check-only` 指定時は不要 |
| `--targets` | △ | `targeted` モード時に変更対象の feature 名を列挙 |
| `--write` | △ | `targeted` モード時の write フラグ (`True`/`False`) |
| `--read` | △ | `targeted` モード時の read フラグ (`True`/`False`) |
| `--check-only` | - | 現状の権限を表示するのみで変更は行わない |
| `--dry-run` | - | 送信予定のペイロードを元に変更内容を表示するのみ |
| `--list-mode` | - | `changed` (既定) または `all`。before/after 一覧の表示範囲 |

## 出力例 (抜粋)

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

- `ERW` = (Enabled, Read, Write) の 3 bit 表現
- 例: `110` → Enabled=True, Read=True, Write=False

## セキュリティに関する注意

- 本スクリプトは vManage の自己署名証明書にも対応するため、HTTPS 証明書検証を無効化しています (`verify=False`)。本番環境で利用する場合は、信頼できる CA を前提とした検証に差し替えることを推奨します。
- コマンドライン引数でパスワードを渡すとシェル履歴に残るため、運用では環境変数や secrets manager の利用を推奨します。
- 本スクリプトは User Group の **すべての tasks を PUT で上書き** します。`--check-only` / `--dry-run` で必ず事前確認してから実行してください。

## ライセンス

本リポジトリの利用条件は社内ポリシーに従ってください。再配布・商用利用を想定する場合は、別途ライセンスファイルの追加を検討してください。
