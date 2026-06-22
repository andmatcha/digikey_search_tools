from __future__ import annotations

import csv
import json
import sqlite3
import uuid
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterable, Iterator

from .api import DigikeyClient
from .config import AppConfig
from .errors import BomError, ToolError
from .normalize import normalize_product_details, utc_now_iso
from .project import BOM_COLUMNS, ProjectContext, write_empty_bom
from .store import PartStore


JsonDict = dict[str, Any]
MONEY = Decimal("0.01")
DIGIKEY_UPLOAD_COLUMNS = [
    "Digi-Key Part Number",
    "Manufacturer Part Number",
    "Quantity",
    "Customer Reference",
]

BOM_DB_FIELDS = {
    "LineId": "line_id",
    "Reference Designator": "reference_designator",
    "Quantity": "quantity",
    "Digi-Key Part Number": "digikey_part_number",
    "Manufacturer": "manufacturer",
    "Manufacturer Part Number": "manufacturer_part_number",
    "Value": "value",
    "Footprint": "footprint",
    "Description": "description",
    "Purpose": "purpose",
    "DNP": "dnp",
    "Notes": "notes",
}


@dataclass(frozen=True)
class BomLine:
    line_number: int
    row: dict[str, str]

    @property
    def line_id(self) -> str:
        return self.row.get("LineId", "")

    @property
    def quantity(self) -> int:
        return parse_quantity(self.row.get("Quantity"))

    @property
    def product_number(self) -> str | None:
        return first_nonempty(
            self.row.get("Digi-Key Part Number"),
            self.row.get("Manufacturer Part Number"),
        )

    @property
    def dnp(self) -> bool:
        return str(self.row.get("DNP") or "").strip().lower() in {"1", "true", "yes", "y", "dnp"}


