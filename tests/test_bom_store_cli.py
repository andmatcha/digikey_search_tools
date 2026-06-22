from __future__ import annotations

import csv
import sqlite3
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from digikey_tools.bom import (
    BomDatabase,
    add_line,
    export_digikey_upload,
    read_bom,
    remove_lines,
    update_lines,
)
from digikey_tools.cli import build_keyword_filters
from digikey_tools.kicad import (
    PinDefinition,
    decide_line_library,
    export_kicad_import_bundle,
    find_kicad_cli,
)
from digikey_tools.library import LibraryDatabase, digikey_model_hints_for_line
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

    def test_library_assessment_keeps_eda_readiness_by_bom_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            project = init_project(root / "board", sample_config())
            bom_db = BomDatabase(project.database_path)
            bom_db.add_line(
                project,
                {
                    "Reference Designator": "R1",
                    "Quantity": "1",
                    "Manufacturer Part Number": "RC0603FR-0710KL",
                    "Value": "10k",
                    "Footprint": "Resistor_SMD:R_0603_1608Metric",
                },
            )
            line = bom_db.list_lines(project)[0]

            assessment = LibraryDatabase(project.database_path).upsert_assessment(
                project,
                line,
                {
                    "kicad_symbol_status": "generic_ok",
                    "kicad_symbol_name": "Device:R",
                    "kicad_footprint_status": "generic_ok",
                    "kicad_3d_model_status": "generic_ok",
                    "external_library_status": "not_required",
                    "overall_status": "usable_with_generic",
                    "confidence": "high",
                    "notes": "0603 resistor can use generic KiCad assets.",
                },
                evidence={
                    "external_sources": [
                        {"provider": "KiCad official library", "url": "https://gitlab.com/kicad/libraries"}
                    ]
                },
            )
            rows = LibraryDatabase(project.database_path).list_project(project, [line])

        self.assertEqual(assessment["reference_designator"], "R1")
        self.assertEqual(assessment["kicad_symbol_name"], "Device:R")
        self.assertEqual(assessment["kicad_footprint_name"], "Resistor_SMD:R_0603_1608Metric")
        self.assertEqual(assessment["external_library_provider"], "KiCad official library")
        self.assertFalse(rows[0]["needs_action"])

    def test_library_digikey_model_hints_reads_saved_raw_payload(self) -> None:
        normalized = {
            "ok": True,
            "fetched_at": "2026-06-22T00:00:00Z",
            "source": {"currency": "JPY"},
            "product": {
                "manufacturer": {"name": "Example"},
                "manufacturer_part_number": "EXAMPLE-IC",
                "description": "Example IC",
                "status": "Active",
                "availability": {"active": True, "immediate": True},
                "quantity_available": 10,
                "variations": [
                    {
                        "digikey_product_number": "123-EXAMPLE-ND",
                        "marketplace": False,
                    }
                ],
                "best_offer": {
                    "digikey_product_number": "123-EXAMPLE-ND",
                    "unit_price": 100.0,
                    "estimated_total_price": 100.0,
                    "purchase_quantity": 1,
                    "package_type": "Cut Tape",
                    "in_stock_enough": True,
                    "quantity_available": 10,
                },
            },
            "warnings": [],
        }
        raw = {
            "Product": {
                "ManufacturerProductNumber": "EXAMPLE-IC",
                "EDAUrl": "https://example.com/example-ic-eda.zip",
                "Product3DModelUrl": "https://example.com/example-ic.step",
            }
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            project = init_project(root / "board", sample_config())
            bom_db = BomDatabase(project.database_path)
            bom_db.add_line(
                project,
                {
                    "Reference Designator": "U1",
                    "Quantity": "1",
                    "Digi-Key Part Number": "123-EXAMPLE-ND",
                    "Manufacturer Part Number": "EXAMPLE-IC",
                },
            )
            line = bom_db.list_lines(project)[0]
            store = PartStore(project.database_path, project.raw_dir)
            store.upsert_product(normalized, raw)

            hints = digikey_model_hints_for_line(store, line)

        self.assertTrue(hints["part_found"])
        self.assertEqual(hints["digikey_eda_status"], "available")
        self.assertEqual(hints["digikey_3d_model_status"], "available")
        self.assertEqual(hints["digikey_3d_model_url"], "https://example.com/example-ic.step")

    def test_kicad_decision_prefers_generic_passives_and_requires_ic_pin_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            project = init_project(root / "board", sample_config())
            bom_db = BomDatabase(project.database_path)
            bom_db.add_line(
                project,
                {
                    "Reference Designator": "R1",
                    "Quantity": "1",
                    "Manufacturer Part Number": "RC0603FR-0710KL",
                    "Value": "10k",
                    "Footprint": "Resistor_SMD:R_0603_1608Metric",
                },
            )
            bom_db.add_line(
                project,
                {
                    "Reference Designator": "U1",
                    "Quantity": "1",
                    "Manufacturer Part Number": "EXAMPLE-IC",
                    "Footprint": "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
                },
            )
            resistor, ic = bom_db.list_lines(project)

        resistor_decision = decide_line_library(resistor)
        ic_decision = decide_line_library(ic)
        self.assertEqual(resistor_decision["updates"]["kicad_symbol_name"], "Device:R")
        self.assertEqual(resistor_decision["updates"]["symbol_policy"], "kicad_generic_preferred")
        self.assertEqual(resistor_decision["updates"]["overall_status"], "usable_with_generic")
        self.assertEqual(ic_decision["updates"]["kicad_symbol_status"], "needs_custom")
        self.assertEqual(ic_decision["updates"]["kicad_footprint_status"], "generic_ok")
        self.assertEqual(ic_decision["updates"]["pin_policy"], "specific_pin_identity_required")
        self.assertEqual(ic_decision["updates"]["kicad_import_status"], "blocked")

    def test_kicad_export_bundle_writes_generated_symbol_and_project_table(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            project = init_project(root / "board", sample_config())
            bom_db = BomDatabase(project.database_path)
            bom_db.add_line(
                project,
                {
                    "Reference Designator": "U1",
                    "Quantity": "1",
                    "Manufacturer Part Number": "EXAMPLE-IC",
                    "Value": "EXAMPLE-IC",
                    "Footprint": "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
                },
            )
            line = bom_db.list_lines(project)[0]
            pin_map = {
                line.line_id: [
                    PinDefinition("1", "VIN", "power_in", "left"),
                    PinDefinition("2", "GND", "power_in", "left"),
                    PinDefinition("3", "SW", "output", "right"),
                    PinDefinition("4", "FB", "input", "right"),
                ]
            }
            library_db = LibraryDatabase(project.database_path)
            decision = decide_line_library(line, pin_map=pin_map)
            library_db.upsert_assessment(project, line, decision["updates"], evidence=decision["evidence"])
            output = export_kicad_import_bundle(
                project,
                [line],
                library_db=library_db,
                output_dir=project.root / "kicad_import",
                kicad_project_dir=project.root,
                pin_map=pin_map,
                library_nickname="dktools_generated",
                apply_to_project=True,
            )

            symbol_text = Path(output["generated_symbol_library"]).read_text(encoding="utf-8")
            with Path(output["symbol_fields_csv"]).open("r", encoding="utf-8", newline="") as handle:
                fields_rows = list(csv.DictReader(handle))
            table_text = (project.root / "sym-lib-table").read_text(encoding="utf-8")

        self.assertIn('symbol "DKTOOLS_EXAMPLE_IC"', symbol_text)
        self.assertIn('name "VIN"', symbol_text)
        self.assertEqual(fields_rows[0]["Import Status"], "ready")
        self.assertEqual(fields_rows[0]["Symbol"], "dktools_generated:DKTOOLS_EXAMPLE_IC")
        self.assertIn('name "dktools_generated"', table_text)

    def test_kicad_cli_fallback_finds_app_bundle_binary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cli_path = Path(tmpdir) / "kicad-cli"
            cli_path.write_text("#!/bin/sh\n", encoding="utf-8")
            with patch("digikey_tools.kicad.shutil.which", return_value=None):
                detected = find_kicad_cli([cli_path])
        self.assertEqual(detected, str(cli_path))

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
