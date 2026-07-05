from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Optional

import requests


@dataclass(slots=True)
class ApiResponse:
    ok: bool
    status_code: Optional[int]
    data: Any
    text: str
    elapsed_ms: int
    error_type: str = ""
    error_message: str = ""


class NvidiaApiClient:
    def __init__(self, api_key: str, base_url: str, timeout: float, user_agent: str) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {api_key}",
                "User-Agent": user_agent,
                "Accept": "application/json",
            }
        )

    def close(self) -> None:
        self.session.close()

    def get_models(self) -> ApiResponse:
        return self._request("GET", "/models")

    def chat_completion(self, model_id: str, max_output_tokens: int) -> ApiResponse:
        payload = {
            "model": model_id,
            "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
            "temperature": 0,
            "max_tokens": max_output_tokens,
            "stream": False,
        }
        return self._request("POST", "/chat/completions", json_payload=payload)

    def embedding(self, model_id: str) -> ApiResponse:
        payload = {"model": model_id, "input": "hello"}
        return self._request("POST", "/embeddings", json_payload=payload)

    def rerank(self, model_id: str) -> ApiResponse:
        payload_variants = [
            {
                "model": model_id,
                "query": "What is NVIDIA?",
                "documents": ["NVIDIA makes GPUs.", "A banana is a fruit."],
            },
            {
                "model": model_id,
                "input": {
                    "query": "What is NVIDIA?",
                    "documents": ["NVIDIA makes GPUs.", "A banana is a fruit."],
                },
            },
        ]
        last_response: ApiResponse | None = None
        for payload in payload_variants:
            response = self._request("POST", "/ranking", json_payload=payload)
            last_response = response
            if response.ok or response.status_code not in (400, 404, 422):
                return response
        return last_response or ApiResponse(False, None, None, "", 0, "client_error", "rerank request not attempted")

    def _request(self, method: str, path: str, json_payload: dict[str, Any] | None = None) -> ApiResponse:
        url = f"{self.base_url}{path}"
        start = time.perf_counter()
        try:
            response = self.session.request(
                method,
                url,
                json=json_payload,
                timeout=self.timeout,
                headers={"Content-Type": "application/json"} if json_payload is not None else None,
            )
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            text = response.text or ""
            try:
                data = response.json() if text else None
            except json.JSONDecodeError:
                data = None
            return ApiResponse(
                ok=200 <= response.status_code < 300,
                status_code=response.status_code,
                data=data,
                text=text,
                elapsed_ms=elapsed_ms,
            )
        except requests.Timeout as exc:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            return ApiResponse(False, None, None, "", elapsed_ms, "timeout", str(exc)[:500])
        except requests.ConnectionError as exc:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            return ApiResponse(False, None, None, "", elapsed_ms, "network_error", str(exc)[:500])
        except requests.RequestException as exc:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            return ApiResponse(False, None, None, "", elapsed_ms, "request_error", str(exc)[:500])
