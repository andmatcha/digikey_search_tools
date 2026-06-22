from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .api import KEYWORD_SEARCH_DOC_URL, PRODUCT_DETAILS_DOC_URL
from .config import AppConfig


JsonDict = dict[str, Any]


def normalize_product_details(
    raw: JsonDict,
    *,
    query: JsonDict,
    config: AppConfig,
    requested_quantity: int,
    cache_hit: bool,
    include_raw: bool = False,
) -> JsonDict:
    product = raw.get("Product") if isinstance(raw.get("Product"), dict) else {}
    normalized_product = normalize_product(
        product,
        requested_quantity=requested_quantity,
    )
    output: JsonDict = {
        "ok": True,
        "fetched_at": utc_now_iso(),
        "cache": {
            "hit": cache_hit,
            "ttl_seconds": config.cache_ttl_seconds,
        },
        "query": query,
        "source": source_block(config, endpoint="/products/v4/search/{productNumber}/productdetails"),
        "product": normalized_product,
        "warnings": build_warnings(normalized_product, requested_quantity),
    }
    if include_raw:
        output["raw"] = raw
    return output


def normalize_keyword_response(
    raw: JsonDict,
    *,
    request_body: JsonDict,
    query: JsonDict,
    config: AppConfig,
    requested_quantity: int,
    cache_hit: bool,
    include_raw: bool = False,
) -> JsonDict:
    products = [
        normalize_product(product, requested_quantity=requested_quantity)
        for product in raw.get("Products") or []
        if isinstance(product, dict)
    ]
    exact_matches = [
        normalize_product(product, requested_quantity=requested_quantity)
        for product in raw.get("ExactMatches") or []
        if isinstance(product, dict)
    ]
    output: JsonDict = {
        "ok": True,
        "fetched_at": utc_now_iso(),
        "cache": {
            "hit": cache_hit,
            "ttl_seconds": config.cache_ttl_seconds,
        },
        "query": query,
        "request_body": request_body,
        "source": source_block(config, endpoint="/products/v4/search/keyword"),
        "summary": {
            "products_count": raw.get("ProductsCount"),
            "returned_products": len(products),
            "exact_matches": len(exact_matches),
        },
        "products": products,
        "exact_matches": exact_matches,
        "filter_options": raw.get("FilterOptions"),
        "applied_parametric_filters": raw.get("AppliedParametricFiltersDto") or [],
    }
    if include_raw:
        output["raw"] = raw
    return output


def normalize_product(product: JsonDict, *, requested_quantity: int) -> JsonDict:
    parameters = normalize_parameters(product.get("Parameters"))
    variations = [
        normalize_variation(variation, requested_quantity=requested_quantity)
        for variation in product.get("ProductVariations") or []
        if isinstance(variation, dict)
    ]
    best_offer = choose_best_offer(variations)
    classifications = product.get("Classifications") or {}
    description = product.get("Description") or {}
    normalized = {
        "manufacturer": normalize_id_name(product.get("Manufacturer")),
        "manufacturer_part_number": product.get("ManufacturerProductNumber"),
        "description": value_or_none(description, "ProductDescription"),
        "detailed_description": value_or_none(description, "DetailedDescription"),
        "category": normalize_category(product.get("Category")),
        "series": normalize_id_name(product.get("Series")),
        "product_url": product.get("ProductUrl"),
        "datasheet_url": product.get("DatasheetUrl"),
        "photo_url": product.get("PhotoUrl"),
        "quantity_available": product.get("QuantityAvailable"),
        "unit_price": product.get("UnitPrice"),
        "status": named_value(product.get("ProductStatus"), "Status"),
        "status_id": value_or_none(product.get("ProductStatus"), "Id"),
        "status_flags": {
            "normally_stocking": product.get("NormallyStocking"),
            "discontinued": product.get("Discontinued"),
            "end_of_life": product.get("EndOfLife"),
            "back_order_not_allowed": product.get("BackOrderNotAllowed"),
            "non_cancelable_non_returnable": product.get("Ncnr"),
        },
        "compliance": {
            "rohs_status": value_or_none(classifications, "RohsStatus"),
            "reach_status": value_or_none(classifications, "ReachStatus"),
            "moisture_sensitivity_level": value_or_none(classifications, "MoistureSensitivityLevel"),
            "export_control_class_number": value_or_none(classifications, "ExportControlClassNumber"),
            "htsus_code": value_or_none(classifications, "HtsusCode"),
        },
        "manufacturer_lead_weeks": product.get("ManufacturerLeadWeeks"),
        "manufacturer_public_quantity": product.get("ManufacturerPublicQuantity"),
        "date_last_buy_chance": product.get("DateLastBuyChance"),
        "shipping_info": product.get("ShippingInfo"),
        "other_names": product.get("OtherNames") or [],
        "parameters": parameters,
        "parameter_map": {
            parameter["name"]: parameter["value"]
            for parameter in parameters
            if parameter.get("name") is not None
        },
        "variations": variations,
        "best_offer": best_offer,
    }
    normalized["availability"] = evaluate_availability(normalized, requested_quantity)
    normalized["score"] = score_product(normalized)
    return normalized


