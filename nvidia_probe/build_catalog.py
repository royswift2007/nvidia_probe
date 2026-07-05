from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests

from .models import NormalizedModel, enrich_model_heat_metrics, format_human_count, infer_capability_profile, infer_created_at, parse_human_count

DEFAULT_BUILD_CATALOG_URL = "https://build.nvidia.com/models?filters=nimType%3Anim_type_preview"


@dataclass(slots=True)
class BuildCatalogModel:
    model_id: str
    publisher: str
    name: str
    display_name: str
    is_available: bool | None
    api_calls_30d: int | None
    api_calls_30d_display: str
    api_calls_30d_source: str
    page: int
    created_at_utc: str = ""
    created_at_source: str = "unknown"
    raw: dict[str, Any] = field(default_factory=dict)

    def to_state(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "publisher": self.publisher,
            "name": self.name,
            "display_name": self.display_name,
            "is_available": self.is_available,
            "api_calls_30d": self.api_calls_30d,
            "api_calls_30d_display": self.api_calls_30d_display,
            "api_calls_30d_source": self.api_calls_30d_source,
            "page": self.page,
            "created_at_utc": self.created_at_utc,
            "created_at_source": self.created_at_source,
        }


@dataclass(slots=True)
class BuildCatalogResult:
    models: list[BuildCatalogModel]
    total_count: int | None
    pages_fetched: int
    url: str
    errors: list[str] = field(default_factory=list)

    def to_state(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "total_count": self.total_count,
            "pages_fetched": self.pages_fetched,
            "errors": self.errors,
            "models": [model.to_state() for model in self.models],
        }


@dataclass(slots=True)
class BuildCatalogApplyResult:
    catalog_total_count: int | None
    catalog_models_count: int
    matched_count: int
    unmatched_model_ids: list[str]


@dataclass(slots=True)
class _ParsedCatalogPage:
    resources: list[dict[str, Any]]
    total_count: int | None


def _page_url(base_url: str, page: int) -> str:
    parsed = urlparse(base_url)
    query_items = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query_items["page"] = str(page)
    return urlunparse(parsed._replace(query=urlencode(query_items)))


def _expand_flight_payload(text: str) -> str:
    # NVIDIA Build is rendered by Next.js. The useful search data is embedded in
    # escaped React Flight script chunks instead of a plain JSON script tag.
    # HTML-unescape first, then unescape JSON quotes so the embedded resource
    # arrays can be parsed with json.loads.
    return html.unescape(text).replace('\\"', '"')


def _find_matching_array_end(text: str, start: int) -> int | None:
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return index + 1
    return None


def _extract_endpoint_group(expanded_text: str) -> _ParsedCatalogPage:
    marker = '"groupValue":"ENDPOINT"'
    marker_index = expanded_text.find(marker)
    if marker_index < 0:
        return _ParsedCatalogPage([], None)

    total_count: int | None = None
    total_match = re.search(r'"groupValue":"ENDPOINT","totalCount":(\d+),"resources":\[', expanded_text[marker_index : marker_index + 500])
    if total_match:
        total_count = int(total_match.group(1))

    resources_token = '"resources":['
    resources_index = expanded_text.find(resources_token, marker_index)
    if resources_index < 0:
        return _ParsedCatalogPage([], total_count)

    array_start = expanded_text.find("[", resources_index)
    if array_start < 0:
        return _ParsedCatalogPage([], total_count)

    array_end = _find_matching_array_end(expanded_text, array_start)
    if array_end is None:
        return _ParsedCatalogPage([], total_count)

    try:
        resources = json.loads(expanded_text[array_start:array_end])
    except json.JSONDecodeError:
        return _ParsedCatalogPage([], total_count)

    if not isinstance(resources, list):
        return _ParsedCatalogPage([], total_count)
    return _ParsedCatalogPage([item for item in resources if isinstance(item, dict)], total_count)


def parse_build_catalog_page(text: str) -> _ParsedCatalogPage:
    return _extract_endpoint_group(_expand_flight_payload(text))


