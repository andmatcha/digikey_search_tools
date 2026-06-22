from __future__ import annotations

import csv
import shutil
from dataclasses import dataclass
from pathlib import Path

from .config import AppConfig, REPO_ROOT
from .errors import ProjectError
from .selection import SelectionCriteria, read_selection_criteria


BOM_COLUMNS = [
    "LineId",
    "Reference Designator",
    "Quantity",
    "Digi-Key Part Number",
    "Manufacturer",
    "Manufacturer Part Number",
    "Value",
    "Footprint",
    "Description",
    "Purpose",
    "DNP",
    "Notes",
]


@dataclass(frozen=True)
class ProjectContext:
    root: Path
    selection_path: Path
    bom_path: Path
    database_path: Path
    raw_dir: Path
    docs_dir: Path
    criteria: SelectionCriteria

    def metadata(self) -> dict[str, object]:
        return {
            "project_root": str(self.root),
            "bom_path": str(self.bom_path),
            "database_path": str(self.database_path),
            "raw_dir": str(self.raw_dir),
            "selection_criteria": self.criteria.to_metadata(),
        }


def resolve_project(path: str | Path | None, config: AppConfig, *, require: bool = True) -> ProjectContext:
    root = Path(path).expanduser() if path else Path.cwd()
    if not root.is_absolute():
        root = (Path.cwd() / root).resolve()
    else:
        root = root.resolve()
    if require and not root.exists():
        raise ProjectError(f"project directory not found: {root}")

    selection_path = root / config.paths.selection_criteria
    bom_path = root / config.paths.bom
    database_path = root / config.paths.database
    raw_dir = root / config.paths.raw_dir
    docs_dir = root / "docs"
    criteria = read_selection_criteria(selection_path)
    return ProjectContext(
        root=root,
        selection_path=selection_path,
        bom_path=bom_path,
        database_path=database_path,
        raw_dir=raw_dir,
        docs_dir=docs_dir,
        criteria=criteria,
    )


def init_project(path: str | Path, config: AppConfig, *, force: bool = False) -> ProjectContext:
    root = Path(path).expanduser()
    if not root.is_absolute():
        root = (Path.cwd() / root).resolve()
    else:
        root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    (root / "bom").mkdir(parents=True, exist_ok=True)
    (root / "data" / "digikey" / "raw").mkdir(parents=True, exist_ok=True)
    (root / "docs").mkdir(parents=True, exist_ok=True)

    selection_path = root / config.paths.selection_criteria
    template = REPO_ROOT / "templates" / "selection_criteria.md"
    if force or not selection_path.exists():
        shutil.copyfile(template, selection_path)

    bom_path = root / config.paths.bom
    if force or not bom_path.exists():
        write_empty_bom(bom_path)

    return resolve_project(root, config)


def write_empty_bom(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=BOM_COLUMNS)
        writer.writeheader()