def normalize_variation(variation: JsonDict, *, requested_quantity: int) -> JsonDict:
    standard_pricing = normalize_price_breaks(variation.get("StandardPricing"))
    my_pricing = normalize_price_breaks(variation.get("MyPricing"))
    min_order_quantity = int_or_none(variation.get("MinimumOrderQuantity")) or 1
    quantity_available = int_or_none(variation.get("QuantityAvailableforPackageType"))
    selected_price = select_price(
        my_pricing if my_pricing else standard_pricing,
        requested_quantity=requested_quantity,
        min_order_quantity=min_order_quantity,
    )
    if selected_price:
        selected_price["pricing_type"] = "my" if my_pricing else "standard"
    return {
        "digikey_product_number": variation.get("DigiKeyProductNumber"),
        "package_type": named_value(variation.get("PackageType"), "Name"),
        "supplier": normalize_id_name(variation.get("Supplier")),
        "quantity_available": quantity_available,
        "minimum_order_quantity": min_order_quantity,
        "standard_package": variation.get("StandardPackage"),
        "max_quantity_for_distribution": variation.get("MaxQuantityForDistribution"),
        "marketplace": variation.get("MarketPlace"),
        "tariff_active": variation.get("TariffActive"),
        "digi_reel_fee": variation.get("DigiReelFee"),
        "standard_pricing": standard_pricing,
        "my_pricing": my_pricing,
        "selected_price": selected_price,
    }


def normalize_parameters(value: Any) -> list[JsonDict]:
    if not isinstance(value, list):
        return []
    parameters: list[JsonDict] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        parameters.append(
            {
                "id": item.get("ParameterId"),
                "name": item.get("ParameterText"),
                "type": item.get("ParameterType"),
                "value_id": item.get("ValueId"),
                "value": item.get("ValueText"),
            }
        )
    return parameters


def normalize_price_breaks(value: Any) -> list[JsonDict]:
    if not isinstance(value, list):
        return []
    breaks: list[JsonDict] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        breaks.append(
            {
                "break_quantity": item.get("BreakQuantity"),
                "unit_price": item.get("UnitPrice"),
                "total_price": item.get("TotalPrice"),
            }
        )
    return sorted(breaks, key=lambda item: int_or_none(item.get("break_quantity")) or 0)


def select_price(
    price_breaks: list[JsonDict],
    *,
    requested_quantity: int,
    min_order_quantity: int,
) -> JsonDict | None:
    if not price_breaks:
        return None
    purchase_quantity = max(requested_quantity, min_order_quantity, 1)
    eligible = [
        item
        for item in price_breaks
        if (int_or_none(item.get("break_quantity")) or 0) <= purchase_quantity
    ]
    chosen = eligible[-1] if eligible else price_breaks[0]
    unit_price = float_or_none(chosen.get("unit_price"))
    estimated_total = unit_price * purchase_quantity if unit_price is not None else None
    return {
        "requested_quantity": requested_quantity,
        "purchase_quantity": purchase_quantity,
        "break_quantity": chosen.get("break_quantity"),
        "unit_price": unit_price,
        "estimated_total_price": round(estimated_total, 6) if estimated_total is not None else None,
    }