class BomDatabase:
    """SQLite-backed BOM store keyed by project_name."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _init_schema(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS bom_projects (
                    project_name TEXT PRIMARY KEY,
                    project_root TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS bom_items (
                    project_name TEXT NOT NULL,
                    line_id TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    reference_designator TEXT NOT NULL DEFAULT '',
                    quantity INTEGER NOT NULL DEFAULT 1,
                    digikey_part_number TEXT NOT NULL DEFAULT '',
                    manufacturer TEXT NOT NULL DEFAULT '',
                    manufacturer_part_number TEXT NOT NULL DEFAULT '',
                    value TEXT NOT NULL DEFAULT '',
                    footprint TEXT NOT NULL DEFAULT '',
                    description TEXT NOT NULL DEFAULT '',
                    purpose TEXT NOT NULL DEFAULT '',
                    dnp INTEGER NOT NULL DEFAULT 0,
                    notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (project_name, line_id),
                    FOREIGN KEY (project_name)
                        REFERENCES bom_projects(project_name)
                        ON DELETE CASCADE
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_bom_items_project_position
                ON bom_items(project_name, position, line_id)
                """
            )

    def ensure_project(self, project: ProjectContext) -> None:
        now = utc_now_iso()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO bom_projects (project_name, project_root, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(project_name) DO UPDATE SET
                    project_root = excluded.project_root,
                    updated_at = excluded.updated_at
                """,
                (project.project_name, str(project.root), now, now),
            )

    def import_csv_if_empty(self, project: ProjectContext) -> int:
        self.ensure_project(project)
        if self.count_lines(project.project_name) > 0 or not project.bom_path.exists():
            return 0
        lines = read_bom(project.bom_path)
        imported = 0
        for line in lines:
            if not any(value.strip() for value in line.row.values()):
                continue
            self._insert_line(project, line.row, write_snapshot=False)
            imported += 1
        if imported:
            self.write_csv_snapshot(project)
        return imported

    def count_lines(self, project_name: str) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM bom_items WHERE project_name = ?",
                (project_name,),
            ).fetchone()
        return int(row["count"])

    def list_lines(self, project: ProjectContext) -> list[BomLine]:
        self.import_csv_if_empty(project)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM bom_items
                WHERE project_name = ?
                ORDER BY position, line_id
                """,
                (project.project_name,),
            ).fetchall()
        return [
            BomLine(index, db_row_to_bom_row(row))
            for index, row in enumerate(rows, start=2)
        ]

    def add_line(self, project: ProjectContext, values: dict[str, str]) -> JsonDict:
        self.import_csv_if_empty(project)
        row = self._insert_line(project, values, write_snapshot=True)
        return {"added": row, "rows": self.count_lines(project.project_name)}

    def _insert_line(
        self,
        project: ProjectContext,
        values: dict[str, str],
        *,
        write_snapshot: bool,
    ) -> dict[str, str]:
        self.ensure_project(project)
        row = normalize_row({column: values.get(column, "") for column in BOM_COLUMNS})
        row["LineId"] = row.get("LineId") or uuid.uuid4().hex[:12]
        row["Quantity"] = str(parse_quantity(row.get("Quantity")))
        now = utc_now_iso()
        with self._connect() as connection:
            position_row = connection.execute(
                """
                SELECT COALESCE(MAX(position), 0) + 1 AS next_position
                FROM bom_items
                WHERE project_name = ?
                """,
                (project.project_name,),
            ).fetchone()
            position = int(position_row["next_position"])
            try:
                connection.execute(
                    """
                    INSERT INTO bom_items (
                        project_name,
                        line_id,
                        position,
                        reference_designator,
                        quantity,
                        digikey_part_number,
                        manufacturer,
                        manufacturer_part_number,
                        value,
                        footprint,
                        description,
                        purpose,
                        dnp,
                        notes,
                        created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    bom_row_to_db_values(project.project_name, row, position, now, now),
                )
            except sqlite3.IntegrityError as error:
                raise BomError(f"BOM line already exists: {row['LineId']}") from error
        if write_snapshot:
            self.write_csv_snapshot(project)
        return row

    def remove_lines(self, project: ProjectContext, match: str) -> JsonDict:
        self.import_csv_if_empty(project)
        field, expected = parse_assignment(match)
        db_field = BOM_DB_FIELDS[field]
        if field == "DNP":
            expected_value: object = 1 if is_dnp_text(expected) else 0
        elif field == "Quantity":
            expected_value = parse_quantity(expected)
        else:
            expected_value = expected
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT *
                FROM bom_items
                WHERE project_name = ? AND {db_field} = ?
                ORDER BY position, line_id
                """,
                (project.project_name, expected_value),
            ).fetchall()
            if not rows:
                raise BomError(f"no BOM rows matched {match}")
            connection.execute(
                f"DELETE FROM bom_items WHERE project_name = ? AND {db_field} = ?",
                (project.project_name, expected_value),
            )
        self.write_csv_snapshot(project)
        return {
            "removed": [db_row_to_bom_row(row) for row in rows],
            "rows": self.count_lines(project.project_name),
        }

    def update_lines(
        self,
        project: ProjectContext,
        match: str,
        assignments: list[str],
    ) -> JsonDict:
        self.import_csv_if_empty(project)
        field, expected = parse_assignment(match)
        match_db_field = BOM_DB_FIELDS[field]
        if field == "DNP":
            expected_value: object = 1 if is_dnp_text(expected) else 0
        elif field == "Quantity":
            expected_value = parse_quantity(expected)
        else:
            expected_value = expected
        updates = dict(parse_assignment(item) for item in assignments)
        for key in updates:
            if key not in BOM_COLUMNS:
                raise BomError(f"unknown BOM column: {key}")
        set_parts = []
        params: list[object] = []
        for key, value in updates.items():
            db_field = BOM_DB_FIELDS[key]
            set_parts.append(f"{db_field} = ?")
            if key == "DNP":
                params.append(1 if is_dnp_text(value) else 0)
            elif key == "Quantity":
                params.append(parse_quantity(value))
            else:
                params.append(value)
        set_parts.append("updated_at = ?")
        params.append(utc_now_iso())
        params.extend([project.project_name, expected_value])
        with self._connect() as connection:
            existing = connection.execute(
                f"""
                SELECT *
                FROM bom_items
                WHERE project_name = ? AND {match_db_field} = ?
                ORDER BY position, line_id
                """,
                (project.project_name, expected_value),
            ).fetchall()
            if not existing:
                raise BomError(f"no BOM rows matched {match}")
            connection.execute(
                f"""
                UPDATE bom_items
                SET {", ".join(set_parts)}
                WHERE project_name = ? AND {match_db_field} = ?
                """,
                params,
            )
            changed = connection.execute(
                f"""
                SELECT *
                FROM bom_items
                WHERE project_name = ? AND {match_db_field} = ?
                ORDER BY position, line_id
                """,
                (project.project_name, expected_value),
            ).fetchall()
        self.write_csv_snapshot(project)
        return {
            "updated": [db_row_to_bom_row(row) for row in changed],
            "rows": self.count_lines(project.project_name),
        }

    def write_csv_snapshot(self, project: ProjectContext) -> None:
        lines = self.list_lines(project)
        write_bom(project.bom_path, [line.row for line in lines])

    def project_names(self) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT project_name FROM bom_projects ORDER BY project_name"
            ).fetchall()
        return [str(row["project_name"]) for row in rows]


