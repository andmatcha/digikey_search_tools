# KiCad Footprint and PCB Import Workflow

Use this reference when the task is to assign KiCad footprints for every BOM row, create or fetch missing footprint libraries, or load a placement-only schematic into the KiCad PCB editor.

## Goal

- Every on-board schematic symbol has a concrete `Footprint` property.
- Every footprint reference resolves from either KiCad standard libraries or a project-local `.pretty` library.
- The footprint decision is recorded in `eda_library_assessments` and summarized in durable project docs.
- A `.kicad_pcb` can be generated from the schematic so the user can open the PCB editor and see all footprints.

## Footprint Decision Order

For each `bom_items` row, decide footprints in this order:

1. Prefer a KiCad standard footprint when package style, pitch, pad count, exposed pad, and mechanical size match the part or datasheet.
2. Use saved Digi-Key payload hints or Digi-Key EDA/model metadata when available. Use `dktools library assess --detect-digikey-models` only as a low-confidence hint until verified.
3. Use the manufacturer drawing/datasheet land pattern when no standard footprint is suitable.
4. Generate a project-local footprint in `kicad/<project>/<project>_bom.pretty/` when a keyed connector, socket, unusual package, or custom mechanical detail must be preserved.
5. If none of the above can be verified, keep the row in `docs/kicad_library_gaps.md` and mark the footprint as `unverified`, `download_needed`, or `blocked`.

Never silently leave a missing footprint. A generic symbol can be acceptable for schematic placement, but the PCB import requires a resolvable footprint file.

## Recording Decisions

Record decisions at BOM-line granularity:

```bash
dktools library assess \
  --match LineId=<line-id> \
  --kicad-symbol <symbol-status> \
  --symbol-name <library:symbol> \
  --kicad-footprint <footprint-status> \
  --footprint-name <library:footprint> \
  --kicad-3d-model <3d-status> \
  --overall <overall-status> \
  --confidence <confidence> \
  --footprint-policy <policy> \
  --notes "<why this footprint is suitable>" \
  --pretty
```

Use statuses consistently:

- `available`: exact or strongly verified library item exists.
- `generic_ok`: generic footprint is electrically/mechanically sufficient.
- `custom`: project-local footprint was generated or imported.
- `unverified`: selected footprint may be plausible but needs datasheet/mechanical review.
- `download_needed`: Digi-Key or vendor model exists but has not been imported.
- `blocked`: footprint could not be selected safely.

## Project Files

Keep project-local libraries portable:

- Add custom footprints under `kicad/<project>/<project>_bom.pretty/*.kicad_mod`.
- Register them in `kicad/<project>/fp-lib-table` with `${KIPRJMOD}`.
- Store exact footprint refs in schematic symbols, for example `nixie_clock_bom:MillMax_9353_1_15_80_18_27_10_0`.
- Track `.pretty/*.kicad_mod` in Git. Do not rely on a user-specific global KiCad library path.

Write or update:

- `docs/kicad_library_decisions.md`: symbol and footprint selected for every BOM row.
- `docs/kicad_footprint_audit.md`: footprint source, verification basis, and unresolved count.
- `docs/kicad_library_gaps.md`: unresolved, unverified, download-needed, or mechanical-review items.

## Footprint Resolution Check

Before PCB import, verify that every unique `Footprint` property resolves.

Use KiCad standard footprint directories from `KICAD10_FOOTPRINT_DIR` or `KICAD9_FOOTPRINT_DIR` when set; otherwise check common install paths such as:

- macOS: `/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints`
- Linux: `/usr/share/kicad/footprints`
- Homebrew/local: `/usr/local/share/kicad/footprints`

For project-local footprints, resolve through `fp-lib-table` first, then `<project-dir>/<library>.pretty`.

Reject these states before PCB import:

- Schematic symbol has an empty `Footprint` property.
- Footprint library directory is missing.
- Footprint `.kicad_mod` file is missing.
- Local `.pretty` exists only in a global user path and is not tracked with the project.

## Automatic PCB Import

Use the bundled script when the user asks to load schematic parts into the PCB editor or when a placement-only `.kicad_pcb` should be committed:

```bash
/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3 \
  .agents/skills/digikey-parts/scripts/import_kicad_schematic_to_pcb.py \
  --schematic kicad/<project>/<project>.kicad_sch \
  --pcb kicad/<project>/<project>.kicad_pcb \
  --replace
```

The script:

- Parses placed schematic symbols with `Reference`, `Value`, `Footprint`, and hidden BOM metadata.
- Skips symbols marked `on_board no` or `dnp yes`.
- Loads footprints from KiCad standard libraries or the project's `fp-lib-table`.
- Writes all footprints into the target `.kicad_pcb`.
- Sets symbol paths so KiCad can associate footprints with schematic symbols in later updates.
- Places footprints in a simple grid. This is only an initial PCB editor loading step, not final layout.

Use `--dry-run` before overwriting an existing board when you only want to verify footprint resolution.

## Manual PCB Import

When using the KiCad GUI:

1. Open `kicad/<project>/<project>.kicad_pro`.
2. Open the schematic editor and confirm that symbols render correctly and have non-empty footprints.
3. Open the PCB editor.
4. Run `Tools` -> `Update PCB from Schematic...`.
5. Enable adding new footprints, review the changes, click update, and save the PCB.

If the schematic has no wires or net labels, KiCad imports footprints but no meaningful nets or ratsnest. That is expected for placement-only BOM schematics.

## Validation After Import

Run at least these checks:

```bash
kicad-cli pcb export svg kicad/<project>/<project>.kicad_pcb \
  --layers F.Cu,F.SilkS,F.Fab,F.CrtYd \
  --output /tmp/<project>_pcb.svg
```

When a real board layout exists, also run:

```bash
kicad-cli pcb drc kicad/<project>/<project>.kicad_pcb \
  --output kicad/<project>/drc.rpt
```

Count-check the result with KiCad Python or a parser: the number of PCB footprints should equal the number of on-board, non-DNP schematic symbols with non-empty footprints. If counts differ, inspect missing and extra references before committing.

## Git Hygiene

Track:

- `.kicad_pcb` when the user wants the PCB import stored in the repository.
- Project-local `.pretty/*.kicad_mod`.
- `fp-lib-table`.
- Footprint audit and gap docs.

Ignore:

- KiCad backups and lock files.
- Generated `.rpt` files unless the user explicitly asks to track reports.
- Temporary SVG exports used only for validation.