def choose_best_offer(variations: list[JsonDict]) -> JsonDict | None:
    candidates: list[JsonDict] = []
    for variation in variations:
        selected = variation.get("selected_price")
        if not isinstance(selected, dict):
            continue
        unit_price = float_or_none(selected.get("unit_price"))
        total_price = float_or_none(selected.get("estimated_total_price"))
        if unit_price is None or total_price is None:
            continue
        quantity_available = int_or_none(variation.get("quantity_available"))
        purchase_quantity = int_or_none(selected.get("purchase_quantity")) or 1
        in_stock_enough = quantity_available is None or quantity_available >= purchase_quantity
        candidates.append(
            {
                "digikey_product_number": variation.get("digikey_product_number"),
                "package_type": variation.get("package_type"),
                "supplier": variation.get("supplier"),
                "in_stock_enough": in_stock_enough,
                "quantity_available": quantity_available,
                **selected,
            }
        )
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda item: (
            not bool(item.get("in_stock_enough")),
            float_or_none(item.get("estimated_total_price")) or float("inf"),
            float_or_none(item.get("unit_price")) or float("inf"),
        ),
    )[0]


def build_warnings(product: JsonDict, requested_quantity: int) -> list[str]:
    warnings: list[str] = []
    flags = product.get("status_flags") or {}
    if flags.get("discontinued"):
        warnings.append("Product is marked discontinued by Digi-Key.")
    if flags.get("end_of_life"):
        warnings.append("Product is marked end-of-life by Digi-Key.")
    if flags.get("non_cancelable_non_returnable"):
        warnings.append("Product is marked non-cancellable and non-returnable.")
    if flags.get("normally_stocking") is False:
        warnings.append("Product is not normally stocked.")
    if not product.get("datasheet_url"):
        warnings.append("No datasheet URL was returned.")
    quantity_available = int_or_none(product.get("quantity_available"))
    if quantity_available is not None and quantity_available < requested_quantity:
        warnings.append("Total available quantity is lower than the requested quantity.")
    best_offer = product.get("best_offer")
    if best_offer is None:
        warnings.append("No usable pricing break was returned.")
    elif not best_offer.get("in_stock_enough"):
        warnings.append("Best priced variation does not have enough stock.")
    return warnings


def evaluate_availability(product: JsonDict, requested_quantity: int) -> JsonDict:
    best_offer = product.get("best_offer") or {}
    flags = product.get("status_flags") or {}
    quantity_available = int_or_none(product.get("quantity_available"))
    purchase_quantity = int_or_none(best_offer.get("purchase_quantity")) or requested_quantity
    selected_variation = find_selected_variation(product)
    marketplace = bool(selected_variation.get("marketplace")) if selected_variation else False
    active = is_active_product(product)
    in_stock = quantity_available is not None and quantity_available >= purchase_quantity
    selected_in_stock = bool(best_offer.get("in_stock_enough"))
    immediate = active and in_stock and selected_in_stock and not marketplace

    reasons: list[str] = []
    if not active:
        reasons.append(f"status is {product.get('status') or 'unknown'}")
    if flags.get("discontinued"):
        reasons.append("discontinued")
    if flags.get("end_of_life"):
        reasons.append("end of life")
    if not in_stock:
        reasons.append("insufficient total stock")
    if not selected_in_stock:
        reasons.append("selected package has insufficient stock")
    if marketplace:
        reasons.append("marketplace product")

    return {
        "active": active,
        "in_stock": in_stock,
        "immediate": immediate,
        "status": product.get("status"),
        "quantity_available": quantity_available,
        "purchase_quantity": purchase_quantity,
        "selected_package_in_stock": selected_in_stock,
        "marketplace": marketplace,
        "reasons": reasons,
    }