def ensure_bom(path: Path) -> None:
    if not path.exists():
        write_empty_bom(path)


def read_bom(path: Path) -> list[BomLine]:
    ensure_bom(path)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        fieldnames = reader.fieldnames or []
    missing = [column for column in BOM_COLUMNS if column not in fieldnames]
    if missing:
        raise BomError(f"BOM is missing required columns: {', '.join(missing)}")
    return [BomLine(index, normalize_row(row)) for index, row in enumerate(rows, start=2)]


def write_bom(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=BOM_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in BOM_COLUMNS})


def add_line(path: Path, values: dict[str, str]) -> JsonDict:
    lines = read_bom(path)
    row = {column: values.get(column, "") for column in BOM_COLUMNS}
    row["LineId"] = row.get("LineId") or uuid.uuid4().hex[:12]
    row["Quantity"] = str(parse_quantity(row.get("Quantity")))
    rows = [line.row for line in lines] + [row]
    write_bom(path, rows)
    return {"added": row, "rows": len(rows)}


def remove_lines(path: Path, match: str) -> JsonDict:
    lines = read_bom(path)
    field, expected = parse_assignment(match)
    kept: list[dict[str, str]] = []
    removed: list[dict[str, str]] = []
    for line in lines:
        if str(line.row.get(field, "")) == expected:
            removed.append(line.row)
        else:
            kept.append(line.row)
    if not removed:
        raise BomError(f"no BOM rows matched {match}")
    write_bom(path, kept)
    return {"removed": removed, "rows": len(kept)}


def update_lines(path: Path, match: str, assignments: list[str]) -> JsonDict:
    lines = read_bom(path)
    field, expected = parse_assignment(match)
    updates = dict(parse_assignment(item) for item in assignments)
    for key in updates:
        if key not in BOM_COLUMNS:
            raise BomError(f"unknown BOM column: {key}")
    changed: list[dict[str, str]] = []
    rows: list[dict[str, str]] = []
    for line in lines:
        row = dict(line.row)
        if str(row.get(field, "")) == expected:
            row.update(updates)
            if "Quantity" in updates:
                row["Quantity"] = str(parse_quantity(row.get("Quantity")))
            changed.append(row)
        rows.append(row)
    if not changed:
        raise BomError(f"no BOM rows matched {match}")
    write_bom(path, rows)
    return {"updated": changed, "rows": len(rows)}


def export_digikey_upload(path: Path, output: Path, *, include_dnp: bool = False) -> JsonDict:
    lines = read_bom(path)
    return export_digikey_upload_lines(lines, output, include_dnp=include_dnp)


def export_digikey_upload_lines(
    lines: list[BomLine],
    output: Path,
    *,
    include_dnp: bool = False,
) -> JsonDict:
    output.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, str]] = []
    for line in lines:
        if line.dnp and not include_dnp:
            continue
        rows.append(
            {
                "Digi-Key Part Number": line.row.get("Digi-Key Part Number", ""),
                "Manufacturer Part Number": line.row.get("Manufacturer Part Number", ""),
                "Quantity": str(line.quantity),
                "Customer Reference": line.row.get("Reference Designator", ""),
            }
        )
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=DIGIKEY_UPLOAD_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return {"output": str(output), "rows": len(rows), "columns": DIGIKEY_UPLOAD_COLUMNS}


def price_bom(
    path: Path,
    *,
    client: DigikeyClient,
    config: AppConfig,
    project: ProjectContext,
    store: PartStore,
    include_dnp: bool = False,
    include_raw: bool = False,
) -> JsonDict:
    return price_bom_lines(
        read_bom(path),
        input_label=str(path),
        client=client,
        config=config,
        project=project,
        store=store,
        include_dnp=include_dnp,
        include_raw=include_raw,
    )


