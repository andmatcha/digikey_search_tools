from __future__ import annotations

import csv
import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .bom import BomLine, parse_quantity
from .library import LibraryDatabase
from .project import ProjectContext


JsonDict = dict[str, Any]

PACKAGE_CODE_TO_METRIC = {
    "0201": "0603Metric",
    "0402": "1005Metric",
    "0603": "1608Metric",
    "0805": "2012Metric",
    "1206": "3216Metric",
    "1210": "3225Metric",
    "1812": "4532Metric",
    "2010": "5025Metric",
    "2512": "6332Metric",
}
PASSIVE_SYMBOLS = {
    "resistor": "Device:R",
    "capacitor": "Device:C",
    "polarized_capacitor": "Device:CP",
    "inductor": "Device:L",
    "ferrite_bead": "Device:Ferrite_Bead",
    "diode": "Device:D",
    "led": "Device:LED",
    "fuse": "Device:Fuse",
    "test_point": "Connector:TestPoint",
}
STANDARD_PACKAGE_HINTS = [
    "Package_",
    "SOIC",
    "SOP",
    "SSOP",
    "TSSOP",
    "MSOP",
    "SOT-",
    "QFN",
    "QFP",
    "LQFP",
    "TQFP",
    "BGA",
    "DFN",
    "DIP",
    "TO-",
]
PIN_TYPE_MAP = {
    "bidirectional": "bidirectional",
    "bidir": "bidirectional",
    "input": "input",
    "in": "input",
    "output": "output",
    "out": "output",
    "tri_state": "tri_state",
    "tristate": "tri_state",
    "passive": "passive",
    "free": "free",
    "unspecified": "unspecified",
    "power_in": "power_in",
    "power input": "power_in",
    "power": "power_in",
    "power_out": "power_out",
    "power output": "power_out",
    "open_collector": "open_collector",
    "open emitter": "open_emitter",
    "open_emitter": "open_emitter",
    "no_connect": "no_connect",
    "nc": "no_connect",
}


@dataclass(frozen=True)
class PinDefinition:
    number: str
    name: str
    pin_type: str = "passive"
    side: str = ""

    def to_json(self) -> JsonDict:
        return {
            "number": self.number,
            "name": self.name,
            "pin_type": self.pin_type,
            "side": self.side,
        }


