from __future__ import annotations

import csv
import json
import uuid
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterable

from .api import DigikeyClient
from .config import AppConfig
from .errors import BomError, ToolError
from .normalize import normalize_product_details
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
    lines = read_bom(path)
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
                    "source_csv": str(path),
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
            "csv_path": str(path),
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


def parse_assignment(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise BomError(f"assignment must be FIELD=VALUE: {value}")
    field, expected = value.split("=", 1)
    field = field.strip()
    if field not in BOM_COLUMNS:
        raise BomError(f"unknown BOM column: {field}")
    return field, expected


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
