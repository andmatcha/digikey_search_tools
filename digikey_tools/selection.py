from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from .errors import ProjectError


@dataclass(frozen=True)
class SelectionCriteria:
    path: Path
    text: str
    sha256: str
    line_count: int

    def to_metadata(self) -> dict[str, object]:
        return {
            "path": str(self.path),
            "sha256": self.sha256,
            "line_count": self.line_count,
            "loaded": True,
        }


def read_selection_criteria(path: Path) -> SelectionCriteria:
    if not path.exists():
        raise ProjectError(f"selection criteria file not found: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ProjectError(f"could not read selection criteria: {path}") from error
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return SelectionCriteria(
        path=path,
        text=text,
        sha256=digest,
        line_count=len(text.splitlines()),
    )
