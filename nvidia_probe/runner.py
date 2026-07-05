from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .build_catalog import apply_build_catalog_to_models, enrich_token_specs_from_build_pages, fetch_free_endpoint_catalog
from .client import NvidiaApiClient
from .cleanup import maybe_cleanup_program, maybe_cleanup_program_after_interrupt
from .config import ProbeConfig
from .environment import collect_environment
from .models import NormalizedModel, normalize_models, select_models_hybrid_topn, should_test_model, sort_models_by_api_calls_30d
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


def _print_progress(message: str = "") -> None:
    print(message, flush=True)


def _format_model_identity(model: NormalizedModel) -> str:
    parts = [model.model_id]
    display_name = model.display_name.strip()
    if display_name and display_name != model.model_id:
        parts.append(f"name={display_name}")
    parts.append(f"type={model.model_type}")
    if model.selection_rank is not None:
        parts.append(f"select_rank={model.selection_rank}")
    if model.selection_bucket:
        parts.append(f"bucket={model.selection_bucket}")
    if model.usage_rank is not None:
        parts.append(f"usage_rank={model.usage_rank}")
    if model.trending_rank is not None:
        parts.append(f"trend_rank={model.trending_rank}")
    calls_display = model.api_calls_30d_display or "unknown"
    parts.append(f"30d_calls={calls_display}")
    if model.api_calls_per_day_display not in ("", "unknown"):
        parts.append(f"daily_calls={model.api_calls_per_day_display}")
    if model.projected_30d_calls_display not in ("", "unknown"):
        parts.append(f"projected_30d={model.projected_30d_calls_display}")
    if model.model_age_days is not None:
        parts.append(f"age={model.model_age_days}d")
    return " | ".join(parts)


def _format_token_spec_coverage(models: list[NormalizedModel]) -> str:
    total = len(models)
    if total <= 0:
        return "上下文/输出 token 规格覆盖: 0/0。"
    context_count = sum(1 for model in models if str(model.context_length).strip().lower() not in {"", "unknown", "none"})
    output_count = sum(1 for model in models if str(model.max_output_tokens).strip().lower() not in {"", "unknown", "none"})
    return f"上下文/输出 token 规格覆盖: context={context_count}/{total}，max_output={output_count}/{total}。"


