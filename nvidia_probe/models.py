from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
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
    context_length_source: str = "unknown"
    max_output_tokens: Any = "unknown"
    max_output_tokens_source: str = "unknown"
    supports_streaming: Any = "unknown"
    supports_tools: Any = "unknown"
    supports_json_mode: Any = "unknown"
    supports_vision: Any = "unknown"
    supports_image_input: Any = "unknown"
    supports_coding: Any = "unknown"
    supports_reasoning: Any = "unknown"
    supports_function_calling: Any = "unknown"
    supports_embedding: Any = "unknown"
    capability_tags: str = ""
    usecase_tags: str = ""
    deployment_providers: str = ""
    is_free: bool | None = None
    pricing_model: str = "unknown"
    free_reason: str = "unknown"
    api_calls_30d: int | None = None
    api_calls_30d_display: str = "unknown"
    api_calls_30d_source: str = "unknown"
    usage_rank: int | None = None
    created_at_utc: str = ""
    created_at_source: str = "unknown"
    model_age_days: float | None = None
    api_calls_per_day: float | None = None
    projected_30d_calls: int | None = None
    projected_30d_calls_display: str = "unknown"
    trending_rank: int | None = None
    newest_rank: int | None = None
    selection_rank: int | None = None
    selection_bucket: str = ""
    selection_reason: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ModelSelectionResult:
    models: list[NormalizedModel]
    summary: dict[str, Any]


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


_MISSING_METADATA_VALUES = {"", "unknown", "none", "null", "n/a", "na"}
_CONTEXT_PATH_TOKENS = (
    "contextlength",
    "contextwindow",
    "contexttokens",
    "contextsize",
    "maxcontext",
    "maxinputtokens",
    "inputtokenlimit",
    "inputtokens",
    "maxsequencelength",
    "sequencelength",
    "modelmaxlength",
    "maxpositionembeddings",
)
_MAX_OUTPUT_PATH_TOKENS = (
    "maxoutputtokens",
    "outputtokenlimit",
    "outputtokens",
    "maxcompletiontokens",
    "completiontokenlimit",
    "maxgenerationtokens",
    "generationtokenlimit",
    "maxtokens",
)
_KNOWN_MODEL_SPECS: dict[str, dict[str, int]] = {
    "z-ai/glm-5.2": {"context_length": 1_000_000, "max_output_tokens": 32_768},
    "minimaxai/minimax-m3": {"context_length": 1_000_000},
    "nvidia/nemotron-3-ultra-550b-a55b": {"context_length": 1_000_000},
    "deepseek-ai/deepseek-v4-flash": {"context_length": 1_000_000},
    "deepseek-ai/deepseek-v4-pro": {"context_length": 1_000_000},
    "mistralai/mistral-medium-3.5-128b": {"context_length": 262_144},
    "moonshotai/kimi-k2.6": {"context_length": 256_000},
    "stepfun-ai/step-3.7-flash": {"context_length": 256_000},
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning": {"context_length": 256_000},
    "nvidia/nemotron-3.5-content-safety": {"context_length": 128_000},
}


def is_missing_metadata_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() in _MISSING_METADATA_VALUES
    return False


def _normalized_path(path: str) -> str:
    return re.sub(r"[^a-z0-9]", "", path.lower())


def _quantity_from_number_and_unit(number: str, unit: str) -> int | None:
    try:
        numeric = float(number.replace(",", ""))
    except ValueError:
        return None
    if numeric <= 0:
        return None
    unit = unit.lower()
    if unit == "k":
        return int(numeric * 1_000)
    if unit == "m":
        return int(numeric * 1_000_000)
    return int(numeric)


