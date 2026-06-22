from __future__ import annotations

import os
import shlex
from pathlib import Path

from .errors import DotenvError


def load_dotenv(path: Path, *, override: bool = False) -> bool:
    """Load KEY=VALUE pairs from .env without printing secret values."""
    if not path.exists():
        return False
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise DotenvError(f"Could not read .env file: {path}") from error

    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            raise DotenvError(f"Invalid .env line {line_number}: missing '='")
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if not is_valid_env_key(key):
            raise DotenvError(f"Invalid .env line {line_number}: invalid key '{key}'")
        if not override and key in os.environ:
            continue
        os.environ[key] = parse_env_value(raw_value)
    return True


def is_valid_env_key(key: str) -> bool:
    if not key or key[0].isdigit():
        return False
    return all(char.isalnum() or char == "_" for char in key)


def parse_env_value(raw_value: str) -> str:
    value = strip_env_comment(raw_value).strip()
    if not value:
        return ""
    try:
        parsed = shlex.split(value, posix=True)
    except ValueError as error:
        raise DotenvError(f"Invalid quoted value in .env: {error}") from error
    if len(parsed) == 1:
        return parsed[0]
    if len(parsed) == 0:
        return ""
    raise DotenvError("Invalid .env value: use quotes for values containing spaces")


def strip_env_comment(value: str) -> str:
    quote: str | None = None
    escaped = False
    for index, char in enumerate(value):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char in {"'", '"'}:
            if quote == char:
                quote = None
            elif quote is None:
                quote = char
            continue
        if char == "#" and quote is None:
            previous = value[index - 1] if index > 0 else " "
            if previous.isspace():
                return value[:index]
    return value


def getenv_first(*keys: str) -> str | None:
    for key in keys:
        value = os.getenv(key)
        if value:
            return value
    return None
