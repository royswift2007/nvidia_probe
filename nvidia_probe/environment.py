from __future__ import annotations

import os
import platform
import socket
import sys
from datetime import datetime, timezone
from typing import Any

import requests


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _safe_get_json(url: str, timeout: float = 8.0) -> dict[str, Any]:
    try:
        response = requests.get(url, timeout=timeout, headers={"User-Agent": "nvidia-model-probe/0.1.0"})
        if response.status_code != 200:
            return {"lookup_error": f"HTTP {response.status_code}"}
        data = response.json()
        return data if isinstance(data, dict) else {"lookup_error": "unexpected_ip_lookup_payload"}
    except Exception as exc:  # noqa: BLE001 - environment lookup must never fail the probe
        return {"lookup_error": type(exc).__name__, "lookup_error_message": str(exc)[:300]}


def collect_environment(no_ip_lookup: bool = False) -> dict[str, Any]:
    env: dict[str, Any] = {
        "tested_at_utc": utc_now_iso(),
        "hostname": socket.gethostname(),
        "fqdn": socket.getfqdn(),
        "os": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "python_version": sys.version.split()[0],
        "proxy_enabled": bool(os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY") or os.getenv("ALL_PROXY")),
        "https_proxy_set": bool(os.getenv("HTTPS_PROXY")),
        "http_proxy_set": bool(os.getenv("HTTP_PROXY")),
        "no_proxy_set": bool(os.getenv("NO_PROXY")),
    }
    if no_ip_lookup:
        env.update({"ip_lookup_skipped": True})
        return env

    ip_info = _safe_get_json("https://ipapi.co/json/", timeout=8.0)
    if ip_info.get("lookup_error"):
        fallback = _safe_get_json("https://ipinfo.io/json", timeout=8.0)
        if not fallback.get("lookup_error"):
            ip_info = fallback

    env.update(
        {
            "public_ip": ip_info.get("ip"),
            "country": ip_info.get("country_name") or ip_info.get("country"),
            "region": ip_info.get("region") or ip_info.get("region_name"),
            "city": ip_info.get("city"),
            "isp": ip_info.get("org") or ip_info.get("asn_org"),
            "timezone": ip_info.get("timezone"),
            "ip_lookup_error": ip_info.get("lookup_error"),
            "ip_lookup_error_message": ip_info.get("lookup_error_message"),
        }
    )
    return env
