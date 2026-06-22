from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .env import getenv_first, load_dotenv
from .errors import ConfigError


JsonDict = dict[str, Any]
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "digikey.json"
DEFAULT_ENV_PATH = REPO_ROOT / ".env"


@dataclass(frozen=True)
class PathConfig:
    default_projects_dir: Path
    selection_criteria: Path
    bom: Path
    database: Path
    raw_dir: Path


@dataclass(frozen=True)
class AppConfig:
    client_id: str
    client_secret: str
    account_id: str | None
    environment: str
    site: str
    language: str
    currency: str
    cache_ttl_seconds: int
    timeout_seconds: int
    max_retries: int
    paths: PathConfig
    config_path: Path
    env_path: Path

    @property
    def api_base_url(self) -> str:
        if self.environment == "sandbox":
            return "https://sandbox-api.digikey.com"
        return "https://api.digikey.com"

    @property
    def token_url(self) -> str:
        return f"{self.api_base_url}/v1/oauth2/token"


def load_app_config(
    *,
    config_path: Path = DEFAULT_CONFIG_PATH,
    env_path: Path = DEFAULT_ENV_PATH,
    overrides: JsonDict | None = None,
    require_credentials: bool = True,
) -> AppConfig:
    load_dotenv(env_path)
    raw = read_json_config(config_path)
    overrides = overrides or {}
    digikey = raw.get("digikey", {})
    paths = raw.get("paths", {})
    if not isinstance(digikey, dict) or not isinstance(paths, dict):
        raise ConfigError("config must include object values for 'digikey' and 'paths'.")

    client_id = str(
        first_present(
            overrides.get("client_id"),
            getenv_first("DIGIKEY_CLIENT_ID", "CLIENT_ID"),
        )
        or ""
    )
    client_secret = str(
        first_present(
            overrides.get("client_secret"),
            getenv_first("DIGIKEY_CLIENT_SECRET", "CLIENT_SECRET"),
        )
        or ""
    )
    if require_credentials and (not client_id or not client_secret):
        raise ConfigError(
            "DIGIKEY_CLIENT_ID/DIGIKEY_CLIENT_SECRET or CLIENT_ID/CLIENT_SECRET are required."
        )

    environment = str(
        first_present(
            overrides.get("environment"),
            getenv_first("DIGIKEY_ENV", "DIGIKEY_ENVIRONMENT"),
            digikey.get("environment"),
            "production",
        )
    ).lower()
    if environment not in {"production", "sandbox"}:
        raise ConfigError("environment must be 'production' or 'sandbox'.")

    return AppConfig(
        client_id=client_id,
        client_secret=client_secret,
        account_id=none_if_empty(
            first_present(
                overrides.get("account_id"),
                getenv_first("DIGIKEY_ACCOUNT_ID", "ACCOUNT_ID"),
                digikey.get("account_id"),
            )
        ),
        environment=environment,
        site=str(
            first_present(overrides.get("site"), os.getenv("DIGIKEY_SITE"), digikey.get("site"), "JP")
        ).upper(),
        language=str(
            first_present(
                overrides.get("language"),
                os.getenv("DIGIKEY_LANGUAGE"),
                digikey.get("language"),
                "ja",
            )
        ),
        currency=str(
            first_present(
                overrides.get("currency"),
                os.getenv("DIGIKEY_CURRENCY"),
                digikey.get("currency"),
                "JPY",
            )
        ).upper(),
        cache_ttl_seconds=int(
            first_present(
                overrides.get("cache_ttl_seconds"),
                os.getenv("DIGIKEY_CACHE_TTL_SECONDS"),
                digikey.get("cache_ttl_seconds"),
                86400,
            )
        ),
        timeout_seconds=int(
            first_present(overrides.get("timeout_seconds"), digikey.get("timeout_seconds"), 30)
        ),
        max_retries=int(
            first_present(overrides.get("max_retries"), digikey.get("max_retries"), 3)
        ),
        paths=PathConfig(
            default_projects_dir=Path(paths.get("default_projects_dir", "projects")),
            selection_criteria=Path(paths.get("selection_criteria", "selection_criteria.md")),
            bom=Path(paths.get("bom", "bom/bom.csv")),
            database=Path(paths.get("database", "data/digikey/parts.sqlite3")),
            raw_dir=Path(paths.get("raw_dir", "data/digikey/raw")),
        ),
        config_path=config_path,
        env_path=env_path,
    )


def read_json_config(path: Path) -> JsonDict:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError as error:
        raise ConfigError(f"config file not found: {path}") from error
    except json.JSONDecodeError as error:
        raise ConfigError(f"invalid JSON config: {path}: {error}") from error
    if not isinstance(data, dict):
        raise ConfigError("config root must be a JSON object.")
    return data


def first_present(*values: object) -> object | None:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def none_if_empty(value: object | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
