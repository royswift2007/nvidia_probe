from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class NormalizedModel:
    model_id: str
    display_name: str = ""
    provider: str = ""
    owned_by: str = ""
    model_type: str = "unknown"
    endpoint_type: str = "unknown"
    context_length: Any = "unknown"
    max_output_tokens: Any = "unknown"
    supports_streaming: Any = "unknown"
    supports_tools: Any = "unknown"
    supports_json_mode: Any = "unknown"
    supports_vision: Any = "unknown"
    supports_embedding: Any = "unknown"
    is_free: bool | None = None
    pricing_model: str = "unknown"
    free_reason: str = "unknown"
    api_calls_30d: int | None = None
    api_calls_30d_display: str = "unknown"
    api_calls_30d_source: str = "unknown"
    usage_rank: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)


def _first_present(data: dict[str, Any], keys: tuple[str, ...], default: Any = "") -> Any:
    for key in keys:
        if key in data and data[key] not in (None, ""):
            return data[key]
    return default


def _deep_first_present(data: dict[str, Any], keys: tuple[str, ...], default: Any = "unknown") -> Any:
    candidates: list[dict[str, Any]] = [data]
    for nested_key in ("metadata", "model", "details", "capabilities", "limits"):
        nested = data.get(nested_key)
        if isinstance(nested, dict):
            candidates.append(nested)
    for candidate in candidates:
        value = _first_present(candidate, keys, None)
        if value is not None:
            return value
    return default


def infer_model_type(model: dict[str, Any]) -> str:
    explicit = str(
        _deep_first_present(
            model,
            ("model_type", "type", "task", "pipeline_tag", "category", "endpoint_type"),
            "",
        )
    ).lower()
    model_id = str(model.get("id") or model.get("model") or model.get("name") or "").lower()
    combined = f"{explicit} {model_id}"

    if any(token in combined for token in ("embedding", "embed", "retrieval")):
        return "embedding"
    if any(token in combined for token in ("rerank", "ranking", "ranker")):
        return "reranker"
    if any(token in combined for token in ("vision", "vlm", "multimodal", "ocr")):
        return "vision"
    if any(token in combined for token in ("image", "diffusion", "sdxl", "flux")):
        return "image"
    if "video" in combined:
        return "video"
    if any(token in combined for token in ("audio", "speech", "tts", "asr")):
        return "audio"
    if any(token in combined for token in ("chat", "instruct", "llm", "language", "completion", "reasoning")):
        return "chat"
    return "chat"


def _iter_key_values(value: Any, prefix: str = ""):
    if isinstance(value, dict):
        for key, nested in value.items():
            key_text = str(key)
            path = f"{prefix}.{key_text}" if prefix else key_text
            yield path, nested
            yield from _iter_key_values(nested, path)
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            path = f"{prefix}[{index}]"
            yield path, nested
            yield from _iter_key_values(nested, path)


def _to_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "y", "1"}:
            return True
        if lowered in {"false", "no", "n", "0"}:
            return False
    return None


