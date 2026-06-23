#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sqlite3
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


UUID_NS = uuid.UUID("6f6f5d53-42f8-4ea8-a7c9-c4a8458e864d")


@dataclass
class BomContext:
    purpose: str = ""
    notes: str = ""
    mpn: str = ""
    refs: str = ""


@dataclass
class SymbolPlacement:
    reference: str
    value: str
    line_id: str
    description: str
    purpose: str
    mpn: str
    lib_id: str
    x: float
    y: float
    start: int
    end: int
    block: str


@dataclass
class BlockDef:
    key: str
    label: str
    note: str = ""
    match: dict[str, Any] = field(default_factory=dict)
    cols: int | None = None
    x: float | None = None
    y: float | None = None
    width: float | None = None
    height: float | None = None
    dx: float | None = None
    dy: float | None = None


@dataclass
class LayoutOptions:
    grid: float = 2.54
    block_columns: int = 2
    origin_x: float = 15.24
    origin_y: float = 20.32
    gap_x: float = 20.32
    gap_y: float = 20.32
    default_cols: int = 6
    dx: float = 50.80
    dy: float = 40.64
    margin_x: float = 30.48
    margin_y: float = 48.26
    header_h: float = 35.56


def s(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def uuid_for(*parts: str) -> str:
    return str(uuid.uuid5(UUID_NS, ":".join(parts)))


def snap(value: float, grid: float) -> float:
    if grid <= 0:
        return value
    return round(value / grid) * grid


def fmt(value: float) -> str:
    return f"{value:.2f}"


def natural_key(text: str) -> list[int | str]:
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", text)]


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


def lib_id_value(block: str) -> str:
    match = re.search(r'\(lib_id\s+"?([^"\s)]+)"?\)', block)
    return match.group(1) if match else ""


def first_at(block: str) -> tuple[float, float]:
    match = re.search(r"(?m)^\s*\(at\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s+-?\d+(?:\.\d+)?\)", block)
    if not match:
        raise ValueError("Placed symbol without an at coordinate was found.")
    return float(match.group(1)), float(match.group(2))


def load_bom_context(db_path: Path | None, project_name: str | None) -> dict[str, BomContext]:
    if not db_path:
        return {}
    query_project = project_name
    with sqlite3.connect(db_path) as conn:
        if query_project is None:
            projects = [row[0] for row in conn.execute("select distinct project_name from bom_items order by project_name")]
            if len(projects) == 1:
                query_project = projects[0]
            elif len(projects) > 1:
                raise ValueError("--project-name is required when the BOM database has multiple projects.")
        rows = conn.execute(
            """
            select line_id, purpose, notes, manufacturer_part_number, reference_designator
            from bom_items
            where project_name = ?
            """,
            (query_project,),
        ).fetchall()
    return {
        line_id: BomContext(purpose=purpose or "", notes=notes or "", mpn=mpn or "", refs=refs or "")
        for line_id, purpose, notes, mpn, refs in rows
    }


def parse_symbols(text: str, bom_context: dict[str, BomContext]) -> list[SymbolPlacement]:
    symbols: list[SymbolPlacement] = []
    for match in re.finditer(r"(?m)^\s*\(symbol\s*$", text):
        block = balanced_sexp(text, match.start())
        lib_id = lib_id_value(block)
        if not lib_id:
            continue
        reference = property_value(block, "Reference")
        if not reference:
            continue
        line_id = property_value(block, "LineId")
        bom = bom_context.get(line_id, BomContext())
        x, y = first_at(block)
        symbols.append(
            SymbolPlacement(
                reference=reference,
                value=property_value(block, "Value"),
                line_id=line_id,
                description=property_value(block, "Description"),
                purpose=property_value(block, "Purpose") or bom.purpose,
                mpn=property_value(block, "Manufacturer Part Number") or bom.mpn,
                lib_id=lib_id,
                x=x,
                y=y,
                start=match.start(),
                end=match.start() + len(block),
                block=block,
            )
        )
    if not symbols:
        raise ValueError("No placed schematic symbols were found.")
    return symbols


def parse_block_config(path: Path | None) -> tuple[list[BlockDef], LayoutOptions, bool]:
    if not path:
        return [], LayoutOptions(), False
    data = json.loads(path.read_text(encoding="utf-8"))
    layout_data = data.get("layout", {})
    opts = LayoutOptions(
        grid=float(data.get("grid", layout_data.get("grid", 2.54))),
        block_columns=int(layout_data.get("block_columns", 2)),
        origin_x=float(layout_data.get("origin", [15.24, 20.32])[0]),
        origin_y=float(layout_data.get("origin", [15.24, 20.32])[1]),
        gap_x=float(layout_data.get("gap", [20.32, 20.32])[0]),
        gap_y=float(layout_data.get("gap", [20.32, 20.32])[1]),
        default_cols=int(layout_data.get("default_cols", 6)),
        dx=float(layout_data.get("dx", 50.80)),
        dy=float(layout_data.get("dy", 40.64)),
        margin_x=float(layout_data.get("margin", [30.48, 48.26])[0]),
        margin_y=float(layout_data.get("margin", [30.48, 48.26])[1]),
        header_h=float(layout_data.get("header_h", 35.56)),
    )
    blocks = [
        BlockDef(
            key=str(item["key"]),
            label=str(item.get("label", item["key"])),
            note=str(item.get("note", "")),
            match=dict(item.get("match", {})),
            cols=int(item["cols"]) if item.get("cols") is not None else None,
            x=float(item["x"]) if item.get("x") is not None else None,
            y=float(item["y"]) if item.get("y") is not None else None,
            width=float(item["width"]) if item.get("width") is not None else None,
            height=float(item["height"]) if item.get("height") is not None else None,
            dx=float(item["dx"]) if item.get("dx") is not None else None,
            dy=float(item["dy"]) if item.get("dy") is not None else None,
        )
        for item in data.get("blocks", [])
    ]
    return blocks, opts, bool(data.get("strip_all_top_level_graphics", False))


def value_list(match: dict[str, Any], key: str) -> list[str]:
    value = match.get(key, [])
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value]


