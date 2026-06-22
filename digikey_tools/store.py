from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from .errors import StoreError
from .normalize import utc_now_iso


JsonDict = dict[str, Any]


@dataclass
class PartRecord:
    product_key: str
    digikey_product_number: str | None
    manufacturer_part_number: str | None
    manufacturer: str | None
    description: str | None
    category_name: str | None
    status: str | None
    active: bool | None
    immediate: bool | None
    quantity_available: int | None
    unit_price: float | None
    estimated_total_price: float | None
    currency: str | None
    purchase_quantity: int | None
    package_type: str | None
    marketplace: bool | None
    rohs_status: str | None
    datasheet_url: str | None
    product_url: str | None
    fetched_at: str

    def to_json(self) -> JsonDict:
        return {
            "product_key": self.product_key,
            "digikey_product_number": self.digikey_product_number,
            "manufacturer_part_number": self.manufacturer_part_number,
            "manufacturer": self.manufacturer,
            "description": self.description,
            "category_name": self.category_name,
            "status": self.status,
            "active": self.active,
            "immediate": self.immediate,
            "quantity_available": self.quantity_available,
            "unit_price": self.unit_price,
            "estimated_total_price": self.estimated_total_price,
            "currency": self.currency,
            "purchase_quantity": self.purchase_quantity,
            "package_type": self.package_type,
            "marketplace": self.marketplace,
            "rohs_status": self.rohs_status,
            "datasheet_url": self.datasheet_url,
            "product_url": self.product_url,
            "fetched_at": self.fetched_at,
        }