def _format_running_stats(processed: int, total: int, available: int, failed: int, skipped: int) -> str:
    return f"累计: 已处理 {processed}/{total}，成功 {available}，失败 {failed}，跳过 {skipped}"


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
    print(
        f"- 混合 TopN: {config.hybrid_topn} "
        f"(稳定热门比例={config.stable_top_ratio}, 新晋热门={config.trending_models}, "
        f"新模型保底={config.newest_models}, 新模型窗口={config.new_model_days}天)"
    )
    print(f"- 抓取模型详情页补全 token 规格: {config.fetch_model_details}")
    print(f"- 模型详情页抓取间隔: {config.detail_delay_min}-{config.detail_delay_max} 秒随机")
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

    cleanup_allowed = False
    interrupted = False
    try:
        _print_progress("正在拉取 NVIDIA 模型列表...")
        models_response = client.get_models()
        if not models_response.ok:
            status, error_type, error_message = classify_response(models_response)
            state["abort_reason"] = f"拉取模型列表失败: {status} {error_type} {error_message[:300]}"
            save_state(config.state_file, state)
            _print_progress(state["abort_reason"])
            cleanup_allowed = True
            return 2

        raw_models = _extract_raw_models(models_response.data)
        state["models_raw"] = raw_models
        state["models_payload_raw"] = models_response.data
        models = normalize_models(models_response.data)
        total_model_count = len(models)
        catalog_apply = None
        catalog_result = None
        if config.use_build_catalog and config.free_only:
            _print_progress("正在拉取 NVIDIA Build Free Endpoint 模型目录...")
            catalog_result = fetch_free_endpoint_catalog(
                url=config.build_catalog_url,
                timeout=config.timeout,
                user_agent=config.request_user_agent,
            )
            state["build_catalog"] = catalog_result.to_state()
            catalog_apply = apply_build_catalog_to_models(models, catalog_result)
            _print_progress(
                f"Build Free Endpoint 目录: 页面总数={catalog_apply.catalog_total_count}；"
                f"已抓取={catalog_apply.catalog_models_count}；"
                f"与 API 模型匹配={catalog_apply.matched_count}。"
            )
            _print_progress(_format_token_spec_coverage(models))
            if catalog_apply.unmatched_model_ids:
                preview = ", ".join(catalog_apply.unmatched_model_ids[:8])
                suffix = "..." if len(catalog_apply.unmatched_model_ids) > 8 else ""
                _print_progress(f"Build 目录中未匹配 API 模型: {preview}{suffix}")
            if catalog_result.errors:
                _print_progress("Build Free Endpoint 目录抓取存在错误: " + "; ".join(catalog_result.errors[:3]))

        free_model_count = sum(1 for model in models if model.is_free is True)
        paid_model_count = sum(1 for model in models if model.is_free is False)
        unknown_cost_count = sum(1 for model in models if model.is_free is None)
        _print_progress(f"已拉取模型总数: {total_model_count}")
        _print_progress(
            f"free 模型统计: 可确认 free={free_model_count}，"
            f"非免费/付费={paid_model_count}，费用未知={unknown_cost_count}"
        )

        selectable_count = 0
        skipped_before_topn = 0
        known_usage = 0
        if config.only_model:
            models = [model for model in models if model.model_id == config.only_model]
            selectable_count = len(models)
            known_usage = sum(1 for model in models if model.api_calls_30d is not None)
            if not models:
                _print_progress(f"未找到指定模型: {config.only_model}")
            else:
                _print_progress(f"指定模型模式: {config.only_model}；匹配数量: {len(models)}")
        else:
            selectable_models = []
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
            selectable_count = len(selectable_models)
            ranked_models = sort_models_by_api_calls_30d(selectable_models)
            known_usage = sum(1 for model in ranked_models if model.api_calls_30d is not None)
            models_with_created_at = sum(1 for model in ranked_models if model.created_at_utc)
            if config.hybrid_topn:
                selection = select_models_hybrid_topn(
                    selectable_models,
                    config.top_free_models,
                    stable_ratio=config.stable_top_ratio,
                    trending_count=config.trending_models,
                    newest_count=config.newest_models,
                    new_model_days=config.new_model_days,
                    priority_model_ids=config.priority_models,
                )
                models = selection.models
                state["selection_summary"] = selection.summary
                if selection.summary.get("strategy") == "hybrid_topn":
                    priority_count = int(selection.summary.get("priority_count") or 0)
                    priority_extra_count = int(selection.summary.get("priority_extra_count") or 0)
                    priority_label = f"，重要中文模型={priority_count}（额外加入={priority_extra_count}）" if priority_count else ""
                    topn_message = (
                        "已使用混合 TopN 策略选择候选模型："
                        f"稳定热门={selection.summary.get('stable_count')}，"
                        f"新晋热门={selection.summary.get('trending_count')}，"
                        f"新模型保底={selection.summary.get('newest_count')}"
                        f"{priority_label}，"
                        f"已选={selection.summary.get('selected_count')}。"
                    )
                elif selection.summary.get("strategy") == "fallback_no_usage":
                    topn_message = "未获取到 30 天 API 调用量数据，回退为检测全部免费候选模型。"
                else:
                    topn_message = "未限制 TopN，检测全部免费候选模型。"
            else:
                if known_usage > 0 and config.top_free_models is not None:
                    models = ranked_models[: config.top_free_models]
                    for selection_index, model in enumerate(models, start=1):
                        model.selection_rank = selection_index
                        model.selection_bucket = "usage_only"
                        model.selection_reason = f"仅按 30 天调用量排序：排名 {model.usage_rank}"
                    topn_message = f"已按 30 天 API 调用量全局排序，仅选择前 {config.top_free_models} 个候选模型。"
                else:
                    models = ranked_models
                    topn_message = "未获取到 30 天 API 调用量数据，回退为检测全部免费候选模型。"
                state["selection_summary"] = {
                    "strategy": "usage_only",
                    "requested_top_n": config.top_free_models,
                    "selected_count": len(models),
                    "known_usage_count": known_usage,
                    "models_with_created_at": models_with_created_at,
                }
            _print_progress(
                f"筛选统计: 可确认 free 且类型匹配={selectable_count}；"
                f"跳过非免费/类型不匹配={skipped_before_topn}；"
                f"有 30 天调用量数据={known_usage}；"
                f"有上架时间数据={models_with_created_at}。"
            )
            _print_progress(topn_message)

        planned_before_limit_count = len(models)
        if config.limit is not None:
            models = models[: config.limit]
            if len(models) < planned_before_limit_count:
                _print_progress(f"--limit 已生效: 从 {planned_before_limit_count} 个候选缩减到 {len(models)} 个。")

        if config.fetch_model_details and catalog_result is not None and models:
            _print_progress("正在低频拉取 NVIDIA Build 模型详情页，补全本次候选模型的上下文长度和最大输出 token...")
            token_detail_summary = enrich_token_specs_from_build_pages(
                models,
                catalog_result,
                timeout=config.timeout,
                user_agent=config.request_user_agent,
                delay_min=config.detail_delay_min,
                delay_max=config.detail_delay_max,
            )
            state["token_detail_summary"] = token_detail_summary
            _print_progress(
                "模型详情页 token 规格补全: "
                f"尝试={token_detail_summary.get('attempted')}；"
                f"成功页={token_detail_summary.get('fetched')}；"
                f"context 更新={token_detail_summary.get('context_updated')}；"
                f"max_output 更新={token_detail_summary.get('max_output_updated')}；"
                f"已知跳过={token_detail_summary.get('skipped_already_known')}；"
                f"未匹配={token_detail_summary.get('unmatched')}；"
                f"错误={len(token_detail_summary.get('errors') or [])}。"
            )
            _print_progress(_format_token_spec_coverage(models))
            if token_detail_summary.get("errors"):
                _print_progress("模型详情页补全存在错误: " + "; ".join((token_detail_summary.get("errors") or [])[:3]))

        if free_model_count:
            plan_free_label = f"{free_model_count} 个可确认 free 模型"
        elif config.use_build_catalog and config.free_only:
            plan_free_label = "0 个可确认 free 模型；Build Free Endpoint 目录未匹配到 API 模型"
        else:
            plan_free_label = f"{free_model_count} 个可确认 free 模型"
        _print_progress(
            f"检测计划: 获取 {plan_free_label}；"
            f"类型匹配候选 {selectable_count} 个；本次检测 {len(models)} 个模型。"
        )
        if known_usage > 0:
            _print_progress(f"30 天 API 调用量覆盖: {known_usage}/{selectable_count} 个候选模型。")
        else:
            _print_progress("30 天 API 调用量覆盖: 0 个候选模型，将按回退策略检测。")
        if models:
            _print_progress("即将检测的模型列表:")
            for planned_index, planned_model in enumerate(models, start=1):
                _print_progress(f"  [{planned_index}/{len(models)}] {_format_model_identity(planned_model)}")
                if planned_model.selection_reason:
                    _print_progress(f"      选择原因: {planned_model.selection_reason}")

        if models and not config.dry_run:
            estimated_min = len(models) * config.delay_min
            estimated_max = len(models) * config.delay_max
            _print_progress(f"预计仅等待时间约: {estimated_min:.0f}-{estimated_max:.0f} 秒，不含 API 响应耗时。")

        done = completed_model_ids(state) if config.resume and not config.force_retest else set()
        breaker = BreakerState()
        total_to_process = len(models)
        processed_count = 0
        available_count = 0
        failed_count = 0
        skipped_count = 0

        for index, model in enumerate(models, start=1):
            progress_prefix = f"[{index}/{total_to_process}]"
            if model.model_id in done:
                processed_count += 1
                skipped_count += 1
                _print_progress(
                    f"{progress_prefix} 跳过已完成模型: {_format_model_identity(model)}；"
                    f"{_format_running_stats(processed_count, total_to_process, available_count, failed_count, skipped_count)}"
                )
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
                processed_count += 1
                skipped_count += 1
                _print_progress(
                    f"{progress_prefix} dry-run 记录模型: {_format_model_identity(model)} ({dry_reason})；"
                    f"{_format_running_stats(processed_count, total_to_process, available_count, failed_count, skipped_count)}"
                )
                continue

            if not selected:
                result = skipped_result(model, reason)
                upsert_result(state, result)
                save_state(config.state_file, state)
                processed_count += 1
                skipped_count += 1
                _print_progress(
                    f"{progress_prefix} 跳过 {_format_model_identity(model)}: {reason}；"
                    f"{_format_running_stats(processed_count, total_to_process, available_count, failed_count, skipped_count)}"
                )
                continue

            _print_progress(f"正在检测 {progress_prefix} {_format_model_identity(model)}")
            result = test_model(client, model, config.max_output_tokens, config.retries)
            upsert_result(state, result)
            save_state(config.state_file, state)
            status = str(result.get("test_status", ""))
            if status == "available":
                available_count += 1
            elif status == "skipped":
                skipped_count += 1
            else:
                failed_count += 1
            processed_count += 1
            _print_progress(
                f"完成 {progress_prefix} {model.model_id} -> status={status} "
                f"http={result.get('http_status')} latency={result.get('latency_total_ms')}ms "
                f"error={result.get('error_type') or ''}；"
                f"{_format_running_stats(processed_count, total_to_process, available_count, failed_count, skipped_count)}"
            )

            breaker.record(
                str(result.get("test_status", "")),
                result.get("http_status") if isinstance(result.get("http_status"), int) else None,
                str(result.get("error_type", "")),
            )

            if result.get("http_status") == 429:
                if config.stop_on_first_429:
                    _print_progress("触发 429 限流。为避免 API 风险，本次任务将立即停止。")
                else:
                    _print_progress(f"触发 429 限流，暂停 {config.rate_limit_sleep:.0f} 秒。")
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
                _print_progress(reason)
                break

            if index < len(models):
                slept = sleep_with_jitter(config.delay_min, config.delay_max)
                if slept:
                    _print_progress(f"安全等待: {slept:.1f} 秒后继续下一个模型。")

        _write_reports(config, state)
        cleanup_allowed = True
        return 0
    except KeyboardInterrupt:
        interrupted = True
        state["abort_reason"] = "用户中断任务，已停止后续模型检测。"
        save_state(config.state_file, state)
        _print_progress("检测已被用户中断，已保存当前状态。")
        return 130
    finally:
        client.close()
        if cleanup_allowed and config.cleanup_prompt != "never":
            maybe_cleanup_program(config.cleanup_prompt, project_root, _result_paths(config))
        elif interrupted and config.cleanup_prompt != "never":
            maybe_cleanup_program_after_interrupt(config.cleanup_prompt, project_root, _result_paths(config))