def matches_block(symbol: SymbolPlacement, block: BlockDef) -> bool:
    match = block.match
    haystacks = {
        "reference": symbol.reference,
        "line_id": symbol.line_id,
        "purpose": symbol.purpose,
        "value": symbol.value,
        "description": symbol.description,
        "mpn": symbol.mpn,
        "lib_id": symbol.lib_id,
        "text": " ".join([symbol.reference, symbol.value, symbol.purpose, symbol.description, symbol.mpn, symbol.lib_id]),
    }

    for key, haystack in haystacks.items():
        exact = value_list(match, key)
        if exact and haystack in exact:
            return True
        prefixes = value_list(match, f"{key}_prefix")
        if prefixes and any(haystack.startswith(prefix) for prefix in prefixes):
            return True
        regexes = value_list(match, f"{key}_regex")
        if regexes and any(re.search(pattern, haystack, flags=re.IGNORECASE) for pattern in regexes):
            return True
    return False


def normalized_purpose_key(purpose: str, reference: str) -> str:
    text = purpose.lower()
    if reference.startswith("XIN") or "display" in text:
        return "display"
    if "power" in text:
        return "power"
    if "control" in text:
        return "control"
    return "other"


def default_blocks_for(symbols: list[SymbolPlacement]) -> list[BlockDef]:
    labels = {
        "power": ("電源系 / Power", "Power conversion, protection, filtering, and bias parts"),
        "control": ("制御系 / Control", "MCU, logic, communication, clock, and debug parts"),
        "display": ("表示系 / Display", "Display drivers, switches, indicators, and sockets"),
        "other": ("その他 / Other", "Parts that need project-specific classification"),
    }
    seen: list[str] = []
    for symbol in symbols:
        key = normalized_purpose_key(symbol.purpose, symbol.reference)
        if key not in seen:
            seen.append(key)
    if "other" not in seen:
        seen.append("other")
    return [BlockDef(key=key, label=labels[key][0], note=labels[key][1]) for key in seen]


