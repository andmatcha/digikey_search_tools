# AIエージェント向け Digi-Key部品検索ツール利用手順

## 基本方針

このツールは、Digi-Keyの部品検索、候補比較、BOM管理、価格計算を行うためのCLIです。プロジェクトに `selection_criteria.md` があればそれを読み、ない場合は現在の依頼文や関連文書でユーザーから伝えられた要件をもとに選定します。BOMはSQLite内の `bom_projects` / `bom_items` に `project_name` ごとに保存され、`bom/bom.csv` は確認・アップロード用のスナップショットとして更新されます。AIエージェントは、検索やBOM操作の前に対象プロジェクトを決め、出力JSON内の `project.selection_criteria.loaded` を確認してください。

`.env` の中身は表示しないでください。認証情報はCLIが自動で読み込みます。

## 初期設定

リポジトリ直下の `.env` に次の値を置きます。

```bash
DIGIKEY_CLIENT_ID=...
DIGIKEY_CLIENT_SECRET=...
DIGIKEY_ACCOUNT_ID=...
```

`DIGIKEY_ACCOUNT_ID` は任意ですが、2-legged OAuthでMyPricingやアカウント別価格が必要な場合に使います。サイト、言語、通貨、環境は `config/digikey.json` で変更できます。

```json
{
  "digikey": {
    "environment": "production",
    "site": "JP",
    "language": "ja",
    "currency": "JPY"
  }
}
```

## プロジェクトを作成する

```bash
python3 -m digikey_tools project init projects/my_board --pretty
```

作成される主なファイルは次の通りです。

- `projects/my_board/selection_criteria.md`: 選定基準。任意。継続的に残したい条件がある場合に使います。
- `projects/my_board/data/digikey/parts.sqlite3`: ローカル部品DBとプロジェクト別BOM DB
- `projects/my_board/bom/bom.csv`: DBから出力されるBOMスナップショット
- `projects/my_board/data/digikey/raw/`: 取得した生JSON
- `projects/my_board/docs/`: 価格サマリなどの出力先

## 選定基準を指定する

継続的に残したい基準がある場合は、`selection_criteria.md` に電源電圧、実装条件、温度範囲、在庫条件、RoHS、除外条件、価格目安などを書きます。外部プロジェクトや一時的な選定では、このファイルは不要です。AIエージェントへの依頼文に要件を直接書き、検索結果だけで判断せず、その要件と照合して候補を選んでください。

## 型番で検索する

```bash
python3 -m digikey_tools --project projects/my_board search part 296-26969-1-ND --quantity 3 --pretty
```

メーカー品番でも検索できます。

```bash
python3 -m digikey_tools --project projects/my_board search part TPS40210DGQR --quantity 3 --pretty
```

主な出力項目:

- `product.status`
- `product.quantity_available`
- `product.best_offer`
- `product.parameter_map`
- `product.availability`
- `warnings`
- `project.selection_criteria`: `loaded` が `true` の場合はファイル由来、`false` の場合は現在の依頼文や関連文書の要件を使う

## 部品データをDBに保存・更新する

APIから部品データを取得して、価格、ステータス、在庫、コンプライアンス、カテゴリ、最良価格、データシートURLなどをSQLiteに保存します。

```bash
python3 -m digikey_tools --project projects/my_board store fetch TPS40210DGQR --quantity 3 --pretty
```

保存済み部品の詳細を確認します。

```bash
python3 -m digikey_tools --project projects/my_board store show TPS40210DGQR --pretty
```

特定部品だけ再取得する場合は `store update` に品番を渡します。

```bash
python3 -m digikey_tools --project projects/my_board store update TPS40210DGQR --refresh --pretty
```

## ステータスやスペックで検索する

```bash
python3 -m digikey_tools --project projects/my_board search keyword "buck converter" \
  --in-stock \
  --normally-stocking \
  --rohs \
  --has-datasheet \
  --exclude-marketplace \
  --min-qty 10 \
  --limit 10 \
  --pretty
```

