from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .api import DigikeyClient
from .bom import (
    BomDatabase,
    export_digikey_upload_lines,
    price_bom_lines,
    price_rows,
    write_csv,
    write_price_summary,
)
from .config import DEFAULT_CONFIG_PATH, DEFAULT_ENV_PATH, AppConfig, load_app_config
from .errors import ToolError, error_to_json
from .normalize import (
    filter_products,
    normalize_keyword_response,
    normalize_product_details,
)
from .project import BOM_COLUMNS, init_project, resolve_project
from .store import PartStore


JsonDict = dict[str, Any]


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config = load_config_for_args(args)
        payload = args.handler(args, config)
        emit_json(payload, pretty=args.pretty, output=getattr(args, "json_output", None))
        return 0 if payload.get("ok", True) else 2
    except ToolError as error:
        emit_json(build_error_response(error), pretty=getattr(args, "pretty", False), output=None)
        return 2
    except (OSError, ValueError) as error:
        emit_json(build_error_response(error), pretty=getattr(args, "pretty", False), output=None)
        return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Agent-friendly Digi-Key search, BOM, and pricing tools.",
    )
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="JSON config path.")
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_PATH), help=".env path.")
    parser.add_argument("--project", help="Project directory. Defaults to current directory.")
    parser.add_argument("--client-id")
    parser.add_argument("--client-secret")
    parser.add_argument("--account-id")
    parser.add_argument("--environment", choices=["production", "sandbox"])
    parser.add_argument("--site")
    parser.add_argument("--language")
    parser.add_argument("--currency")
    parser.add_argument("--cache-ttl-seconds", type=int)
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON.")

    subparsers = parser.add_subparsers(dest="command", required=True)

    project_parser = subparsers.add_parser("project", help="Project scaffold commands.")
    project_sub = project_parser.add_subparsers(dest="project_command", required=True)
    project_init = project_sub.add_parser("init", help="Create a project directory.")
    project_init.add_argument("path")
    project_init.add_argument("--force", action="store_true")
    project_init.add_argument("--pretty", action="store_true", default=argparse.SUPPRESS)
    project_init.set_defaults(handler=handle_project_init, requires_api=False)

    search_parser = subparsers.add_parser("search", help="Search Digi-Key parts.")
    search_sub = search_parser.add_subparsers(dest="search_command", required=True)

    part_parser = search_sub.add_parser("part", help="Fetch details for one product number.")
    part_parser.add_argument("product_number")
    part_parser.add_argument("--manufacturer-id")
    part_parser.add_argument("--includes")
    part_parser.add_argument("--quantity", type=int, default=1)
    part_parser.add_argument("--project", default=argparse.SUPPRESS)
    part_parser.add_argument("--refresh", action="store_true")
    part_parser.add_argument("--include-raw", action="store_true")
    part_parser.add_argument("--no-save", action="store_true")
    part_parser.add_argument("-o", "--json-output")
    part_parser.add_argument("--pretty", action="store_true", default=argparse.SUPPRESS)
    part_parser.set_defaults(handler=handle_search_part, requires_api=True)

    keyword_parser = search_sub.add_parser("keyword", help="Search by keyword and filters.")
    keyword_parser.add_argument("keywords")
    keyword_parser.add_argument("--project", default=argparse.SUPPRESS)
    keyword_parser.add_argument("--limit", type=int, default=10)
    keyword_parser.add_argument("--offset", type=int, default=0)
    keyword_parser.add_argument("--quantity", type=int, default=1)
    keyword_parser.add_argument("--sort-field", default="QuantityAvailable")
    keyword_parser.add_argument("--sort-order", choices=["Ascending", "Descending"], default="Descending")
    keyword_parser.add_argument("--manufacturer-id", action="append", default=[])
    keyword_parser.add_argument("--category-id", action="append", default=[])
    keyword_parser.add_argument("--status-id", action="append", default=[])
    keyword_parser.add_argument("--packaging-id", action="append", default=[])
    keyword_parser.add_argument("--series-id", action="append", default=[])
    keyword_parser.add_argument("--param-category-id")
    keyword_parser.add_argument("--param", action="append", default=[], help="API param filter as PARAMETER_ID=VALUE_ID.")
    keyword_parser.add_argument("--min-qty", type=int)
    keyword_parser.add_argument("--in-stock", action="store_true")
    keyword_parser.add_argument("--normally-stocking", action="store_true")
    keyword_parser.add_argument("--rohs", action="store_true")
    keyword_parser.add_argument("--non-rohs", action="store_true")
    keyword_parser.add_argument("--has-datasheet", action="store_true")
    keyword_parser.add_argument("--has-photo", action="store_true")
    keyword_parser.add_argument("--has-3d-model", action="store_true")
    keyword_parser.add_argument("--new-products", action="store_true")
    market = keyword_parser.add_mutually_exclusive_group()
    market.add_argument("--exclude-marketplace", action="store_true")
    market.add_argument("--marketplace-only", action="store_true")
    keyword_parser.add_argument("--tariff-only", action="store_true")
    keyword_parser.add_argument("--exclude-tariff", action="store_true")
    keyword_parser.add_argument("--status", help="Local normalized status filter, e.g. Active.")
    keyword_parser.add_argument("--active-only", action="store_true")
    keyword_parser.add_argument("--spec-equals", action="append", default=[], help="Local spec filter as NAME=VALUE.")
    keyword_parser.add_argument("--spec-contains", action="append", default=[], help="Local spec contains filter as NAME=VALUE.")
    keyword_parser.add_argument("--refresh", action="store_true")
    keyword_parser.add_argument("--include-raw", action="store_true")
    keyword_parser.add_argument("--no-save", action="store_true")
    keyword_parser.add_argument("-o", "--json-output")
    keyword_parser.add_argument("--pretty", action="store_true", default=argparse.SUPPRESS)
    keyword_parser.set_defaults(handler=handle_search_keyword, requires_api=True)

    bom_parser = subparsers.add_parser("bom", help="Edit and price local BOM CSV.")
    bom_sub = bom_parser.add_subparsers(dest="bom_command", required=True)

    bom_init = bom_sub.add_parser("init", help="Create an empty BOM CSV.")
    bom_init.add_argument("--project", default=argparse.SUPPRESS)
    bom_init.add_argument("--pretty", action="store_true", default=argparse.SUPPRESS)
    bom_init.set_defaults(handler=handle_bom_init, requires_api=False)

    bom_list = bom_sub.add_parser("list", help="List BOM rows from the project database.")
    bom_list.add_argument("--project", default=argparse.SUPPRESS)
    bom_list.add_argument("--pretty", action="store_true", default=argparse.SUPPRESS)
    bom_list.set_defaults(handler=handle_bom_list, requires_api=False)

    bom_projects = bom_sub.add_parser("projects", help="List BOM project names in the database.")
    bom_projects.add_argument("--project", default=argparse.SUPPRESS)
    bom_projects.add_argument("--pretty", action="store_true", default=argparse.SUPPRESS)
    bom_projects.set_defaults(handler=handle_bom_projects, requires_api=False)

    bom_add = bom_sub.add_parser("add", help="Add one BOM row.")
    bom_add.add_argument("--project", default=argparse.SUPPRESS)
    bom_add.add_argument("--reference", default="")
    bom_add.add_argument("--quantity", type=int, default=1)
    bom_add.add_argument("--digikey-part", default="")
    bom_add.add_argument("--manufacturer", default="")
    bom_add.add_argument("--manufacturer-part", default="")
    bom_add.add_argument("--value", default="")
    bom_add.add_argument("--footprint", default="")
    bom_add.add_argument("--description", default="")
    bom_add.add_argument("--purpose", default="")
    bom_add.add_argument("--dnp", action="store_true")
    bom_add.add_argument("--notes", default="")
    bom_add.add_argument("--pretty", action="store_true", default=argparse.SUPPRESS)
    bom_add.set_defaults(handler=handle_bom_add, requires_api=False)

    bom_remove = bom_sub.add_parser("remove", help="Remove rows matching FIELD=VALUE.")
    bom_remove.add_argument("--project", default=argparse.SUPPRESS)
    bom_remove.add_argument("--match", required=True)
    bom_remove.add_argument("--pretty", action="store_true", default=argparse.SUPPRESS)
    bom_remove.set_defaults(handler=handle_bom_remove, requires_api=False)

    bom_update = bom_sub.add_parser("update", help="Update rows matching FIELD=VALUE.")
    bom_update.add_argument("--project", default=argparse.SUPPRESS)
    bom_update.add_argument("--match", required=True)
    bom_update.add_argument("--set", dest="sets", action="append", required=True)
    bom_update.add_argument("--pretty", action="store_true", default=argparse.SUPPRESS)
    bom_update.set_defaults(handler=handle_bom_update, requires_api=False)

    bom_export = bom_sub.add_parser("export-digikey", help="Write Digi-Key upload CSV.")
    bom_export.add_argument("--project", default=argparse.SUPPRESS)
    bom_export.add_argument("--output", default="bom/digikey_upload.csv")
    bom_export.add_argument("--include-dnp", action="store_true")
    bom_export.add_argument("--pretty", action="store_true", default=argparse.SUPPRESS)
    bom_export.set_defaults(handler=handle_bom_export, requires_api=False)

    bom_price = bom_sub.add_parser("price", help="Fetch prices for BOM rows.")
    bom_price.add_argument("--project", default=argparse.SUPPRESS)
    bom_price.add_argument("--price-csv", default="bom/price.csv")
    bom_price.add_argument("--summary-md", default="docs/price_summary.md")
    bom_price.add_argument("--json-output")
    bom_price.add_argument("--include-dnp", action="store_true")
    bom_price.add_argument("--include-raw", action="store_true")
    bom_price.add_argument("--refresh", action="store_true")
    bom_price.add_argument("--pretty", action="store_true", default=argparse.SUPPRESS)
    bom_price.set_defaults(handler=handle_bom_price, requires_api=True)

    store_parser = subparsers.add_parser("store", help="Inspect or update local part store.")
    store_sub = store_parser.add_subparsers(dest="store_command", required=True)

    store_list = store_sub.add_parser("list", help="List saved parts.")
    store_list.add_argument("--project", default=argparse.SUPPRESS)
    store_list.add_argument("--pretty", action="store_true", default=argparse.SUPPRESS)
    store_list.set_defaults(handler=handle_store_list, requires_api=False)

    store_export = store_sub.add_parser("export", help="Export local store as JSON.")
    store_export.add_argument("--project", default=argparse.SUPPRESS)
    store_export.add_argument("-o", "--output")
    store_export.add_argument("--pretty", action="store_true", default=argparse.SUPPRESS)
    store_export.set_defaults(handler=handle_store_export, requires_api=False)

    store_update = store_sub.add_parser("update", help="Refresh parts from store or BOM.")
    store_update.add_argument("--project", default=argparse.SUPPRESS)
    source = store_update.add_mutually_exclusive_group()
    source.add_argument("--from-bom", action="store_true")
    source.add_argument("--all", action="store_true")
    store_update.add_argument("--include-raw", action="store_true")
    store_update.add_argument("--refresh", action="store_true")
    store_update.add_argument("--pretty", action="store_true", default=argparse.SUPPRESS)
    store_update.set_defaults(handler=handle_store_update, requires_api=True)

    return parser