def _label_values(resource: dict[str, Any], key: str) -> tuple[list[str], list[str]]:
    values: list[str] = []
    unresolved: list[str] = []
    for label in resource.get("labels") or []:
        if not isinstance(label, dict) or label.get("key") != key:
            continue
        values.extend(str(item) for item in (label.get("values") or []) if item not in (None, ""))
        unresolved.extend(str(item) for item in (label.get("unresolvedValues") or []) if item not in (None, ""))
    return values, unresolved


def _attribute_value(resource: dict[str, Any], keys: tuple[str, ...]) -> Any:
    normalized_keys = {re.sub(r"[^a-z0-9]", "", key.lower()) for key in keys}
    for attribute in resource.get("attributes") or []:
        if not isinstance(attribute, dict):
            continue
        key = str(attribute.get("key") or "")
        normalized_key = re.sub(r"[^a-z0-9]", "", key.lower())
        if normalized_key in normalized_keys:
            return attribute.get("value")
    return None


def _bool_value(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y"}:
            return True
        if lowered in {"false", "0", "no", "n"}:
            return False
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    return None


def _catalog_model_from_resource(resource: dict[str, Any], page: int) -> BuildCatalogModel | None:
    nim_values, nim_unresolved = _label_values(resource, "nimType")
    is_free_endpoint = "Free Endpoint" in nim_values or "nim_type_preview" in nim_unresolved
    if not is_free_endpoint:
        return None

    publisher_values, _ = _label_values(resource, "publisher")
    publisher = publisher_values[0] if publisher_values else ""
    name = str(resource.get("name") or "").strip()
    if not name:
        resource_id = str(resource.get("resourceId") or "")
        name = resource_id.rsplit("/", 1)[-1].strip()
    if not name:
        return None

    model_id = f"{publisher}/{name}" if publisher else name
    display_name = str(resource.get("displayName") or name)
    available = _bool_value(_attribute_value(resource, ("AVAILABLE", "available")))
    raw_calls = _attribute_value(
        resource,
        (
            "last_month_api_invocation_count",
            "lastMonthApiInvocationCount",
            "api_calls_30d",
            "apiCalls30d",
        ),
    )
    api_calls = parse_human_count(raw_calls)
    api_calls_display = str(raw_calls) if isinstance(raw_calls, str) and raw_calls else format_human_count(api_calls)
    created_at_utc, created_at_source = infer_created_at(resource)

    return BuildCatalogModel(
        model_id=model_id,
        publisher=publisher,
        name=name,
        display_name=display_name,
        is_available=available,
        api_calls_30d=api_calls,
        api_calls_30d_display=api_calls_display,
        api_calls_30d_source="build_catalog:last_month_api_invocation_count" if api_calls is not None else "unknown",
        page=page,
        created_at_utc=created_at_utc,
        created_at_source=f"build_catalog:{created_at_source}" if created_at_source != "unknown" else "unknown",
        raw=resource,
    )


def fetch_free_endpoint_catalog(
    url: str = DEFAULT_BUILD_CATALOG_URL,
    timeout: float = 60.0,
    user_agent: str = "nvidia-model-probe/0.1.0",
    max_pages: int = 10,
) -> BuildCatalogResult:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
    )
    models_by_id: dict[str, BuildCatalogModel] = {}
    total_count: int | None = None
    errors: list[str] = []
    pages_fetched = 0

    try:
        for page in range(1, max_pages + 1):
            page_url = _page_url(url, page)
            try:
                response = session.get(page_url, timeout=timeout)
                response.raise_for_status()
            except requests.RequestException as exc:
                errors.append(f"page={page}: {exc}")
                break

            pages_fetched += 1
            parsed = parse_build_catalog_page(response.text)
            if parsed.total_count is not None:
                total_count = parsed.total_count

            new_count = 0
            for resource in parsed.resources:
                catalog_model = _catalog_model_from_resource(resource, page)
                if catalog_model is None:
                    continue
                key = catalog_model.model_id.lower()
                if key in models_by_id:
                    continue
                models_by_id[key] = catalog_model
                new_count += 1

            if total_count is not None and len(models_by_id) >= total_count:
                break
            if not parsed.resources or (page > 1 and new_count == 0):
                break
    finally:
        session.close()

    return BuildCatalogResult(
        models=list(models_by_id.values()),
        total_count=total_count,
        pages_fetched=pages_fetched,
        url=url,
        errors=errors,
    )