メーカーID、カテゴリID、ステータスID、Digi-KeyのパラメトリックフィルタIDが分かっている場合はAPI側フィルタに渡せます。

```bash
python3 -m digikey_tools --project projects/my_board search keyword "MOSFET" \
  --category-id 278 \
  --manufacturer-id 296 \
  --param-category-id 278 \
  --param 1989=391153 \
  --limit 20 \
  --pretty
```

APIが返した候補に対して、ローカル側でスペック名を使った追加フィルタもできます。

```bash
python3 -m digikey_tools --project projects/my_board search keyword "LDO regulator" \
  --in-stock \
  --spec-contains "Output Type=Fixed" \
  --spec-contains "Mounting Type=Surface Mount" \
  --pretty
```

## BOMに部品を追加する

```bash
python3 -m digikey_tools --project projects/my_board bom add \
  --reference U1 \
  --quantity 1 \
  --digikey-part 296-26969-1-ND \
  --manufacturer "Texas Instruments" \
  --manufacturer-part TPS40210DGQR \
  --description "Boost controller" \
  --purpose "Nixie boost converter" \
  --notes "依頼文の電源条件を満たす" \
  --pretty
```

`DNP` としてBOMに残す場合:

```bash
python3 -m digikey_tools --project projects/my_board bom add \
  --reference R99 \
  --quantity 1 \
  --manufacturer-part EXAMPLE \
  --dnp \
  --notes "未実装候補" \
  --pretty
```

## BOMを更新・削除する

BOMはSQLiteで管理されます。`LineId` は `bom add` の出力、`bom list`、または `bom/bom.csv` のスナップショットで確認します。

```bash
python3 -m digikey_tools --project projects/my_board bom list --pretty
```

同じDB内で管理されているプロジェクト名を確認する場合:

```bash
python3 -m digikey_tools --project projects/my_board bom projects --pretty
```

```bash
python3 -m digikey_tools --project projects/my_board bom update \
  --match LineId=abcd1234ef56 \
  --set Quantity=5 \
  --set Notes="試作5台分" \
  --pretty
```

```bash
python3 -m digikey_tools --project projects/my_board bom remove \
  --match LineId=abcd1234ef56 \
  --pretty
```

## KiCad/EDAライブラリ評価を保存する

BOM明細ごとに、KiCadの汎用シンボル、汎用フットプリント、汎用3Dモデルが使えるか、Digi-Key上にEDA/CAD/3Dモデルがあるか、SnapEDA、Ultra Librarian、メーカー公式、GitHub等からライブラリを入手できるかをSQLiteへ保存できます。評価は `project_name` と `LineId` に紐づくため、同じ型番でも用途や実装サイズが違う明細を別判断として扱えます。

汎用KiCadライブラリで十分な抵抗の例:

```bash
python3 -m digikey_tools --project projects/my_board library assess \
  --match LineId=abcd1234ef56 \
  --kicad-symbol generic_ok \
  --symbol-name Device:R \
  --kicad-footprint generic_ok \
  --footprint-name Resistor_SMD:R_0603_1608Metric \
  --kicad-3d-model generic_ok \
  --overall usable_with_generic \
  --confidence high \
  --notes "0603抵抗なのでKiCad標準の汎用資産で十分" \
  --pretty
```

Digi-Keyや外部サービスからモデルを取得する必要があるICの例:

```bash
python3 -m digikey_tools --project projects/my_board library assess \
  --match LineId=abcd1234ef56 \
  --kicad-symbol needs_custom \
  --kicad-footprint needs_custom \
  --kicad-3d-model needs_custom \
  --digikey-eda unknown \
  --digikey-3d-model unknown \
  --external-library available \
  --source "SnapEDA=https://www.snapeda.com/parts/example" \
  --overall needs_download \
  --confidence medium \
  --recommended-action "外部ライブラリを取得し、ピン番号と寸法をデータシートで照合する" \
  --pretty
```

