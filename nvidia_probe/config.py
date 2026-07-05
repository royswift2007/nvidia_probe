from __future__ import annotations

import argparse
import getpass
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_OUTPUT_DIR = "results"
DEFAULT_INCLUDE_TYPES = ("chat", "embedding", "reranker")
DEFAULT_SKIP_TYPES = ("image", "video", "audio")
DEFAULT_BUILD_CATALOG_URL = "https://build.nvidia.com/models?filters=nimType%3Anim_type_preview"


@dataclass(slots=True)
class ProbeConfig:
    api_key: str
    base_url: str = DEFAULT_BASE_URL
    output_dir: Path = Path(DEFAULT_OUTPUT_DIR)
    state_file: Path = Path(DEFAULT_OUTPUT_DIR) / "probe_state.json"
    report_csv: Path = Path(DEFAULT_OUTPUT_DIR) / "nvidia_models_report.csv"
    report_xlsx: Path = Path(DEFAULT_OUTPUT_DIR) / "nvidia_models_report.xlsx"
    limit: Optional[int] = None
    top_free_models: Optional[int] = 20
    only_model: Optional[str] = None
    hybrid_topn: bool = True
    stable_top_ratio: float = 0.7
    trending_models: int = 4
    newest_models: int = 2
    new_model_days: float = 14.0
    include_types: tuple[str, ...] = DEFAULT_INCLUDE_TYPES
    exclude_types: tuple[str, ...] = DEFAULT_SKIP_TYPES
    delay_min: float = 10.0
    delay_max: float = 25.0
    timeout: float = 60.0
    retries: int = 0
    max_output_tokens: int = 8
    rate_limit_sleep: float = 600.0
    consecutive_429_breaker: int = 1
    consecutive_403_breaker: int = 5
    consecutive_network_breaker: int = 10
    stop_on_first_429: bool = True
    dry_run: bool = False
    resume: bool = False
    force_retest: bool = False
    no_ip_lookup: bool = False
    cleanup_prompt: str = "auto"
    strict_safe: bool = False
    free_only: bool = True
    allow_unknown_cost: bool = False
    use_build_catalog: bool = True
    build_catalog_url: str = DEFAULT_BUILD_CATALOG_URL
    request_user_agent: str = "nvidia-model-probe/0.1.0"
    raw_args: dict[str, object] = field(default_factory=dict)

    def apply_strict_safe_defaults(self) -> None:
        if not self.strict_safe:
            return
        self.delay_min = max(self.delay_min, 60.0)
        self.delay_max = max(self.delay_max, 120.0)
        self.retries = 0
        self.max_output_tokens = min(self.max_output_tokens, 8)
        self.rate_limit_sleep = max(self.rate_limit_sleep, 900.0)
        self.consecutive_429_breaker = 1
        self.consecutive_403_breaker = min(self.consecutive_403_breaker, 3)
        self.consecutive_network_breaker = min(self.consecutive_network_breaker, 5)
        self.stop_on_first_429 = True


def parse_csv_tuple(value: str | Iterable[str] | None, default: tuple[str, ...]) -> tuple[str, ...]:
    if value is None:
        return default
    if isinstance(value, str):
        items = [part.strip().lower() for part in value.split(",") if part.strip()]
        return tuple(items) if items else default
    items = [str(part).strip().lower() for part in value if str(part).strip()]
    return tuple(items) if items else default


def resolve_api_key(args: argparse.Namespace) -> str:
    api_key = args.api_key or os.getenv("NVIDIA_API_KEY") or os.getenv("NGC_API_KEY")
    if api_key:
        return api_key.strip()

    if not sys.stdin.isatty():
        raise SystemExit(
            "未找到 NVIDIA API Key，且当前不是交互式终端，无法安全输入。"
            "请设置环境变量 NVIDIA_API_KEY 后重试。"
        )

    print("需要 NVIDIA API Key 才能拉取模型列表并测试模型；不会把 Key 写入报告或状态文件。")
    api_key = getpass.getpass("请输入 NVIDIA API Key（输入不可见）: ").strip()
    if not api_key:
        raise SystemExit("未输入 NVIDIA API Key，已停止。")
    return api_key


def build_probe_config(args: argparse.Namespace) -> ProbeConfig:
    output_dir = Path(args.output_dir).expanduser().resolve()
    config = ProbeConfig(
        api_key=resolve_api_key(args),
        base_url=(args.base_url or os.getenv("NVIDIA_BASE_URL") or DEFAULT_BASE_URL).rstrip("/"),
        output_dir=output_dir,
        state_file=output_dir / "probe_state.json",
        report_csv=output_dir / "nvidia_models_report.csv",
        report_xlsx=output_dir / "nvidia_models_report.xlsx",
        limit=args.limit,
        top_free_models=args.top_free_models,
        only_model=args.only_model,
        hybrid_topn=not bool(args.no_hybrid_topn),
        stable_top_ratio=float(args.stable_top_ratio),
        trending_models=int(args.trending_models),
        newest_models=int(args.newest_models),
        new_model_days=float(args.new_model_days),
        include_types=parse_csv_tuple(args.include_types, DEFAULT_INCLUDE_TYPES),
        exclude_types=parse_csv_tuple(args.exclude_types, DEFAULT_SKIP_TYPES),
        delay_min=float(args.delay_min),
        delay_max=float(args.delay_max),
        timeout=float(args.timeout),
        retries=int(args.retries),
        max_output_tokens=int(args.max_output_tokens),
        rate_limit_sleep=float(args.rate_limit_sleep),
        consecutive_429_breaker=int(args.consecutive_429_breaker),
        consecutive_403_breaker=int(args.consecutive_403_breaker),
        consecutive_network_breaker=int(args.consecutive_network_breaker),
        stop_on_first_429=not bool(args.continue_after_429),
        dry_run=bool(args.dry_run),
        resume=bool(args.resume),
        force_retest=bool(args.force_retest),
        no_ip_lookup=bool(args.no_ip_lookup),
        cleanup_prompt=args.cleanup_prompt,
        strict_safe=bool(args.strict_safe),
        free_only=not bool(args.no_free_only),
        allow_unknown_cost=bool(args.allow_unknown_cost),
        use_build_catalog=not bool(args.no_build_catalog),
        build_catalog_url=args.build_catalog_url,
        raw_args={key: value for key, value in vars(args).items() if key != "api_key"},
    )
    if config.delay_max < config.delay_min:
        raise SystemExit("--delay-max 不能小于 --delay-min。")
    if config.delay_min < 0 or config.delay_max < 0:
        raise SystemExit("请求间隔不能为负数。")
    if config.retries < 0:
        raise SystemExit("--retries 不能为负数。")
    if config.max_output_tokens <= 0:
        raise SystemExit("--max-output-tokens 必须大于 0。")
    if config.top_free_models is not None and config.top_free_models <= 0:
        raise SystemExit("--top-free-models 必须大于 0，或不传该参数使用默认值。")
    if not 0 <= config.stable_top_ratio <= 1:
        raise SystemExit("--stable-top-ratio 必须在 0 到 1 之间。")
    if config.trending_models < 0:
        raise SystemExit("--trending-models 不能为负数。")
    if config.newest_models < 0:
        raise SystemExit("--newest-models 不能为负数。")
    if config.new_model_days <= 0:
        raise SystemExit("--new-model-days 必须大于 0。")
    config.apply_strict_safe_defaults()
    return config
