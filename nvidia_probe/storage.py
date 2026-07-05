from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


def initial_state(environment: dict[str, Any], config_args: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "environment": environment,
        "config": config_args,
        "models_raw": [],
        "results": [],
        "summary": {},
        "abort_reason": "",
    }


def load_state(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=str(path.parent), suffix=".tmp") as file:
        json.dump(state, file, ensure_ascii=False, indent=2)
        temp_name = file.name
    Path(temp_name).replace(path)


def completed_model_ids(state: dict[str, Any]) -> set[str]:
    results = state.get("results") or []
    ids: set[str] = set()
    for item in results:
        if isinstance(item, dict) and item.get("model_id"):
            ids.add(str(item["model_id"]))
    return ids


def upsert_result(state: dict[str, Any], result: dict[str, Any]) -> None:
    results = state.setdefault("results", [])
    model_id = result.get("model_id")
    for index, existing in enumerate(results):
        if isinstance(existing, dict) and existing.get("model_id") == model_id:
            results[index] = result
            return
    results.append(result)