def load_config_for_args(args: argparse.Namespace) -> AppConfig:
    overrides: JsonDict = {
        "client_id": args.client_id,
        "client_secret": args.client_secret,
        "account_id": args.account_id,
        "environment": args.environment,
        "site": args.site,
        "language": args.language,
        "currency": args.currency,
        "cache_ttl_seconds": args.cache_ttl_seconds,
    }
    return load_app_config(
        config_path=Path(args.config),
        env_path=Path(args.env_file),
        overrides={key: value for key, value in overrides.items() if value is not None},
        require_credentials=getattr(args, "requires_api", True),
    )


def handle_project_init(args: argparse.Namespace, config: AppConfig) -> JsonDict:
    project = init_project(args.path, config, force=args.force)
    bom_db = BomDatabase(project.database_path)
    bom_db.ensure_project(project)
    bom_db.import_csv_if_empty(project)
    return {
        "ok": True,
        "command": "project init",
        "project": project.metadata(),
        "created_or_updated": {
            "selection_criteria": str(project.selection_path),
            "bom": str(project.bom_path),
            "database_dir": str(project.database_path.parent),
            "raw_dir": str(project.raw_dir),
            "docs_dir": str(project.docs_dir),
        },
    }


def handle_search_part(args: argparse.Namespace, config: AppConfig) -> JsonDict:
    project = resolve_project(args.project, config)
    client = DigikeyClient(config, cache_dir=project.raw_dir / "cache", refresh=args.refresh)
    raw, cache_hit = client.product_details(
        args.product_number,
        manufacturer_id=args.manufacturer_id,
        includes=args.includes,
    )
    result = normalize_product_details(
        raw,
        query={
            "product_number": args.product_number,
            "manufacturer_id": args.manufacturer_id,
            "includes": args.includes,
            "requested_quantity": args.quantity,
        },
        config=config,
        requested_quantity=args.quantity,
        cache_hit=cache_hit,
        include_raw=args.include_raw,
    )
    result["project"] = project.metadata()
    if not args.no_save:
        key = PartStore(project.database_path, project.raw_dir).upsert_product(result, raw)
        result["stored"] = {"database": str(project.database_path), "product_key": key}
    return result


