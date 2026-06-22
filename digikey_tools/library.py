from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .bom import BomLine
from .errors import LibraryError
from .normalize import utc_now_iso
from .project import ProjectContext


JsonDict = dict[str, Any]

ASSET_STATUSES = [
    "unknown",
    "generic_ok",
    "available",
    "not_found",
    "needs_custom",
    "not_required",
    "risk",
    "unverified",
]
OVERALL_STATUSES = [
    "unknown",
    "ready",
    "usable_with_generic",
    "needs_download",
    "needs_custom",
    "blocked",
    "review",
]
CONFIDENCE_LEVELS = ["unknown", "low", "medium", "high"]
SYMBOL_POLICIES = [
    "unknown",
    "kicad_generic_preferred",
    "specific_required",
    "generated_specific",
    "verified_specific",
    "generic_possible_verify_pins",
    "manual_required",
    "external",
]
FOOTPRINT_POLICIES = [
    "unknown",
    "kicad_generic_preferred",
    "standard_package_preferred",
    "bom_specified_verify",
    "footprint_required",
    "external",
    "custom",
]
PIN_POLICIES = [
    "unknown",
    "generic_pin_identity_ok",
    "specific_pin_identity_required",
    "pin_map_provided",
    "symbol_pinout_must_be_verified",
    "not_required",
]
IMPORT_STATUSES = ["unknown", "ready", "needs_review", "blocked", "imported"]

STATUS_FIELDS = [
    "kicad_symbol_status",
    "kicad_footprint_status",
    "kicad_3d_model_status",
    "digikey_eda_status",
    "digikey_3d_model_status",
    "external_library_status",
]
TEXT_FIELDS = [
    "kicad_symbol_name",
    "kicad_footprint_name",
    "kicad_3d_model_path",
    "digikey_eda_url",
    "digikey_3d_model_url",
    "external_library_provider",
    "external_library_url",
    "recommended_action",
    "notes",
]
POLICY_FIELDS = [
    "symbol_policy",
    "footprint_policy",
    "pin_policy",
    "kicad_import_status",
]
IDENTITY_FIELDS = [
    "digikey_part_number",
    "manufacturer",
    "manufacturer_part_number",
    "reference_designator",
    "value",
    "footprint",
]
ASSESSMENT_FIELDS = (
    IDENTITY_FIELDS
    + STATUS_FIELDS
    + TEXT_FIELDS
    + POLICY_FIELDS
    + ["overall_status", "confidence"]
)
READY_OVERALL_STATUSES = {"ready", "usable_with_generic"}
NEEDS_ACTION_STATUSES = {"unknown", "needs_custom", "risk", "unverified"}


