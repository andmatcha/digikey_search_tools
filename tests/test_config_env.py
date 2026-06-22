from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from digikey_tools.config import load_app_config
from digikey_tools.env import load_dotenv


CONFIG_JSON = """{
  "digikey": {
    "environment": "sandbox",
    "site": "US",
    "language": "en",
    "currency": "USD",
    "cache_ttl_seconds": 10,
    "timeout_seconds": 5,
    "max_retries": 0
  },
  "paths": {
    "default_projects_dir": "projects",
    "selection_criteria": "selection_criteria.md",
    "bom": "bom/bom.csv",
    "database": "data/digikey/parts.sqlite3",
    "raw_dir": "data/digikey/raw"
  }
}
"""


class ConfigEnvTest(unittest.TestCase):
    def test_load_dotenv_reads_quoted_values_without_overriding(self) -> None:
        keys = ["DIGIKEY_TEST_CLIENT_ID", "DIGIKEY_TEST_KEEP"]
        original = {key: os.environ.get(key) for key in keys}
        try:
            os.environ["DIGIKEY_TEST_KEEP"] = "from-shell"
            with tempfile.TemporaryDirectory() as tmpdir:
                env_path = Path(tmpdir) / ".env"
                env_path.write_text(
                    "\n".join(
                        [
                            "DIGIKEY_TEST_CLIENT_ID=abc",
                            'DIGIKEY_TEST_KEEP="from dotenv"',
                        ]
                    ),
                    encoding="utf-8",
                )
                self.assertTrue(load_dotenv(env_path))
            self.assertEqual(os.environ["DIGIKEY_TEST_CLIENT_ID"], "abc")
            self.assertEqual(os.environ["DIGIKEY_TEST_KEEP"], "from-shell")
        finally:
            for key, value in original.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_load_app_config_can_skip_credentials_for_local_commands(self) -> None:
        keys = ["DIGIKEY_CLIENT_ID", "DIGIKEY_CLIENT_SECRET", "CLIENT_ID", "CLIENT_SECRET"]
        original = {key: os.environ.get(key) for key in keys}
        try:
            for key in keys:
                os.environ.pop(key, None)
            with tempfile.TemporaryDirectory() as tmpdir:
                config_path = Path(tmpdir) / "digikey.json"
                env_path = Path(tmpdir) / ".env"
                config_path.write_text(CONFIG_JSON, encoding="utf-8")
                config = load_app_config(
                    config_path=config_path,
                    env_path=env_path,
                    require_credentials=False,
                )
            self.assertEqual(config.environment, "sandbox")
            self.assertEqual(config.site, "US")
            self.assertEqual(config.currency, "USD")
            self.assertEqual(config.client_id, "")
        finally:
            for key, value in original.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