def handle_search_keyword(args: argparse.Namespace, config: AppConfig) -> JsonDict:
    project = resolve_project(args.project, config)
    filter_options = build_keyword_filters(args)
    client = DigikeyClient(config, cache_dir=project.raw_dir / "cache", refresh=args.refresh)
    raw, cache_hit, request_body = client.keyword_search(
        args.keywords,
        limit=args.limit,
        offset=args.offset,
        filter_options=filter_options,
        sort_field=args.sort_field,
        sort_order=args.sort_order,
    )
    result = normalize_keyword_response(
        raw,
        request_body=request_body,
        query={
            "keywords": args.keywords,
            "requested_quantity": args.quantity,
            "local_filters": {
                "status": args.status,
                "active_only": args.active_only,
                "spec_equals": args.spec_equals,
                "spec_contains": args.spec_contains,
            },
        },
        config=config,
        requested_quantity=args.quantity,
        cache_hit=cache_hit,
        include_raw=args.include_raw,
    )
    filtered = filter_products(
        result["products"],
        status=args.status,
        spec_equals=args.spec_equals,
        spec_contains=args.spec_contains,
        min_quantity_available=args.min_qty,
        active_only=args.active_only,
    )
    result["products"] = filtered
    result["summary"]["returned_after_local_filters"] = len(filtered)
    result["project"] = project.metadata()
    if not args.no_save:
        store = PartStore(project.database_path, project.raw_dir)
        query_id = store.save_query("keyword", args.keywords, result)
        stored = []
        for product in filtered:
            try:
                stored.append(
                    store.upsert_product(
                        {
                            "ok": True,
                            "fetched_at": result["fetched_at"],
                            "source": result["source"],
                            "product": product,
                        }
                    )
                )
            except ToolError:
                continue
        result["stored"] = {
            "database": str(project.database_path),
            "query_id": query_id,
            "product_keys": stored,
        }
    return result


