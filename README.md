# digikey_search_tools

AIエージェントが使いやすいDigi-Key部品検索、部品選定、BOM管理、価格計算ツール群です。Python標準ライブラリ中心で実装しており、プロジェクトごとに `selection_criteria.md` と `bom/bom.csv` を持たせて運用します。

## クイックスタート

```bash
python3 -m digikey_tools project init projects/my_board --pretty
python3 -m digikey_tools --project projects/my_board search part 296-26969-1-ND --quantity 1 --pretty
python3 -m digikey_tools --project projects/my_board bom add --reference U1 --quantity 1 --digikey-part 296-26969-1-ND --pretty
python3 -m digikey_tools --project projects/my_board bom price --pretty
python3 -m digikey_tools --project projects/my_board bom export-digikey --output bom/digikey_upload.csv --pretty
```

## 設定

API認証情報はリポジトリ直下の `.env` に置きます。このファイルはGit管理対象外です。

```bash
DIGIKEY_CLIENT_ID=...
DIGIKEY_CLIENT_SECRET=...
DIGIKEY_ACCOUNT_ID=...
```

国、言語、通貨、API環境などは `config/digikey.json` で変更できます。

## ドキュメント

- [要件定義書](docs/requirements.md)
- [実装計画書](docs/implementation_plan.md)
- [AIエージェント向け利用手順](docs/agent_usage.md)

## AIエージェント用スキル

- Codex: `.agents/skills/digikey-parts/SKILL.md`
- Claude Code: `.claude/skills/digikey-parts/SKILL.md`

Codexでは `$digikey-parts`、Claude Codeでは `/digikey-parts` として呼び出せます。どちらも、このリポジトリのCLIを使ってDigi-Key検索、BOM編集、価格計算、ローカル部品DB更新を行うための薄い手順スキルです。

## 外部ディレクトリから使う設定

このリポジトリでは、外部ディレクトリから自然に使えるようにするセットアップスクリプトを用意しています。

```bash
cd /Users/jinaoyagi/workspace/personal/digikey_search_tools
scripts/setup_external_use.sh
```

このスクリプトは次を設定します。

- `dktools` コマンドをPATH上の書き込み可能な場所に作成
- Codex用スキルを `~/.agents/skills/digikey-parts` へsymlink
- Claude Code用スキルを `~/.claude/skills/digikey-parts` へsymlink

この環境では `/opt/homebrew/bin/dktools` として設定済みです。

手動で設定する場合は次の通りです。

```bash
mkdir -p ~/.agents/skills ~/.claude/skills
ln -s /Users/jinaoyagi/workspace/personal/digikey_search_tools/.agents/skills/digikey-parts ~/.agents/skills/digikey-parts
ln -s /Users/jinaoyagi/workspace/personal/digikey_search_tools/.claude/skills/digikey-parts ~/.claude/skills/digikey-parts
```

既にリンクやディレクトリが存在する場合、セットアップスクリプトは上書きせず停止します。現在の向き先を確認してから置き換えてください。

外部プロジェクトでは、対象ディレクトリに移動してから初期化すると自然に使えます。

```bash
mkdir -p /path/to/my_board
cd /path/to/my_board
dktools project init . --pretty
dktools search keyword "buck converter" --in-stock --rohs --has-datasheet --exclude-marketplace --pretty
dktools bom add --reference U1 --quantity 1 --manufacturer-part TPS40210DGQR --pretty
dktools bom price --pretty
```

設定ファイルと `.env` は既定ではこのリポジトリ直下のものを使います。外部プロジェクト専用の認証情報や地域設定を使う場合は、`--config` と `--env-file` を明示してください。

```bash
dktools --config /path/to/digikey.json --env-file /path/to/.env search part 296-26969-1-ND --pretty
```

Python仮想環境内で使う場合は、editable installでも利用できます。

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e /Users/jinaoyagi/workspace/personal/digikey_search_tools
```

## テスト

```bash
python3 -m unittest discover -s tests
```