class PartStore:
    def __init__(self, db_path: Path, raw_dir: Path) -> None:
        self.db_path = db_path
        self.raw_dir = raw_dir
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.raw_dir.mkdir(parents=True, exist_ok=True)
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
                CREATE TABLE IF NOT EXISTS parts (
                    product_key TEXT PRIMARY KEY,
                    digikey_product_number TEXT,
                    manufacturer_part_number TEXT,
                    manufacturer TEXT,
                    description TEXT,
                    status TEXT,
                    quantity_available INTEGER,
                    unit_price REAL,
                    estimated_total_price REAL,
                    currency TEXT,
                    product_url TEXT,
                    datasheet_url TEXT,
                    fetched_at TEXT NOT NULL,
                    normalized_json TEXT NOT NULL,
                    raw_json_path TEXT
                )
                """
            )
            self._ensure_parts_columns(connection)
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS queries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    query_type TEXT NOT NULL,
                    query_text TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    result_json TEXT NOT NULL
                )
                """
            )

    def _ensure_parts_columns(self, connection: sqlite3.Connection) -> None:
        existing = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(parts)").fetchall()
        }
        columns = {
            "status_id": "INTEGER",
            "active": "INTEGER",
            "immediate": "INTEGER",
            "normally_stocking": "INTEGER",
            "discontinued": "INTEGER",
            "end_of_life": "INTEGER",
            "back_order_not_allowed": "INTEGER",
            "ncnr": "INTEGER",
            "rohs_status": "TEXT",
            "reach_status": "TEXT",
            "moisture_sensitivity_level": "TEXT",
            "category_id": "INTEGER",
            "category_name": "TEXT",
            "series_name": "TEXT",
            "photo_url": "TEXT",
            "purchase_quantity": "INTEGER",
            "break_quantity": "INTEGER",
            "package_type": "TEXT",
            "pricing_type": "TEXT",
            "best_offer_in_stock": "INTEGER",
            "best_offer_quantity_available": "INTEGER",
            "marketplace": "INTEGER",
            "score": "INTEGER",
            "best_offer_json": "TEXT",
            "parameters_json": "TEXT",
            "parameter_map_json": "TEXT",
            "variations_json": "TEXT",
            "warnings_json": "TEXT",
            "last_api_query_json": "TEXT",
        }
        for name, column_type in columns.items():
            if name not in existing:
                connection.execute(f"ALTER TABLE parts ADD COLUMN {name} {column_type}")

    def upsert_product(self, normalized: JsonDict, raw: JsonDict | None = None) -> str:
        product = normalized.get("product") if isinstance(normalized.get("product"), dict) else normalized
        if not isinstance(product, dict):
            raise StoreError("normalized product payload is invalid.")
        best = product.get("best_offer") or {}
        manufacturer = product.get("manufacturer") or {}
        category = product.get("category") or {}
        compliance = product.get("compliance") or {}
        availability = product.get("availability") or {}
        status_flags = product.get("status_flags") or {}
        selected_variation = selected_variation_for_product(product)
        product_key = first_nonempty(
            best.get("digikey_product_number"),
            product.get("manufacturer_part_number"),
            product.get("product_url"),
        )
        if not product_key:
            raise StoreError("product does not include a usable product key.")
        fetched_at = str(normalized.get("fetched_at") or utc_now_iso())
        raw_path = self._write_raw(product_key, raw) if raw is not None else None
        source = normalized.get("source") or {}
        query = normalized.get("query") or {}
        warnings = normalized.get("warnings") or []
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO parts (
                    product_key,
                    digikey_product_number,
                    manufacturer_part_number,
                    manufacturer,
                    description,
                    status,
                    quantity_available,
                    unit_price,
                    estimated_total_price,
                    currency,
                    product_url,
                    datasheet_url,
                    fetched_at,
                    normalized_json,
                    raw_json_path,
                    status_id,
                    active,
                    immediate,
                    normally_stocking,
                    discontinued,
                    end_of_life,
                    back_order_not_allowed,
                    ncnr,
                    rohs_status,
                    reach_status,
                    moisture_sensitivity_level,
                    category_id,
                    category_name,
                    series_name,
                    photo_url,
                    purchase_quantity,
                    break_quantity,
                    package_type,
                    pricing_type,
                    best_offer_in_stock,
                    best_offer_quantity_available,
                    marketplace,
                    score,
                    best_offer_json,
                    parameters_json,
                    parameter_map_json,
                    variations_json,
                    warnings_json,
                    last_api_query_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(product_key) DO UPDATE SET
                    digikey_product_number = excluded.digikey_product_number,
                    manufacturer_part_number = excluded.manufacturer_part_number,
                    manufacturer = excluded.manufacturer,
                    description = excluded.description,
                    status = excluded.status,
                    quantity_available = excluded.quantity_available,
                    unit_price = excluded.unit_price,
                    estimated_total_price = excluded.estimated_total_price,
                    currency = excluded.currency,
                    product_url = excluded.product_url,
                    datasheet_url = excluded.datasheet_url,
                    fetched_at = excluded.fetched_at,
                    normalized_json = excluded.normalized_json,
                    raw_json_path = COALESCE(excluded.raw_json_path, parts.raw_json_path),
                    status_id = excluded.status_id,
                    active = excluded.active,
                    immediate = excluded.immediate,
                    normally_stocking = excluded.normally_stocking,
                    discontinued = excluded.discontinued,
                    end_of_life = excluded.end_of_life,
                    back_order_not_allowed = excluded.back_order_not_allowed,
                    ncnr = excluded.ncnr,
                    rohs_status = excluded.rohs_status,
                    reach_status = excluded.reach_status,
                    moisture_sensitivity_level = excluded.moisture_sensitivity_level,
                    category_id = excluded.category_id,
                    category_name = excluded.category_name,
                    series_name = excluded.series_name,
                    photo_url = excluded.photo_url,
                    purchase_quantity = excluded.purchase_quantity,
                    break_quantity = excluded.break_quantity,
                    package_type = excluded.package_type,
                    pricing_type = excluded.pricing_type,
                    best_offer_in_stock = excluded.best_offer_in_stock,
                    best_offer_quantity_available = excluded.best_offer_quantity_available,
                    marketplace = excluded.marketplace,
                    score = excluded.score,
                    best_offer_json = excluded.best_offer_json,
                    parameters_json = excluded.parameters_json,
                    parameter_map_json = excluded.parameter_map_json,
                    variations_json = excluded.variations_json,
                    warnings_json = excluded.warnings_json,
                    last_api_query_json = excluded.last_api_query_json
                """,
                (
                    product_key,
                    best.get("digikey_product_number"),
                    product.get("manufacturer_part_number"),
                    manufacturer.get("name") if isinstance(manufacturer, dict) else None,
                    product.get("description"),
                    product.get("status"),
                    product.get("quantity_available"),
                    best.get("unit_price"),
                    best.get("estimated_total_price"),
                    source.get("currency"),
                    product.get("product_url"),
                    product.get("datasheet_url"),
                    fetched_at,
                    json.dumps(normalized, ensure_ascii=False),
                    str(raw_path) if raw_path else None,
                    product.get("status_id"),
                    bool_to_int(availability.get("active")),
                    bool_to_int(availability.get("immediate")),
                    bool_to_int(status_flags.get("normally_stocking")),
                    bool_to_int(status_flags.get("discontinued")),
                    bool_to_int(status_flags.get("end_of_life")),
                    bool_to_int(status_flags.get("back_order_not_allowed")),
                    bool_to_int(status_flags.get("non_cancelable_non_returnable")),
                    compliance.get("rohs_status"),
                    compliance.get("reach_status"),
                    compliance.get("moisture_sensitivity_level"),
                    category.get("id") if isinstance(category, dict) else None,
                    category.get("name") if isinstance(category, dict) else None,
                    (product.get("series") or {}).get("name")
                    if isinstance(product.get("series"), dict)
                    else None,
                    product.get("photo_url"),
                    best.get("purchase_quantity"),
                    best.get("break_quantity"),
                    best.get("package_type"),
                    best.get("pricing_type"),
                    bool_to_int(best.get("in_stock_enough")),
                    best.get("quantity_available"),
                    bool_to_int(selected_variation.get("marketplace")) if selected_variation else None,
                    product.get("score"),
                    json.dumps(best, ensure_ascii=False),
                    json.dumps(product.get("parameters") or [], ensure_ascii=False),
                    json.dumps(product.get("parameter_map") or {}, ensure_ascii=False),
                    json.dumps(product.get("variations") or [], ensure_ascii=False),
                    json.dumps(warnings, ensure_ascii=False),
                    json.dumps(query, ensure_ascii=False),
                ),
            )
        return product_key

    def save_query(self, query_type: str, query_text: str, result: JsonDict) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO queries (query_type, query_text, fetched_at, result_json)
                VALUES (?, ?, ?, ?)
                """,
                (
                    query_type,
                    query_text,
                    str(result.get("fetched_at") or utc_now_iso()),
                    json.dumps(result, ensure_ascii=False),
                ),
            )
            return int(cursor.lastrowid)

    def list_parts(
        self,
        *,
        status: str | None = None,
        active_only: bool = False,
        missing_datasheet: bool = False,
    ) -> list[PartRecord]:
        where: list[str] = []
        params: list[object] = []
        if status:
            where.append("LOWER(status) = LOWER(?)")
            params.append(status)
        if active_only:
            where.append("active = 1")
        if missing_datasheet:
            where.append("(datasheet_url IS NULL OR datasheet_url = '')")
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT product_key, digikey_product_number, manufacturer_part_number,
                       manufacturer, description, category_name, status, active,
                       immediate, quantity_available, unit_price,
                       estimated_total_price, currency, purchase_quantity,
                       package_type, marketplace, rohs_status, datasheet_url,
                       product_url, fetched_at
                FROM parts
                {where_sql}
                ORDER BY manufacturer, manufacturer_part_number, product_key
                """,
                params,
            ).fetchall()
        return [
            PartRecord(
                product_key=row["product_key"],
                digikey_product_number=row["digikey_product_number"],
                manufacturer_part_number=row["manufacturer_part_number"],
                manufacturer=row["manufacturer"],
                description=row["description"],
                category_name=row["category_name"],
                status=row["status"],
                active=bool_or_none(row["active"]),
                immediate=bool_or_none(row["immediate"]),
                quantity_available=row["quantity_available"],
                unit_price=row["unit_price"],
                estimated_total_price=row["estimated_total_price"],
                currency=row["currency"],
                purchase_quantity=row["purchase_quantity"],
                package_type=row["package_type"],
                marketplace=bool_or_none(row["marketplace"]),
                rohs_status=row["rohs_status"],
                datasheet_url=row["datasheet_url"],
                product_url=row["product_url"],
                fetched_at=row["fetched_at"],
            )
            for row in rows
        ]

    def get_part(self, identifier: str) -> JsonDict | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM parts
                WHERE product_key = ?
                   OR digikey_product_number = ?
                   OR manufacturer_part_number = ?
                ORDER BY fetched_at DESC
                LIMIT 1
                """,
                (identifier, identifier, identifier),
            ).fetchone()
        return part_row_to_json(row) if row else None

    def datasheet_for(self, identifier: str) -> JsonDict | None:
        part = self.get_part(identifier)
        if not part:
            return None
        return {
            "product_key": part.get("product_key"),
            "digikey_product_number": part.get("digikey_product_number"),
            "manufacturer_part_number": part.get("manufacturer_part_number"),
            "manufacturer": part.get("manufacturer"),
            "description": part.get("description"),
            "datasheet_url": part.get("datasheet_url"),
            "product_url": part.get("product_url"),
            "raw_json_path": part.get("raw_json_path"),
            "fetched_at": part.get("fetched_at"),
        }

    def saved_product_numbers(self) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT COALESCE(digikey_product_number, manufacturer_part_number, product_key) AS pn
                FROM parts
                ORDER BY fetched_at DESC
                """
            ).fetchall()
        return [str(row["pn"]) for row in rows if row["pn"]]

    def export_json(self) -> JsonDict:
        with self._connect() as connection:
            parts = [
                json.loads(row["normalized_json"])
                for row in connection.execute("SELECT normalized_json FROM parts ORDER BY product_key")
            ]
            queries = [
                {
                    "id": row["id"],
                    "query_type": row["query_type"],
                    "query_text": row["query_text"],
                    "fetched_at": row["fetched_at"],
                    "result": json.loads(row["result_json"]),
                }
                for row in connection.execute(
                    "SELECT id, query_type, query_text, fetched_at, result_json FROM queries ORDER BY id"
                )
            ]
        return {
            "parts": parts,
            "queries": queries,
        }

    def _write_raw(self, product_key: str, raw: JsonDict) -> Path:
        filename = f"{safe_filename(product_key)}.json"
        path = self.raw_dir / filename
        path.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path


def first_nonempty(*values: object) -> str | None:
    for value in values:
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return cleaned[:120] or "part"


def bool_to_int(value: Any) -> int | None:
    if value is None:
        return None
    return 1 if bool(value) else 0


def bool_or_none(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(value)


def selected_variation_for_product(product: JsonDict) -> JsonDict | None:
    best = product.get("best_offer") or {}
    selected_number = best.get("digikey_product_number")
    for variation in product.get("variations") or []:
        if variation.get("digikey_product_number") == selected_number:
            return variation
    return None


def part_row_to_json(row: sqlite3.Row) -> JsonDict:
    result = {key: row[key] for key in row.keys()}
    for key in [
        "active",
        "immediate",
        "normally_stocking",
        "discontinued",
        "end_of_life",
        "back_order_not_allowed",
        "ncnr",
        "best_offer_in_stock",
        "marketplace",
    ]:
        result[key] = bool_or_none(result.get(key))
    for key in [
        "best_offer_json",
        "parameters_json",
        "parameter_map_json",
        "variations_json",
        "warnings_json",
        "last_api_query_json",
        "normalized_json",
    ]:
        value = result.get(key)
        if isinstance(value, str) and value:
            try:
                result[key.removesuffix("_json")] = json.loads(value)
            except json.JSONDecodeError:
                result[key.removesuffix("_json")] = value
    return result