def handle_bom_init(args: argparse.Namespace, config: AppConfig) -> JsonDict:
    project = resolve_project(args.project, config)
    bom_db = BomDatabase(project.database_path)
    bom_db.ensure_project(project)
    imported = bom_db.import_csv_if_empty(project)
    bom_db.write_csv_snapshot(project)
    return {
        "ok": True,
        "project": project.metadata(),
        "bom": {
            "source": "sqlite",
            "project_name": project.project_name,
            "database": str(project.database_path),
            "csv_snapshot": str(project.bom_path),
            "columns": BOM_COLUMNS,
            "imported_from_csv": imported,
            "rows": len(bom_db.list_lines(project)),
        },
    }


def handle_bom_list(args: argparse.Namespace, config: AppConfig) -> JsonDict:
    project = resolve_project(args.project, config)
    bom_db = BomDatabase(project.database_path)
    lines = bom_db.list_lines(project)
    bom_db.write_csv_snapshot(project)
    return {
        "ok": True,
        "project": project.metadata(),
        "bom": {
            "source": "sqlite",
            "project_name": project.project_name,
            "rows": [line.row for line in lines],
            "row_count": len(lines),
            "csv_snapshot": str(project.bom_path),
        },
    }


def handle_bom_projects(args: argparse.Namespace, config: AppConfig) -> JsonDict:
    project = resolve_project(args.project, config)
    bom_db = BomDatabase(project.database_path)
    bom_db.ensure_project(project)
    return {
        "ok": True,
        "project": project.metadata(),
        "bom_projects": {
            "database": str(project.database_path),
            "project_names": bom_db.project_names(),
        },
    }


