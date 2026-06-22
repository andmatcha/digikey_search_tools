from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import StoreError
from .normalize import utc_now_iso


JsonDict = dict[str, Any]


@dataclass
class PartRecord:
    product_key: str
    digikey_product_number: str | None
    manufacturer_part_number: str | None
    manufacturer: str | None
    status: str | None
    quantity_available: int | None
    unit_price: float | None
    currency: str | None
    fetched_at: str

    def to_json(self) -> JsonDict:
        return {
            "product_key": self.product_key,
            "digikey_product_number": self.digikey_product_number,
            "manufacturer_part_number": self.manufacturer_part_number,
            "manufacturer": self.manufacturer,
            "status": self.status,
            "quantity_available": self.quantity_available,
            "unit_price": self.unit_price,
            "currency": self.currency,
            "fetched_at": self.fetched_at,
        }


class PartStore:
    def __init__(self, db_path: Path, raw_dir: Path) -> None:
        self.db_path = db_path
        self.raw_dir = raw_dir
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

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

    def upsert_product(self, normalized: JsonDict, raw: JsonDict | None = None) -> str:
        product = normalized.get("product") if isinstance(normalized.get("product"), dict) else normalized
        if not isinstance(product, dict):
            raise StoreError("normalized product payload is invalid.")
        best = product.get("best_offer") or {}
        manufacturer = product.get("manufacturer") or {}
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
                    raw_json_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    raw_json_path = COALESCE(excluded.raw_json_path, parts.raw_json_path)
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

    def list_parts(self) -> list[PartRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT product_key, digikey_product_number, manufacturer_part_number,
                       manufacturer, status, quantity_available, unit_price,
                       currency, fetched_at
                FROM parts
                ORDER BY manufacturer, manufacturer_part_number, product_key
                """
            ).fetchall()
        return [
            PartRecord(
                product_key=row["product_key"],
                digikey_product_number=row["digikey_product_number"],
                manufacturer_part_number=row["manufacturer_part_number"],
                manufacturer=row["manufacturer"],
                status=row["status"],
                quantity_available=row["quantity_available"],
                unit_price=row["unit_price"],
                currency=row["currency"],
                fetched_at=row["fetched_at"],
            )
            for row in rows
        ]

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
