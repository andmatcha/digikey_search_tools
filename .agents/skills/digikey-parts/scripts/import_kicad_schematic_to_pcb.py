#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
from dataclasses import dataclass
from pathlib import Path


KICAD_FOOTPRINT_DIR_CANDIDATES = [
    Path(os.environ["KICAD10_FOOTPRINT_DIR"]) if os.environ.get("KICAD10_FOOTPRINT_DIR") else None,
    Path(os.environ["KICAD9_FOOTPRINT_DIR"]) if os.environ.get("KICAD9_FOOTPRINT_DIR") else None,
    Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints"),
    Path("/usr/share/kicad/footprints"),
    Path("/usr/local/share/kicad/footprints"),
]


@dataclass
class SchematicFootprint:
    reference: str
    value: str
    footprint: str
    uuid: str
    digikey_part_number: str
    manufacturer_part_number: str
    line_id: str
    description: str


def require_pcbnew():
    try:
        import pcbnew  # type: ignore[import-not-found]
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "pcbnew Python module was not found. Run this script with KiCad's bundled Python, for example:\n"
            "/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3 "
            ".agents/skills/digikey-parts/scripts/import_kicad_schematic_to_pcb.py "
            "--schematic kicad/<project>/<project>.kicad_sch --pcb kicad/<project>/<project>.kicad_pcb"
        ) from exc
    return pcbnew


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(path)


def balanced_sexp(text: str, start: int) -> str:
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    raise ValueError("Unbalanced KiCad S-expression.")


def unescape_kicad_string(value: str) -> str:
    return value.replace(r"\\", "\\").replace(r"\"", '"')


def property_value(block: str, name: str) -> str:
    pattern = re.compile(rf'\(property\s+"{re.escape(name)}"\s+"((?:\\.|[^"])*)"')
    match = pattern.search(block)
    return unescape_kicad_string(match.group(1)) if match else ""


def is_on_board(block: str) -> bool:
    if re.search(r"\(on_board\s+no\)", block):
        return False
    if re.search(r"\(dnp\s+yes\)", block):
        return False
    return True


def parse_schematic(path: Path) -> tuple[str, list[SchematicFootprint]]:
    text = path.read_text(encoding="utf-8")
    root_uuid_match = re.search(r'(?m)^\s*\(uuid\s+"([^"]+)"\)', text)
    if not root_uuid_match:
        raise ValueError(f"Root schematic UUID was not found in {path}")
    root_uuid = root_uuid_match.group(1)

    footprints: list[SchematicFootprint] = []
    for match in re.finditer(r"(?m)^\s*\(symbol\s*$", text):
        block = balanced_sexp(text, match.start())
        if "(lib_id " not in block or not is_on_board(block):
            continue
        uuid_match = re.search(r'\n\s*\(uuid\s+"([^"]+)"\)', block)
        if not uuid_match:
            raise ValueError("Placed symbol without uuid was found.")
        item = SchematicFootprint(
            reference=property_value(block, "Reference"),
            value=property_value(block, "Value"),
            footprint=property_value(block, "Footprint"),
            uuid=uuid_match.group(1),
            digikey_part_number=property_value(block, "Digi-Key Part Number"),
            manufacturer_part_number=property_value(block, "Manufacturer Part Number"),
            line_id=property_value(block, "LineId"),
            description=property_value(block, "Description"),
        )
        if not item.reference:
            raise ValueError(f"Placed symbol is missing Reference: {block[:200]}")
        if not item.footprint:
            raise ValueError(f"{item.reference} is missing a Footprint property.")
        footprints.append(item)
    if not footprints:
        raise ValueError(f"No on-board schematic symbols with footprints were found in {path}")
    return root_uuid, footprints


def standard_footprint_dir() -> Path:
    for candidate in KICAD_FOOTPRINT_DIR_CANDIDATES:
        if candidate and candidate.is_dir():
            return candidate
    raise FileNotFoundError("KiCad standard footprint directory was not found.")


def expand_kicad_uri(uri: str, project_dir: Path) -> Path:
    expanded = uri.replace("${KIPRJMOD}", str(project_dir))
    expanded = re.sub(
        r"\$\{([^}]+)\}",
        lambda match: os.environ.get(match.group(1), match.group(0)),
        expanded,
    )
    return Path(os.path.expanduser(expanded))


def parse_fp_lib_table(project_dir: Path) -> dict[str, Path]:
    table_path = project_dir / "fp-lib-table"
    if not table_path.is_file():
        return {}
    text = table_path.read_text(encoding="utf-8")
    libraries: dict[str, Path] = {}
    for match in re.finditer(r'\(lib\s+\(name\s+"([^"]+)"\).*?\(uri\s+"([^"]+)"\)', text):
        libraries[match.group(1)] = expand_kicad_uri(match.group(2), project_dir)
    return libraries


def footprint_library_path(lib: str, project_dir: Path, fp_lib_table: dict[str, Path]) -> Path:
    if lib in fp_lib_table:
        return fp_lib_table[lib]

    project_local = project_dir / f"{lib}.pretty"
    if project_local.is_dir():
        return project_local

    return standard_footprint_dir() / f"{lib}.pretty"


