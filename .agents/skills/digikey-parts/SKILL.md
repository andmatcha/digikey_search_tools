---
name: digikey-parts
description: Use this skill when selecting electronic parts with Digi-Key, searching by part number or specs, checking status/stock/pricing, editing project BOM CSVs, exporting Digi-Key upload CSVs, refreshing the local part store, or calculating BOM cost with the local digikey_search_tools Python CLI. Trigger for Digi-Key, BOM, electronic component selection, part replacement, price estimation, availability checks, and project selection_criteria.md workflows in this repository.
---

# Digi-Key Parts Workflow

Use the installed `dktools` wrapper from any directory:

```bash
dktools ...
```

If `dktools` is not available, run the module from the repository root:

```bash
python3 -m digikey_tools ...
```

Keep the workflow grounded in the target project's `selection_criteria.md`. Do not print `.env` contents, OAuth tokens, client secrets, or account IDs.

## First Checks

1. Identify the project directory. If none exists, create one:

```bash
dktools project init <project-dir> --pretty
```

2. For an external project, `cd` into the project directory and omit `--project` for normal commands.
3. Read or inspect the project's `selection_criteria.md` before recommending parts.
4. Use the CLI for current Digi-Key data. Do not scrape Digi-Key pages.
5. Read `docs/agent_usage.md` when exact command options or output interpretation are needed.

## Common Commands

Search one Digi-Key part number or manufacturer part number:

```bash
dktools search part <part-number> --quantity <qty> --pretty
```

Search candidates with common procurement filters:

```bash
dktools search keyword "<query>" \
  --in-stock \
  --normally-stocking \
  --rohs \
  --has-datasheet \
  --exclude-marketplace \
  --min-qty <qty> \
  --limit 10 \
  --pretty
```

Add a selected part to the local BOM:

```bash
dktools bom add \
  --reference <refdes> \
  --quantity <qty> \
  --digikey-part <dk-part-number> \
  --manufacturer "<manufacturer>" \
  --manufacturer-part <mpn> \
  --description "<description>" \
  --purpose "<purpose>" \
  --notes "<selection rationale>" \
  --pretty
```

Update or remove BOM rows by `LineId`:

```bash
dktools bom update \
  --match LineId=<line-id> \
  --set Quantity=<qty> \
  --set Notes="<note>" \
  --pretty
```

```bash
dktools bom remove \
  --match LineId=<line-id> \
  --pretty
```

Calculate BOM pricing and write CSV/Markdown/JSON outputs:

```bash
dktools bom price \
  --price-csv bom/price.csv \
  --summary-md docs/price_summary.md \
  --json-output docs/price_result.json \
  --pretty
```

Create a Digi-Key upload CSV:

```bash
dktools bom export-digikey \
  --output bom/digikey_upload.csv \
  --pretty
```

Refresh local stored part data:

```bash
dktools store update --from-bom --pretty
```

## Selection Rules

- Prefer active, normally stocked, in-stock, RoHS-compliant parts with datasheets.
- Treat Marketplace-only, EOL, obsolete, NCNR, missing datasheet, excessive MOQ, and insufficient stock as risks.
- Use `product.best_offer.purchase_quantity` for cost reasoning because it reflects minimum order quantity.
- Use `product.parameter_map` for spec checks, but verify against `selection_criteria.md` before final recommendation.
- Use KeywordSearch for exploration, then ProductDetails through `search part` or `bom price` for final confirmation.
- Include the reason for a selected part in the BOM `Notes` or project docs.

## Validation

Run local tests after changing this tool or its workflows:

```bash
python3 -m unittest discover -s tests
```