def detect_kicad_environment() -> JsonDict:
    cli_path = find_kicad_cli()
    version = None
    cli_ok = False
    if cli_path:
        try:
            result = subprocess.run(
                [cli_path, "version"],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
            cli_ok = result.returncode == 0
            version = (result.stdout or result.stderr).strip() or None
        except (OSError, subprocess.SubprocessError):
            cli_ok = False
    symbol_dirs = candidate_dirs(
        "KICAD_SYMBOL_DIR",
        [
            "/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols",
            "/usr/share/kicad/symbols",
            "/usr/local/share/kicad/symbols",
        ],
    )
    footprint_dirs = candidate_dirs(
        "KICAD_FOOTPRINT_DIR",
        [
            "/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints",
            "/usr/share/kicad/footprints",
            "/usr/local/share/kicad/footprints",
        ],
    )
    return {
        "kicad_cli": {
            "path": cli_path,
            "available": cli_ok,
            "version": version,
        },
        "symbol_dirs": [str(path) for path in symbol_dirs],
        "footprint_dirs": [str(path) for path in footprint_dirs],
    }


def find_kicad_cli(candidates: list[Path] | None = None) -> str | None:
    path = shutil.which("kicad-cli")
    if path:
        return path
    search_paths = candidates or [
        Path("/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"),
    ]
    for candidate in search_paths:
        if candidate.exists() and candidate.is_file():
            return str(candidate)
    return None


def candidate_dirs(env_name: str, defaults: list[str]) -> list[Path]:
    values = []
    env_value = PathEnv.get(env_name)
    if env_value:
        values.append(env_value)
    values.extend(defaults)
    paths = []
    for value in values:
        path = Path(value).expanduser()
        if path.exists():
            paths.append(path)
    return paths


class PathEnv:
    @staticmethod
    def get(name: str) -> str | None:
        import os

        value = os.environ.get(name)
        return value if value and value.strip() else None


def load_pin_map(path: Path | None) -> dict[str, list[PinDefinition]]:
    if path is None:
        return {}
    pins: dict[str, list[PinDefinition]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            keys = pin_row_keys(row)
            if not keys:
                continue
            pin = PinDefinition(
                number=first_nonempty(row.get("PinNumber"), row.get("Number"), row.get("Pin")) or "",
                name=first_nonempty(row.get("PinName"), row.get("Name"), row.get("Signal")) or "",
                pin_type=normalize_pin_type(first_nonempty(row.get("PinType"), row.get("Type"))),
                side=str(row.get("Side") or "").strip().lower(),
            )
            if not pin.number:
                continue
            for key in keys:
                pins.setdefault(key, []).append(pin)
    return pins


def pin_row_keys(row: dict[str, str]) -> list[str]:
    keys = []
    for column in [
        "LineId",
        "line_id",
        "Reference Designator",
        "Reference",
        "Ref",
        "Manufacturer Part Number",
        "MPN",
        "Digi-Key Part Number",
        "DigikeyPartNumber",
    ]:
        value = str(row.get(column) or "").strip()
        if value:
            keys.append(value)
    return keys


def pins_for_line(pin_map: dict[str, list[PinDefinition]], line: BomLine) -> list[PinDefinition]:
    keys = [
        line.line_id,
        line.row.get("Reference Designator", ""),
        line.row.get("Manufacturer Part Number", ""),
        line.row.get("Digi-Key Part Number", ""),
    ]
    for key in keys:
        if key and key in pin_map:
            return pin_map[key]
    return []


def decide_line_library(
    line: BomLine,
    *,
    existing: JsonDict | None = None,
    pin_map: dict[str, list[PinDefinition]] | None = None,
    kicad_environment: JsonDict | None = None,
) -> JsonDict:
    part_kind = classify_line(line)
    pins = pins_for_line(pin_map or {}, line)
    footprint_name = choose_footprint(line, part_kind)
    symbol_name = choose_symbol(line, part_kind, pins=pins, existing=existing)
    symbol_policy = symbol_policy_for(part_kind, symbol_name, pins, existing)
    footprint_policy = footprint_policy_for(line, part_kind, footprint_name)
    pin_policy = pin_policy_for(part_kind, pins, existing)
    kicad_checks = check_kicad_assets(symbol_name, footprint_name, kicad_environment)
    statuses = statuses_for_decision(
        part_kind=part_kind,
        symbol_name=symbol_name,
        symbol_policy=symbol_policy,
        footprint_name=footprint_name,
        footprint_policy=footprint_policy,
        pin_policy=pin_policy,
        pins=pins,
    )
    decision = {
        "part_kind": part_kind,
        "symbol_policy": symbol_policy,
        "footprint_policy": footprint_policy,
        "pin_policy": pin_policy,
        "symbol_name": symbol_name,
        "footprint_name": footprint_name,
        "generated_symbol_name": generated_symbol_name(line) if pins else "",
        "pin_count": len(pins),
        "kicad_checks": kicad_checks,
    }
    updates = {
        "kicad_symbol_status": statuses["symbol_status"],
        "kicad_symbol_name": symbol_name,
        "kicad_footprint_status": statuses["footprint_status"],
        "kicad_footprint_name": footprint_name,
        "kicad_3d_model_status": statuses["model_status"],
        "external_library_status": statuses["external_status"],
        "overall_status": statuses["overall_status"],
        "confidence": statuses["confidence"],
        "recommended_action": statuses["recommended_action"],
        "notes": statuses["notes"],
        "symbol_policy": symbol_policy,
        "footprint_policy": footprint_policy,
        "pin_policy": pin_policy,
        "kicad_import_status": statuses["import_status"],
    }
    return {"updates": updates, "evidence": {"auto_decision": decision}, "decision": decision}


def classify_line(line: BomLine) -> str:
    ref = str(line.row.get("Reference Designator") or "").strip().upper()
    text = " ".join(
        str(line.row.get(column) or "")
        for column in ["Value", "Description", "Purpose", "Notes", "Manufacturer Part Number", "Footprint"]
    ).lower()
    prefix = re.match(r"[A-Z]+", ref)
    ref_prefix = prefix.group(0) if prefix else ""
    if ref_prefix.startswith("R") and not ref_prefix.startswith(("RN", "RV")):
        return "resistor"
    if ref_prefix in {"C", "CP"}:
        if any(token in text for token in ["polar", "electrolytic", "tantalum", "cpol"]):
            return "polarized_capacitor"
        return "capacitor"
    if ref_prefix == "L":
        return "inductor"
    if ref_prefix in {"FB", "FBL"} or "ferrite" in text:
        return "ferrite_bead"
    if ref_prefix == "D":
        return "led" if "led" in text else "diode"
    if ref_prefix == "F":
        return "fuse"
    if ref_prefix in {"TP", "JTP"}:
        return "test_point"
    if ref_prefix in {"U", "IC"}:
        return "ic"
    if ref_prefix in {"Q", "M"}:
        return "discrete_semiconductor"
    if ref_prefix in {"J", "P", "CN", "CONN"}:
        return "connector"
    if any(token in text for token in ["resistor", "resistance"]):
        return "resistor"
    if "capacitor" in text:
        return "capacitor"
    return "unknown"


def choose_symbol(
    line: BomLine,
    part_kind: str,
    *,
    pins: list[PinDefinition],
    existing: JsonDict | None,
) -> str:
    existing_symbol = str((existing or {}).get("kicad_symbol_name") or "").strip()
    existing_status = str((existing or {}).get("kicad_symbol_status") or "")
    if existing_symbol and existing_status in {"generic_ok", "available"}:
        return existing_symbol
    if part_kind in PASSIVE_SYMBOLS:
        return PASSIVE_SYMBOLS[part_kind]
    if pins:
        return f"dktools_generated:{generated_symbol_name(line)}"
    return existing_symbol


def choose_footprint(line: BomLine, part_kind: str) -> str:
    footprint = str(line.row.get("Footprint") or "").strip()
    if footprint:
        return footprint
    package_code = package_code_for(line)
    if package_code and part_kind == "resistor":
        return f"Resistor_SMD:R_{package_code}_{PACKAGE_CODE_TO_METRIC[package_code]}"
    if package_code and part_kind in {"capacitor", "polarized_capacitor"}:
        return f"Capacitor_SMD:C_{package_code}_{PACKAGE_CODE_TO_METRIC[package_code]}"
    if package_code and part_kind in {"inductor", "ferrite_bead"}:
        return f"Inductor_SMD:L_{package_code}_{PACKAGE_CODE_TO_METRIC[package_code]}"
    return ""


def package_code_for(line: BomLine) -> str:
    text = " ".join(
        str(line.row.get(column) or "")
        for column in ["Value", "Description", "Footprint", "Manufacturer Part Number", "Notes"]
    )
    for code in sorted(PACKAGE_CODE_TO_METRIC, key=len, reverse=True):
        if re.search(rf"(?<!\d){code}(?!\d)", text):
            return code
    return ""


def symbol_policy_for(
    part_kind: str,
    symbol_name: str,
    pins: list[PinDefinition],
    existing: JsonDict | None,
) -> str:
    if part_kind in PASSIVE_SYMBOLS:
        return "kicad_generic_preferred"
    if pins:
        return "generated_specific"
    if symbol_name and (existing or {}).get("kicad_symbol_status") in {"generic_ok", "available"}:
        return "verified_specific"
    if part_kind in {"ic", "discrete_semiconductor"}:
        return "specific_required"
    if part_kind == "connector":
        return "generic_possible_verify_pins"
    return "manual_required"


def footprint_policy_for(line: BomLine, part_kind: str, footprint_name: str) -> str:
    if not footprint_name:
        return "footprint_required"
    if part_kind in PASSIVE_SYMBOLS:
        return "kicad_generic_preferred"
    if any(token in footprint_name for token in STANDARD_PACKAGE_HINTS):
        return "standard_package_preferred"
    return "bom_specified_verify"


def pin_policy_for(
    part_kind: str,
    pins: list[PinDefinition],
    existing: JsonDict | None,
) -> str:
    if part_kind in PASSIVE_SYMBOLS:
        return "generic_pin_identity_ok"
    if pins:
        return "pin_map_provided"
    if (existing or {}).get("kicad_symbol_status") in {"generic_ok", "available"}:
        return "symbol_pinout_must_be_verified"
    if part_kind in {"ic", "discrete_semiconductor", "connector"}:
        return "specific_pin_identity_required"
    return "unknown"


def statuses_for_decision(
    *,
    part_kind: str,
    symbol_name: str,
    symbol_policy: str,
    footprint_name: str,
    footprint_policy: str,
    pin_policy: str,
    pins: list[PinDefinition],
) -> JsonDict:
    passive = part_kind in PASSIVE_SYMBOLS
    if passive:
        confidence = "high" if footprint_name else "medium"
        return {
            "symbol_status": "generic_ok",
            "footprint_status": "generic_ok" if footprint_name else "unknown",
            "model_status": "generic_ok" if footprint_name else "unknown",
            "external_status": "not_required",
            "overall_status": "usable_with_generic" if footprint_name else "review",
            "confidence": confidence,
            "import_status": "ready" if footprint_name else "needs_review",
            "recommended_action": "" if footprint_name else "KiCad標準フットプリントを確定する",
            "notes": "KiCad標準の汎用シンボル/フットプリントを優先する受動部品",
        }
    if symbol_policy == "generated_specific":
        return {
            "symbol_status": "available",
            "footprint_status": "generic_ok" if footprint_name else "unknown",
            "model_status": "generic_ok" if footprint_name else "unknown",
            "external_status": "not_required",
            "overall_status": "ready" if footprint_name else "review",
            "confidence": "medium",
            "import_status": "ready" if footprint_name else "needs_review",
            "recommended_action": "" if footprint_name else "標準パッケージフットプリントを確定する",
            "notes": "ピン表から個別ICシンボルを生成し、フットプリントは標準パッケージを優先",
        }
    if symbol_policy == "verified_specific":
        return {
            "symbol_status": "available",
            "footprint_status": "generic_ok" if footprint_name else "unknown",
            "model_status": "generic_ok" if footprint_name else "unknown",
            "external_status": "not_required",
            "overall_status": "ready" if footprint_name else "review",
            "confidence": "medium",
            "import_status": "ready" if footprint_name else "needs_review",
            "recommended_action": "" if footprint_name else "標準パッケージフットプリントを確定する",
            "notes": "個別シンボルのピン配置/ピン名を使い、フットプリントは標準パッケージを優先",
        }
    action = "個別ICのピン番号、ピン名、電気タイプをpin-map CSVで指定する"
    if not footprint_name:
        action += "。標準パッケージフットプリントも確定する"
    return {
        "symbol_status": "needs_custom",
        "footprint_status": "generic_ok" if footprint_name and footprint_policy != "footprint_required" else "unknown",
        "model_status": "generic_ok" if footprint_name and footprint_policy != "footprint_required" else "unknown",
        "external_status": "unknown",
        "overall_status": "needs_custom",
        "confidence": "medium" if footprint_name else "low",
        "import_status": "blocked",
        "recommended_action": action,
        "notes": "IC/半導体は汎用パッケージのフットプリントを優先し、シンボルは個別ピン配置/ピン名を必須にする",
    }


def check_kicad_assets(symbol_name: str, footprint_name: str, environment: JsonDict | None) -> JsonDict:
    if not environment:
        return {}
    return {
        "symbol_exists": symbol_exists(symbol_name, environment),
        "footprint_exists": footprint_exists(footprint_name, environment),
        "kicad_cli_available": bool((environment.get("kicad_cli") or {}).get("available")),
    }


def symbol_exists(symbol_name: str, environment: JsonDict) -> bool | None:
    if not symbol_name or ":" not in symbol_name:
        return None
    library_name, symbol = symbol_name.split(":", 1)
    for directory in environment.get("symbol_dirs") or []:
        path = Path(str(directory)) / f"{library_name}.kicad_sym"
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if f'(symbol "{symbol}"' in text:
            return True
    return False if environment.get("symbol_dirs") else None


def footprint_exists(footprint_name: str, environment: JsonDict) -> bool | None:
    if not footprint_name or ":" not in footprint_name:
        return None
    library_name, footprint = footprint_name.split(":", 1)
    for directory in environment.get("footprint_dirs") or []:
        path = Path(str(directory)) / f"{library_name}.pretty" / f"{footprint}.kicad_mod"
        if path.exists():
            return True
    return False if environment.get("footprint_dirs") else None


def merge_decision_updates(
    existing: JsonDict | None,
    updates: JsonDict,
    *,
    overwrite: bool,
) -> JsonDict:
    if overwrite or not existing:
        return updates
    merged: JsonDict = {}
    for key, value in updates.items():
        current = existing.get(key)
        if is_empty_decision_value(current):
            merged[key] = value
    return merged


def is_empty_decision_value(value: object) -> bool:
    return value is None or str(value).strip() in {"", "unknown"}


def export_kicad_import_bundle(
    project: ProjectContext,
    lines: list[BomLine],
    *,
    library_db: LibraryDatabase,
    output_dir: Path,
    kicad_project_dir: Path,
    pin_map: dict[str, list[PinDefinition]],
    library_nickname: str,
    apply_to_project: bool = False,
    kicad_environment: JsonDict | None = None,
) -> JsonDict:
    output_dir.mkdir(parents=True, exist_ok=True)
    assessments = library_db.assessments_by_line(project.project_name)
    plan_rows = []
    generated_symbols: list[tuple[str, list[PinDefinition], BomLine]] = []
    for line in lines:
        assessment = assessments.get(line.line_id)
        pins = pins_for_line(pin_map, line)
        symbol_name = str((assessment or {}).get("kicad_symbol_name") or "")
        if pins and (not symbol_name or symbol_name.startswith("dktools_generated:")):
            symbol_name = f"{library_nickname}:{generated_symbol_name(line)}"
            generated_symbols.append((generated_symbol_name(line), pins, line))
        row = kicad_plan_row(line, assessment, symbol_name=symbol_name, pins=pins)
        plan_rows.append(row)

    plan_path = output_dir / "dktools_import_plan.json"
    fields_csv = output_dir / "dktools_symbol_fields.csv"
    footprints_csv = output_dir / "dktools_footprint_assignments.csv"
    library_path = output_dir / f"{library_nickname}.kicad_sym"
    report_path = output_dir / "dktools_library_report.md"

    plan = {
        "project": project.metadata(),
        "kicad_project_dir": str(kicad_project_dir),
        "kicad_environment": kicad_environment or {},
        "library_nickname": library_nickname,
        "generated_symbol_library": str(library_path),
        "rows": plan_rows,
        "summary": {
            "rows": len(plan_rows),
            "ready": len([row for row in plan_rows if row["import_status"] == "ready"]),
            "blocked": len([row for row in plan_rows if row["import_status"] == "blocked"]),
            "needs_review": len([row for row in plan_rows if row["import_status"] == "needs_review"]),
            "generated_symbols": len(generated_symbols),
        },
    }
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_symbol_fields_csv(fields_csv, plan_rows)
    write_footprint_assignments_csv(footprints_csv, plan_rows)
    write_generated_symbol_library(library_path, generated_symbols)
    write_kicad_report(report_path, plan)

    applied = False
    sym_lib_table = None
    if apply_to_project:
        sym_lib_table = update_sym_lib_table(
            kicad_project_dir,
            library_nickname=library_nickname,
            library_path=library_path,
        )
        applied = True

    return {
        "output_dir": str(output_dir),
        "plan_json": str(plan_path),
        "symbol_fields_csv": str(fields_csv),
        "footprint_assignments_csv": str(footprints_csv),
        "generated_symbol_library": str(library_path),
        "report_md": str(report_path),
        "sym_lib_table": str(sym_lib_table) if sym_lib_table else None,
        "applied_to_project": applied,
        "summary": plan["summary"],
    }


def kicad_plan_row(
    line: BomLine,
    assessment: JsonDict | None,
    *,
    symbol_name: str,
    pins: list[PinDefinition],
) -> JsonDict:
    source = line.row
    import_status = str((assessment or {}).get("kicad_import_status") or "")
    if not import_status:
        if not assessment:
            import_status = "blocked"
        elif (assessment or {}).get("overall_status") in {"ready", "usable_with_generic"}:
            import_status = "ready"
        else:
            import_status = "needs_review"
    return {
        "line_id": line.line_id,
        "reference": source.get("Reference Designator", ""),
        "quantity": parse_quantity(source.get("Quantity")),
        "value": source.get("Value", ""),
        "symbol": symbol_name,
        "footprint": str((assessment or {}).get("kicad_footprint_name") or source.get("Footprint", "")),
        "manufacturer": source.get("Manufacturer", ""),
        "manufacturer_part_number": source.get("Manufacturer Part Number", ""),
        "digikey_part_number": source.get("Digi-Key Part Number", ""),
        "description": source.get("Description", ""),
        "symbol_policy": (assessment or {}).get("symbol_policy", "unknown"),
        "footprint_policy": (assessment or {}).get("footprint_policy", "unknown"),
        "pin_policy": (assessment or {}).get("pin_policy", "unknown"),
        "pin_count": len(pins),
        "import_status": import_status,
        "recommended_action": (assessment or {}).get("recommended_action", ""),
        "notes": (assessment or {}).get("notes", source.get("Notes", "")),
    }


def write_symbol_fields_csv(path: Path, rows: list[JsonDict]) -> None:
    fieldnames = [
        "Reference",
        "LineId",
        "Value",
        "Symbol",
        "Footprint",
        "Manufacturer",
        "Manufacturer Part Number",
        "Digi-Key Part Number",
        "Description",
        "Library Decision",
        "Pin Policy",
        "Import Status",
        "Recommended Action",
        "Notes",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "Reference": row["reference"],
                    "LineId": row["line_id"],
                    "Value": row["value"],
                    "Symbol": row["symbol"],
                    "Footprint": row["footprint"],
                    "Manufacturer": row["manufacturer"],
                    "Manufacturer Part Number": row["manufacturer_part_number"],
                    "Digi-Key Part Number": row["digikey_part_number"],
                    "Description": row["description"],
                    "Library Decision": row["symbol_policy"],
                    "Pin Policy": row["pin_policy"],
                    "Import Status": row["import_status"],
                    "Recommended Action": row["recommended_action"],
                    "Notes": row["notes"],
                }
            )


def write_footprint_assignments_csv(path: Path, rows: list[JsonDict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["Reference", "Footprint", "LineId", "Import Status"])
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "Reference": row["reference"],
                    "Footprint": row["footprint"],
                    "LineId": row["line_id"],
                    "Import Status": row["import_status"],
                }
            )


