from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