class LibraryDatabase:
    """SQLite-backed EDA/KiCad library assessment store keyed by BOM line."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _init_schema(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS eda_library_assessments (
                    project_name TEXT NOT NULL,
                    line_id TEXT NOT NULL,
                    digikey_part_number TEXT NOT NULL DEFAULT '',
                    manufacturer TEXT NOT NULL DEFAULT '',
                    manufacturer_part_number TEXT NOT NULL DEFAULT '',
                    reference_designator TEXT NOT NULL DEFAULT '',
                    value TEXT NOT NULL DEFAULT '',
                    footprint TEXT NOT NULL DEFAULT '',
                    kicad_symbol_status TEXT NOT NULL DEFAULT 'unknown',
                    kicad_symbol_name TEXT NOT NULL DEFAULT '',
                    kicad_footprint_status TEXT NOT NULL DEFAULT 'unknown',
                    kicad_footprint_name TEXT NOT NULL DEFAULT '',
                    kicad_3d_model_status TEXT NOT NULL DEFAULT 'unknown',
                    kicad_3d_model_path TEXT NOT NULL DEFAULT '',
                    digikey_eda_status TEXT NOT NULL DEFAULT 'unknown',
                    digikey_eda_url TEXT NOT NULL DEFAULT '',
                    digikey_3d_model_status TEXT NOT NULL DEFAULT 'unknown',
                    digikey_3d_model_url TEXT NOT NULL DEFAULT '',
                    external_library_status TEXT NOT NULL DEFAULT 'unknown',
                    external_library_provider TEXT NOT NULL DEFAULT '',
                    external_library_url TEXT NOT NULL DEFAULT '',
                    overall_status TEXT NOT NULL DEFAULT 'unknown',
                    confidence TEXT NOT NULL DEFAULT 'unknown',
                    symbol_policy TEXT NOT NULL DEFAULT 'unknown',
                    footprint_policy TEXT NOT NULL DEFAULT 'unknown',
                    pin_policy TEXT NOT NULL DEFAULT 'unknown',
                    kicad_import_status TEXT NOT NULL DEFAULT 'unknown',
                    recommended_action TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT '',
                    evidence_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (project_name, line_id),
                    FOREIGN KEY (project_name, line_id)
                        REFERENCES bom_items(project_name, line_id)
                        ON DELETE CASCADE
                )
                """
            )
            self._ensure_columns(connection)
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_eda_library_assessments_project_status
                ON eda_library_assessments(project_name, overall_status, confidence)
                """
            )

    def _ensure_columns(self, connection: sqlite3.Connection) -> None:
        existing = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(eda_library_assessments)").fetchall()
        }
        columns = {
            "digikey_part_number": "TEXT NOT NULL DEFAULT ''",
            "manufacturer": "TEXT NOT NULL DEFAULT ''",
            "manufacturer_part_number": "TEXT NOT NULL DEFAULT ''",
            "reference_designator": "TEXT NOT NULL DEFAULT ''",
            "value": "TEXT NOT NULL DEFAULT ''",
            "footprint": "TEXT NOT NULL DEFAULT ''",
            "kicad_symbol_status": "TEXT NOT NULL DEFAULT 'unknown'",
            "kicad_symbol_name": "TEXT NOT NULL DEFAULT ''",
            "kicad_footprint_status": "TEXT NOT NULL DEFAULT 'unknown'",
            "kicad_footprint_name": "TEXT NOT NULL DEFAULT ''",
            "kicad_3d_model_status": "TEXT NOT NULL DEFAULT 'unknown'",
            "kicad_3d_model_path": "TEXT NOT NULL DEFAULT ''",
            "digikey_eda_status": "TEXT NOT NULL DEFAULT 'unknown'",
            "digikey_eda_url": "TEXT NOT NULL DEFAULT ''",
            "digikey_3d_model_status": "TEXT NOT NULL DEFAULT 'unknown'",
            "digikey_3d_model_url": "TEXT NOT NULL DEFAULT ''",
            "external_library_status": "TEXT NOT NULL DEFAULT 'unknown'",
            "external_library_provider": "TEXT NOT NULL DEFAULT ''",
            "external_library_url": "TEXT NOT NULL DEFAULT ''",
            "overall_status": "TEXT NOT NULL DEFAULT 'unknown'",
            "confidence": "TEXT NOT NULL DEFAULT 'unknown'",
            "symbol_policy": "TEXT NOT NULL DEFAULT 'unknown'",
            "footprint_policy": "TEXT NOT NULL DEFAULT 'unknown'",
            "pin_policy": "TEXT NOT NULL DEFAULT 'unknown'",
            "kicad_import_status": "TEXT NOT NULL DEFAULT 'unknown'",
            "recommended_action": "TEXT NOT NULL DEFAULT ''",
            "notes": "TEXT NOT NULL DEFAULT ''",
            "evidence_json": "TEXT NOT NULL DEFAULT '{}'",
            "created_at": "TEXT NOT NULL DEFAULT ''",
            "updated_at": "TEXT NOT NULL DEFAULT ''",
        }
        for name, column_type in columns.items():
            if name not in existing:
                connection.execute(
                    f"ALTER TABLE eda_library_assessments ADD COLUMN {name} {column_type}"
                )

    def upsert_assessment(
        self,
        project: ProjectContext,
        line: BomLine,
        updates: JsonDict,
        *,
        evidence: JsonDict | None = None,
    ) -> JsonDict:
        validate_updates(updates)
        existing = self.get_assessment(project.project_name, line.line_id)
        record = default_assessment_for_line(line)
        if existing:
            record.update({field: existing.get(field, record[field]) for field in ASSESSMENT_FIELDS})
        record.update(identity_for_line(line))
        record.update({key: value for key, value in updates.items() if value is not None})

        merged_evidence = dict(existing.get("evidence") or {}) if existing else {}
        if evidence:
            merged_evidence.update(evidence)
        sync_primary_external_source(record, merged_evidence)

        now = utc_now_iso()
        created_at = str(existing.get("created_at") or now) if existing else now
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO eda_library_assessments (
                    project_name,
                    line_id,
                    digikey_part_number,
                    manufacturer,
                    manufacturer_part_number,
                    reference_designator,
                    value,
                    footprint,
                    kicad_symbol_status,
                    kicad_symbol_name,
                    kicad_footprint_status,
                    kicad_footprint_name,
                    kicad_3d_model_status,
                    kicad_3d_model_path,
                    digikey_eda_status,
                    digikey_eda_url,
                    digikey_3d_model_status,
                    digikey_3d_model_url,
                    external_library_status,
                    external_library_provider,
                    external_library_url,
                    overall_status,
                    confidence,
                    symbol_policy,
                    footprint_policy,
                    pin_policy,
                    kicad_import_status,
                    recommended_action,
                    notes,
                    evidence_json,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_name, line_id) DO UPDATE SET
                    digikey_part_number = excluded.digikey_part_number,
                    manufacturer = excluded.manufacturer,
                    manufacturer_part_number = excluded.manufacturer_part_number,
                    reference_designator = excluded.reference_designator,
                    value = excluded.value,
                    footprint = excluded.footprint,
                    kicad_symbol_status = excluded.kicad_symbol_status,
                    kicad_symbol_name = excluded.kicad_symbol_name,
                    kicad_footprint_status = excluded.kicad_footprint_status,
                    kicad_footprint_name = excluded.kicad_footprint_name,
                    kicad_3d_model_status = excluded.kicad_3d_model_status,
                    kicad_3d_model_path = excluded.kicad_3d_model_path,
                    digikey_eda_status = excluded.digikey_eda_status,
                    digikey_eda_url = excluded.digikey_eda_url,
                    digikey_3d_model_status = excluded.digikey_3d_model_status,
                    digikey_3d_model_url = excluded.digikey_3d_model_url,
                    external_library_status = excluded.external_library_status,
                    external_library_provider = excluded.external_library_provider,
                    external_library_url = excluded.external_library_url,
                    overall_status = excluded.overall_status,
                    confidence = excluded.confidence,
                    symbol_policy = excluded.symbol_policy,
                    footprint_policy = excluded.footprint_policy,
                    pin_policy = excluded.pin_policy,
                    kicad_import_status = excluded.kicad_import_status,
                    recommended_action = excluded.recommended_action,
                    notes = excluded.notes,
                    evidence_json = excluded.evidence_json,
                    updated_at = excluded.updated_at
                """,
                (
                    project.project_name,
                    line.line_id,
                    record["digikey_part_number"],
                    record["manufacturer"],
                    record["manufacturer_part_number"],
                    record["reference_designator"],
                    record["value"],
                    record["footprint"],
                    record["kicad_symbol_status"],
                    record["kicad_symbol_name"],
                    record["kicad_footprint_status"],
                    record["kicad_footprint_name"],
                    record["kicad_3d_model_status"],
                    record["kicad_3d_model_path"],
                    record["digikey_eda_status"],
                    record["digikey_eda_url"],
                    record["digikey_3d_model_status"],
                    record["digikey_3d_model_url"],
                    record["external_library_status"],
                    record["external_library_provider"],
                    record["external_library_url"],
                    record["overall_status"],
                    record["confidence"],
                    record["symbol_policy"],
                    record["footprint_policy"],
                    record["pin_policy"],
                    record["kicad_import_status"],
                    record["recommended_action"],
                    record["notes"],
                    json.dumps(merged_evidence, ensure_ascii=False, sort_keys=True),
                    created_at,
                    now,
                ),
            )
        saved = self.get_assessment(project.project_name, line.line_id)
        if saved is None:
            raise LibraryError(f"could not save library assessment: {line.line_id}")
        return saved

    def get_assessment(self, project_name: str, line_id: str) -> JsonDict | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM eda_library_assessments
                WHERE project_name = ? AND line_id = ?
                """,
                (project_name, line_id),
            ).fetchone()
        return assessment_row_to_json(row) if row else None

    def list_project(
        self,
        project: ProjectContext,
        lines: list[BomLine],
        *,
        include_unassessed: bool = True,
    ) -> list[JsonDict]:
        assessments = self.assessments_by_line(project.project_name)
        rows: list[JsonDict] = []
        for line in lines:
            assessment = assessments.get(line.line_id)
            if assessment is None and not include_unassessed:
                continue
            rows.append(
                {
                    "line_id": line.line_id,
                    "reference_designator": line.row.get("Reference Designator", ""),
                    "manufacturer_part_number": line.row.get("Manufacturer Part Number", ""),
                    "digikey_part_number": line.row.get("Digi-Key Part Number", ""),
                    "source_row": line.row,
                    "assessment": assessment,
                    "needs_action": assessment_needs_action(assessment),
                }
            )
        return rows

    def assessments_by_line(self, project_name: str) -> dict[str, JsonDict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM eda_library_assessments
                WHERE project_name = ?
                ORDER BY reference_designator, manufacturer_part_number, line_id
                """,
                (project_name,),
            ).fetchall()
        return {
            str(row["line_id"]): assessment_row_to_json(row)
            for row in rows
        }


