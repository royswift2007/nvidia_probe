from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .client import NvidiaApiClient
from .cleanup import maybe_cleanup_program
from .config import ProbeConfig
from .environment import collect_environment
from .models import normalize_models, should_test_model, sort_models_by_api_calls_30d
from .ratelimit import BreakerState, should_break, sleep_with_jitter
from .report import calculate_summary, print_table, write_csv, write_excel
from .storage import completed_model_ids, initial_state, load_state, save_state, upsert_result
from .testers import classify_response, skipped_result, test_model


def _extract_raw_models(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        raw = payload.get("data") or payload.get("models") or payload.get("items") or []
    elif isinstance(payload, list):
        raw = payload
    else:
        raw = []
    return [item for item in raw if isinstance(item, dict)]


def _print_startup(config: ProbeConfig, environment: dict[str, Any]) -> None:
    masked_key = f"***{config.api_key[-4:]}" if config.api_key else "missing"
    print("NVIDIA Model Probe 启动")
    print(f"- Base URL: {config.base_url}")
    print(f"- API Key: {masked_key}")
    print(f"- 输出目录: {config.output_dir}")
    print(f"- 当前主机: {environment.get('hostname', '')}")
    print(f"- 公网 IP: {environment.get('public_ip', '')}")
    print(f"- 国家/地区: {environment.get('country', '')} {environment.get('region', '')}")
    print(f"- 默认测试类型: {','.join(config.include_types)}")
    print(f"- 默认排除类型: {','.join(config.exclude_types)}")
    print(f"- 只测试可确认免费模型: {config.free_only}")
    print(f"- 允许未知费用模型: {config.allow_unknown_cost}")
    print(f"- 默认 Top 免费模型数量: {config.top_free_models}")
    print(f"- 请求间隔: {config.delay_min}-{config.delay_max} 秒随机")
    print(f"- 重试次数: {config.retries}")
    print(f"- 首次 429 立即停止: {config.stop_on_first_429}")
    print(f"- 连续 403 熔断阈值: {config.consecutive_403_breaker}")
    if config.dry_run:
        print("- Dry-run: 只拉取和导出模型列表，不调用模型。")


def _result_paths(config: ProbeConfig) -> list[Path]:
    return [config.state_file, config.report_csv, config.report_xlsx]


def _write_reports(config: ProbeConfig, state: dict[str, Any]) -> None:
    results = state.get("results") or []
    summary = calculate_summary(results)
    state["summary"] = summary
    save_state(config.state_file, state)
    write_csv(config.report_csv, results)
    excel_written = write_excel(config.report_xlsx, results, summary, state.get("environment") or {})
    print("\n报告已生成：")
    print(f"- JSON: {config.state_file}")
    print(f"- CSV: {config.report_csv}")
    if excel_written:
        print(f"- Excel: {config.report_xlsx}")
    else:
        print("- Excel: 未生成，未安装 openpyxl。可执行 pip install openpyxl 后重试。")
    print("\n汇总：")
    for key, value in summary.items():
        print(f"- {key}: {value}")
    print_table(results)


def run_probe(config: ProbeConfig, project_root: Path) -> int:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    environment = collect_environment(no_ip_lookup=config.no_ip_lookup)
    _print_startup(config, environment)

    existing = load_state(config.state_file) if config.resume else None
    if existing:
        state = existing
        state["environment"] = environment
        state.setdefault("config", config.raw_args)
        print(f"检测到断点文件，已载入: {config.state_file}")
    else:
        state = initial_state(environment, config.raw_args)

    client = NvidiaApiClient(
        api_key=config.api_key,
        base_url=config.base_url,
        timeout=config.timeout,
        user_agent=config.request_user_agent,
    )

    try:
        print("正在拉取 NVIDIA 模型列表...")
        models_response = client.get_models()
        if not models_response.ok:
            status, error_type, error_message = classify_response(models_response)
            state["abort_reason"] = f"拉取模型列表失败: {status} {error_type} {error_message[:300]}"
            save_state(config.state_file, state)
            print(state["abort_reason"])
            return 2

        raw_models = _extract_raw_models(models_response.data)
        state["models_raw"] = raw_models
        state["models_payload_raw"] = models_response.data
        models = normalize_models(models_response.data)
        print(f"已拉取模型数量: {len(models)}")

        if config.only_model:
            models = [model for model in models if model.model_id == config.only_model]
            if not models:
                print(f"未找到指定模型: {config.only_model}")
        else:
            selectable_models = []
            skipped_before_topn = 0
            for model in models:
                selected, _ = should_test_model(
                    model,
                    config.include_types,
                    config.exclude_types,
                    config.only_model,
                    free_only=config.free_only,
                    allow_unknown_cost=config.allow_unknown_cost,
                )
                if selected:
                    selectable_models.append(model)
                else:
                    skipped_before_topn += 1
            ranked_models = sort_models_by_api_calls_30d(selectable_models)
            known_usage = sum(1 for model in ranked_models if model.api_calls_30d is not None)
            if known_usage > 0 and config.top_free_models is not None:
                models = ranked_models[: config.top_free_models]
                topn_message = f"已按 30 天 API 调用量全局排序，仅选择前 {config.top_free_models} 个候选模型。"
            else:
                models = ranked_models
                topn_message = "未获取到 30 天 API 调用量数据，回退为检测全部免费候选模型。"
            print(
                f"免费且类型匹配候选模型: {len(selectable_models)}；"
                f"跳过非免费/类型不匹配模型: {skipped_before_topn}；"
                f"有 30 天调用量数据: {known_usage}。"
            )
            print(topn_message)

        if config.limit is not None:
            models = models[: config.limit]

        print(f"本次候选模型数量: {len(models)}")
        if models and not config.dry_run:
            estimated_min = len(models) * config.delay_min
            estimated_max = len(models) * config.delay_max
            print(f"预计仅等待时间约: {estimated_min:.0f}-{estimated_max:.0f} 秒，不含 API 响应耗时。")

        done = completed_model_ids(state) if config.resume and not config.force_retest else set()
        breaker = BreakerState()

        for index, model in enumerate(models, start=1):
            if model.model_id in done:
                print(f"[{index}/{len(models)}] 跳过已完成模型: {model.model_id}")
                continue

            selected, reason = should_test_model(
                model,
                config.include_types,
                config.exclude_types,
                config.only_model,
                free_only=config.free_only,
                allow_unknown_cost=config.allow_unknown_cost,
            )
            if config.dry_run:
                dry_reason = "dry_run" if selected else f"dry_run:{reason}"
                result = skipped_result(model, dry_reason)
                upsert_result(state, result)
                save_state(config.state_file, state)
                print(f"[{index}/{len(models)}] dry-run 记录模型: {model.model_id} ({dry_reason})")
                continue

            if not selected:
                result = skipped_result(model, reason)
                upsert_result(state, result)
                save_state(config.state_file, state)
                print(f"[{index}/{len(models)}] 跳过 {model.model_id}: {reason}")
                continue

            print(f"[{index}/{len(models)}] 测试 {model.model_id} ({model.model_type})...")
            result = test_model(client, model, config.max_output_tokens, config.retries)
            upsert_result(state, result)
            save_state(config.state_file, state)
            print(
                f"  -> {result.get('test_status')} http={result.get('http_status')} "
                f"latency={result.get('latency_total_ms')}ms error={result.get('error_type')}"
            )

            breaker.record(
                str(result.get("test_status", "")),
                result.get("http_status") if isinstance(result.get("http_status"), int) else None,
                str(result.get("error_type", "")),
            )

            if result.get("http_status") == 429:
                if config.stop_on_first_429:
                    print("触发 429 限流。为避免 API 风险，本次任务将立即停止。")
                else:
                    print(f"触发 429 限流，暂停 {config.rate_limit_sleep:.0f} 秒。")
                    time.sleep(config.rate_limit_sleep)

            stop, reason = should_break(
                breaker,
                config.consecutive_429_breaker,
                config.consecutive_network_breaker,
                consecutive_403_breaker=config.consecutive_403_breaker,
                stop_on_first_429=config.stop_on_first_429,
            )
            if stop:
                state["abort_reason"] = reason
                save_state(config.state_file, state)
                print(reason)
                break

            if index < len(models):
                slept = sleep_with_jitter(config.delay_min, config.delay_max)
                if slept:
                    print(f"已安全等待 {slept:.1f} 秒。")

        _write_reports(config, state)
        return 0
    finally:
        client.close()
        if config.cleanup_prompt != "never":
            maybe_cleanup_program(config.cleanup_prompt, project_root, _result_paths(config))
