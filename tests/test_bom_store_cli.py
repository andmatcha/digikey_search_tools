from __future__ import annotations

import csv
import sqlite3
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

from digikey_tools.bom import (
    BomDatabase,
    add_line,
    export_digikey_upload,
    read_bom,
    remove_lines,
    update_lines,
)
from digikey_tools.cli import build_keyword_filters
from digikey_tools.project import init_project, write_empty_bom
from digikey_tools.store import PartStore
from test_normalize import sample_config


class BomStoreCliTest(unittest.TestCase):
    def test_bom_database_keeps_rows_by_project_name_and_writes_csv_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            project_a = init_project(root / "board_a", sample_config())
            project_b = init_project(root / "board_b", sample_config())
            db_path = root / "shared.sqlite3"
            bom_db = BomDatabase(db_path)

            added_a = bom_db.add_line(
                project_a,
                {
                    "Reference Designator": "U1",
                    "Quantity": "2",
                    "Manufacturer Part Number": "TPS40210DGQR",
                },
            )
            bom_db.add_line(
                project_b,
                {
                    "Reference Designator": "U2",
                    "Quantity": "1",
                    "Manufacturer Part Number": "SN74HC595N",
                },
            )

            lines_a = bom_db.list_lines(project_a)
            lines_b = bom_db.list_lines(project_b)

            self.assertEqual(len(lines_a), 1)
            self.assertEqual(len(lines_b), 1)
            self.assertEqual(lines_a[0].row["LineId"], added_a["added"]["LineId"])
            self.assertEqual(lines_a[0].row["Manufacturer Part Number"], "TPS40210DGQR")
            self.assertEqual(lines_b[0].row["Manufacturer Part Number"], "SN74HC595N")
            self.assertEqual(read_bom(project_a.bom_path)[0].row["Manufacturer Part Number"], "TPS40210DGQR")

    def test_bom_add_update_remove_and_export(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            bom_path = Path(tmpdir) / "bom.csv"
            upload_path = Path(tmpdir) / "digikey_upload.csv"
            write_empty_bom(bom_path)

            added = add_line(
                bom_path,
                {
                    "Reference Designator": "U1",
                    "Quantity": "2",
                    "Manufacturer": "Texas Instruments",
                    "Manufacturer Part Number": "TPS40210DGQR",
                    "Notes": "boost",
                },
            )
            line_id = added["added"]["LineId"]
            self.assertEqual(len(read_bom(bom_path)), 1)

            updated = update_lines(
                bom_path,
                f"LineId={line_id}",
                ["Digi-Key Part Number=296-26969-1-ND", "Quantity=3"],
            )
            self.assertEqual(updated["updated"][0]["Quantity"], "3")

            exported = export_digikey_upload(bom_path, upload_path)
            self.assertEqual(exported["rows"], 1)
            with upload_path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["Digi-Key Part Number"], "296-26969-1-ND")
            self.assertEqual(rows[0]["Quantity"], "3")

            removed = remove_lines(bom_path, f"LineId={line_id}")
            self.assertEqual(removed["rows"], 0)

    def test_store_upserts_and_lists_parts(self) -> None:
        normalized = {
            "ok": True,
            "fetched_at": "2026-06-22T00:00:00Z",
            "source": {"currency": "JPY"},
            "product": {
                "manufacturer": {"name": "Texas Instruments"},
                "manufacturer_part_number": "TPS40210DGQR",
                "description": "Boost controller",
                "status": "Active",
                "status_id": 1,
                "status_flags": {
                    "normally_stocking": True,
                    "discontinued": False,
                    "end_of_life": False,
                    "back_order_not_allowed": False,
                    "non_cancelable_non_returnable": False,
                },
                "availability": {
                    "active": True,
                    "immediate": True,
                },
                "category": {"id": 1234, "name": "PMIC"},
                "compliance": {"rohs_status": "ROHS3 Compliant"},
                "quantity_available": 25,
                "product_url": "https://example.com/product",
                "datasheet_url": "https://example.com/datasheet.pdf",
                "parameters": [{"name": "Voltage - Supply", "value": "4.5V ~ 52V"}],
                "parameter_map": {"Voltage - Supply": "4.5V ~ 52V"},
                "variations": [
                    {
                        "digikey_product_number": "296-26969-1-ND",
                        "marketplace": False,
                    }
                ],
                "best_offer": {
                    "digikey_product_number": "296-26969-1-ND",
                    "unit_price": 346.0,
                    "estimated_total_price": 692.0,
                    "purchase_quantity": 2,
                    "package_type": "Cut Tape",
                    "pricing_type": "standard",
                    "in_stock_enough": True,
                    "quantity_available": 25,
                },
            },
            "warnings": [],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            store = PartStore(Path(tmpdir) / "parts.sqlite3", Path(tmpdir) / "raw")
            key = store.upsert_product(normalized, {"Product": {"test": True}})
            records = store.list_parts()
            part = store.get_part("TPS40210DGQR")
            datasheet = store.datasheet_for("296-26969-1-ND")
            exported = store.export_json()
        self.assertEqual(key, "296-26969-1-ND")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].manufacturer_part_number, "TPS40210DGQR")
        self.assertTrue(records[0].active)
        self.assertTrue(records[0].immediate)
        self.assertEqual(records[0].estimated_total_price, 692.0)
        self.assertEqual(records[0].purchase_quantity, 2)
        self.assertEqual(records[0].package_type, "Cut Tape")
        self.assertEqual(records[0].rohs_status, "ROHS3 Compliant")
        self.assertEqual(records[0].datasheet_url, "https://example.com/datasheet.pdf")
        self.assertEqual(part["category_name"], "PMIC")
        self.assertEqual(part["parameter_map"]["Voltage - Supply"], "4.5V ~ 52V")
        self.assertEqual(datasheet["datasheet_url"], "https://example.com/datasheet.pdf")
        self.assertEqual(len(exported["parts"]), 1)

    def test_store_migrates_existing_parts_table(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "parts.sqlite3"
            with sqlite3.connect(db_path) as connection:
                connection.execute(
                    """
                    CREATE TABLE parts (
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
            store = PartStore(db_path, Path(tmpdir) / "raw")
            with sqlite3.connect(db_path) as connection:
                columns = {
                    row[1]
                    for row in connection.execute("PRAGMA table_info(parts)").fetchall()
                }
        self.assertIn("rohs_status", columns)
        self.assertIn("best_offer_json", columns)
        self.assertIn("datasheet_url", columns)

    def test_keyword_filter_builder_maps_common_options(self) -> None:
        args = Namespace(
            manufacturer_id=["123"],
            category_id=["456"],
            status_id=[],
            packaging_id=[],
            series_id=[],
            exclude_marketplace=True,
            marketplace_only=False,
            exclude_tariff=False,
            tariff_only=False,
            min_qty=10,
            in_stock=True,
            normally_stocking=True,
            rohs=True,
            non_rohs=False,
            has_datasheet=True,
            has_photo=False,
            has_3d_model=False,
            new_products=False,
            param_category_id="789",
            param=["111=abc"],
        )
        filters = build_keyword_filters(args)
        self.assertEqual(filters["ManufacturerFilter"], [{"Id": "123"}])
        self.assertEqual(filters["CategoryFilter"], [{"Id": "456"}])
        self.assertEqual(filters["MarketPlaceFilter"], "ExcludeMarketPlace")
        self.assertEqual(filters["MinimumQuantityAvailable"], 10)
        self.assertIn("RohsCompliant", filters["SearchOptions"])
        self.assertEqual(
            filters["ParameterFilterRequest"]["ParameterFilters"],
            [{"ParameterId": 111, "FilterValues": [{"Id": "abc"}]}],
        )


if __name__ == "__main__":
    unittest.main()