def price_bom_lines(
    lines: list[BomLine],
    *,
    input_label: str,
    client: DigikeyClient,
    config: AppConfig,
    project: ProjectContext,
    store: PartStore,
    include_dnp: bool = False,
    include_raw: bool = False,
) -> JsonDict:
    line_items: list[JsonDict] = []
    ok_count = 0
    total = Decimal("0.00")
    for line in lines:
        item: JsonDict = {
            "line": line.line_number,
            "source_row": line.row,
            "input": {
                "line_id": line.line_id,
                "product_number": line.product_number,
                "quantity": line.quantity,
                "reference": line.row.get("Reference Designator", ""),
                "dnp": line.dnp,
            },
        }
        if line.dnp and not include_dnp:
            item["ok"] = True
            item["skipped"] = True
            item["reason"] = "DNP"
            line_items.append(item)
            continue
        if not line.product_number:
            item["ok"] = False
            item["error"] = "No Digi-Key or manufacturer part number was found."
            line_items.append(item)
            continue
        try:
            raw, cache_hit = client.product_details(line.product_number)
            normalized = normalize_product_details(
                raw,
                query={
                    "product_number": line.product_number,
                    "requested_quantity": line.quantity,
                    "source": input_label,
                    "line": line.line_number,
                },
                config=config,
                requested_quantity=line.quantity,
                cache_hit=cache_hit,
                include_raw=include_raw,
            )
            product = normalized["product"]
            store.upsert_product(normalized, raw)
            best = product.get("best_offer") or {}
            total += decimal_money(best.get("estimated_total_price"))
            item.update(
                {
                    "ok": True,
                    "cache": normalized["cache"],
                    "product": product,
                    "warnings": normalized["warnings"],
                }
            )
            ok_count += 1
        except ToolError as error:
            item["ok"] = False
            item["error"] = {"type": error.__class__.__name__, "message": str(error)}
        line_items.append(item)

    return {
        "ok": all(item.get("ok") for item in line_items),
        "project": project.metadata(),
        "source": {
            "provider": "Digi-Key",
            "currency": config.currency,
            "environment": config.environment,
        },
        "input": {
            "source": input_label,
            "rows": len(lines),
            "include_dnp": include_dnp,
        },
        "summary": {
            "ok_count": ok_count,
            "error_count": len([item for item in line_items if item.get("ok") is False]),
            "skipped_count": len([item for item in line_items if item.get("skipped")]),
            "estimated_total_price": float(total),
            "currency": config.currency,
        },
        "line_items": line_items,
    }