def parse_token_quantity(value: Any, minimum_without_unit: int = 1) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value) if value >= minimum_without_unit else None
    if not isinstance(value, str):
        return None

    text = value.strip()
    if not text:
        return None

    unit_match = re.search(r"(?<![a-z0-9.])(\d[\d,]*(?:\.\d+)?)\s*([kKmM])\b", text)
    if unit_match:
        return _quantity_from_number_and_unit(unit_match.group(1), unit_match.group(2))

    plain_match = re.search(r"(?<![\d.])(\d[\d,]+|\d{4,})(?![\d.])", text)
    if not plain_match:
        return None
    try:
        numeric = int(plain_match.group(1).replace(",", ""))
    except ValueError:
        return None
    return numeric if numeric >= minimum_without_unit else None


def _token_quantities_from_text(text: str, minimum_without_unit: int = 4_096) -> list[int]:
    values: list[int] = []
    for match in re.finditer(r"(?<![a-z0-9.])(\d[\d,]*(?:\.\d+)?)\s*([kKmM])\b", text):
        parsed = _quantity_from_number_and_unit(match.group(1), match.group(2))
        if parsed is not None:
            values.append(parsed)
    for match in re.finditer(r"(?<![\d.])(\d[\d,]+|\d{4,})(?![\d.])", text):
        parsed = parse_token_quantity(match.group(1), minimum_without_unit=minimum_without_unit)
        if parsed is not None:
            values.append(parsed)
    return values


def _clean_spec_text(text: str) -> str:
    return html.unescape(text).replace('\\"', '"').replace("\\u003c", "<").replace("\\u003e", ">").replace("\\n", "\n")


def _infer_structured_token_specs(model: dict[str, Any], source_prefix: str) -> dict[str, Any]:
    context_candidates: list[tuple[int, str]] = []
    max_output_candidates: list[tuple[int, str]] = []
    for path, value in _iter_key_values(model):
        normalized = _normalized_path(path)
        if normalized.endswith("minimum") or normalized.endswith("min"):
            continue
        parsed = parse_token_quantity(value)
        if parsed is None:
            continue
        if any(token in normalized for token in _CONTEXT_PATH_TOKENS):
            context_candidates.append((parsed, f"{source_prefix}:{path}"))
        if any(token in normalized for token in _MAX_OUTPUT_PATH_TOKENS):
            max_output_candidates.append((parsed, f"{source_prefix}:{path}"))

    result: dict[str, Any] = {
        "context_length": "unknown",
        "context_length_source": "unknown",
        "max_output_tokens": "unknown",
        "max_output_tokens_source": "unknown",
    }
    if context_candidates:
        value, source = max(context_candidates, key=lambda item: item[0])
        result["context_length"] = value
        result["context_length_source"] = source
    if max_output_candidates:
        value, source = max(max_output_candidates, key=lambda item: item[0])
        result["max_output_tokens"] = value
        result["max_output_tokens_source"] = source
    return result