def default_assessment_for_line(line: BomLine) -> JsonDict:
    return {
        **identity_for_line(line),
        "kicad_symbol_status": "unknown",
        "kicad_symbol_name": "",
        "kicad_footprint_status": "unknown",
        "kicad_footprint_name": line.row.get("Footprint", ""),
        "kicad_3d_model_status": "unknown",
        "kicad_3d_model_path": "",
        "digikey_eda_status": "unknown",
        "digikey_eda_url": "",
        "digikey_3d_model_status": "unknown",
        "digikey_3d_model_url": "",
        "external_library_status": "unknown",
        "external_library_provider": "",
        "external_library_url": "",
        "overall_status": "unknown",
        "confidence": "unknown",
        "symbol_policy": "unknown",
        "footprint_policy": "unknown",
        "pin_policy": "unknown",
        "kicad_import_status": "unknown",
        "recommended_action": "",
        "notes": "",
    }


def identity_for_line(line: BomLine) -> JsonDict:
    return {
        "digikey_part_number": line.row.get("Digi-Key Part Number", ""),
        "manufacturer": line.row.get("Manufacturer", ""),
        "manufacturer_part_number": line.row.get("Manufacturer Part Number", ""),
        "reference_designator": line.row.get("Reference Designator", ""),
        "value": line.row.get("Value", ""),
        "footprint": line.row.get("Footprint", ""),
    }


