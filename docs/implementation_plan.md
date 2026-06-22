# 実装計画書

## 方針

まず、再利用可能なPythonパッケージとしてCLIを作る。`nixie_bom` の単発スクリプトで実証済みのDigi-Key Product Information V4呼び出し、JSON正規化、BOM価格集計を土台にしつつ、設定、プロジェクト初期化、SQLite保存、BOM編集、AI向け利用文書を追加する。

## ディレクトリ構成

```text
digikey_search_tools/
  config/
    digikey.json
  digikey_tools/
    __main__.py
    api.py
    bom.py
    cli.py
    config.py
    env.py
    library.py
    normalize.py
    project.py
    selection.py
    store.py
  docs/
    requirements.md
    implementation_plan.md
    agent_usage.md
  templates/
    selection_criteria.md
  tests/
    test_*.py
  projects/
    <project>/
      selection_criteria.md  # 任意
      bom/
        bom.csv
      data/
        digikey/
          parts.sqlite3
          raw/
      docs/
```

## 実装段階

### 1. 設計文書

- 要件定義書を作成する。
- 実装計画書を作成する。
- ここで一度、日本語コミットメッセージでコミット・プッシュする。

### 2. コアCLI

- `pyproject.toml` を作成する。
- `.env` ローダ、JSON設定ローダ、Digi-Key APIクライアントを実装する。
- ProductDetailsとKeywordSearchを呼び出せるようにする。
- APIレスポンスをAI向けJSONへ正規化する。
- 選定基準Markdownが存在する場合は読み、出力メタデータへ含める。存在しない場合もCLI操作は継続し、未読み込みであることをメタデータへ含める。

### 3. プロジェクト・BOM・保存

- `project init` でプロジェクト雛形を生成する。
- `bom init/add/remove/update/export-digikey/price` を実装する。
- BOMはSQLiteの `bom_projects` / `bom_items` を正とし、`project_name` ごとに明細を管理する。
- `bom/bom.csv` はDigi-Keyアップロードや人間確認用のスナップショットとしてDBから生成する。
- SQLite保存とraw JSON保存を実装する。
- `store fetch/show/update/list/export/datasheet` を実装する。
- 部品取得時に価格、ステータス、在庫、ステータスフラグ、カテゴリ、RoHS/REACH、最良価格、データシートURLを `parts` の列へ保存する。
- `library assess/list` を実装し、BOM明細単位でKiCad/EDAライブラリ評価をSQLiteに保存する。
- 保存済みDigi-Key payloadからEDA/CAD/3DモデルURLらしき情報を抽出し、確定情報ではなく調査補助の根拠として評価レコードへ保存できるようにする。
- `library decide` を実装し、抵抗・コンデンサなどはKiCad標準汎用ライブラリ優先、ICは個別ピン配置/ピン名必須という方針でBOM明細ごとの扱いを自動判定する。
- `library export-kicad` を実装し、KiCad取り込み用CSV/JSON、生成 `.kicad_sym`、レポートを出力し、必要に応じて `sym-lib-table` へ生成ライブラリを登録する。

### 4. ドキュメント・テスト

- AIエージェント向けの日本語利用手順書を作成する。
- 任意利用の選定基準Markdown雛形を作成する。
- 単体テストを追加する。
- `python3 -m unittest` で検証する。
- 最後に日本語コミットメッセージでコミット・プッシュする。

## CLI案