def _normalized_match_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _add_lookup(lookup: dict[str, list[NormalizedModel]], key: str, model: NormalizedModel) -> None:
    if not key:
        return
    lookup.setdefault(key, []).append(model)


def apply_build_catalog_to_models(
    models: list[NormalizedModel],
    catalog_result: BuildCatalogResult,
) -> BuildCatalogApplyResult:
    exact_lookup: dict[str, NormalizedModel] = {}
    normalized_lookup: dict[str, list[NormalizedModel]] = {}

    for model in models:
        candidate_values = {model.model_id, model.display_name}
        if "/" in model.model_id:
            candidate_values.add(model.model_id.rsplit("/", 1)[-1])
        for value in candidate_values:
            value = str(value or "").strip()
            if not value:
                continue
            exact_lookup.setdefault(value.lower(), model)
            _add_lookup(normalized_lookup, _normalized_match_key(value), model)

    matched = 0
    unmatched: list[str] = []
    for catalog_model in catalog_result.models:
        exact_candidates = [catalog_model.model_id.lower(), catalog_model.name.lower(), catalog_model.display_name.lower()]
        target = next((exact_lookup[key] for key in exact_candidates if key in exact_lookup), None)
        if target is None:
            normalized_candidates = [
                _normalized_match_key(catalog_model.model_id),
                _normalized_match_key(catalog_model.name),
                _normalized_match_key(catalog_model.display_name),
            ]
            for key in normalized_candidates:
                matches = normalized_lookup.get(key) or []
                unique_matches = list({id(item): item for item in matches}.values())
                if len(unique_matches) == 1:
                    target = unique_matches[0]
                    break

        if target is None:
            unmatched.append(catalog_model.model_id)
            continue

        matched += 1
        target.is_free = True
        target.pricing_model = "free_endpoint"
        target.free_reason = f"build_catalog:Free Endpoint:{catalog_model.model_id}"
        if not target.display_name:
            target.display_name = catalog_model.display_name
        if not target.provider:
            target.provider = catalog_model.publisher
        if catalog_model.api_calls_30d is not None:
            target.api_calls_30d = catalog_model.api_calls_30d
            target.api_calls_30d_display = catalog_model.api_calls_30d_display
            target.api_calls_30d_source = catalog_model.api_calls_30d_source
        if catalog_model.created_at_utc:
            target.created_at_utc = catalog_model.created_at_utc
            target.created_at_source = catalog_model.created_at_source
            enrich_model_heat_metrics(target)
        capability_profile = infer_capability_profile(catalog_model.raw, target.model_type)
        target.supports_image_input = capability_profile["supports_image_input"]
        target.supports_coding = capability_profile["supports_coding"]
        target.supports_reasoning = capability_profile["supports_reasoning"]
        target.supports_function_calling = capability_profile["supports_function_calling"]
        if target.supports_tools == "unknown":
            target.supports_tools = capability_profile["supports_tools"]
        if target.supports_vision in ("unknown", False):
            target.supports_vision = capability_profile["supports_vision"]
        target.capability_tags = capability_profile["capability_tags"]
        target.usecase_tags = capability_profile["usecase_tags"]
        target.deployment_providers = capability_profile["deployment_providers"]
        target.raw.setdefault("_build_catalog", catalog_model.to_state())

    return BuildCatalogApplyResult(
        catalog_total_count=catalog_result.total_count,
        catalog_models_count=len(catalog_result.models),
        matched_count=matched,
        unmatched_model_ids=unmatched,
    )
