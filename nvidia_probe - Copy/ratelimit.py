from __future__ import annotations

import random
import time
from dataclasses import dataclass


@dataclass(slots=True)
class BreakerState:
    consecutive_429: int = 0
    consecutive_403: int = 0
    consecutive_network: int = 0
    consecutive_auth: int = 0
    consecutive_restriction: int = 0
    tested: int = 0
    failed: int = 0

    def record(self, status: str, http_status: int | None = None, error_type: str = "") -> None:
        self.tested += 1
        if status != "available":
            self.failed += 1
        if http_status == 429 or status == "rate_limited":
            self.consecutive_429 += 1
        else:
            self.consecutive_429 = 0

        if http_status == 403 or status == "forbidden_or_region_block":
            self.consecutive_403 += 1
        else:
            self.consecutive_403 = 0

        if status in {"forbidden_or_region_block", "rate_limited", "unauthorized"} or error_type in {
            "forbidden_or_region_block",
            "rate_limited",
            "unauthorized",
        }:
            self.consecutive_restriction += 1
        else:
            self.consecutive_restriction = 0

        if status == "network_error" or error_type in {"network_error", "timeout", "request_error"}:
            self.consecutive_network += 1
        else:
            self.consecutive_network = 0

        if http_status == 401 or status == "unauthorized":
            self.consecutive_auth += 1
        else:
            self.consecutive_auth = 0

    @property
    def failure_rate(self) -> float:
        if self.tested <= 0:
            return 0.0
        return self.failed / self.tested


def sleep_with_jitter(delay_min: float, delay_max: float) -> float:
    delay = random.uniform(delay_min, delay_max)
    if delay > 0:
        time.sleep(delay)
    return delay


def should_break(
    state: BreakerState,
    consecutive_429_breaker: int,
    consecutive_network_breaker: int,
    consecutive_403_breaker: int = 5,
    stop_on_first_429: bool = True,
) -> tuple[bool, str]:
    if stop_on_first_429 and state.consecutive_429 >= 1:
        return True, "检测到 429 限流。为避免 API 风险，已立即停止测试。"
    if state.consecutive_auth >= 2:
        return True, "连续鉴权失败达到 2 次，停止测试。"
    if state.consecutive_429 >= consecutive_429_breaker:
        return True, f"连续 429 达到 {consecutive_429_breaker} 次，停止测试。"
    if state.consecutive_403 >= consecutive_403_breaker:
        return True, f"连续 403/地区或权限限制达到 {consecutive_403_breaker} 次，停止测试。"
    if state.consecutive_restriction >= 6:
        return True, "连续限制类错误达到 6 次，疑似地区、权限或风控限制，停止测试。"
    if state.consecutive_network >= consecutive_network_breaker:
        return True, f"连续网络错误达到 {consecutive_network_breaker} 次，停止测试。"
    if state.tested >= 10 and state.failure_rate >= 0.9:
        return True, "已测试超过 10 个模型且失败率超过 90%，疑似地区、IP、DNS、代理或 API Key 权限问题，停止测试。"
    return False, ""