def is_active_product(product: JsonDict) -> bool:
    flags = product.get("status_flags") or {}
    if flags.get("discontinued") or flags.get("end_of_life"):
        return False
    status = str(product.get("status") or "").strip().lower()
    return status in {"active", "アクティブ"}


def score_product(product: JsonDict) -> int:
    score = 0
    availability = product.get("availability") or {}
    flags = product.get("status_flags") or {}
    compliance = product.get("compliance") or {}
    if availability.get("active"):
        score += 30
    if availability.get("in_stock"):
        score += 25
    if availability.get("immediate"):
        score += 20
    if product.get("datasheet_url"):
        score += 10
    if "compliant" in str(compliance.get("rohs_status") or "").lower():
        score += 10
    if flags.get("normally_stocking"):
        score += 5
    if availability.get("marketplace"):
        score -= 15
    if flags.get("non_cancelable_non_returnable"):
        score -= 5
    return score


def filter_products(
    products: list[JsonDict],
    *,
    status: str | None = None,
    spec_equals: list[str] | None = None,
    spec_contains: list[str] | None = None,
    min_quantity_available: int | None = None,
    active_only: bool = False,
) -> list[JsonDict]:
    result = products
    if status:
        expected = status.strip().lower()
        result = [p for p in result if str(p.get("status") or "").strip().lower() == expected]
    if active_only:
        result = [p for p in result if (p.get("availability") or {}).get("active")]
    if min_quantity_available is not None:
        result = [
            p
            for p in result
            if (int_or_none(p.get("quantity_available")) or 0) >= min_quantity_available
        ]
    for spec in spec_equals or []:
        name, expected = split_spec_filter(spec)
        result = [
            p
            for p in result
            if str((p.get("parameter_map") or {}).get(name) or "").strip().lower()
            == expected.strip().lower()
        ]
    for spec in spec_contains or []:
        name, expected = split_spec_filter(spec)
        needle = expected.strip().lower()
        result = [
            p
            for p in result
            if needle in str((p.get("parameter_map") or {}).get(name) or "").strip().lower()
        ]
    return sorted(result, key=lambda product: product.get("score", 0), reverse=True)


def split_spec_filter(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise ValueError(f"spec filter must be NAME=VALUE: {value}")
    name, expected = value.split("=", 1)
    return name.strip(), expected.strip()


def find_selected_variation(product: JsonDict) -> JsonDict | None:
    best = product.get("best_offer") or {}
    selected_number = best.get("digikey_product_number")
    for variation in product.get("variations") or []:
        if variation.get("digikey_product_number") == selected_number:
            return variation
    return None


def normalize_id_name(value: Any) -> JsonDict | None:
    if not isinstance(value, dict):
        return None
    result = {"id": value.get("Id"), "name": value.get("Name")}
    return result if result["id"] is not None or result["name"] is not None else None


def normalize_category(value: Any) -> JsonDict | None:
    if not isinstance(value, dict):
        return None
    return {
        "id": value.get("CategoryId"),
        "name": value.get("Name"),
        "parent_id": value.get("ParentId"),
        "product_count": value.get("ProductCount"),
    }


def named_value(value: Any, field_name: str) -> str | None:
    if isinstance(value, dict):
        field = value.get(field_name)
        return str(field) if field is not None else None
    return None


def value_or_none(value: Any, key: str) -> Any:
    return value.get(key) if isinstance(value, dict) else None


def int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def source_block(config: AppConfig, *, endpoint: str) -> JsonDict:
    return {
        "provider": "Digi-Key",
        "api": "Product Information V4",
        "environment": config.environment,
        "endpoint": endpoint,
        "documentation": PRODUCT_DETAILS_DOC_URL
        if "productdetails" in endpoint
        else KEYWORD_SEARCH_DOC_URL,
        "site": config.site,
        "language": config.language,
        "currency": config.currency,
    }


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
