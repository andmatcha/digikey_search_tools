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

## テスト

```bash
python3 -m unittest discover -s tests
```