def infer_free_status(model: dict[str, Any]) -> tuple[bool | None, str, str]:
    """Return free status from explicit metadata only.

    The probe intentionally refuses to treat a model as free unless the model
    payload contains an explicit free/no-cost hint. Unknown models are skipped
    by default so the tool does not accidentally test potentially billable
    endpoints.
    """
    explicit_free_keys = {
        "free",
        "is_free",
        "isfree",
        "free_endpoint",
        "freeendpoint",
        "free_to_use",
        "freetouse",
        "free_tier",
        "freetier",
        "no_cost",
        "nocost",
        "zero_cost",
        "zerocost",
    }
    explicit_paid_keys = {
        "paid",
        "billable",
        "metered",
        "requires_payment",
        "requirespayment",
        "requires_billing",
        "requiresbilling",
        "has_pricing",
        "haspricing",
    }
    free_values = {
        "free",
        "free_endpoint",
        "free-endpoint",
        "free_tier",
        "free-tier",
        "no_cost",
        "no-cost",
        "zero_cost",
        "zero-cost",
    }
    paid_values = {"paid", "metered", "billable", "subscription", "enterprise", "commercial"}

    pricing_model = str(
        _deep_first_present(
            model,
            ("pricing_model", "pricingModel", "pricing", "billing", "tier", "plan", "cost", "price"),
            "unknown",
        )
    )

    for path, value in _iter_key_values(model):
        key = path.split(".")[-1].split("[")[0].replace("-", "_").lower()
        bool_value = _to_bool(value)
        if key in explicit_free_keys and bool_value is True:
            return True, pricing_model, f"explicit_free_flag:{path}"
        if key in explicit_free_keys and bool_value is False:
            return False, pricing_model, f"explicit_free_false:{path}"
        if key in explicit_paid_keys and bool_value is True:
            return False, pricing_model, f"explicit_paid_flag:{path}"
        if key in {"requires_payment", "requiresbilling", "requires_billing"} and bool_value is False:
            return True, pricing_model, f"explicit_no_payment_required:{path}"

        if isinstance(value, str):
            normalized = value.strip().lower().replace(" ", "_")
            if normalized in {"free_endpoint", "free-endpoint"}:
                return True, pricing_model, f"explicit_free_badge:{path}"
            if key in {"pricing", "pricing_model", "billing", "tier", "plan", "cost", "price", "access", "badge", "badges", "label", "labels", "tag", "tags"}:
                if normalized in free_values:
                    return True, pricing_model, f"explicit_free_value:{path}"
                if normalized in paid_values:
                    return False, pricing_model, f"explicit_paid_value:{path}"
        elif isinstance(value, (int, float)) and key in {"price", "cost", "amount", "unit_price", "unitprice"}:
            if value > 0:
                return False, pricing_model, f"positive_price:{path}"
            if value == 0:
                return True, pricing_model, f"zero_price:{path}"

    return None, pricing_model, "unknown_cost"


