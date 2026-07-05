from __future__ import annotations

import argparse
from pathlib import Path

from .config import DEFAULT_BASE_URL, DEFAULT_BUILD_CATALOG_URL, DEFAULT_OUTPUT_DIR, build_probe_config
from .merge import merge_states, write_merge_csv, write_merge_excel
from .runner import run_probe


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nvidia-probe",
        description="安全、低频地检测当前服务器环境下 NVIDIA Build API 模型可用性。",
    )
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="拉取模型列表并执行低频可用性测试。")
    run_parser.add_argument("--api-key", help="NVIDIA API Key。推荐使用 NVIDIA_API_KEY 环境变量。")
    run_parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="NVIDIA API Base URL。")
    run_parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="输出目录。")
    run_parser.add_argument("--limit", type=int, default=None, help="最多处理多少个模型；在 Top 免费模型筛选后再应用。")
    run_parser.add_argument(
        "--top-free-models",
        type=int,
        default=20,
        help="按 30 天 API 调用量排序后最多测试多少个免费模型；默认 20。",
    )
    run_parser.add_argument("--only-model", default=None, help="只测试指定模型 ID。")
    run_parser.add_argument("--include-types", default="chat,embedding,reranker", help="逗号分隔的测试类型。")
    run_parser.add_argument("--exclude-types", default="image,video,audio", help="逗号分隔的跳过类型。")
    run_parser.add_argument("--delay-min", type=float, default=30.0, help="模型测试间隔下限，单位秒；默认安全优先。")
    run_parser.add_argument("--delay-max", type=float, default=75.0, help="模型测试间隔上限，单位秒；默认安全优先。")
    run_parser.add_argument("--timeout", type=float, default=60.0, help="单请求超时时间，单位秒。")
    run_parser.add_argument("--retries", type=int, default=0, help="失败重试次数；默认 0，避免重复触发限制。")
    run_parser.add_argument("--max-output-tokens", type=int, default=8, help="测试请求最大输出 token；默认 8，降低请求成本。")
    run_parser.add_argument("--rate-limit-sleep", type=float, default=600.0, help="遇到 429 后暂停秒数。")
    run_parser.add_argument("--consecutive-429-breaker", type=int, default=1, help="连续 429 熔断阈值；默认首次 429 即停止。")
    run_parser.add_argument("--consecutive-403-breaker", type=int, default=5, help="连续 403/地区或权限限制熔断阈值。")
    run_parser.add_argument("--consecutive-network-breaker", type=int, default=10, help="连续网络错误熔断阈值。")
    run_parser.add_argument("--continue-after-429", action="store_true", help="遇到 429 后不立即停止。不建议使用。")
    run_parser.add_argument("--dry-run", action="store_true", help="只拉模型列表和导出，不真实调用模型。")
    run_parser.add_argument("--resume", action="store_true", help="读取已有 probe_state.json 断点续跑。")
    run_parser.add_argument("--force-retest", action="store_true", help="即使已有结果也重新测试。")
    run_parser.add_argument("--no-ip-lookup", action="store_true", help="禁用公网 IP 地理信息查询。")
    run_parser.add_argument("--strict-safe", action="store_true", help="启用更保守的安全默认值。")
    run_parser.add_argument(
        "--no-free-only",
        action="store_true",
        help="关闭默认的只测试可确认免费模型策略。不建议使用。",
    )
    run_parser.add_argument(
        "--allow-unknown-cost",
        action="store_true",
        help="允许测试无法从元数据确认免费/收费的模型。不建议使用。",
    )
    run_parser.add_argument(
        "--no-build-catalog",
        action="store_true",
        help="不抓取 NVIDIA Build Free Endpoint 页面辅助识别免费模型。不建议使用。",
    )
    run_parser.add_argument(
        "--build-catalog-url",
        default=DEFAULT_BUILD_CATALOG_URL,
        help="NVIDIA Build Free Endpoint 模型页面 URL。",
    )
    run_parser.add_argument(
        "--cleanup-prompt",
        choices=("auto", "always", "never"),
        default="auto",
        help="任务结束后是否询问删除程序文件。auto/always 会询问，never 不询问。",
    )

    merge_parser = subparsers.add_parser("merge", help="合并多个服务器生成的 probe_state.json。")
    merge_parser.add_argument("--inputs", nargs="+", required=True, help="多个 probe_state.json 文件路径。")
    merge_parser.add_argument("--output-dir", default="merged", help="合并报告输出目录。")

    return parser


def run_merge(args: argparse.Namespace) -> int:
    input_paths = [Path(item).expanduser().resolve() for item in args.inputs]
    output_dir = Path(args.output_dir).expanduser().resolve()
    rows = merge_states(input_paths)
    csv_path = output_dir / "merge_report.csv"
    xlsx_path = output_dir / "merge_report.xlsx"
    write_merge_csv(csv_path, rows)
    excel_written = write_merge_excel(xlsx_path, rows)
    print(f"已合并 {len(input_paths)} 个报告，模型行数: {len(rows)}")
    print(f"- CSV: {csv_path}")
    if excel_written:
        print(f"- Excel: {xlsx_path}")
    else:
        print("- Excel: 未生成，未安装 openpyxl。")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    if args.command == "merge":
        return run_merge(args)
    if args.command == "run":
        config = build_probe_config(args)
        project_root = Path(__file__).resolve().parent.parent
        return run_probe(config, project_root)
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