保存済みのDigi-Keyレスポンスから、EDA/CAD/3DモデルらしきURLを補助的に拾う場合:

```bash
python3 -m digikey_tools --project projects/my_board library assess \
  --match LineId=abcd1234ef56 \
  --detect-digikey-models \
  --confidence low \
  --notes "Digi-Key保存済みpayloadから自動抽出。最終確認は未実施" \
  --pretty
```

この検出はネットワークを叩かず、`store fetch`、`search part`、`bom price` などで保存済みのSQLite/raw JSONだけを読みます。raw JSONが保存されていない部品では `unknown` のままになることがあります。

評価状況の一覧:

```bash
python3 -m digikey_tools --project projects/my_board library list --pretty
```

未評価、未検証、要自作、要ダウンロードなど作業が残る明細だけを確認:

```bash
python3 -m digikey_tools --project projects/my_board library list --needs-action --pretty
```

主な状態値:

- 個別資産: `unknown`, `generic_ok`, `available`, `not_found`, `needs_custom`, `not_required`, `risk`, `unverified`
- 明細全体: `ready`, `usable_with_generic`, `needs_download`, `needs_custom`, `blocked`, `review`, `unknown`
- 確度: `low`, `medium`, `high`, `unknown`

## KiCadライブラリ方針を自動判定する

抵抗、コンデンサ、インダクタ、ダイオードなどはKiCad標準の汎用シンボルと汎用フットプリントを優先します。ICや半導体などは、SOIC、TSSOP、QFNなどの汎用パッケージフットプリントを優先しつつ、シンボルは個別部品のピン番号、ピン名、電気タイプに合わせる扱いにします。

```bash
python3 -m digikey_tools --project projects/my_board library decide --all --pretty
```

ICのピン表がない場合、その行は `kicad_import_status=blocked` として保存されます。データシートからピン表CSVを作ると、プロジェクト用シンボル生成まで進められます。

ピン表CSVの例:

```csv
LineId,PinNumber,PinName,PinType,Side
abcd1234ef56,1,VIN,power_in,left
abcd1234ef56,2,GND,power_in,left
abcd1234ef56,3,SW,output,right
abcd1234ef56,4,FB,input,right
```

`LineId` の代わりに `Reference Designator`、`Manufacturer Part Number`、`Digi-Key Part Number` でも紐づけできます。`PinType` は `input`、`output`、`bidirectional`、`passive`、`power_in`、`power_out`、`no_connect` などを使えます。

ピン表を使って自動判定する場合:

```bash
python3 -m digikey_tools --project projects/my_board library decide \
  --all \
  --pin-map docs/pins.csv \
  --overwrite \
  --pretty
```

KiCad CLIがインストールされていれば、`library decide` は `kicad-cli version` と標準ライブラリ探索結果を根拠に含めます。KiCad CLIがない環境でも判定とファイル生成は継続します。探索を省略したい場合は `--no-kicad-env` を付けます。

## KiCad取り込み用ファイルを一括生成する

現在のBOMと `eda_library_assessments` から、KiCad取り込み用のファイル群を生成します。

```bash
python3 -m digikey_tools --project projects/my_board library export-kicad \
  --kicad-project /path/to/kicad_project \
  --output-dir kicad_import \
  --pin-map docs/pins.csv \
  --apply \
  --pretty
```

出力される主なファイル:

- `dktools_import_plan.json`: BOM行ごとのシンボル、フットプリント、ピン方針、取り込み可否
- `dktools_symbol_fields.csv`: KiCadのシンボルフィールド更新に使うCSV
- `dktools_footprint_assignments.csv`: Reference Designatorごとのフットプリント割当CSV
- `dktools_generated.kicad_sym`: ピン表CSVから生成したプロジェクト用シンボルライブラリ
- `dktools_library_report.md`: ブロック中の明細と推奨アクション