def classify_symbols(symbols: list[SymbolPlacement], blocks: list[BlockDef]) -> dict[str, list[SymbolPlacement]]:
    block_map = {block.key: [] for block in blocks}
    has_match_rules = any(block.match for block in blocks)
    for symbol in symbols:
        target = ""
        if has_match_rules:
            for block in blocks:
                if block.match and matches_block(symbol, block):
                    target = block.key
                    break
        if not target:
            auto_key = normalized_purpose_key(symbol.purpose, symbol.reference)
            target = auto_key if auto_key in block_map else blocks[-1].key
        block_map[target].append(symbol)
    for items in block_map.values():
        items.sort(key=lambda item: natural_key(item.reference))
    return block_map


def block_dimensions(block: BlockDef, count: int, opts: LayoutOptions) -> tuple[int, float, float, float, float]:
    cols = block.cols or opts.default_cols
    cols = max(1, cols)
    dx = block.dx or opts.dx
    dy = block.dy or opts.dy
    rows = max(1, math.ceil(max(1, count) / cols))
    width = block.width or (opts.margin_x * 2 + (min(cols, max(1, count)) - 1) * dx + 30.48)
    height = block.height or (opts.header_h + opts.margin_y + (rows - 1) * dy + 25.40)
    return cols, dx, dy, width, height