def write_generated_symbol_library(
    path: Path,
    symbols: list[tuple[str, list[PinDefinition], BomLine]],
) -> None:
    lines = [
        "(kicad_symbol_lib",
        '  (version 20231120)',
        '  (generator "digikey_search_tools")',
    ]
    for symbol_name, pins, line in symbols:
        lines.extend(kicad_symbol_block(symbol_name, pins, line))
    lines.append(")")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def kicad_symbol_block(symbol_name: str, pins: list[PinDefinition], line: BomLine) -> list[str]:
    reference = reference_prefix(line.row.get("Reference Designator", "")) or "U"
    value = line.row.get("Value") or line.row.get("Manufacturer Part Number") or symbol_name
    rows = max((len(pins) + 1) // 2, 2)
    height = max(rows * 2.54, 7.62)
    top = round(height / 2, 2)
    bottom = -top
    block = [
        f'  (symbol "{escape_kicad(symbol_name)}"',
        '    (pin_names (offset 0.508))',
        '    (in_bom yes)',
        '    (on_board yes)',
        f'    (property "Reference" "{escape_kicad(reference)}" (at 0 {top + 2.54:.2f} 0) (effects (font (size 1.27 1.27))))',
        f'    (property "Value" "{escape_kicad(value)}" (at 0 {bottom - 2.54:.2f} 0) (effects (font (size 1.27 1.27))))',
        '    (property "Footprint" "" (at 0 0 0) (effects (font (size 1.27 1.27)) hide))',
        '    (property "Datasheet" "" (at 0 0 0) (effects (font (size 1.27 1.27)) hide))',
        f'    (rectangle (start -5.08 {top:.2f}) (end 5.08 {bottom:.2f}) (stroke (width 0.254) (type default)) (fill (type background)))',
    ]
    for pin in positioned_pins(pins):
        block.append(kicad_pin_line(pin))
    block.append("  )")
    return block


def positioned_pins(pins: list[PinDefinition]) -> list[JsonDict]:
    left = [pin for pin in pins if pin.side == "left"]
    right = [pin for pin in pins if pin.side == "right"]
    top = [pin for pin in pins if pin.side == "top"]
    bottom = [pin for pin in pins if pin.side == "bottom"]
    unspecified = [pin for pin in pins if pin.side not in {"left", "right", "top", "bottom"}]
    for index, pin in enumerate(unspecified):
        (left if index % 2 == 0 else right).append(pin)
    positioned = []
    positioned.extend(side_positions(left, side="left"))
    positioned.extend(side_positions(right, side="right"))
    positioned.extend(side_positions(top, side="top"))
    positioned.extend(side_positions(bottom, side="bottom"))
    return positioned


def side_positions(pins: list[PinDefinition], *, side: str) -> list[JsonDict]:
    positioned = []
    count = max(len(pins), 1)
    start = (count - 1) * 1.27
    for index, pin in enumerate(pins):
        offset = start - index * 2.54
        if side == "left":
            x, y, rotation = -7.62, offset, 0
        elif side == "right":
            x, y, rotation = 7.62, offset, 180
        elif side == "top":
            x, y, rotation = offset, 7.62, 270
        else:
            x, y, rotation = offset, -7.62, 90
        positioned.append(
            {
                "number": pin.number,
                "name": pin.name or pin.number,
                "pin_type": pin.pin_type,
                "x": x,
                "y": y,
                "rotation": rotation,
            }
        )
    return positioned


def kicad_pin_line(pin: JsonDict) -> str:
    return (
        f'    (pin {pin["pin_type"]} line '
        f'(at {pin["x"]:.2f} {pin["y"]:.2f} {pin["rotation"]}) '
        f'(length 2.54) '
        f'(name "{escape_kicad(str(pin["name"]))}" (effects (font (size 1.27 1.27)))) '
        f'(number "{escape_kicad(str(pin["number"]))}" (effects (font (size 1.27 1.27)))))'
    )


def write_kicad_report(path: Path, plan: JsonDict) -> None:
    rows = plan["rows"]
    blocked = [row for row in rows if row["import_status"] == "blocked"]
    lines = [
        "# KiCadライブラリ一括インポート計画",
        "",
        f"- 対象BOM行: {plan['summary']['rows']}",
        f"- 取り込み可能: {plan['summary']['ready']}",
        f"- 要確認: {plan['summary']['needs_review']}",
        f"- ブロック: {plan['summary']['blocked']}",
        f"- 生成シンボル: {plan['summary']['generated_symbols']}",
        "",
        "## ブロック中の明細",
        "",
        "| Reference | MPN | 理由 |",
        "| --- | --- | --- |",
    ]
    if blocked:
        for row in blocked:
            lines.append(
                f"| {row['reference']} | {row['manufacturer_part_number']} | {row['recommended_action']} |"
            )
    else:
        lines.append("| なし | なし | なし |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def update_sym_lib_table(
    kicad_project_dir: Path,
    *,
    library_nickname: str,
    library_path: Path,
) -> Path:
    kicad_project_dir.mkdir(parents=True, exist_ok=True)
    table_path = kicad_project_dir / "sym-lib-table"
    uri = library_uri_for_project(kicad_project_dir, library_path)
    entry = f'  (lib (name "{escape_kicad(library_nickname)}")(type "KiCad")(uri "{escape_kicad(uri)}")(options "")(descr "Generated by digikey_search_tools"))'
    if not table_path.exists():
        table_path.write_text(f"(sym_lib_table\n{entry}\n)\n", encoding="utf-8")
        return table_path
    text = table_path.read_text(encoding="utf-8")
    if f'(name "{library_nickname}")' in text:
        return table_path
    insert_at = text.rfind(")")
    if insert_at == -1:
        table_path.write_text(f"(sym_lib_table\n{entry}\n)\n", encoding="utf-8")
    else:
        updated = text[:insert_at].rstrip() + "\n" + entry + "\n" + text[insert_at:]
        table_path.write_text(updated, encoding="utf-8")
    return table_path


def library_uri_for_project(kicad_project_dir: Path, library_path: Path) -> str:
    try:
        relative = library_path.resolve().relative_to(kicad_project_dir.resolve())
        return "${KIPRJMOD}/" + relative.as_posix()
    except ValueError:
        return str(library_path.resolve())


def reference_prefix(reference: str) -> str:
    match = re.match(r"[A-Za-z]+", str(reference).strip())
    return match.group(0).upper() if match else ""


def generated_symbol_name(line: BomLine) -> str:
    base = first_nonempty(
        line.row.get("Manufacturer Part Number"),
        line.row.get("Digi-Key Part Number"),
        line.line_id,
    )
    return "DKTOOLS_" + safe_identifier(base or line.line_id)


def safe_identifier(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", value.strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned[:80] or "PART"


def normalize_pin_type(value: str | None) -> str:
    key = str(value or "").strip().lower()
    return PIN_TYPE_MAP.get(key, "passive")


def first_nonempty(*values: object) -> str | None:
    for value in values:
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def escape_kicad(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