def parse_human_count(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        return int(value) if value >= 0 else None
    if not isinstance(value, str):
        return None

    text = value.strip().lower().replace(",", "")
    if not text:
        return None

    pattern = re.compile(r"(?P<number>\d+(?:\.\d+)?)\s*(?P<suffix>k|m|b|thousand|million|billion)?")
    match = pattern.search(text)
    if not match:
        return None
    number = float(match.group("number"))
    suffix = match.group("suffix") or ""
    multiplier = {
        "": 1,
        "k": 1_000,
        "thousand": 1_000,
        "m": 1_000_000,
        "million": 1_000_000,
        "b": 1_000_000_000,
        "billion": 1_000_000_000,
    }.get(suffix, 1)
    count = int(number * multiplier)
    return count if count >= 0 else None


def format_human_count(count: int | None) -> str:
    if count is None:
        return "unknown"
    if count >= 1_000_000_000:
        return f"{count / 1_000_000_000:.1f}B".replace(".0B", "B")
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M".replace(".0M", "M")
    if count >= 1_000:
        return f"{count / 1_000:.1f}K".replace(".0K", "K")
    return str(count)


def infer_api_calls_30d(model: dict[str, Any]) -> tuple[int | None, str, str]:
    known_keys = {
        "apicalls30d",
        "apicallslast30days",
        "apicallsinlast30days",
        "apiusage30d",
        "apiusagelast30days",
        "last30daysapicalls",
        "monthlyapicalls",
        "monthlyusage",
        "calls30d",
        "requests30d",
        "inferences30d",
        "usage30d",
    }

    fallback: tuple[int | None, str, str] = (None, "unknown", "unknown")
    for path, value in _iter_key_values(model):
        key = path.split(".")[-1].split("[")[0]
        normalized_key = re.sub(r"[^a-z0-9]", "", key.lower())
        normalized_path = re.sub(r"[^a-z0-9]", "", path.lower())
        parsed = parse_human_count(value)
        if parsed is None:
            continue

        if normalized_key in known_keys or normalized_path in known_keys:
            display = str(value) if isinstance(value, str) else format_human_count(parsed)
            return parsed, display, path

        has_api_signal = any(token in normalized_path for token in ("api", "request", "inference"))
        has_call_signal = any(token in normalized_path for token in ("call", "usage", "request", "inference"))
        has_30d_signal = any(token in normalized_path for token in ("30", "last30", "month", "monthly"))
        if has_api_signal and has_call_signal and has_30d_signal:
            display = str(value) if isinstance(value, str) else format_human_count(parsed)
            return parsed, display, path

        if isinstance(value, str):
            text = value.lower()
            if "api" in text and "call" in text and ("30" in text or "last" in text or "month" in text):
                return parsed, value, path

        if fallback[0] is None and has_api_signal and has_call_signal:
            display = str(value) if isinstance(value, str) else format_human_count(parsed)
            fallback = (parsed, display, path)

    return fallback


def normalize_model(model: dict[str, Any]) -> NormalizedModel:
    model_id = str(_first_present(model, ("id", "model", "name"), "")).strip()
    model_type = infer_model_type(model)
    is_free, pricing_model, free_reason = infer_free_status(model)
    api_calls_30d, api_calls_30d_display, api_calls_30d_source = infer_api_calls_30d(model)
    return NormalizedModel(
        model_id=model_id,
        display_name=str(_deep_first_present(model, ("display_name", "displayName", "name", "id"), model_id)),
        provider=str(_deep_first_present(model, ("provider", "publisher", "organization"), "")),
        owned_by=str(_deep_first_present(model, ("owned_by", "ownedBy", "owner"), "")),
        model_type=model_type,
        endpoint_type=str(_deep_first_present(model, ("endpoint_type", "endpoint", "api_type", "type"), model_type)),
        context_length=_deep_first_present(
            model,
            (
                "context_length",
                "contextWindow",
                "context_window",
                "max_context_length",
                "max_context_window",
                "input_token_limit",
                "max_input_tokens",
            ),
            "unknown",
        ),
        max_output_tokens=_deep_first_present(
            model,
            ("max_output_tokens", "output_token_limit", "max_tokens", "max_completion_tokens"),
            "unknown",
        ),
        supports_streaming=_deep_first_present(model, ("supports_streaming", "streaming"), "unknown"),
        supports_tools=_deep_first_present(model, ("supports_tools", "tools", "tool_calling"), "unknown"),
        supports_json_mode=_deep_first_present(model, ("supports_json_mode", "json_mode"), "unknown"),
        supports_vision=_deep_first_present(model, ("supports_vision", "vision"), model_type == "vision"),
        supports_embedding=_deep_first_present(model, ("supports_embedding", "embedding"), model_type == "embedding"),
        is_free=is_free,
        pricing_model=pricing_model,
        free_reason=free_reason,
        api_calls_30d=api_calls_30d,
        api_calls_30d_display=api_calls_30d_display,
        api_calls_30d_source=api_calls_30d_source,
        raw=model,
    )


def normalize_models(payload: Any) -> list[NormalizedModel]:
    if isinstance(payload, dict):
        raw_models = payload.get("data") or payload.get("models") or payload.get("items") or []
    elif isinstance(payload, list):
        raw_models = payload
    else:
        raw_models = []

    normalized: list[NormalizedModel] = []
    seen: set[str] = set()
    for item in raw_models:
        if not isinstance(item, dict):
            continue
        model = normalize_model(item)
        if not model.model_id or model.model_id in seen:
            continue
        normalized.append(model)
        seen.add(model.model_id)
    normalized.sort(key=lambda item: item.model_id.lower())
    return normalized


def sort_models_by_api_calls_30d(models: list[NormalizedModel]) -> list[NormalizedModel]:
    ranked = sorted(
        models,
        key=lambda item: (
            item.api_calls_30d is None,
            -(item.api_calls_30d or 0),
            item.model_id.lower(),
        ),
    )
    for index, model in enumerate(ranked, start=1):
        model.usage_rank = index
    return ranked


def should_test_model(
    model: NormalizedModel,
    include_types: tuple[str, ...],
    exclude_types: tuple[str, ...],
    only_model: str | None = None,
    free_only: bool = True,
    allow_unknown_cost: bool = False,
) -> tuple[bool, str]:
    if only_model and model.model_id != only_model:
        return False, "not_selected"
    if free_only:
        if model.is_free is False:
            return False, f"not_free:{model.free_reason}"
        if model.is_free is None and not allow_unknown_cost:
            return False, f"unknown_cost:{model.free_reason}"
    if model.model_type in exclude_types:
        return False, f"excluded_type:{model.model_type}"
    if include_types and model.model_type not in include_types:
        return False, f"not_included_type:{model.model_type}"
    return True, "selected"