def validate_updates(updates: JsonDict) -> None:
    for field in STATUS_FIELDS:
        value = updates.get(field)
        if value is not None and value not in ASSET_STATUSES:
            raise LibraryError(f"{field} must be one of: {', '.join(ASSET_STATUSES)}")
    overall = updates.get("overall_status")
    if overall is not None and overall not in OVERALL_STATUSES:
        raise LibraryError(f"overall_status must be one of: {', '.join(OVERALL_STATUSES)}")
    confidence = updates.get("confidence")
    if confidence is not None and confidence not in CONFIDENCE_LEVELS:
        raise LibraryError(f"confidence must be one of: {', '.join(CONFIDENCE_LEVELS)}")
    symbol_policy = updates.get("symbol_policy")
    if symbol_policy is not None and symbol_policy not in SYMBOL_POLICIES:
        raise LibraryError(f"symbol_policy must be one of: {', '.join(SYMBOL_POLICIES)}")
    footprint_policy = updates.get("footprint_policy")
    if footprint_policy is not None and footprint_policy not in FOOTPRINT_POLICIES:
        raise LibraryError(f"footprint_policy must be one of: {', '.join(FOOTPRINT_POLICIES)}")
    pin_policy = updates.get("pin_policy")
    if pin_policy is not None and pin_policy not in PIN_POLICIES:
        raise LibraryError(f"pin_policy must be one of: {', '.join(PIN_POLICIES)}")
    import_status = updates.get("kicad_import_status")
    if import_status is not None and import_status not in IMPORT_STATUSES:
        raise LibraryError(f"kicad_import_status must be one of: {', '.join(IMPORT_STATUSES)}")


def assessment_row_to_json(row: sqlite3.Row) -> JsonDict:
    result = {key: row[key] for key in row.keys() if key != "evidence_json"}
    result["evidence"] = parse_json_object(row["evidence_json"])
    return result


def parse_json_object(value: object) -> JsonDict:
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {"raw": value}
    return parsed if isinstance(parsed, dict) else {"value": parsed}


def sync_primary_external_source(record: JsonDict, evidence: JsonDict) -> None:
    sources = evidence.get("external_sources")
    if not isinstance(sources, list) or not sources:
        return
    first = sources[0] if isinstance(sources[0], dict) else {}
    if first.get("provider") and not record.get("external_library_provider"):
        record["external_library_provider"] = str(first["provider"])
    if first.get("url") and not record.get("external_library_url"):
        record["external_library_url"] = str(first["url"])


def assessment_needs_action(assessment: JsonDict | None) -> bool:
    if assessment is None:
        return True
    if str(assessment.get("recommended_action") or "").strip():
        return True
    overall = str(assessment.get("overall_status") or "unknown")
    confidence = str(assessment.get("confidence") or "unknown")
    if overall in READY_OVERALL_STATUSES and confidence in {"medium", "high"}:
        return False
    if overall not in READY_OVERALL_STATUSES:
        return True
    return any(
        assessment.get(field) in NEEDS_ACTION_STATUSES
        for field in [
            "kicad_symbol_status",
            "kicad_footprint_status",
            "kicad_3d_model_status",
        ]
    )