def load_footprint(pcbnew, footprint_id: str, project_dir: Path, fp_lib_table: dict[str, Path]):
    if ":" not in footprint_id:
        raise ValueError(f"Footprint must be in Library:Name form: {footprint_id}")
    lib, name = footprint_id.split(":", 1)
    lib_path = footprint_library_path(lib, project_dir, fp_lib_table)
    if not lib_path.is_dir():
        raise FileNotFoundError(f"Footprint library not found for {footprint_id}: {lib_path}")
    footprint_path = lib_path / f"{name}.kicad_mod"
    if not footprint_path.is_file():
        raise FileNotFoundError(f"Footprint file not found for {footprint_id}: {footprint_path}")
    footprint = pcbnew.FootprintLoad(str(lib_path), name)
    if footprint is None:
        raise ValueError(f"KiCad failed to load footprint {footprint_id}")
    footprint.SetFPID(pcbnew.LIB_ID(lib, name))
    return footprint


def set_symbol_path(pcbnew, footprint, root_uuid: str, symbol_uuid: str) -> None:
    path = pcbnew.KIID_PATH()
    path.push_back(pcbnew.KIID(root_uuid))
    path.push_back(pcbnew.KIID(symbol_uuid))
    footprint.SetPath(path)


def set_hidden_field(footprint, name: str, value: str) -> None:
    if not value:
        return
    footprint.SetField(name, value)
    for field in footprint.GetFields():
        if field.GetName() == name:
            field.SetVisible(False)


def place_footprints(
    pcbnew,
    board_path: Path,
    project_dir: Path,
    root_uuid: str,
    items: list[SchematicFootprint],
    replace: bool,
    dry_run: bool,
    cols: int,
    x0_mm: float,
    y0_mm: float,
    dx_mm: float,
    dy_mm: float,
) -> None:
    fp_lib_table = parse_fp_lib_table(project_dir)

    if dry_run:
        for item in items:
            load_footprint(pcbnew, item.footprint, project_dir, fp_lib_table)
        return

    board = pcbnew.LoadBoard(str(board_path)) if board_path.exists() else pcbnew.BOARD()

    existing = list(board.GetFootprints())
    if existing and not replace:
        raise ValueError(
            f"{board_path} already contains {len(existing)} footprints. "
            "Re-run with --replace to regenerate placement."
        )
    for footprint in existing:
        board.Delete(footprint)

    for index, item in enumerate(items):
        footprint = load_footprint(pcbnew, item.footprint, project_dir, fp_lib_table)
        footprint.SetReference(item.reference)
        footprint.SetValue(item.value)
        footprint.Reference().SetVisible(True)
        footprint.Value().SetVisible(False)
        col = index % cols
        row = index // cols
        footprint.SetPosition(pcbnew.VECTOR2I_MM(x0_mm + col * dx_mm, y0_mm + row * dy_mm))
        set_symbol_path(pcbnew, footprint, root_uuid, item.uuid)
        set_hidden_field(footprint, "Digi-Key Part Number", item.digikey_part_number)
        set_hidden_field(footprint, "Manufacturer Part Number", item.manufacturer_part_number)
        set_hidden_field(footprint, "LineId", item.line_id)
        set_hidden_field(footprint, "Description", item.description)
        board.Add(footprint)

    board.Save(str(board_path))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Place all schematic footprints into a KiCad PCB file.")
    parser.add_argument("--schematic", type=Path, required=True, help="Input .kicad_sch file.")
    parser.add_argument("--pcb", type=Path, required=True, help="Output .kicad_pcb file.")
    parser.add_argument(
        "--project-dir",
        type=Path,
        help="KiCad project directory containing fp-lib-table; defaults to the schematic directory.",
    )
    parser.add_argument("--replace", action="store_true", help="Replace existing footprints in the PCB file.")
    parser.add_argument("--dry-run", action="store_true", help="Resolve all footprints without writing the PCB file.")
    parser.add_argument("--cols", type=int, default=16, help="Initial placement grid columns.")
    parser.add_argument("--x0", type=float, default=20.0, help="Initial placement X origin in mm.")
    parser.add_argument("--y0", type=float, default=20.0, help="Initial placement Y origin in mm.")
    parser.add_argument("--dx", type=float, default=25.0, help="Initial placement X spacing in mm.")
    parser.add_argument("--dy", type=float, default=25.0, help="Initial placement Y spacing in mm.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.cols <= 0:
        raise ValueError("--cols must be greater than zero.")

    schematic = args.schematic.resolve()
    pcb = args.pcb.resolve()
    project_dir = (args.project_dir or schematic.parent).resolve()

    pcbnew = require_pcbnew()
    root_uuid, items = parse_schematic(schematic)
    place_footprints(
        pcbnew,
        pcb,
        project_dir,
        root_uuid,
        items,
        args.replace,
        args.dry_run,
        args.cols,
        args.x0,
        args.y0,
        args.dx,
        args.dy,
    )
    action = "Resolved" if args.dry_run else "Placed"
    print(f"{action} {len(items)} footprints for {display_path(schematic)}")
    if not args.dry_run:
        print(f"Wrote {display_path(pcb)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
