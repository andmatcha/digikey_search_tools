from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from digikey_tools.bom import BomDatabase
from digikey_tools.config import AppConfig, PathConfig
from digikey_tools.project import init_project, resolve_project


def sample_config() -> AppConfig:
    return AppConfig(
        client_id="",
        client_secret="",
        account_id=None,
        environment="production",
        site="JP",
        language="ja",
        currency="JPY",
        cache_ttl_seconds=86400,
        timeout_seconds=30,
        max_retries=3,
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


class ExternalProjectTest(unittest.TestCase):
    def test_relative_project_paths_are_resolved_from_current_directory(self) -> None:
        original_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                os.chdir(tmpdir)
                project = init_project("board", sample_config())
                resolved = resolve_project("board", sample_config())
            finally:
                os.chdir(original_cwd)

            self.assertEqual(project.root, (Path(tmpdir) / "board").resolve())
            self.assertEqual(resolved.root, (Path(tmpdir) / "board").resolve())
            self.assertTrue((Path(tmpdir) / "board" / "selection_criteria.md").exists())
            self.assertTrue((Path(tmpdir) / "board" / "bom" / "bom.csv").exists())

    def test_selection_criteria_is_optional_for_existing_external_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "external_board"
            project_root.mkdir()

            resolved = resolve_project(project_root, sample_config())

            self.assertEqual(resolved.root, project_root.resolve())
            self.assertFalse(resolved.criteria.loaded)
            self.assertIsNone(resolved.criteria.sha256)
            self.assertEqual(resolved.criteria.line_count, 0)
            self.assertFalse((project_root / "selection_criteria.md").exists())
            self.assertEqual(resolved.metadata()["selection_criteria"]["loaded"], False)

            added = BomDatabase(resolved.database_path).add_line(
                resolved,
                {
                    "Reference Designator": "U1",
                    "Quantity": "1",
                    "Manufacturer Part Number": "TPS40210DGQR",
                    "Notes": "requirements were provided in the request",
                },
            )

            self.assertEqual(added["rows"], 1)
            self.assertTrue((project_root / "bom" / "bom.csv").exists())


if __name__ == "__main__":
    unittest.main()
