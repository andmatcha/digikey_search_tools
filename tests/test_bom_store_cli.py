from __future__ import annotations

import csv
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

from digikey_tools.bom import add_line, export_digikey_upload, read_bom, remove_lines, update_lines
from digikey_tools.cli import build_keyword_filters
from digikey_tools.project import write_empty_bom
from digikey_tools.store import PartStore


class BomStoreCliTest(unittest.TestCase):
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
                "quantity_available": 25,
                "product_url": "https://example.com/product",
                "datasheet_url": "https://example.com/datasheet.pdf",
                "best_offer": {
                    "digikey_product_number": "296-26969-1-ND",
                    "unit_price": 346.0,
                    "estimated_total_price": 692.0,
                },
            },
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            store = PartStore(Path(tmpdir) / "parts.sqlite3", Path(tmpdir) / "raw")
            key = store.upsert_product(normalized, {"Product": {"test": True}})
            records = store.list_parts()
            exported = store.export_json()
        self.assertEqual(key, "296-26969-1-ND")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].manufacturer_part_number, "TPS40210DGQR")
        self.assertEqual(len(exported["parts"]), 1)

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
