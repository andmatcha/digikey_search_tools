---
name: digikey-parts
description: Use this skill when selecting electronic parts with Digi-Key, searching by part number or specs, checking status/stock/pricing, editing project-name keyed BOM records in SQLite, exporting Digi-Key upload CSVs, refreshing the local part store, calculating BOM cost, deciding KiCad symbols/footprints, generating placement-only KiCad schematics, organizing KiCad schematics by functional block, or importing schematic footprints into a KiCad PCB with the local digikey_search_tools Python CLI. Trigger for Digi-Key, BOM, electronic component selection, part replacement, price estimation, availability checks, KiCad library/footprint assignment, KiCad functional block layout, KiCad PCB import, and project selection_criteria.md workflows in this repository.
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

Create a placement-only KiCad project or schematic from BOM rows:

- Before generating or editing `.kicad_sch`, read `references/kicad_bom_placement_workflow.md` from this skill.
- Treat `bom_items` as the source of truth, expand every reference designator range, and verify expanded symbol count equals the BOM quantity sum.
- Embed concrete symbol definitions in `.kicad_sch` under `(lib_symbols ...)` for every used `lib_id`; an empty or incomplete `lib_symbols` section causes KiCad to show red `??` placeholders.
- Avoid KiCad alias/derived symbols whose library definition uses `(extends ...)` in generated placement schematics. Prefer the concrete base symbol when its pinout matches, preserve the exact MPN in `Value` and properties, and document the substitution.
- Run the reusable validator after KiCad CLI checks:

```bash
python3 .agents/skills/digikey-parts/scripts/validate_kicad_placement.py \
  kicad/<project>/<project>.kicad_sch \
  --erc kicad/<project>/erc.rpt \
  --svg /tmp/<project>.svg
```

Organize a generated schematic by functional block:

- Before moving schematic symbols into power/control/display frames or adding block rectangles/text, read `references/kicad_function_block_layout_workflow.md` from this skill.
- Prefer project-specific block rules in `docs/kicad_function_blocks.json`; fall back to `bom_items.purpose` via `LineId` when available.
- Keep all moved symbols and generated block graphics on the KiCad grid.

```bash
python3 .agents/skills/digikey-parts/scripts/organize_kicad_schematic_blocks.py \
  --schematic kicad/<project>/<project>.kicad_sch \
  --bom-db data/digikey/parts.sqlite3 \
  --project-name <bom-project-name> \
  --config docs/kicad_function_blocks.json \
  --summary-md docs/kicad_function_blocks.md \
  --in-place
```

Assign KiCad footprints and load schematic parts into the PCB editor:

- Before assigning footprints, creating project-local `.pretty` files, or generating/updating `.kicad_pcb`, read `references/kicad_footprint_pcb_workflow.md` from this skill.
- Resolve footprints in this order: KiCad standard footprint, Digi-Key/EDA model or saved payload hint, manufacturer drawing/datasheet, then project-local generated footprint.
- Record every footprint decision with `dktools library assess`, write `docs/kicad_footprint_audit.md`, and keep unresolved or mechanically risky items in `docs/kicad_library_gaps.md`.
- Run the PCB import script with KiCad's bundled Python, not system Python:

```bash
/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3 \
  .agents/skills/digikey-parts/scripts/import_kicad_schematic_to_pcb.py \
  --schematic kicad/<project>/<project>.kicad_sch \
  --pcb kicad/<project>/<project>.kicad_pcb \
  --replace
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
- Prefer KiCad standard footprints when dimensions and package style match; use project-local `.pretty` footprints only when standard libraries do not contain a suitable land pattern or a keyed/mechanical detail must be preserved.
- For ICs and semiconductors, prefer generic KiCad package footprints when suitable, but require part-specific symbol pin numbers, pin names, and pin electrical types. Use a pin-map CSV before exporting generated symbols.
- For generated placement schematics, verify each KiCad symbol name exists in the installed `.kicad_sym` files instead of guessing names. For example, use `Device:D` for a generic diode rather than inventing `Device:D_Fast`.
- When a KiCad standard symbol is only an alias or extends another symbol, use the concrete base symbol if the pin order and electrical meaning match. Record the original manufacturer part number in symbol properties and the decision docs.
- Use `library list --needs-action` before KiCad work to find unassessed, unverified, download-needed, or custom-library-needed BOM rows.
- Include the reason for a selected part in the BOM `Notes` or project docs.

## Validation

Run local tests after changing this tool or its workflows:

```bash
python3 -m unittest discover -s tests
```

For generated KiCad placement projects, also run `kicad-cli sch upgrade`, `kicad-cli sch export svg`, `kicad-cli sch erc`, and `scripts/validate_kicad_placement.py`. With intentionally unwired schematics, unconnected or not-driven ERC messages are expected, but `lib_symbol_mismatch`, `endpoint_off_grid`, missing symbol/library errors, red `??`, or reference/value-only symbols are not acceptable. Re-run these checks after functional block reorganization because block frames and moved symbols can introduce off-grid coordinates if edited incorrectly.

For generated KiCad PCB imports, verify that every on-board schematic symbol with a non-empty `Footprint` property produced a PCB footprint, then run `kicad-cli pcb export svg` or `kicad-cli pcb drc` when a board-level check is useful. A placement-only schematic can produce footprints without nets; missing ratsnest connections are expected until the schematic is wired.