def handle_bom_add(args: argparse.Namespace, config: AppConfig) -> JsonDict:
    project = resolve_project(args.project, config)
    values = {
        "Reference Designator": args.reference,
        "Quantity": str(args.quantity),
        "Digi-Key Part Number": args.digikey_part,
        "Manufacturer": args.manufacturer,
        "Manufacturer Part Number": args.manufacturer_part,
        "Value": args.value,
        "Footprint": args.footprint,
        "Description": args.description,
        "Purpose": args.purpose,
        "DNP": "yes" if args.dnp else "",
        "Notes": args.notes,
    }
    result = BomDatabase(project.database_path).add_line(project, values)
    return {"ok": True, "project": project.metadata(), "bom": result}


def handle_bom_remove(args: argparse.Namespace, config: AppConfig) -> JsonDict:
    project = resolve_project(args.project, config)
    result = BomDatabase(project.database_path).remove_lines(project, args.match)
    return {"ok": True, "project": project.metadata(), "bom": result}


def handle_bom_update(args: argparse.Namespace, config: AppConfig) -> JsonDict:
    project = resolve_project(args.project, config)
    result = BomDatabase(project.database_path).update_lines(project, args.match, args.sets)
    return {"ok": True, "project": project.metadata(), "bom": result}


def handle_bom_export(args: argparse.Namespace, config: AppConfig) -> JsonDict:
    project = resolve_project(args.project, config)
    output = resolve_project_output(project.root, args.output)
    bom_db = BomDatabase(project.database_path)
    lines = bom_db.list_lines(project)
    bom_db.write_csv_snapshot(project)
    result = export_digikey_upload_lines(lines, output, include_dnp=args.include_dnp)
    return {"ok": True, "project": project.metadata(), "digikey_upload": result}


def handle_bom_price(args: argparse.Namespace, config: AppConfig) -> JsonDict:
    project = resolve_project(args.project, config)
    client = DigikeyClient(config, cache_dir=project.raw_dir / "cache", refresh=args.refresh)
    store = PartStore(project.database_path, project.raw_dir)
    bom_db = BomDatabase(project.database_path)
    lines = bom_db.list_lines(project)
    bom_db.write_csv_snapshot(project)
    result = price_bom_lines(
        lines,
        input_label=f"sqlite:{project.database_path}#bom:{project.project_name}",
        client=client,
        config=config,
        project=project,
        store=store,
        include_dnp=args.include_dnp,
        include_raw=args.include_raw,
    )
    rows = price_rows(result)
    price_csv = resolve_project_output(project.root, args.price_csv)
    summary_md = resolve_project_output(project.root, args.summary_md)
    write_csv(price_csv, rows)
    write_price_summary(summary_md, result, rows)
    result["outputs"] = {"price_csv": str(price_csv), "summary_md": str(summary_md)}
    if args.json_output:
        json_output = resolve_project_output(project.root, args.json_output)
        json_output.parent.mkdir(parents=True, exist_ok=True)
        json_output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result["outputs"]["json"] = str(json_output)
    return result


def handle_store_list(args: argparse.Namespace, config: AppConfig) -> JsonDict:
    project = resolve_project(args.project, config)
    store = PartStore(project.database_path, project.raw_dir)
    return {
        "ok": True,
        "project": project.metadata(),
        "parts": [record.to_json() for record in store.list_parts()],
    }


