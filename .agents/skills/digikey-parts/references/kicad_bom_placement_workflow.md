# KiCad BOM Placement Workflow

Use this reference when the task is to create a new KiCad project or `.kicad_sch` and place every BOM part without wiring it yet. The goal is a schematic that opens visually in KiCad, can be kept in Git, and preserves a clear audit trail for library decisions.

## Source of Truth

- Use SQLite `bom_items` for the active project as the source of truth. Treat `bom/bom.csv` as a snapshot only.
- Confirm `count(*)` and `sum(quantity)` before generation.
- Expand reference designator ranges such as `R1-R4`, `QA1-QA6`, and repeated connector/tube-pin ranges before writing the schematic.
- Fail generation if the expanded reference count does not equal the BOM row quantity.
- Record all symbol/footprint decisions back to `eda_library_assessments` with `dktools library assess`.

## Library Decisions

- Prefer KiCad generic symbols and footprints for resistors, capacitors, inductors, ferrites, fuses, diodes, connectors, and test points when pin identity is generic.
- For ICs and semiconductors, prefer KiCad package footprints when suitable, but require either a verified standard symbol or a project-local generated symbol with a pin map.
- Verify symbol names against the installed KiCad `.kicad_sym` files. Do not invent names. For example, `Device:D` exists; `Device:D_Fast` may not.
- Store decisions at BOM-line granularity, not just by manufacturer part number.
- Preserve the exact manufacturer part number in `Value` and/or a custom property even when the schematic uses a generic or base KiCad symbol.

## Avoid Alias Rendering Failures

KiCad standard libraries often contain alias or derived symbols using `(extends "...")`. These can render as reference/value text only when copied into a generated schematic without the same library context.

Rules:

- Prefer concrete base symbols that contain their own drawing and pins for generated placement schematics.
- If an alias and its base symbol have the same pinout, use the base symbol as the `lib_id`, keep the exact MPN in `Value`, and document the substitution.
- If the base symbol does not safely match the part pinout, generate a project-local symbol from a pin map instead.
- Avoid unresolved `(extends ...)` definitions in generated `.kicad_sch` files unless you have visually verified the result in KiCad.

Examples from known KiCad 10 symbols:

| Part intent | Avoid for generated placement | Prefer concrete symbol when pinout matches |
| --- | --- | --- |
| MMBTA42 NPN BEC SOT-23 | `Transistor_BJT:MMBTA42` | `Transistor_BJT:Q_NPN_BEC` |
| MMBTA92 PNP BEC SOT-23 | `Transistor_BJT:MMBTA92` | `Transistor_BJT:Q_PNP_BEC` |
| AP63203 TSOT-23-6 buck | `Regulator_Switching:AP63203WU` | `Regulator_Switching:AP63200WU` |
| TCAN334G SOIC-8 CAN transceiver | `Interface_CAN_LIN:TCAN334G` | `Interface_CAN_LIN:TCAN334` |
| STM32G0B1CBTx LQFP-48 | `MCU_ST_STM32G0:STM32G0B1CBTx` | `MCU_ST_STM32G0:STM32G0B1C_B-C-E_Tx` |

These substitutions are acceptable only when the pin order and electrical meaning match the target part. Otherwise, generate a project-local symbol.

## Writing `.kicad_sch`

For each placed symbol:

- Set `lib_id` to the selected symbol.
- Set `Reference`, `Value`, `Footprint`, `Datasheet`, `Description`, Digi-Key part number, manufacturer part number, and `LineId` properties.
- Keep `in_bom` and `on_board` true unless the BOM row is intentionally DNP.
- Include an `instances` block with the reference designator.
- Place symbols on KiCad's connection grid, normally 2.54 mm, to avoid `endpoint_off_grid` warnings.

Most important:

- Do not leave `(lib_symbols)` empty.
- Embed a concrete symbol definition under `(lib_symbols ...)` for every `lib_id` used by the schematic.
- Include project-local `.kicad_sym` and `.pretty` libraries when custom symbols or footprints are generated.
- Use `${KIPRJMOD}` paths in `sym-lib-table` and `fp-lib-table` so the project works after cloning.

Known failure signatures:

- Red `??` placeholder for every part: `.kicad_sch` has empty or incomplete `(lib_symbols ...)`, or KiCad cannot resolve project/global libraries.
- Reference/value text appears but the symbol body and pins are invisible: a copied alias/derived symbol using `(extends ...)` is not rendering. Use a concrete base symbol or generated symbol.
- `endpoint_off_grid` appears for every placed symbol: placement coordinates are not on KiCad's connection grid.
- ERC reports `lib_symbol_mismatch`: embedded symbol definitions differ from the installed library copy; avoid modified aliases or use a project-local symbol intentionally.

## Required Docs

Write durable docs beside the generated KiCad project:

- `docs/kicad_library_decisions.md`: every BOM line, selected symbol, selected footprint, status, confidence, and rationale.
- `docs/kicad_library_gaps.md`: parts that need manual symbol, footprint, pinout, or mechanical verification.
- `docs/pins.csv`: pin maps used for generated or part-specific symbols.

## Validation

After generation, run:

```bash
kicad-cli sch upgrade kicad/<project>/<project>.kicad_sch
kicad-cli sch export svg kicad/<project>/<project>.kicad_sch --output /tmp/<project>_svg --exclude-drawing-sheet
kicad-cli sch erc kicad/<project>/<project>.kicad_sch --output kicad/<project>/erc.rpt
python3 .agents/skills/digikey-parts/scripts/validate_kicad_placement.py \
  kicad/<project>/<project>.kicad_sch \
  --erc kicad/<project>/erc.rpt \
  --svg /tmp/<project>_svg/<project>.svg
```

For an intentionally unwired placement schematic, ERC can report `pin_not_connected`, `pin_not_driven`, or `power_pin_not_driven`. Do not accept `endpoint_off_grid`, `lib_symbol_mismatch`, missing symbol/library errors, or visual `??` placeholders.

If possible, open the SVG or KiCad project and visually check at least one part from each symbol family: passives, connectors, BJTs/FETs, ICs, and project-local generated symbols.

## Git Hygiene

Track:

- `.kicad_pro`
- `.kicad_sch`
- `sym-lib-table`
- `fp-lib-table`
- project-local `.kicad_sym`
- project-local `.pretty/*.kicad_mod`
- decision docs and pin maps

Ignore:

- `*.kicad_prl`
- `*.kicad_pro-bak`, `*.kicad_sch-bak`, `*.kicad_pcb-bak`
- `*-backups/`
- `.history/`
- `~*.lck`
- generated ERC/DRC reports such as `*.rpt`, unless the user explicitly wants reports tracked