def assign_positions(
    blocks: list[BlockDef],
    block_map: dict[str, list[SymbolPlacement]],
    opts: LayoutOptions,
) -> tuple[dict[str, tuple[float, float, float, float]], dict[str, tuple[float, float]]]:
    rectangles: dict[str, tuple[float, float, float, float]] = {}
    positions: dict[str, tuple[float, float]] = {}
    cursor_x = opts.origin_x
    cursor_y = opts.origin_y
    row_height = 0.0
    auto_index = 0

    for block in blocks:
        items = block_map.get(block.key, [])
        if not items:
            continue
        cols, dx, dy, width, height = block_dimensions(block, len(items), opts)
        if block.x is not None and block.y is not None:
            x = block.x
            y = block.y
        else:
            if auto_index > 0 and auto_index % opts.block_columns == 0:
                cursor_x = opts.origin_x
                cursor_y += row_height + opts.gap_y
                row_height = 0.0
            x = cursor_x
            y = cursor_y
            cursor_x += width + opts.gap_x
            row_height = max(row_height, height)
            auto_index += 1
        x = snap(x, opts.grid)
        y = snap(y, opts.grid)
        width = snap(width, opts.grid)
        height = snap(height, opts.grid)
        rectangles[block.key] = (x, y, x + width, y + height)
        for index, symbol in enumerate(items):
            symbol_x = x + opts.margin_x + (index % cols) * dx
            symbol_y = y + opts.margin_y + (index // cols) * dy
            positions[symbol.reference] = (snap(symbol_x, opts.grid), snap(symbol_y, opts.grid))
    return rectangles, positions


def shift_symbol_block(block: str, new_x: float, new_y: float) -> str:
    old_x, old_y = first_at(block)
    delta_x = new_x - old_x
    delta_y = new_y - old_y

    def repl(match: re.Match[str]) -> str:
        x = float(match.group(2)) + delta_x
        y = float(match.group(4)) + delta_y
        return f"{match.group(1)}{fmt(x)}{match.group(3)}{fmt(y)}{match.group(5)}{match.group(6)}"

    at_line = re.compile(
        r"(?m)^(\s*\(at\s+)(-?\d+(?:\.\d+)?)(\s+)(-?\d+(?:\.\d+)?)(\s+)(-?\d+(?:\.\d+)?)"
    )
    return at_line.sub(repl, block)


def block_rectangle(block: BlockDef, rect: tuple[float, float, float, float]) -> str:
    x1, y1, x2, y2 = rect
    return f"""\t(rectangle
\t\t(start {fmt(x1)} {fmt(y1)})
\t\t(end {fmt(x2)} {fmt(y2)})
\t\t(stroke (width 0.254) (type dash))
\t\t(fill (type none))
\t\t(uuid {s(uuid_for("functional-block-layout", block.key, "rectangle"))})
\t)"""


def block_text(text: str, x: float, y: float, size: float, key: str) -> str:
    thickness = max(0.15, size * 0.10)
    return f"""\t(text {s(text)}
\t\t(at {fmt(x)} {fmt(y)} 0)
\t\t(effects
\t\t\t(font (size {fmt(size)} {fmt(size)}) (thickness {fmt(thickness)}))
\t\t\t(justify left bottom)
\t\t)
\t\t(uuid {s(uuid_for("functional-block-layout", key, text))})
\t)"""


def generated_graphics(blocks: list[BlockDef], rectangles: dict[str, tuple[float, float, float, float]], opts: LayoutOptions) -> list[str]:
    graphics: list[str] = []
    for block in blocks:
        rect = rectangles.get(block.key)
        if not rect:
            continue
        x1, y1, _, _ = rect
        graphics.append(block_rectangle(block, rect))
        graphics.append(block_text(block.label, snap(x1 + 5.08, opts.grid), snap(y1 + 10.16, opts.grid), 3.00, f"{block.key}-label"))
        if block.note:
            graphics.append(block_text(block.note, snap(x1 + 5.08, opts.grid), snap(y1 + 17.78, opts.grid), 1.60, f"{block.key}-note"))
    return graphics


def generated_uuid_set(blocks: list[BlockDef]) -> set[str]:
    ids: set[str] = set()
    for block in blocks:
        ids.add(uuid_for("functional-block-layout", block.key, "rectangle"))
        ids.add(uuid_for("functional-block-layout", f"{block.key}-label", block.label))
        if block.note:
            ids.add(uuid_for("functional-block-layout", f"{block.key}-note", block.note))
    return ids


def top_level_graphic_spans(text: str, strip_all: bool, ids: set[str]) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for match in re.finditer(r"(?m)^\t\((rectangle|text)\b", text):
        block = balanced_sexp(text, match.start())
        uuid_match = re.search(r'\(uuid\s+"([^"]+)"\)', block)
        if strip_all or (uuid_match and uuid_match.group(1) in ids):
            spans.append((match.start(), match.start() + len(block)))
    return spans


def rewrite_schematic(
    text: str,
    symbols: list[SymbolPlacement],
    positions: dict[str, tuple[float, float]],
    graphics: list[str],
    strip_all_graphics: bool,
    generated_ids: set[str],
) -> str:
    replacements: list[tuple[int, int, str]] = []
    for symbol in symbols:
        new_position = positions.get(symbol.reference)
        if not new_position:
            continue
        replacements.append((symbol.start, symbol.end, shift_symbol_block(symbol.block, *new_position)))
    for start, end in top_level_graphic_spans(text, strip_all_graphics, generated_ids):
        replacements.append((start, end, ""))
    replacements.sort(key=lambda item: item[0])
    first_symbol_start = min(symbol.start for symbol in symbols)
    graphic_body = "\n".join(graphics)

    parts: list[str] = []
    cursor = 0
    inserted = False
    for start, end, replacement in replacements:
        if not inserted and first_symbol_start <= start:
            parts.append(text[cursor:first_symbol_start])
            if graphic_body:
                parts.append(graphic_body)
                parts.append("\n")
            cursor = first_symbol_start
            inserted = True
        parts.append(text[cursor:start])
        parts.append(replacement)
        cursor = end
    if not inserted:
        parts.append(text[cursor:first_symbol_start])
        if graphic_body:
            parts.append(graphic_body)
            parts.append("\n")
        cursor = first_symbol_start
    parts.append(text[cursor:])
    return "".join(parts)


def write_config_template(path: Path, symbols: list[SymbolPlacement]) -> None:
    purposes = sorted({symbol.purpose for symbol in symbols if symbol.purpose})
    blocks: list[dict[str, Any]] = []
    if purposes:
        for purpose in purposes:
            key = re.sub(r"[^a-z0-9]+", "_", purpose.lower()).strip("_") or "block"
            blocks.append(
                {
                    "key": key,
                    "label": purpose,
                    "note": "Auto-generated from BOM purpose; edit match rules and block geometry as needed.",
                    "match": {"purpose": [purpose]},
                    "cols": 6,
                }
            )
    else:
        blocks = [
            {"key": "power", "label": "電源系 / Power", "match": {"reference_regex": ["^(F|L|Q|D|CIN|COUT|RFB|RBLD)"]}, "cols": 6},
            {"key": "control", "label": "制御系 / Control", "match": {"reference_regex": ["^(U|Y|J|R|C)"]}, "cols": 6},
            {"key": "display", "label": "表示系 / Display", "match": {"reference_regex": ["^(X|LED|DISP)"]}, "cols": 6},
            {"key": "other", "label": "その他 / Other", "match": {}, "cols": 6},
        ]
    template = {
        "grid": 2.54,
        "layout": {
            "block_columns": 2,
            "origin": [15.24, 20.32],
            "gap": [20.32, 20.32],
            "default_cols": 6,
            "dx": 50.80,
            "dy": 40.64,
            "margin": [30.48, 48.26],
            "header_h": 35.56,
        },
        "blocks": blocks,
    }
    path.write_text(json.dumps(template, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_summary(path: Path, blocks: list[BlockDef], block_map: dict[str, list[SymbolPlacement]]) -> None:
    lines = [
        "# KiCad 回路図機能ブロック配置",
        "",
        "`organize_kicad_schematic_blocks.py` による機能ブロック配置の記録。",
        "",
        "| Block | Count | References |",
        "| --- | ---: | --- |",
    ]
    for block in blocks:
        items = block_map.get(block.key, [])
        refs = " ".join(symbol.reference for symbol in items)
        lines.append(f"| {block.label} | {len(items)} | `{refs}` |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Organize a KiCad schematic into functional block frames.")
    parser.add_argument("--schematic", type=Path, required=True, help="Input .kicad_sch file.")
    parser.add_argument("--output", type=Path, help="Output .kicad_sch path. Use --in-place to overwrite input.")
    parser.add_argument("--in-place", action="store_true", help="Overwrite the input schematic.")
    parser.add_argument("--config", type=Path, help="JSON block layout/classification config.")
    parser.add_argument("--bom-db", type=Path, help="SQLite BOM database with bom_items purpose/LineId data.")
    parser.add_argument("--project-name", help="Project name in the BOM database.")
    parser.add_argument("--write-config-template", type=Path, help="Write a starter block config and exit.")
    parser.add_argument("--summary-md", type=Path, help="Optional Markdown summary path.")
    parser.add_argument("--dry-run", action="store_true", help="Classify and plan placement without writing a schematic.")
    parser.add_argument(
        "--strip-all-top-level-graphics",
        action="store_true",
        help="Remove all top-level rectangles/text before inserting block frames. Use only for generated placement schematics.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    schematic = args.schematic.resolve()
    text = schematic.read_text(encoding="utf-8")
    bom_context = load_bom_context(args.bom_db.resolve() if args.bom_db else None, args.project_name)
    symbols = parse_symbols(text, bom_context)

    if args.write_config_template:
        write_config_template(args.write_config_template, symbols)
        print(f"Wrote {args.write_config_template}")
        return 0

    blocks, opts, config_strip_all = parse_block_config(args.config)
    if not blocks:
        blocks = default_blocks_for(symbols)
    if "other" not in {block.key for block in blocks}:
        blocks.append(BlockDef(key="other", label="その他 / Other", note="Unmatched parts"))

    block_map = classify_symbols(symbols, blocks)
    rectangles, positions = assign_positions(blocks, block_map, opts)
    graphics = generated_graphics(blocks, rectangles, opts)
    print(f"Planned {len(symbols)} symbols into {sum(1 for items in block_map.values() if items)} blocks")
    for block in blocks:
        count = len(block_map.get(block.key, []))
        if count:
            print(f"- {block.key}: {count}")

    if args.summary_md and not args.dry_run:
        write_summary(args.summary_md, blocks, block_map)

    if args.dry_run:
        return 0

    if args.in_place:
        output = schematic
    elif args.output:
        output = args.output.resolve()
    else:
        raise ValueError("Specify --output, --in-place, --dry-run, or --write-config-template.")

    new_text = rewrite_schematic(
        text,
        symbols,
        positions,
        graphics,
        args.strip_all_top_level_graphics or config_strip_all,
        generated_uuid_set(blocks),
    )
    output.write_text(new_text, encoding="utf-8")
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