`--apply` を付けると、KiCadプロジェクトの `sym-lib-table` に生成シンボルライブラリを登録します。既存の `.kicad_sch` や `.kicad_pcb` は直接書き換えません。回路図に配置済みのシンボルへフィールドを反映する場合は、生成されたCSVをKiCad側のシンボルフィールド表で取り込むか、次段のKiCad連携処理でReference Designatorをキーに反映します。

将来KiCadプロジェクトと照合するときは、BOMの `Reference Designator`、`Footprint`、`LineId` をキーに、`.kicad_sch`、`.kicad_pcb`、ライブラリテーブル側の実体確認へ進めます。

## BOMの価格を計算する

```bash
python3 -m digikey_tools --project projects/my_board bom price \
  --price-csv bom/price.csv \
  --summary-md docs/price_summary.md \
  --json-output docs/price_result.json \
  --pretty
```

既定ではDNP行は集計から除外されます。含める場合は `--include-dnp` を付けます。

価格計算では次を行います。

- BOM各行のDigi-Key品番またはメーカー品番でProductDetailsを取得
- 最小注文数量を反映した購入数量を算出
- 梱包形態ごとの価格から最良候補を選択
- 在庫、ステータス、Marketplace、EOL、NCNRなどの警告を出力
- SQLiteとraw JSONに取得結果を保存
- `project_name` に紐づくDB上のBOMを読み、`bom/bom.csv` をスナップショットとして更新

## Digi-Keyアップロード用CSVを作成する

```bash
python3 -m digikey_tools --project projects/my_board bom export-digikey \
  --output bom/digikey_upload.csv \
  --pretty
```

出力列:

- `Digi-Key Part Number`
- `Manufacturer Part Number`
- `Quantity`
- `Customer Reference`

Digi-Key側の部品リストやBOMアップロード画面で列マッピングしやすい最小構成です。

## ローカル部品DBを確認・更新する

保存済み部品一覧:

```bash
python3 -m digikey_tools --project projects/my_board store list --pretty
```

有効部品だけ、またはデータシートURLが未保存の部品だけを絞り込めます。

```bash
python3 -m digikey_tools --project projects/my_board store list --active-only --pretty
python3 -m digikey_tools --project projects/my_board store list --missing-datasheet --pretty
```

BOMに含まれる部品を一括更新:

```bash
python3 -m digikey_tools --project projects/my_board store update --from-bom --pretty
```

保存済み部品を一括更新:

```bash
python3 -m digikey_tools --project projects/my_board store update --all --pretty
```

DB内容をJSONへ出力:

```bash
python3 -m digikey_tools --project projects/my_board store export --output docs/local_store.json --pretty
```

## データシートにアクセスする

`store fetch`、`search part`、`bom price`、`store update` で取得したデータには、Digi-Keyが返したデータシートURLが保存されます。

URLを表示:

```bash
python3 -m digikey_tools --project projects/my_board store datasheet TPS40210DGQR --pretty
```

ブラウザで開く:

```bash
python3 -m digikey_tools --project projects/my_board store datasheet TPS40210DGQR --open --pretty
```

ローカルに保存:

```bash
python3 -m digikey_tools --project projects/my_board store datasheet TPS40210DGQR --download-dir docs/datasheets --pretty
```

未保存の場合は先に次を実行してください。

```bash
python3 -m digikey_tools --project projects/my_board store fetch TPS40210DGQR --pretty
```

## 検証コマンド

```bash
python3 -m unittest discover -s tests
```

実APIを叩かずに、設定、正規化、BOM操作、SQLite保存、検索フィルタ生成を検証します。

## 判断時の注意

- `warnings` が空でも、`selection_criteria.md`、現在の依頼文、または関連文書にある必須条件と照合する。
- `status` が `Active` または `アクティブ` でも、在庫・Marketplace・最小注文数量を確認する。
- `estimated_total_price` は送料、税、手数料を含まない。
- `KeywordSearch` は候補探索用で、最終確認は `search part` または `bom price` のProductDetails結果で行う。
- `.env` の値、アクセストークン、Client Secretは出力しない。
