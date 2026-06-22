# digikey_search_tools

AIエージェントが使いやすいDigi-Key部品検索、部品選定、BOM管理、価格計算ツール群です。Python標準ライブラリ中心で実装しており、任意の `selection_criteria.md` とSQLiteデータベースでBOMを管理します。`selection_criteria.md` がない外部プロジェクトでも、AIエージェントに要件を伝えて選定できます。`bom/bom.csv` はDigi-Key連携や確認用のスナップショットとして出力されます。

## 1. API設定

Digi-KeyのAPIを使うには、[Digi-Key API Developer Portal](https://developer.digikey.com/) でアカウント登録またはログインし、アプリケーションを作成します。アプリ作成時にOAuth2のClient IDとClient Secretが発行されるので、[Product Information V4](https://developer.digikey.com/products) を使えるように設定してから、このツールの `.env` に保存します。

公式ドキュメントでは、2-legged OAuthでClient ID、Client Secret、`client_credentials` を使ってアクセストークンを取得する流れが説明されています。このツールはトークン取得を内部で行うため、通常はClient IDとClient Secretを設定すれば使えます。詳しくは [OAuth 2.0: 2 Legged Flow](https://developer.digikey.com/tutorials-and-resources/oauth-20-2-legged-flow) を参照してください。

API認証情報はリポジトリ直下の `.env` に置きます。このファイルはGit管理対象外です。

```bash
DIGIKEY_CLIENT_ID=...
DIGIKEY_CLIENT_SECRET=...
DIGIKEY_ACCOUNT_ID=...
```

国、言語、通貨、API環境などは `config/digikey.json` で変更できます。

## 2. AIエージェント用スキル

- Codexリポジトリ用: `.agents/skills/digikey-parts/SKILL.md`
- Claude Code: `.claude/skills/digikey-parts/SKILL.md`

Codexでは `$digikey-parts`、Claude Codeでは `/digikey-parts` として呼び出せます。どちらも、このリポジトリのCLIを使ってDigi-Key検索、DB上のBOM編集、価格計算、ローカル部品DB更新を行うための薄い手順スキルです。

外部プロジェクトから自然に呼び出す場合は、次の外部利用設定でスキルへのリンクもまとめて作成できます。

## 3. 外部ディレクトリから使う設定

このリポジトリでは、外部ディレクトリから自然に使えるようにするセットアップスクリプトを用意しています。

```bash
cd /path/to/digikey_search_tools
scripts/setup_external_use.sh
```

このスクリプトは次を設定します。

- `dktools` コマンドをPATH上の書き込み可能な場所に作成
- Codex用スキルを `~/.codex/skills/digikey-parts` へsymlink
- リポジトリ/エージェント用エイリアスを `~/.agents/skills/digikey-parts` へsymlink
- Claude Code用スキルを `~/.claude/skills/digikey-parts` へsymlink

手動で設定する場合は次の通りです。

```bash
DIGIKEY_TOOLS_DIR=/path/to/digikey_search_tools
mkdir -p ~/.codex/skills ~/.agents/skills ~/.claude/skills
ln -s "$DIGIKEY_TOOLS_DIR/.agents/skills/digikey-parts" ~/.codex/skills/digikey-parts
ln -s "$DIGIKEY_TOOLS_DIR/.agents/skills/digikey-parts" ~/.agents/skills/digikey-parts
ln -s "$DIGIKEY_TOOLS_DIR/.claude/skills/digikey-parts" ~/.claude/skills/digikey-parts
```

既にリンクやディレクトリが存在する場合、セットアップスクリプトは上書きせず停止します。現在の向き先を確認してから置き換えてください。

Python仮想環境内で使う場合は、editable installでも利用できます。

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e /path/to/digikey_search_tools
```

設定ファイルと `.env` は既定ではこのリポジトリ直下のものを使います。外部プロジェクト専用の認証情報や地域設定を使う場合は、`--config` と `--env-file` を明示してください。

```bash
dktools --config /path/to/digikey.json --env-file /path/to/.env search part 296-26969-1-ND --pretty
```

## 4. 外部プロジェクトでの使い方

外部プロジェクトでは、まずAIエージェントに要件を伝えてから `$digikey-parts` を使うよう依頼すると自然に扱えます。`selection_criteria.md` がない場合でも、プロンプト内の条件を選定基準として使えます。

```text
$digikey-parts を使って、24V入力から5V/2Aを作る降圧レギュレータ候補を探してください。
条件は在庫あり、RoHS、データシートあり、Marketplace除外、SMD実装優先です。
候補ごとに価格、在庫、主な仕様、採用リスクを比較してください。
```

```text
$digikey-parts を使って、このプロジェクトのBOMにTPS40210DGQRを追加して価格を確認してください。
用途は昇圧コンバータ制御ICです。数量は試作5台分で見積もってください。
```

```text
$digikey-parts を使って、現在のBOMを更新し、EOL、NCNR、在庫不足、データシートなしの部品を洗い出してください。
問題がある部品は代替候補もDigi-Keyから探してください。
```

CLIを直接使う場合は、対象ディレクトリに移動してから初期化すると自然に使えます。

```bash
mkdir -p /path/to/my_board
cd /path/to/my_board
dktools project init . --pretty
dktools search keyword "buck converter" --in-stock --rohs --has-datasheet --exclude-marketplace --pretty
dktools store fetch TPS40210DGQR --pretty
dktools store datasheet TPS40210DGQR --pretty
dktools bom add --reference U1 --quantity 1 --manufacturer-part TPS40210DGQR --pretty
dktools bom list --pretty
dktools bom projects --pretty
dktools bom price --pretty
```

`selection_criteria.md` は任意です。継続的に残したい選定基準がある場合は `dktools project init . --pretty` で雛形を作るか、自分で作成してください。一時的な選定や外部プロジェクトでは、AIエージェントへの依頼文に電源条件、実装条件、在庫条件、除外条件などを直接書いて使えます。ファイルがない場合、CLIの出力メタデータでは `project.selection_criteria.loaded` が `false` になります。

複数プロジェクトを1つのSQLite DBでまとめたい場合は、`config/digikey.json` の `paths.database` に絶対パスを指定してください。その場合もBOM明細は `project_name` ごとに分離されます。

スキルは `~/.codex/skills/digikey-parts` から読み込まれ、CLIは `dktools` を使って現在のディレクトリをプロジェクトとして扱います。

## 5. コマンド例

```bash
python3 -m digikey_tools project init projects/my_board --pretty
python3 -m digikey_tools --project projects/my_board search part 296-26969-1-ND --quantity 1 --pretty
python3 -m digikey_tools --project projects/my_board store fetch 296-26969-1-ND --pretty
python3 -m digikey_tools --project projects/my_board store datasheet 296-26969-1-ND --pretty
python3 -m digikey_tools --project projects/my_board bom add --reference U1 --quantity 1 --digikey-part 296-26969-1-ND --pretty
python3 -m digikey_tools --project projects/my_board bom list --pretty
python3 -m digikey_tools --project projects/my_board bom projects --pretty
python3 -m digikey_tools --project projects/my_board bom price --pretty
python3 -m digikey_tools --project projects/my_board bom export-digikey --output bom/digikey_upload.csv --pretty
```

保存済み部品のデータシートをブラウザで開く、またはPDFとして保存する場合:

```bash
dktools store datasheet TPS40210DGQR --open --pretty
dktools store datasheet TPS40210DGQR --download-dir docs/datasheets --pretty
```

## 6. ドキュメント

- [要件定義書](docs/requirements.md)
- [実装計画書](docs/implementation_plan.md)
- [AIエージェント向け利用手順](docs/agent_usage.md)

## 7. テスト

```bash
python3 -m unittest discover -s tests
```
