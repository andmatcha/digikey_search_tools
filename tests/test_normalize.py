from __future__ import annotations

import unittest
from pathlib import Path

from digikey_tools.config import AppConfig, PathConfig
from digikey_tools.normalize import normalize_product_details, select_price


def sample_config() -> AppConfig:
    return AppConfig(
        client_id="client",
        client_secret="secret",
        account_id="0",
        environment="sandbox",
        site="JP",
        language="ja",
        currency="JPY",
        cache_ttl_seconds=3600,
        timeout_seconds=30,
        max_retries=0,
        paths=PathConfig(
            default_projects_dir=Path("projects"),
            selection_criteria=Path("selection_criteria.md"),
            bom=Path("bom/bom.csv"),
            database=Path("data/digikey/parts.sqlite3"),
            raw_dir=Path("data/digikey/raw"),
        ),
        config_path=Path("config/digikey.json"),
        env_path=Path(".env"),
    )


class NormalizeTest(unittest.TestCase):
    def test_select_price_uses_moq_and_highest_eligible_break(self) -> None:
        selected = select_price(
            [
                {"break_quantity": 1, "unit_price": 120.0},
                {"break_quantity": 10, "unit_price": 95.0},
            ],
            requested_quantity=3,
            min_order_quantity=10,
        )
        self.assertEqual(selected["purchase_quantity"], 10)
        self.assertEqual(selected["break_quantity"], 10)
        self.assertEqual(selected["estimated_total_price"], 950.0)

    def test_normalize_product_details_extracts_agent_fields(self) -> None:
        raw = {
            "Product": {
                "Description": {
                    "ProductDescription": "Boost controller",
                    "DetailedDescription": "Boost controller, 10-HVSSOP",
                },
                "Manufacturer": {"Id": 123, "Name": "Texas Instruments"},
                "ManufacturerProductNumber": "TPS40210DGQR",
                "DatasheetUrl": "https://example.com/tps40210.pdf",
                "ProductUrl": "https://www.digikey.jp/example",
                "QuantityAvailable": 25,
                "ProductStatus": {"Id": 1, "Status": "Active"},
                "NormallyStocking": True,
                "Discontinued": False,
                "EndOfLife": False,
                "Ncnr": False,
                "Classifications": {"RohsStatus": "ROHS3 Compliant"},
                "Parameters": [
                    {
                        "ParameterId": 1,
                        "ParameterText": "Voltage - Supply",
                        "ParameterType": "String",
                        "ValueId": "abc",
                        "ValueText": "4.5V ~ 52V",
                    }
                ],
                "ProductVariations": [
                    {
                        "DigiKeyProductNumber": "296-26969-1-ND",
                        "PackageType": {"Id": 1, "Name": "Cut Tape"},
                        "QuantityAvailableforPackageType": 25,
                        "MinimumOrderQuantity": 1,
                        "StandardPricing": [{"BreakQuantity": 1, "UnitPrice": 346.0}],
                    }
                ],
            }
        }
        normalized = normalize_product_details(
            raw,
            query={"product_number": "TPS40210DGQR"},
            config=sample_config(),
            requested_quantity=2,
            cache_hit=False,
        )
        product = normalized["product"]
        self.assertEqual(product["manufacturer"]["name"], "Texas Instruments")
        self.assertEqual(product["parameter_map"]["Voltage - Supply"], "4.5V ~ 52V")
        self.assertEqual(product["best_offer"]["digikey_product_number"], "296-26969-1-ND")
        self.assertEqual(product["best_offer"]["estimated_total_price"], 692.0)
        self.assertTrue(product["availability"]["immediate"])
        self.assertEqual(normalized["warnings"], [])


if __name__ == "__main__":
    unittest.main()