def price_rows(result: JsonDict) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    currency = result.get("summary", {}).get("currency", "")
    for item in result.get("line_items", []):
        source = item.get("source_row") or {}
        product = item.get("product") or {}
        best = product.get("best_offer") or {}
        availability = product.get("availability") or {}
        rows.append(
            {
                "LineId": source.get("LineId", item.get("input", {}).get("line_id", "")),
                "Reference Designator": source.get("Reference Designator", ""),
                "Quantity": item.get("input", {}).get("quantity", ""),
                "Purchase Quantity": best.get("purchase_quantity", ""),
                "Digi-Key Part Number": best.get("digikey_product_number")
                or source.get("Digi-Key Part Number", ""),
                "Manufacturer": (product.get("manufacturer") or {}).get("name")
                or source.get("Manufacturer", ""),
                "Manufacturer Part Number": product.get("manufacturer_part_number")
                or source.get("Manufacturer Part Number", ""),
                "Description": product.get("description") or source.get("Description", ""),
                "Status": product.get("status", ""),
                "Immediate": bool_text(availability.get("immediate")),
                "Quantity Available": availability.get("quantity_available", ""),
                "Package Type": best.get("package_type", ""),
                f"Unit Price {currency}": money(best.get("unit_price")),
                f"Line Total {currency}": money(best.get("estimated_total_price")),
                "Product URL": product.get("product_url", ""),
                "Datasheet URL": product.get("datasheet_url", ""),
                "Skipped": bool_text(item.get("skipped")),
                "Warnings": "; ".join(item.get("warnings") or []),
                "Availability Reasons": "; ".join(availability.get("reasons") or []),
                "Notes": source.get("Notes", ""),
            }
        )
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else []
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_price_summary(path: Path, result: JsonDict, rows: list[dict[str, Any]]) -> None:
    currency = result.get("summary", {}).get("currency", "")
    total = decimal_money(result.get("summary", {}).get("estimated_total_price"))
    status_counts: dict[str, int] = defaultdict(int)
    for row in rows:
        status_counts[str(row.get("Status") or "Skipped")] += 1
    status_lines = "\n".join(f"- {status}: {count}" for status, count in sorted(status_counts.items()))
    warning_lines = "\n".join(
        f"| {row.get('Reference Designator')} | {row.get('Manufacturer Part Number')} | {row.get('Warnings') or row.get('Availability Reasons')} |"
        for row in rows
        if row.get("Warnings") or row.get("Availability Reasons")
    )
    if not warning_lines:
        warning_lines = "| なし | なし | なし |"
    text = f"""# Digi-Key BOM価格サマリ

| 項目 | 値 |
| --- | ---: |
| 対象明細数 | {result.get('input', {}).get('rows')} |
| 取得成功 | {result.get('summary', {}).get('ok_count')} |
| 取得失敗 | {result.get('summary', {}).get('error_count')} |
| DNPスキップ | {result.get('summary', {}).get('skipped_count')} |
| 合計 | {total:,.2f} {currency} |

## ステータス内訳

{status_lines}

## 注意事項

- 合計はDigi-Key APIが返した単価を元にした概算で、送料、税、手数料は含まない。
- `Purchase Quantity` は最小注文数量を反映した購入数量で、BOM上の数量と異なる場合がある。
- DNPは既定では集計から除外する。

## 警告・要確認

| Reference Designator | Manufacturer Part Number | 内容 |
| --- | --- | --- |
{warning_lines}
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def normalize_row(row: dict[str, str | None]) -> dict[str, str]:
    return {column: str(row.get(column) or "") for column in BOM_COLUMNS}


def db_row_to_bom_row(row: sqlite3.Row) -> dict[str, str]:
    return {
        "LineId": str(row["line_id"] or ""),
        "Reference Designator": str(row["reference_designator"] or ""),
        "Quantity": str(parse_quantity(str(row["quantity"]))),
        "Digi-Key Part Number": str(row["digikey_part_number"] or ""),
        "Manufacturer": str(row["manufacturer"] or ""),
        "Manufacturer Part Number": str(row["manufacturer_part_number"] or ""),
        "Value": str(row["value"] or ""),
        "Footprint": str(row["footprint"] or ""),
        "Description": str(row["description"] or ""),
        "Purpose": str(row["purpose"] or ""),
        "DNP": "yes" if bool(row["dnp"]) else "",
        "Notes": str(row["notes"] or ""),
    }


def bom_row_to_db_values(
    project_name: str,
    row: dict[str, str],
    position: int,
    created_at: str,
    updated_at: str,
) -> tuple[object, ...]:
    return (
        project_name,
        row["LineId"],
        position,
        row.get("Reference Designator", ""),
        parse_quantity(row.get("Quantity")),
        row.get("Digi-Key Part Number", ""),
        row.get("Manufacturer", ""),
        row.get("Manufacturer Part Number", ""),
        row.get("Value", ""),
        row.get("Footprint", ""),
        row.get("Description", ""),
        row.get("Purpose", ""),
        1 if is_dnp_text(row.get("DNP", "")) else 0,
        row.get("Notes", ""),
        created_at,
        updated_at,
    )


def parse_assignment(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise BomError(f"assignment must be FIELD=VALUE: {value}")
    field, expected = value.split("=", 1)
    field = field.strip()
    if field not in BOM_COLUMNS:
        raise BomError(f"unknown BOM column: {field}")
    return field, expected


def is_dnp_text(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "dnp"}


def parse_quantity(value: str | None) -> int:
    if value is None or not str(value).strip():
        return 1
    try:
        quantity = int(float(str(value).strip()))
    except ValueError:
        return 1
    return max(quantity, 1)


def first_nonempty(*values: str | None) -> str | None:
    for value in values:
        if value and str(value).strip():
            return str(value).strip()
    return None


def decimal_money(value: Any) -> Decimal:
    if value is None or value == "":
        return Decimal("0.00")
    return Decimal(str(value)).quantize(MONEY, rounding=ROUND_HALF_UP)


def money(value: Any) -> str:
    if value is None or value == "":
        return ""
    return f"{decimal_money(value):.2f}"


def bool_text(value: Any) -> str:
    return "yes" if bool(value) else "no"