def handle_store_export(args: argparse.Namespace, config: AppConfig) -> JsonDict:
    project = resolve_project(args.project, config)
    result = PartStore(project.database_path, project.raw_dir).export_json()
    payload = {"ok": True, "project": project.metadata(), "store": result}
    if args.output:
        output = resolve_project_output(project.root, args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        payload["output"] = str(output)
    return payload


def handle_store_update(args: argparse.Namespace, config: AppConfig) -> JsonDict:
    project = resolve_project(args.project, config)
    store = PartStore(project.database_path, project.raw_dir)
    if args.from_bom or not args.all:
        lines = BomDatabase(project.database_path).list_lines(project)
        product_numbers = [line.product_number for line in lines if line.product_number and not line.dnp]
    else:
        product_numbers = store.saved_product_numbers()
    client = DigikeyClient(config, cache_dir=project.raw_dir / "cache", refresh=args.refresh)
    updated: list[JsonDict] = []
    for product_number in product_numbers:
        raw, cache_hit = client.product_details(str(product_number))
        normalized = normalize_product_details(
            raw,
            query={"product_number": product_number, "store_update": True},
            config=config,
            requested_quantity=1,
            cache_hit=cache_hit,
            include_raw=args.include_raw,
        )
        key = store.upsert_product(normalized, raw)
        updated.append({"product_number": product_number, "product_key": key, "cache_hit": cache_hit})
    return {
        "ok": True,
        "project": project.metadata(),
        "updated": updated,
        "count": len(updated),
    }


def build_keyword_filters(args: argparse.Namespace) -> JsonDict:
    filters: JsonDict = {}
    add_filter_ids(filters, "ManufacturerFilter", args.manufacturer_id)
    add_filter_ids(filters, "CategoryFilter", args.category_id)
    add_filter_ids(filters, "StatusFilter", args.status_id)
    add_filter_ids(filters, "PackagingFilter", args.packaging_id)
    add_filter_ids(filters, "SeriesFilter", args.series_id)
    if args.exclude_marketplace:
        filters["MarketPlaceFilter"] = "ExcludeMarketPlace"
    elif args.marketplace_only:
        filters["MarketPlaceFilter"] = "MarketPlaceOnly"
    if args.exclude_tariff:
        filters["TariffFilter"] = "ExcludeTariff"
    if args.tariff_only:
        filters["TariffFilter"] = "TariffOnly"
    if args.min_qty is not None:
        filters["MinimumQuantityAvailable"] = args.min_qty
    options: list[str] = []
    if args.in_stock:
        options.append("InStock")
    if args.normally_stocking:
        options.append("NormallyStocking")
    if args.rohs:
        options.append("RohsCompliant")
    if args.non_rohs:
        options.append("NonRohsCompliant")
    if args.has_datasheet:
        options.append("HasDatasheet")
    if args.has_photo:
        options.append("HasProductPhoto")
    if args.has_3d_model:
        options.append("Has3DModel")
    if args.new_products:
        options.append("NewProduct")
    if options:
        filters["SearchOptions"] = options
    if args.param:
        filters["ParameterFilterRequest"] = build_param_filter(args.param_category_id, args.param)
    return filters


def add_filter_ids(filters: JsonDict, name: str, values: list[str]) -> None:
    if values:
        filters[name] = [{"Id": str(value)} for value in values]


def build_param_filter(category_id: str | None, params: list[str]) -> JsonDict:
    request: JsonDict = {}
    if category_id:
        request["CategoryFilter"] = {"Id": str(category_id)}
    parameter_filters = []
    for item in params:
        if "=" not in item:
            raise ValueError(f"--param must be PARAMETER_ID=VALUE_ID: {item}")
        parameter_id, value_id = item.split("=", 1)
        parameter_filters.append(
            {
                "ParameterId": int(parameter_id),
                "FilterValues": [{"Id": value_id}],
            }
        )
    request["ParameterFilters"] = parameter_filters
    return request


def resolve_project_output(project_root: Path, output: str) -> Path:
    path = Path(output)
    if path.is_absolute():
        return path
    return project_root / path


def emit_json(payload: JsonDict, *, pretty: bool, output: str | None) -> None:
    text = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2 if pretty else None,
        separators=None if pretty else (",", ":"),
    )
    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


def build_error_response(error: BaseException) -> JsonDict:
    return {
        "ok": False,
        "error": error_to_json(error),
        "hints": [
            "Keep Digi-Key credentials in .env and do not print them.",
            "Use project init before project-scoped search or BOM commands.",
            "Use --environment sandbox only with sandbox credentials.",
        ],
    }


if __name__ == "__main__":
    sys.exit(main())