def digikey_model_hints_for_line(part_store: Any, line: BomLine) -> JsonDict:
    identifiers = [
        line.row.get("Digi-Key Part Number", ""),
        line.row.get("Manufacturer Part Number", ""),
    ]
    part = None
    matched_identifier = ""
    for identifier in identifiers:
        if not str(identifier).strip():
            continue
        part = part_store.get_part(str(identifier).strip())
        if part:
            matched_identifier = str(identifier).strip()
            break
    if not part:
        return {
            "part_found": False,
            "matched_identifier": "",
            "links": [],
            "digikey_eda_status": "unknown",
            "digikey_3d_model_status": "unknown",
        }

    payloads: list[tuple[str, Any]] = []
    if part.get("normalized"):
        payloads.append(("normalized", part["normalized"]))
    raw_searched = False
    raw_path_value = part.get("raw_json_path")
    if raw_path_value:
        raw_path = Path(str(raw_path_value))
        if raw_path.exists():
            raw_searched = True
            try:
                payloads.append(("raw", json.loads(raw_path.read_text(encoding="utf-8"))))
            except (OSError, json.JSONDecodeError):
                payloads.append(("raw_error", {"path": str(raw_path)}))

    links: list[JsonDict] = []
    for label, payload in payloads:
        links.extend(extract_model_links(payload, root=label))
    links = dedupe_links(links)
    eda_links = [link for link in links if link["kind"] == "eda_library"]
    model_links = [link for link in links if link["kind"] == "3d_model"]

    missing_status = "not_found" if raw_searched else "unknown"
    return {
        "part_found": True,
        "matched_identifier": matched_identifier,
        "product_key": part.get("product_key"),
        "manufacturer_part_number": part.get("manufacturer_part_number"),
        "digikey_product_number": part.get("digikey_product_number"),
        "raw_json_path": part.get("raw_json_path"),
        "raw_searched": raw_searched,
        "links": links,
        "digikey_eda_status": "available" if eda_links else missing_status,
        "digikey_eda_url": first_url(eda_links),
        "digikey_3d_model_status": "available" if model_links else missing_status,
        "digikey_3d_model_url": first_url(model_links),
    }


def extract_model_links(value: Any, *, root: str = "$") -> list[JsonDict]:
    links: list[JsonDict] = []

    def walk(item: Any, path: str) -> None:
        if len(links) >= 50:
            return
        if isinstance(item, dict):
            for key, child in item.items():
                walk(child, f"{path}.{key}")
            return
        if isinstance(item, list):
            for index, child in enumerate(item):
                walk(child, f"{path}[{index}]")
            return
        label = path.lower()
        if not is_model_context(label):
            return
        if isinstance(item, bool) and item:
            links.append({"kind": model_kind(label, ""), "path": path, "value": True})
            return
        if isinstance(item, str) and looks_like_resource(item):
            links.append(
                {
                    "kind": model_kind(label, item),
                    "path": path,
                    "url": item,
                }
            )

    walk(value, root)
    return links


def dedupe_links(links: list[JsonDict]) -> list[JsonDict]:
    seen: set[tuple[str, str, str]] = set()
    deduped = []
    for link in links:
        key = (
            str(link.get("kind") or ""),
            str(link.get("path") or ""),
            str(link.get("url") or link.get("value") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(link)
    return deduped


def is_model_context(label: str) -> bool:
    tokens = [
        "3d",
        "cad",
        "ecad",
        "eda",
        "model",
        "symbol",
        "footprint",
        "kicad",
        "snapeda",
        "ultralibrarian",
    ]
    return any(token in label for token in tokens)


def looks_like_resource(value: str) -> bool:
    lowered = value.lower()
    if lowered.startswith(("http://", "https://")):
        return True
    endings = [
        ".step",
        ".stp",
        ".wrl",
        ".igs",
        ".iges",
        ".kicad_mod",
        ".kicad_sym",
        ".pretty",
        ".zip",
    ]
    return any(lowered.split("?", 1)[0].endswith(ending) for ending in endings)


def model_kind(label: str, value: str) -> str:
    lowered = f"{label} {value.lower()}"
    if any(token in lowered for token in ["3d", ".step", ".stp", ".wrl", ".igs", ".iges"]):
        return "3d_model"
    return "eda_library"


def first_url(links: list[JsonDict]) -> str:
    for link in links:
        if link.get("url"):
            return str(link["url"])
    return ""
