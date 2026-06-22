---
name: digikey-parts
description: Use this skill when selecting electronic parts with Digi-Key, searching by part number or specs, checking status/stock/pricing, editing project-name keyed BOM records in SQLite, exporting Digi-Key upload CSVs, refreshing the local part store, or calculating BOM cost with the local digikey_search_tools Python CLI. Trigger for Digi-Key, BOM, electronic component selection, part replacement, price estimation, availability checks, and project selection_criteria.md workflows in this repository.
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

Keep the workflow grounded in the target project's `selection_criteria.md` when it exists, or in the requirements the user provided in the current request/project docs. Do not print `.env` contents, OAuth tokens, client secrets, or account IDs.

## First Checks

1. Identify the project directory. If none exists, create one:

```bash
dktools project init <project-dir> --pretty
```

2. For an external project, `cd` into the project directory and omit `--project` for normal commands.
3. Check `project.selection_criteria.loaded` in CLI output. If it is true, read or inspect the project's `selection_criteria.md` before recommending parts; if it is false, use the requirements provided in the current request or project docs.
4. Use the CLI for current Digi-Key data. Do not scrape Digi-Key pages.
5. Read `docs/agent_usage.md` when exact command options or output interpretation are needed.

## Common Commands

Search one Digi-Key part number or manufacturer part number:

```bash
dktools search part <part-number> --quantity <qty> --pretty
```

Fetch and persist current Digi-Key part data, including price, status, stock, compliance, and datasheet URL:

```bash
dktools store fetch <part-number> --quantity <qty> --pretty
```

Show a saved part or its datasheet:

```bash
dktools store show <part-number> --pretty
dktools store datasheet <part-number> --pretty
dktools store datasheet <part-number> --open --pretty
dktools store datasheet <part-number> --download-dir docs/datasheets --pretty
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

List DB-managed BOM rows and confirm `LineId` values:

```bash
dktools bom list --pretty
```

List project names stored in the current BOM database:

```bash
dktools bom projects --pretty
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

Record KiCad/EDA library readiness for a BOM line:

```bash
dktools library assess \
  --match LineId=<line-id> \
  --kicad-symbol generic_ok \
  --symbol-name Device:R \
  --kicad-footprint generic_ok \
  --footprint-name Resistor_SMD:R_0603_1608Metric \
  --kicad-3d-model generic_ok \
  --overall usable_with_generic \
  --confidence high \
  --pretty
```

Use saved Digi-Key payloads to seed Digi-Key EDA/3D model hints without calling the API:

```bash
dktools library assess \
  --match LineId=<line-id> \
  --detect-digikey-models \
  --confidence low \
  --notes "Auto-detected from saved Digi-Key payload; not yet verified." \
  --pretty
```

List unresolved KiCad/EDA library work for BOM rows:

```bash
dktools library list --needs-action --pretty
```

Decide KiCad library handling for all BOM rows. Generic KiCad libraries are preferred for passives, while IC symbols require part-specific pin names and pin numbers:

```bash
dktools library decide --all --pin-map docs/pins.csv --pretty
```

Export a KiCad import bundle. This writes JSON/CSV outputs plus generated project symbols from the pin map; `--apply` registers the generated symbol library in `sym-lib-table` without editing `.kicad_sch` or `.kicad_pcb`:

```bash
dktools library export-kicad \
  --kicad-project . \
  --pin-map docs/pins.csv \
  --apply \
  --pretty
```

Refresh local stored part data:

```bash
dktools store update --from-bom --pretty
dktools store update <part-number> --refresh --pretty
```

## Selection Rules

- Prefer active, normally stocked, in-stock, RoHS-compliant parts with datasheets.
- Treat Marketplace-only, EOL, obsolete, NCNR, missing datasheet, excessive MOQ, and insufficient stock as risks.
- Use `product.best_offer.purchase_quantity` for cost reasoning because it reflects minimum order quantity.
- Use `product.parameter_map` for spec checks, and verify against `selection_criteria.md` when present or the user's stated requirements before final recommendation.
- Use KeywordSearch for exploration, then ProductDetails through `search part` or `bom price` for final confirmation.
- Treat SQLite `bom_items` keyed by `project_name` as the source of truth; treat `bom/bom.csv` as a generated snapshot.
- Treat SQLite `parts` columns as the quick local index for status, price, stock, compliance, and datasheet URLs; refresh with `store fetch` or `store update` before final decisions.
- Treat SQLite `eda_library_assessments` as the source of truth for KiCad/EDA symbol, footprint, 3D model, Digi-Key model, and external-library readiness for each BOM `LineId`.
- Store library decisions at BOM-line granularity, not only by part number, because the same part number can need different footprints or verification in different contexts.
- Prefer KiCad built-in generic symbols and footprints for resistors, capacitors, inductors, diodes, ferrite beads, fuses, and test points.
- For ICs and semiconductors, prefer generic KiCad package footprints when suitable, but require part-specific symbol pin numbers, pin names, and pin electrical types. Use a pin-map CSV before exporting generated symbols.
- Use `library list --needs-action` before KiCad work to find unassessed, unverified, download-needed, or custom-library-needed BOM rows.
- Include the reason for a selected part in the BOM `Notes` or project docs.

## Validation

Run local tests after changing this tool or its workflows:

```bash
python3 -m unittest discover -s tests
```