def _infer_text_token_specs(text: str, source_prefix: str) -> dict[str, Any]:
    cleaned = _clean_spec_text(text)
    context_candidates: list[int] = []
    max_output_candidates: list[int] = []

    lowered = cleaned.lower()
    for match in re.finditer(r"context", lowered):
        segment = cleaned[max(0, match.start() - 180) : match.end() + 260]
        context_candidates.extend(_token_quantities_from_text(segment, minimum_without_unit=4_096))

    for match in re.finditer(
        r"[\"'](?:max_tokens|maxTokens)[\"']\s*:\s*\{.{0,5000}?[\"']maximum[\"']\s*:\s*(\d[\d,]*)",
        cleaned,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        parsed = parse_token_quantity(match.group(1), minimum_without_unit=1)
        if parsed is not None:
            max_output_candidates.append(parsed)

    for match in re.finditer(r"(?:max(?:imum)?\s+output|output\s+token|completion\s+token|generation\s+token)", lowered):
        segment = cleaned[max(0, match.start() - 80) : match.end() + 180]
        max_output_candidates.extend(_token_quantities_from_text(segment, minimum_without_unit=1_024))

    result: dict[str, Any] = {
        "context_length": "unknown",
        "context_length_source": "unknown",
        "max_output_tokens": "unknown",
        "max_output_tokens_source": "unknown",
    }
    if context_candidates:
        result["context_length"] = max(context_candidates)
        result["context_length_source"] = f"{source_prefix}:text"
    if max_output_candidates:
        result["max_output_tokens"] = max(max_output_candidates)
        result["max_output_tokens_source"] = f"{source_prefix}:schema_or_text"
    return result


def _infer_known_model_specs(model_id: str, display_name: str = "") -> dict[str, Any]:
    key = model_id.strip().lower()
    known = dict(_KNOWN_MODEL_SPECS.get(key, {}))
    text_candidates = _token_quantities_from_text(f"{model_id} {display_name}", minimum_without_unit=4_096)
    if text_candidates and "context_length" not in known:
        known["context_length"] = max(text_candidates)

    result: dict[str, Any] = {
        "context_length": "unknown",
        "context_length_source": "unknown",
        "max_output_tokens": "unknown",
        "max_output_tokens_source": "unknown",
    }
    if "context_length" in known:
        result["context_length"] = known["context_length"]
        result["context_length_source"] = "known_model_specs"
    if "max_output_tokens" in known:
        result["max_output_tokens"] = known["max_output_tokens"]
        result["max_output_tokens_source"] = "known_model_specs"
    return result


def infer_token_specs(model: dict[str, Any], text: str = "", source_prefix: str = "metadata") -> dict[str, Any]:
    result = _infer_structured_token_specs(model, source_prefix)
    if text:
        text_result = _infer_text_token_specs(text, source_prefix)
        if is_missing_metadata_value(result["context_length"]):
            result["context_length"] = text_result["context_length"]
            result["context_length_source"] = text_result["context_length_source"]
        if is_missing_metadata_value(result["max_output_tokens"]):
            result["max_output_tokens"] = text_result["max_output_tokens"]
            result["max_output_tokens_source"] = text_result["max_output_tokens_source"]

    model_id = str(model.get("id") or model.get("model") or model.get("name") or "")
    display_name = str(model.get("display_name") or model.get("displayName") or "")
    known_result = _infer_known_model_specs(model_id, display_name)
    if is_missing_metadata_value(result["context_length"]):
        result["context_length"] = known_result["context_length"]
        result["context_length_source"] = known_result["context_length_source"]
    if is_missing_metadata_value(result["max_output_tokens"]):
        result["max_output_tokens"] = known_result["max_output_tokens"]
        result["max_output_tokens_source"] = known_result["max_output_tokens_source"]
    return result


def apply_token_specs_to_model(model: NormalizedModel, specs: dict[str, Any], overwrite: bool = False) -> tuple[bool, bool]:
    context_updated = False
    max_output_updated = False
    if overwrite or is_missing_metadata_value(model.context_length):
        if not is_missing_metadata_value(specs.get("context_length")):
            model.context_length = specs.get("context_length")
            model.context_length_source = str(specs.get("context_length_source") or "unknown")
            context_updated = True
    if overwrite or is_missing_metadata_value(model.max_output_tokens):
        if not is_missing_metadata_value(specs.get("max_output_tokens")):
            model.max_output_tokens = specs.get("max_output_tokens")
            model.max_output_tokens_source = str(specs.get("max_output_tokens_source") or "unknown")
            max_output_updated = True
    return context_updated, max_output_updated


def _format_utc_datetime(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_datetime_utc(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        timestamp = float(value) / 1000 if value > 10_000_000_000 else float(value)
        try:
            parsed = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if re.fullmatch(r"\d+(?:\.\d+)?", text):
            return parse_datetime_utc(float(text))
        normalized = text.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
    else:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _as_text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        values: list[str] = []
        for nested in value.values():
            values.extend(_as_text_list(nested))
        return values
    if isinstance(value, (list, tuple, set)):
        values = []
        for item in value:
            values.extend(_as_text_list(item))
        return values
    if isinstance(value, (int, float, bool)):
        return [str(value)]
    return []


def _csv_unique(values: list[str]) -> str:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return ", ".join(result)


def _truthy_from_tokens(tokens: list[str], keywords: tuple[str, ...]) -> bool | str:
    normalized = " | ".join(tokens).lower().replace("_", "-")
    if any(keyword in normalized for keyword in keywords):
        return True
    return "unknown"


def _label_values_from_raw(model: dict[str, Any], label_key: str) -> list[str]:
    values: list[str] = []
    target = label_key.lower()
    for path, value in _iter_key_values(model):
        key = path.split(".")[-1].split("[")[0].lower()
        if key == target:
            values.extend(_as_text_list(value))
        if key == "labels" and isinstance(value, list):
            for label in value:
                if not isinstance(label, dict):
                    continue
                if str(label.get("key") or "").lower() == target:
                    values.extend(_as_text_list(label.get("values")))
                    values.extend(_as_text_list(label.get("unresolvedValues")))
    return values


def infer_capability_profile(model: dict[str, Any], model_type: str) -> dict[str, Any]:
    general_tags = _label_values_from_raw(model, "general")
    usecase_tags = _label_values_from_raw(model, "usecase")
    cloud_partners = _label_values_from_raw(model, "cloudPartnerType")
    playground_types = _label_values_from_raw(model, "playgroundType")
    text_tokens = general_tags + usecase_tags + playground_types + [str(model.get("id") or model.get("model") or model.get("name") or "")]
    all_text = " | ".join(text_tokens).lower().replace("_", "-")

    supports_image_input: Any = _truthy_from_tokens(
        text_tokens,
        (
            "image-to-text",
            "image text",
            "image-text",
            "vision",
            "vlm",
            "visual",
            "ocr",
            "multimodal",
            "vision-language",
        ),
    )
    supports_vision: Any = supports_image_input if supports_image_input is True else (model_type == "vision" or "vision" in all_text or "vlm" in all_text)
    supports_coding: Any = _truthy_from_tokens(text_tokens, ("coding", "code generation", "code-generation", "code"))
    supports_reasoning: Any = _truthy_from_tokens(text_tokens, ("reasoning", "advanced reasoning", "thinking", "math"))
    supports_function_calling: Any = _truthy_from_tokens(text_tokens, ("tool use", "tool-use", "tool calling", "function calling", "agentic", "agent"))

    return {
        "supports_image_input": supports_image_input,
        "supports_vision": supports_vision,
        "supports_coding": supports_coding,
        "supports_reasoning": supports_reasoning,
        "supports_function_calling": supports_function_calling,
        "supports_tools": supports_function_calling,
        "capability_tags": _csv_unique(general_tags),
        "usecase_tags": _csv_unique(usecase_tags),
        "deployment_providers": _csv_unique(cloud_partners),
    }


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


def infer_created_at(model: dict[str, Any]) -> tuple[str, str]:
    strong_keys = {
        "datecreated",
        "createdat",
        "created",
        "creationdate",
        "datepublished",
        "publishedat",
        "publishdate",
        "releasedate",
        "releaseat",
        "releasedat",
        "launchedat",
        "launchdate",
    }
    weak_keys = {
        "datemodified",
        "updatedat",
        "updated",
        "modifiedat",
        "lastmodified",
        "msgtimestamp",
    }
    weak_candidate: tuple[datetime, str] | None = None
    for path, value in _iter_key_values(model):
        key = path.split(".")[-1].split("[")[0]
        normalized_key = re.sub(r"[^a-z0-9]", "", key.lower())
        parsed = parse_datetime_utc(value)
        if parsed is None:
            continue
        if normalized_key in strong_keys:
            return _format_utc_datetime(parsed), path
        if weak_candidate is None and normalized_key in weak_keys:
            weak_candidate = (parsed, path)
    if weak_candidate is not None:
        parsed, path = weak_candidate
        return _format_utc_datetime(parsed), path
    return "", "unknown"


def enrich_model_heat_metrics(model: NormalizedModel, now: datetime | None = None) -> None:
    if now is None:
        now = datetime.now(timezone.utc)
    created = parse_datetime_utc(model.created_at_utc)
    if created is None or created > now:
        model.model_age_days = None
        model.api_calls_per_day = None
        model.projected_30d_calls = None
        model.projected_30d_calls_display = "unknown"
        return

    age_seconds = max((now - created).total_seconds(), 3600.0)
    age_days = age_seconds / 86400.0
    model.model_age_days = round(age_days, 2)
    if model.api_calls_30d is None:
        model.api_calls_per_day = None
        model.projected_30d_calls = None
        model.projected_30d_calls_display = "unknown"
        return

    observed_days = min(max(age_days, 1.0), 30.0)
    calls_per_day = model.api_calls_30d / observed_days
    projected = int(calls_per_day * 30)
    model.api_calls_per_day = round(calls_per_day, 2)
    model.projected_30d_calls = projected
    model.projected_30d_calls_display = format_human_count(projected)


def normalize_model(model: dict[str, Any]) -> NormalizedModel:
    model_id = str(_first_present(model, ("id", "model", "name"), "")).strip()
    model_type = infer_model_type(model)
    is_free, pricing_model, free_reason = infer_free_status(model)
    api_calls_30d, api_calls_30d_display, api_calls_30d_source = infer_api_calls_30d(model)
    created_at_utc, created_at_source = infer_created_at(model)
    capability_profile = infer_capability_profile(model, model_type)
    token_specs = infer_token_specs(model, source_prefix="api_models")
    explicit_supports_tools = _deep_first_present(model, ("supports_tools", "tools", "tool_calling"), None)
    explicit_supports_vision = _deep_first_present(model, ("supports_vision", "vision"), None)
    normalized = NormalizedModel(
        model_id=model_id,
        display_name=str(_deep_first_present(model, ("display_name", "displayName", "name", "id"), model_id)),
        provider=str(_deep_first_present(model, ("provider", "publisher", "organization"), "")),
        owned_by=str(_deep_first_present(model, ("owned_by", "ownedBy", "owner"), "")),
        model_type=model_type,
        endpoint_type=str(_deep_first_present(model, ("endpoint_type", "endpoint", "api_type", "type"), model_type)),
        context_length=token_specs["context_length"],
        context_length_source=token_specs["context_length_source"],
        max_output_tokens=token_specs["max_output_tokens"],
        max_output_tokens_source=token_specs["max_output_tokens_source"],
        supports_streaming=_deep_first_present(model, ("supports_streaming", "streaming"), "unknown"),
        supports_tools=explicit_supports_tools if explicit_supports_tools is not None else capability_profile["supports_tools"],
        supports_json_mode=_deep_first_present(model, ("supports_json_mode", "json_mode"), "unknown"),
        supports_vision=explicit_supports_vision if explicit_supports_vision is not None else capability_profile["supports_vision"],
        supports_image_input=capability_profile["supports_image_input"],
        supports_coding=capability_profile["supports_coding"],
        supports_reasoning=capability_profile["supports_reasoning"],
        supports_function_calling=capability_profile["supports_function_calling"],
        supports_embedding=_deep_first_present(model, ("supports_embedding", "embedding"), model_type == "embedding"),
        capability_tags=capability_profile["capability_tags"],
        usecase_tags=capability_profile["usecase_tags"],
        deployment_providers=capability_profile["deployment_providers"],
        is_free=is_free,
        pricing_model=pricing_model,
        free_reason=free_reason,
        api_calls_30d=api_calls_30d,
        api_calls_30d_display=api_calls_30d_display,
        api_calls_30d_source=api_calls_30d_source,
        created_at_utc=created_at_utc,
        created_at_source=created_at_source,
        raw=model,
    )
    enrich_model_heat_metrics(normalized)
    return normalized


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


def sort_models_by_trending_heat(models: list[NormalizedModel]) -> list[NormalizedModel]:
    ranked = sorted(
        models,
        key=lambda item: (
            item.projected_30d_calls is None,
            -(item.projected_30d_calls or 0),
            item.model_age_days is None,
            item.model_age_days or 999999.0,
            item.model_id.lower(),
        ),
    )
    for index, model in enumerate(ranked, start=1):
        model.trending_rank = index
    return ranked


def sort_models_by_newest(models: list[NormalizedModel]) -> list[NormalizedModel]:
    ranked = sorted(
        models,
        key=lambda item: (
            item.model_age_days is None,
            item.model_age_days or 999999.0,
            item.api_calls_30d is None,
            -(item.api_calls_30d or 0),
            item.model_id.lower(),
        ),
    )
    for index, model in enumerate(ranked, start=1):
        model.newest_rank = index
    return ranked


def _hybrid_bucket_sizes(total: int, stable_ratio: float, trending_count: int, newest_count: int) -> tuple[int, int, int]:
    if total <= 0:
        return 0, 0, 0
    newest = min(max(newest_count, 0), total)
    trending = min(max(trending_count, 0), total - newest)
    stable = max(total - trending - newest, 0)
    desired_stable = int(round(total * stable_ratio))
    if desired_stable > stable and trending + newest > 0:
        take = min(desired_stable - stable, trending + newest)
        reduce_newest = min(newest, take)
        newest -= reduce_newest
        take -= reduce_newest
        reduce_trending = min(trending, take)
        trending -= reduce_trending
        stable = total - trending - newest
    return stable, trending, newest


def select_models_hybrid_topn(
    models: list[NormalizedModel],
    top_n: int | None,
    stable_ratio: float = 0.7,
    trending_count: int = 6,
    newest_count: int = 0,
    new_model_days: float = 14.0,
) -> ModelSelectionResult:
    for model in models:
        model.selection_rank = None
        model.selection_bucket = ""
        model.selection_reason = ""
        enrich_model_heat_metrics(model)

    usage_ranked = sort_models_by_api_calls_30d(models)
    known_usage_count = sum(1 for model in usage_ranked if model.api_calls_30d is not None)
    if top_n is None or top_n >= len(usage_ranked):
        selected = list(usage_ranked)
        for index, model in enumerate(selected, start=1):
            model.selection_rank = index
            model.selection_bucket = "all_candidates"
            model.selection_reason = "未限制 TopN，检测全部候选模型"
        return ModelSelectionResult(
            selected,
            {
                "strategy": "all_candidates",
                "requested_top_n": top_n,
                "selected_count": len(selected),
                "stable_count": len(selected),
                "trending_count": 0,
                "newest_count": 0,
                "fallback_fill_count": 0,
                "known_usage_count": known_usage_count,
                "models_with_created_at": sum(1 for model in models if model.created_at_utc),
                "new_model_days": new_model_days,
            },
        )

    if known_usage_count <= 0:
        selected = list(usage_ranked)
        for index, model in enumerate(selected, start=1):
            model.selection_rank = index
            model.selection_bucket = "fallback_no_usage"
            model.selection_reason = "未获取到 30 天调用量数据，回退检测全部免费候选模型"
        return ModelSelectionResult(
            selected,
            {
                "strategy": "fallback_no_usage",
                "requested_top_n": top_n,
                "selected_count": len(selected),
                "stable_count": len(selected),
                "trending_count": 0,
                "newest_count": 0,
                "fallback_fill_count": 0,
                "known_usage_count": known_usage_count,
                "models_with_created_at": sum(1 for model in models if model.created_at_utc),
                "new_model_days": new_model_days,
            },
        )

    stable_size, trending_size, newest_size = _hybrid_bucket_sizes(top_n, stable_ratio, trending_count, newest_count)
    trending_candidates = [
        model
        for model in sort_models_by_trending_heat(models)
        if model.projected_30d_calls is not None and model.model_age_days is not None and model.model_age_days <= 30.0
    ]
    newest_candidates = [model for model in sort_models_by_newest(models) if model.model_age_days is not None and model.model_age_days <= new_model_days]

    selected: list[NormalizedModel] = []
    seen: set[str] = set()
    bucket_counts = {"stable_popular": 0, "trending_new": 0, "newest_free": 0, "fallback_fill": 0}

    def reserve_bucket(candidates: list[NormalizedModel], quota: int, reserved_ids: set[str] | None = None) -> list[NormalizedModel]:
        if quota <= 0:
            return []
        excluded = reserved_ids or set()
        reserved: list[NormalizedModel] = []
        local_seen: set[str] = set()
        for candidate in candidates:
            if len(reserved) >= quota:
                break
            if candidate.model_id in excluded or candidate.model_id in local_seen:
                continue
            reserved.append(candidate)
            local_seen.add(candidate.model_id)
        return reserved

    def add_from_bucket(
        candidates: list[NormalizedModel],
        quota: int,
        bucket: str,
        reason_builder,
        excluded_ids: set[str] | None = None,
    ) -> None:
        if quota <= 0:
            return
        excluded = excluded_ids or set()
        for candidate in candidates:
            if len(selected) >= top_n or bucket_counts[bucket] >= quota:
                break
            if candidate.model_id in seen or candidate.model_id in excluded:
                continue
            selected.append(candidate)
            seen.add(candidate.model_id)
            bucket_counts[bucket] += 1
            candidate.selection_bucket = bucket
            candidate.selection_reason = reason_builder(candidate)

    reserved_for_non_stable: set[str] = set()
    reserved_trending = reserve_bucket(trending_candidates, trending_size, reserved_for_non_stable)
    reserved_for_non_stable.update(model.model_id for model in reserved_trending)
    reserved_newest = reserve_bucket(newest_candidates, newest_size, reserved_for_non_stable)
    reserved_for_non_stable.update(model.model_id for model in reserved_newest)

    add_from_bucket(
        usage_ranked,
        stable_size,
        "stable_popular",
        lambda item: f"稳定热门池：30 天调用量排名 {item.usage_rank}，调用量 {item.api_calls_30d_display}",
        excluded_ids=reserved_for_non_stable,
    )
    add_from_bucket(
        reserved_trending,
        trending_size,
        "trending_new",
        lambda item: (
            f"新晋热门池：折算 30 天调用量 {item.projected_30d_calls_display}，"
            f"日均 {item.api_calls_per_day or 0:.0f}，年龄 {item.model_age_days} 天"
        ),
    )
    add_from_bucket(
        reserved_newest,
        newest_size,
        "newest_free",
        lambda item: f"新模型保底池：年龄 {item.model_age_days} 天，30 天调用量 {item.api_calls_30d_display}",
    )
    if len(selected) < top_n:
        add_from_bucket(
            trending_candidates,
            bucket_counts["trending_new"] + (top_n - len(selected)),
            "trending_new",
            lambda item: (
                f"新晋热门池扩展：折算 30 天调用量 {item.projected_30d_calls_display}，"
                f"日均 {item.api_calls_per_day or 0:.0f}，年龄 {item.model_age_days} 天"
            ),
        )

    for index, model in enumerate(selected, start=1):
        model.selection_rank = index

    return ModelSelectionResult(
        selected,
        {
            "strategy": "hybrid_topn",
            "requested_top_n": top_n,
            "selected_count": len(selected),
            "stable_count": bucket_counts["stable_popular"],
            "trending_count": bucket_counts["trending_new"],
            "newest_count": bucket_counts["newest_free"],
            "fallback_fill_count": bucket_counts["fallback_fill"],
            "known_usage_count": known_usage_count,
            "models_with_created_at": sum(1 for model in models if model.created_at_utc),
            "new_model_days": new_model_days,
            "trending_window_days": 30.0,
            "stable_ratio": stable_ratio,
            "trending_quota": trending_size,
            "newest_quota": newest_size,
        },
    )


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
