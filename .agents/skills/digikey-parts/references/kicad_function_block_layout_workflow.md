# KiCad Function Block Layout Workflow

Use this reference when a placement-only KiCad schematic should be reorganized by functional blocks such as power, control, communication, display drivers, connectors, or tube/socket groups.

## Contents

- Goal
- Classification Inputs
- Automatic Layout Script
- Block Config JSON
- Visual Rules
- Validation
- Git Hygiene

## Goal

- Keep every BOM symbol and embedded `lib_symbols` definition intact.
- Move placed symbols into readable functional groups.
- Add top-level KiCad `rectangle` and `text` graphics as block frames and labels.
- Keep all generated coordinates on the KiCad connection grid, normally 2.54 mm.
- Preserve existing `Reference`, `Value`, `Footprint`, `LineId`, and library properties.

Do not use this workflow as final schematic design. It is for BOM-derived placement schematics before real wiring and hierarchical decomposition.

## Classification Inputs

Prefer classification data in this order:

1. Project-specific block config JSON with explicit reference or regex match rules.
2. `bom_items.purpose` from the SQLite BOM database, matched through the schematic symbol `LineId` property.
3. Symbol properties such as `Purpose`, `Description`, `Manufacturer Part Number`, and `Value`.
4. Conservative reference-designator heuristics, with unmatched parts placed in `Other`.

When the schematic was generated from BOM rows, keep `LineId` on every symbol. It lets the layout script recover `purpose` and notes from SQLite without guessing from reference names alone.

## Automatic Layout Script

Use the bundled script when a generated `.kicad_sch` should be organized without hand-editing S-expressions:

```bash
python3 .agents/skills/digikey-parts/scripts/organize_kicad_schematic_blocks.py \
  --schematic kicad/<project>/<project>.kicad_sch \
  --bom-db data/digikey/parts.sqlite3 \
  --project-name <bom-project-name> \
  --config docs/kicad_function_blocks.json \
  --summary-md docs/kicad_function_blocks.md \
  --in-place
```

Useful modes:

```bash
# Check classification and planned block counts without writing.
python3 .agents/skills/digikey-parts/scripts/organize_kicad_schematic_blocks.py \
  --schematic kicad/<project>/<project>.kicad_sch \
  --bom-db data/digikey/parts.sqlite3 \
  --project-name <bom-project-name> \
  --dry-run

# Create a starter config from BOM purpose values.
python3 .agents/skills/digikey-parts/scripts/organize_kicad_schematic_blocks.py \
  --schematic kicad/<project>/<project>.kicad_sch \
  --bom-db data/digikey/parts.sqlite3 \
  --project-name <bom-project-name> \
  --write-config-template docs/kicad_function_blocks.json
```

Use `--strip-all-top-level-graphics` only for generated placement schematics when older generated rectangles/text should be removed. It removes top-level schematic graphics, not symbol library drawings, but it can still remove manual annotations.

## Block Config JSON

Keep project-specific grouping in a JSON file, usually `docs/kicad_function_blocks.json`, when automatic `Power` / `Control` / `Display` grouping is too coarse.

Example:

```json
{
  "grid": 2.54,
  "layout": {
    "block_columns": 2,
    "origin": [15.24, 20.32],
    "gap": [20.32, 20.32],
    "default_cols": 6,
    "dx": 50.8,
    "dy": 40.64,
    "margin": [30.48, 48.26],
    "header_h": 35.56
  },
  "blocks": [
    {
      "key": "hv_power",
      "label": "電源系 / HV Boost",
      "note": "12V input, HV boost, feedback, compensation, and protection",
      "match": {
        "reference_regex": ["^(U1|FHV|L1|Q1|D1|CIN|COUT|RFB|RBLD|RCOMP)"]
      },
      "cols": 7
    },
    {
      "key": "control",
      "label": "制御系 / MCU, Clock, Debug",
      "match": {
        "purpose_regex": ["Control"],
        "reference_regex": ["^(U2|Y|JSWD|RNRST|RSRCLR)"]
      },
      "cols": 5
    },
    {
      "key": "other",
      "label": "その他 / Other",
      "match": {},
      "cols": 6
    }
  ]
}
```

Match rules are evaluated in block order. Supported match keys include `reference`, `reference_prefix`, `reference_regex`, `line_id`, `purpose`, `purpose_regex`, `value_regex`, `description_regex`, `mpn_regex`, `lib_id`, and `text_regex`.

For a fully manual block layout, set `x`, `y`, `width`, and `height` on each block. If omitted, the script lays blocks out automatically.

## Visual Rules

- Use a few meaningful blocks; avoid making one frame per BOM row.
- Split power rails when it improves scanning, such as `HV Boost` and `3.3V Buck`.
- Separate communication connectors/transceivers from MCU/debug when the design has enough parts.
- Keep sockets, repeated LEDs, or display pins in a repeated grid inside their own block.
- Keep labels short enough to remain readable in KiCad SVG export.
- Place every generated block frame and symbol on the 2.54 mm grid to avoid `endpoint_off_grid`.

## Validation

After reorganizing, rerun the normal placement validation:

```bash
kicad-cli sch export svg kicad/<project>/<project>.kicad_sch \
  --output /tmp/<project>_svg \
  --exclude-drawing-sheet
kicad-cli sch erc kicad/<project>/<project>.kicad_sch \
  --output kicad/<project>/erc.rpt
python3 .agents/skills/digikey-parts/scripts/validate_kicad_placement.py \
  kicad/<project>/<project>.kicad_sch \
  --erc kicad/<project>/erc.rpt \
  --svg /tmp/<project>_svg/<project>.svg
```

Validate with the schematic in its real KiCad project directory and normal project filename. If a copy is placed in an arbitrary `/tmp` directory, KiCad may not load the project's `sym-lib-table` or `fp-lib-table`, causing false `lib_symbol_issues` or `footprint_link_issues` for project-local libraries.

Expected for placement-only schematics: unconnected or not-driven ERC messages. Not acceptable: `endpoint_off_grid`, missing symbols, red `??`, or reference/value-only symbols.

If a `.kicad_pcb` was already generated, regenerate or update it after schematic reorganization only when symbol identities, references, or footprints changed. Pure schematic coordinate changes do not require PCB import.

## Git Hygiene

Track:

- The updated `.kicad_sch`.
- `docs/kicad_function_blocks.json` when project-specific grouping is needed.
- `docs/kicad_function_blocks.md` or equivalent short summary when useful.

Ignore:

- Temporary SVG and ERC files used only for validation.
- KiCad backup and lock files.
