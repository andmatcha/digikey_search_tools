from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .config import AppConfig
from .errors import DigikeyApiError


JsonDict = dict[str, Any]
PRODUCT_DETAILS_DOC_URL = (
    "https://developer.digikey.com/products/product-information-v4/"
    "productsearch/productdetails"
)
KEYWORD_SEARCH_DOC_URL = (
    "https://developer.digikey.com/products/product-information-v4/"
    "productsearch/keywordsearch"
)


class JsonResponseCache:
    def __init__(self, cache_dir: Path, ttl_seconds: int, *, refresh: bool = False) -> None:
        self.cache_dir = cache_dir
        self.ttl_seconds = ttl_seconds
        self.refresh = refresh

    def get(self, key: str) -> JsonDict | None:
        if self.refresh or self.ttl_seconds <= 0:
            return None
        path = self.cache_dir / f"{key}.json"
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        cached_at = payload.get("cached_at_epoch")
        if not isinstance(cached_at, (int, float)):
            return None
        if time.time() - cached_at > self.ttl_seconds:
            return None
        data = payload.get("data")
        return data if isinstance(data, dict) else None

    def set(self, key: str, data: JsonDict) -> None:
        if self.ttl_seconds <= 0:
            return
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path = self.cache_dir / f"{key}.json"
        tmp_path = path.with_suffix(".tmp")
        payload = {
            "cached_at_epoch": time.time(),
            "data": data,
        }
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp_path.replace(path)


class DigikeyClient:
    def __init__(self, config: AppConfig, *, cache_dir: Path | None = None, refresh: bool = False) -> None:
        self.config = config
        self.cache = JsonResponseCache(
            cache_dir or Path(".cache/digikey"),
            config.cache_ttl_seconds,
            refresh=refresh,
        )
        self._access_token: str | None = None
        self._access_token_expires_at = 0.0

    def product_details(
        self,
        product_number: str,
        *,
        manufacturer_id: str | None = None,
        includes: str | None = None,
    ) -> tuple[JsonDict, bool]:
        query: dict[str, str] = {}
        if manufacturer_id:
            query["manufacturerId"] = manufacturer_id
        if includes:
            query["includes"] = includes
        cache_key = self._cache_key("productdetails", product_number, query)
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached, True

        encoded = urllib.parse.quote(product_number, safe="")
        data = self._get_json(f"/products/v4/search/{encoded}/productdetails", query=query)
        self.cache.set(cache_key, data)
        return data, False

    def keyword_search(
        self,
        keywords: str,
        *,
        limit: int = 10,
        offset: int = 0,
        filter_options: JsonDict | None = None,
        sort_field: str = "QuantityAvailable",
        sort_order: str = "Descending",
        includes: str | None = None,
    ) -> tuple[JsonDict, bool, JsonDict]:
        body: JsonDict = {
            "Keywords": keywords,
            "Limit": limit,
            "Offset": offset,
            "SortOptions": {
                "Field": sort_field,
                "SortOrder": sort_order,
            },
        }
        if filter_options:
            body["FilterOptionsRequest"] = filter_options
        cache_key = self._cache_key("keyword", body, includes or "")
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached, True, body

        query = {"includes": includes} if includes else None
        data = self._post_json("/products/v4/search/keyword", body=body, query=query)
        self.cache.set(cache_key, data)
        return data, False, body

    def _cache_key(self, *parts: object) -> str:
        material = {
            "environment": self.config.environment,
            "site": self.config.site,
            "language": self.config.language,
            "currency": self.config.currency,
            "account_id": self.config.account_id or "",
            "parts": parts,
        }
        encoded = json.dumps(material, sort_keys=True, ensure_ascii=True, default=str)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def _get_json(self, path: str, *, query: dict[str, str] | None = None) -> JsonDict:
        url = f"{self.config.api_base_url}{path}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"
        return self._request_json("GET", url, headers=self._api_headers(), auth=True)

    def _post_json(
        self,
        path: str,
        *,
        body: JsonDict,
        query: dict[str, str] | None = None,
    ) -> JsonDict:
        url = f"{self.config.api_base_url}{path}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"
        headers = self._api_headers()
        headers["Content-Type"] = "application/json"
        encoded_body = json.dumps(body).encode("utf-8")
        return self._request_json("POST", url, headers=headers, body=encoded_body, auth=True)

    def _api_headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._get_access_token()}",
            "User-Agent": "digikey-search-tools/0.1",
            "X-DIGIKEY-Client-Id": self.config.client_id,
            "X-DIGIKEY-Locale-Currency": self.config.currency,
            "X-DIGIKEY-Locale-Language": self.config.language,
            "X-DIGIKEY-Locale-Site": self.config.site,
        }
        if self.config.account_id:
            headers["X-DIGIKEY-Account-Id"] = self.config.account_id
        return headers

    def _get_access_token(self) -> str:
        if self._access_token and time.time() < self._access_token_expires_at - 30:
            return self._access_token
        form = urllib.parse.urlencode(
            {
                "client_id": self.config.client_id,
                "client_secret": self.config.client_secret,
                "grant_type": "client_credentials",
            }
        ).encode("utf-8")
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "digikey-search-tools/0.1",
        }
        payload = self._request_json(
            "POST",
            self.config.token_url,
            headers=headers,
            body=form,
            auth=False,
        )
        token = payload.get("access_token")
        if not isinstance(token, str) or not token:
            raise DigikeyApiError("Digi-Key token response did not include access_token")
        expires_in = int_or_default(payload.get("expires_in"), 600)
        self._access_token = token
        self._access_token_expires_at = time.time() + expires_in
        return token

    def _request_json(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        body: bytes | None = None,
        auth: bool,
    ) -> JsonDict:
        last_error: DigikeyApiError | None = None
        did_refresh_token = False
        for attempt in range(self.config.max_retries + 1):
            request = urllib.request.Request(url, data=body, headers=headers, method=method)
            try:
                with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                    raw = response.read().decode("utf-8")
                    parsed = json.loads(raw) if raw else {}
                    if not isinstance(parsed, dict):
                        raise DigikeyApiError("Digi-Key returned non-object JSON")
                    return parsed
            except urllib.error.HTTPError as error:
                response_body = read_error_body(error)
                headers_dict = dict(error.headers.items())
                if auth and error.code == 401 and not did_refresh_token:
                    self._access_token = None
                    headers = self._api_headers()
                    did_refresh_token = True
                    continue
                last_error = DigikeyApiError(
                    f"Digi-Key API returned HTTP {error.code}",
                    status_code=error.code,
                    response_body=response_body,
                    headers=headers_dict,
                )
                if error.code in {429, 500, 502, 503, 504} and attempt < self.config.max_retries:
                    time.sleep(parse_retry_after(error.headers.get("Retry-After")) or 2**attempt)
                    continue
                raise last_error
            except urllib.error.URLError as error:
                last_error = DigikeyApiError(f"Network error: {error.reason}")
                if attempt < self.config.max_retries:
                    time.sleep(2**attempt)
                    continue
                raise last_error
            except json.JSONDecodeError as error:
                raise DigikeyApiError(f"Digi-Key returned invalid JSON: {error}") from error
        if last_error:
            raise last_error
        raise DigikeyApiError("Digi-Key request failed")


def read_error_body(error: urllib.error.HTTPError) -> Any:
    raw = error.read().decode("utf-8", errors="replace")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def parse_retry_after(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return max(int(value), 0)
    except ValueError:
        return None


def int_or_default(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
