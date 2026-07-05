from __future__ import annotations

from typing import Any

from .client import ApiResponse, NvidiaApiClient
from .environment import utc_now_iso
from .models import NormalizedModel


def classify_response(response: ApiResponse) -> tuple[str, str, str]:
    if response.error_type:
        if response.error_type == "timeout":
            return "timeout", "timeout", response.error_message
        if response.error_type == "network_error":
            return "network_error", "network_error", response.error_message
        return "request_error", response.error_type, response.error_message

    status = response.status_code
    message = response.text[:1000] if response.text else ""
    if response.ok:
        return "available", "", ""
    if status == 400:
        return "invalid_request", "bad_request", message
    if status == 401:
        return "unauthorized", "unauthorized", message
    if status == 403:
        return "forbidden_or_region_block", "forbidden_or_region_block", message
    if status == 404:
        return "model_not_found_or_not_exposed", "not_found", message
    if status == 408:
        return "timeout", "timeout", message
    if status == 429:
        return "rate_limited", "rate_limited", message
    if isinstance(status, int) and 500 <= status <= 599:
        return "server_error", "server_error", message
    return "unknown_error", "unknown_error", message


def extract_response_preview(data: Any, text: str) -> str:
    if isinstance(data, dict):
        try:
            choices = data.get("choices") or []
            if choices and isinstance(choices[0], dict):
                message = choices[0].get("message") or {}
                if isinstance(message, dict) and message.get("content"):
                    return str(message.get("content"))[:300]
                if choices[0].get("text"):
                    return str(choices[0].get("text"))[:300]
            if data.get("data"):
                return str(data.get("data"))[:300]
            if data.get("results"):
                return str(data.get("results"))[:300]
        except Exception:  # noqa: BLE001
            pass
    return text[:300] if text else ""


def extract_vector_dimension(data: Any) -> int | str:
    if not isinstance(data, dict):
        return ""
    values = data.get("data")
    if not isinstance(values, list) or not values:
        return ""
    first = values[0]
    if not isinstance(first, dict):
        return ""
    embedding = first.get("embedding")
    if isinstance(embedding, list):
        return len(embedding)
    return ""


def base_result(model: NormalizedModel) -> dict[str, Any]:
    return {
        "model_id": model.model_id,
        "display_name": model.display_name,
        "provider": model.provider,
        "owned_by": model.owned_by,
        "model_type": model.model_type,
        "endpoint_type": model.endpoint_type,
        "is_free": model.is_free,
        "pricing_model": model.pricing_model,
        "free_reason": model.free_reason,
        "api_calls_30d": model.api_calls_30d,
        "api_calls_30d_display": model.api_calls_30d_display,
        "api_calls_30d_source": model.api_calls_30d_source,
        "usage_rank": model.usage_rank,
        "context_length": "",
        "max_output_tokens": "",
        "supports_streaming": "",
        "supports_tools": "",
        "supports_json_mode": "",
        "supports_vision": "",
        "supports_embedding": "",
        "test_status": "pending",
        "http_status": "",
        "latency_total_ms": "",
        "retry_count": 0,
        "error_type": "",
        "error_message": "",
        "response_preview": "",
        "tested_at_utc": "",
        "skip_reason": "",
        "vector_dimension": "",
    }


def enrich_callable_model_details(result: dict[str, Any], model: NormalizedModel) -> None:
    result.update(
        {
            "context_length": model.context_length,
            "max_output_tokens": model.max_output_tokens,
            "supports_streaming": model.supports_streaming,
            "supports_tools": model.supports_tools,
            "supports_json_mode": model.supports_json_mode,
            "supports_vision": model.supports_vision,
            "supports_embedding": model.supports_embedding,
        }
    )


def skipped_result(model: NormalizedModel, reason: str) -> dict[str, Any]:
    result = base_result(model)
    result.update(
        {
            "test_status": "skipped",
            "skip_reason": reason,
            "tested_at_utc": utc_now_iso(),
        }
    )
    return result


def test_model(client: NvidiaApiClient, model: NormalizedModel, max_output_tokens: int, retries: int) -> dict[str, Any]:
    result = base_result(model)
    attempts = retries + 1
    last_response: ApiResponse | None = None
    for attempt in range(attempts):
        if model.model_type == "embedding":
            response = client.embedding(model.model_id)
        elif model.model_type == "reranker":
            response = client.rerank(model.model_id)
        else:
            response = client.chat_completion(model.model_id, max_output_tokens=max_output_tokens)
        last_response = response
        status, error_type, error_message = classify_response(response)
        if status == "available" or status in {"unauthorized", "forbidden_or_region_block", "rate_limited", "invalid_request", "model_not_found_or_not_exposed"}:
            break
    if last_response is None:
        result.update(
            {
                "test_status": "unknown_error",
                "error_type": "not_attempted",
                "error_message": "request was not attempted",
                "tested_at_utc": utc_now_iso(),
            }
        )
        return result

    status, error_type, error_message = classify_response(last_response)
    result.update(
        {
            "test_status": status,
            "http_status": last_response.status_code if last_response.status_code is not None else "",
            "latency_total_ms": last_response.elapsed_ms,
            "retry_count": max(0, attempt),
            "error_type": error_type,
            "error_message": error_message[:1000] if error_message else "",
            "response_preview": extract_response_preview(last_response.data, last_response.text),
            "tested_at_utc": utc_now_iso(),
            "vector_dimension": extract_vector_dimension(last_response.data)
            if status == "available" and model.model_type == "embedding"
            else "",
        }
    )
    if status == "available":
        enrich_callable_model_details(result, model)
    return result
