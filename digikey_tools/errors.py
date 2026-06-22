from __future__ import annotations

from typing import Any


JsonDict = dict[str, Any]


class ToolError(Exception):
    """Base class for expected CLI errors."""


class ConfigError(ToolError):
    """Raised when local configuration is incomplete or invalid."""


class DotenvError(ConfigError):
    """Raised when .env cannot be parsed."""


class ProjectError(ToolError):
    """Raised when a project directory is invalid."""


class BomError(ToolError):
    """Raised when a BOM CSV cannot be read or edited."""


class StoreError(ToolError):
    """Raised when local storage cannot be updated."""


class DigikeyApiError(ToolError):
    """Raised when Digi-Key returns an HTTP or payload error."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        response_body: Any = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body
        self.headers = headers or {}


def error_to_json(error: BaseException) -> JsonDict:
    if isinstance(error, DigikeyApiError):
        return {
            "type": error.__class__.__name__,
            "message": str(error),
            "status_code": error.status_code,
            "response_body": error.response_body,
            "headers": {
                key: value
                for key, value in error.headers.items()
                if key.lower().startswith("x-")
                or key.lower() in {"retry-after", "content-type"}
            },
        }
    return {
        "type": error.__class__.__name__,
        "message": str(error),
    }