```bash
python3 -m digikey_tools project init projects/my_board
python3 -m digikey_tools --project projects/my_board search part TPS40210DGQR --quantity 3 --pretty
python3 -m digikey_tools --project projects/my_board store fetch TPS40210DGQR --quantity 3 --pretty
python3 -m digikey_tools --project projects/my_board store datasheet TPS40210DGQR --pretty
python3 -m digikey_tools --project projects/my_board search keyword "buck converter" --in-stock --rohs --has-datasheet --exclude-marketplace --limit 10 --pretty
python3 -m digikey_tools --project projects/my_board bom add --reference U1 --quantity 1 --manufacturer-part TPS40210DGQR --notes "boost controller"
python3 -m digikey_tools --project projects/my_board bom list --pretty
python3 -m digikey_tools --project projects/my_board bom price --summary-md docs/price_summary.md --price-csv bom/price.csv
python3 -m digikey_tools --project projects/my_board bom export-digikey --output bom/digikey_upload.csv
python3 -m digikey_tools --project projects/my_board store update --from-bom
python3 -m digikey_tools --project projects/my_board library assess --match LineId=abcd1234ef56 --kicad-symbol generic_ok --symbol-name Device:R --kicad-footprint generic_ok --footprint-name Resistor_SMD:R_0603_1608Metric --kicad-3d-model generic_ok --overall usable_with_generic --confidence high
python3 -m digikey_tools --project projects/my_board library decide --all --pin-map docs/pins.csv --pretty
python3 -m digikey_tools --project projects/my_board library list --needs-action --pretty
python3 -m digikey_tools --project projects/my_board library export-kicad --kicad-project . --pin-map docs/pins.csv --apply --pretty
```

## SQLite設計

初期スキーマは次のテーブルにする。

- `parts`: 正規化済み部品情報、Digi-Key品番、メーカー品番、メーカー、ステータス、在庫、価格、購入数量、RoHS/REACH、カテゴリ、データシートURL、取得日時、raw JSONパス。
- `queries`: 検索クエリ、検索種別、正規化結果、取得日時。
- `bom_projects`: `project_name`、プロジェクトルート、作成・更新日時。
- `bom_items`: `project_name` に紐づくBOM明細、LineId、位置、数量、品番、DNP、メモなど。
- `eda_library_assessments`: `project_name` と `LineId` に紐づくKiCad/EDAライブラリ評価。KiCad汎用シンボル、フットプリント、3Dモデル、Digi-Key上のEDA/CAD/3Dモデル、外部サービス提供元、全体状態、確度、推奨アクション、根拠JSONを保存する。

検索やBOM価格計算のたびに `parts` をupsertし、`store update` では保存済み品番またはBOM上の品番を再取得する。
ライブラリ評価はBOM行の `LineId` を主キーにする。同一メーカー品番でも値、実装サイズ、Reference Designator、基板上の用途によってKiCad資産の判断が変わるため、部品番号単位ではなくBOM明細単位に保持する。`symbol_policy`、`footprint_policy`、`pin_policy`、`kicad_import_status` で、汎用KiCad資産を使うのか、個別ピン表が必要なのか、インポート可能なのかを保持する。将来KiCadプロジェクトを読む場合は、`Reference Designator` と `Footprint` から `.kicad_sch` / `.kicad_pcb` の実体と照合する。

## 検証

- `.env` パースで秘密情報を出力しない。
- JSON設定の既定値と上書きを検証する。
- ProductDetails正規化で価格、ステータス、パラメータ、警告を抽出できることを検証する。
- KeywordSearchリクエスト生成で検索オプションとフィルタを表現できることを検証する。
- SQLite上のBOM追加、更新、削除、Digi-KeyアップロードCSV出力を検証する。
- project_nameごとにBOM明細が分離されることを検証する。
- 価格計算はDigi-Key APIをモックしたデータで検証する。
- SQLite upsertと一覧取得を検証する。
- KiCad/EDAライブラリ評価がBOM明細単位で保存・一覧化できることを検証する。
- 保存済みraw JSONからDigi-Key EDA/3Dモデルのヒントを抽出できることを検証する。
- 汎用受動部品はKiCad標準ライブラリ優先、ICは個別ピン情報必須として判定されることを検証する。
- ピン表があるICについて、生成 `.kicad_sym`、シンボルフィールドCSV、`sym-lib-table` 登録ができることを検証する。

## 注意点

- `.env` はコミットしない。
- 2-legged OAuthではアカウントIDが必要になる場合があるため、`DIGIKEY_ACCOUNT_ID` を任意で読めるようにする。
- APIのレート制限に配慮し、キャッシュ、TTL、リトライ、`Retry-After` を扱う。
- APIが返すフィールドは将来変わりうるため、未知フィールドをエラー扱いにしない。
