# AIエージェント向け Digi-Key部品検索ツール利用手順

## 基本方針

このツールは、プロジェクトごとの `selection_criteria.md` を読みながら、Digi-Keyの部品検索、候補比較、BOM管理、価格計算を行うためのCLIです。BOMはSQLite内の `bom_projects` / `bom_items` に `project_name` ごとに保存され、`bom/bom.csv` は確認・アップロード用のスナップショットとして更新されます。AIエージェントは、検索やBOM操作の前に必ず対象プロジェクトを決め、出力JSON内の `project.selection_criteria` を確認してください。

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

- `projects/my_board/selection_criteria.md`: 選定基準
- `projects/my_board/data/digikey/parts.sqlite3`: ローカル部品DBとプロジェクト別BOM DB
- `projects/my_board/bom/bom.csv`: DBから出力されるBOMスナップショット
- `projects/my_board/data/digikey/raw/`: 取得した生JSON
- `projects/my_board/docs/`: 価格サマリなどの出力先

## 選定基準を書く

`selection_criteria.md` に、電源電圧、実装条件、温度範囲、在庫条件、RoHS、除外条件、価格目安などを書きます。検索結果だけで判断せず、このファイルと照合して候補を選んでください。

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
- `project.selection_criteria`

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
  --notes "selection_criteria.mdの電源条件を満たす" \
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

- `warnings` が空でも、必ず `selection_criteria.md` の必須条件と照合する。
- `status` が `Active` または `アクティブ` でも、在庫・Marketplace・最小注文数量を確認する。
- `estimated_total_price` は送料、税、手数料を含まない。
- `KeywordSearch` は候補探索用で、最終確認は `search part` または `bom price` のProductDetails結果で行う。
- `.env` の値、アクセストークン、Client Secretは出力しない。
