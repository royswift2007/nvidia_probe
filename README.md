# NVIDIA Model Probe

一个保守限速的 NVIDIA Build API 免费模型可用性检测工具，用于在不同国家、不同服务器、不同 IP 环境中测试模型是否可调用，并输出 JSON、CSV 和 Excel 报告。

## 设计目标

- 默认串行测试，避免高并发触发限制。
- 自动拉取 NVIDIA OpenAI-compatible 模型列表。
- 默认只测试能从模型元数据明确判断为免费的模型；无法确认免费的模型默认跳过。
- 对 chat、embedding、reranker 模型进行低成本探测。
- 默认跳过 image、video、audio 等高成本生成模型。
- 记录服务器公网 IP、国家、系统、Python 版本等环境信息。
- 保存断点 JSON，支持中断后继续。
- 运行时实时输出 free 模型数量、计划检测数量、当前模型、结果和累计进度。
- 输出 CSV、JSON，安装 openpyxl 后输出 Excel。
- 执行完成后弹出或提示是否保留程序；默认删除程序文件，仅输入 y/yes 或选择“是”才保留程序文件。

## 远程服务器一条命令运行

在 Linux 远程服务器上，可以直接执行一条命令完成拉取、安装、运行。命令会自动检查 `git`、`python3` 和 Python `venv/ensurepip`；在 Debian/Ubuntu 且有 root/sudo 权限时，如果缺少 `python3.13-venv`、`python3-venv` 这类依赖，会自动尝试安装。随后脚本会创建虚拟环境；如果没有设置 `NVIDIA_API_KEY`，会提示隐藏输入 API Key，然后开始测试。

推荐使用下面这种 `bash -c "$(curl ...)"` 形式，而不是 `curl ... | bash`，这样后续 Python 进程仍然可以从交互式终端安全读取 API Key：

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/royswift2007/nvidia_probe/main/scripts/run_remote.sh)"
```

如果服务器没有 `curl`，但有 `wget`：

```bash
bash -c "$(wget -qO- https://raw.githubusercontent.com/royswift2007/nvidia_probe/main/scripts/run_remote.sh)"
```

也可以在同一条命令里传入测试参数，例如只安全预检 3 个模型：

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/royswift2007/nvidia_probe/main/scripts/run_remote.sh)" nvidia-probe --top-free-models 3
```

默认运行结束后会询问是否卸载程序。一键运行时，测试结果默认保存到当前目录的 `nvidia_probe_results`，程序安装目录默认是当前目录的 `.nvidia_probe`。选择卸载时会在 Python 进程退出后删除 `.nvidia_probe` 整个程序目录，只保留 `nvidia_probe_results` 中的测试结果。若想运行后不询问卸载，可追加参数：

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/royswift2007/nvidia_probe/main/scripts/run_remote.sh)" nvidia-probe --cleanup-prompt never
```

默认会安装到当前目录下的 `.nvidia_probe`。如需指定安装目录：

```bash
NVIDIA_PROBE_INSTALL_DIR=/tmp/nvidia_probe bash -c "$(curl -fsSL https://raw.githubusercontent.com/royswift2007/nvidia_probe/main/scripts/run_remote.sh)"
```

如需指定结果目录：

```bash
NVIDIA_PROBE_RESULT_DIR=/root/nvidia_results bash -c "$(curl -fsSL https://raw.githubusercontent.com/royswift2007/nvidia_probe/main/scripts/run_remote.sh)"
```

如果上一次卸载后只剩 `.nvidia_probe/results` 这类旧结果目录，新脚本会先把旧结果迁移到 `nvidia_probe_results` 或带时间戳的备份目录，再重新克隆程序。

如果缺少系统依赖，脚本会尽量自动处理。你的服务器如果出现 `ensurepip is not available`，说明缺少当前 Python 小版本对应的 venv 包，例如 Python 3.13 需要 `python3.13-venv`。Ubuntu/Debian 可手动执行：

```bash
sudo apt update && sudo apt install -y curl git python3 python3-venv python3.13-venv
```

如果不是 Python 3.13，请把 `python3.13-venv` 替换为当前版本，例如 `python3.12-venv`。

## 安装

推荐在虚拟环境中安装：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -e .
```

Linux/macOS：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

如果创建虚拟环境时报 `ensurepip is not available`，请先安装当前 Python 版本对应的 venv 包，例如 `sudo apt install -y python3.13-venv`。

## API Key

真实拉取模型列表和调用模型通常必须使用有效 NVIDIA API Key，不建议也不保证匿名测试可用。

本项目不会在代码里预置 API Key，也不会把 API Key 写入报告或状态文件。运行时按以下优先级读取：

1. 命令行参数 `--api-key`。
2. 环境变量 `NVIDIA_API_KEY`。
3. 环境变量 `NGC_API_KEY`。
4. 如果以上都没有，且当前是交互式终端，会提示用户隐藏输入 API Key。

推荐直接运行命令，然后按提示输入，输入内容不会显示：

```bash
nvidia-probe run --top-free-models 3 --cleanup-prompt never
```

也可以使用环境变量，避免每次输入：

PowerShell：

```powershell
$env:NVIDIA_API_KEY="你的 NVIDIA API Key"
```

Linux/macOS：

```bash
export NVIDIA_API_KEY="你的 NVIDIA API Key"
```

非交互式环境，例如后台脚本、CI、cron、systemd，必须提前设置 `NVIDIA_API_KEY`，否则无法安全提示输入。

## 默认测试数量策略

默认不会测试全部免费模型，而是先拉取模型列表，再只保留可确认免费的模型，然后使用“混合 TopN”策略默认选择 20 个模型：

1. 稳定热门池：优先保留长期 30 天 API 调用量靠前的模型。
2. 新晋热门池：优先保留最近 30 天内上架、日均调用量高、折算 30 天热度高的新模型。
3. 新模型保底池：默认不占名额；如果你想额外保留刚上架但调用量还没起来的新模型，可以通过 `--newest-models` 手动开启。

默认 Top20 配比大致是：稳定热门 14 个、新晋热门 6 个、新模型保底 0 个，不再使用“补位池”把名额回填给普通老模型。这样既保留高请求数量的老模型，也能覆盖类似 `z-ai/glm-5.2` 这种刚上架但增长很快的新模型，同时不增加测试请求总量。如果新晋热门候选不足，工具不会再用普通老模型补位，本次实际测试数量可能少于 `--top-free-models`。

如果 NVIDIA 模型列表接口没有返回任何 30 天调用量字段，工具会把调用量标记为 `unknown`，并回退为检测全部可确认免费的候选模型。

默认会额外抓取 NVIDIA Build 的 Free Endpoint 页面 `https://build.nvidia.com/models?filters=nimType%3Anim_type_preview`，该页面当前搜索总数约为 77 个 Free Endpoint 模型。工具会按页面分页抓取完整目录，把 `Free Endpoint` 标记、`last_month_api_invocation_count` 和 `dateCreated` 回填到 API 模型列表，再只测试匹配到的免费模型。这样不会把 API `/models` 返回的 121 个费用未知模型全部当成免费模型。

由于 NVIDIA `/models` 接口和 Build Free Endpoint 列表页通常不直接提供上下文长度、最大输出 token 这类规格，工具默认会在最终 TopN/limit 候选模型确定后，再以 1 到 3 秒随机间隔低频抓取对应的单模型 Build 详情页，尽量从详情页文本和请求 schema 中补全 `context_length` 与 `max_output_tokens`。如需关闭详情页补全，可传入 `--no-model-details`；如需调整详情页抓取间隔，可使用 `--detail-delay-min` 和 `--detail-delay-max`。

可以自定义测试数量：

```powershell
nvidia-probe run --top-free-models 10 --cleanup-prompt never
```

如果确实要测试更多免费模型：

```powershell
nvidia-probe run --top-free-models 50 --cleanup-prompt never
```

也可以调整混合 TopN 配比：

```powershell
nvidia-probe run --top-free-models 20 --stable-top-ratio 0.7 --trending-models 6 --newest-models 0 --new-model-days 14
```

如需退回旧逻辑，只按 30 天总调用量排序：

```powershell
nvidia-probe run --no-hybrid-topn --top-free-models 20
```

## 运行时实时进度

运行时会持续在终端输出总体和详细检测状态，适合 SSH、tmux、screen 或服务器日志查看。关键输出包括：

- 已拉取模型总数，以及 Build Free Endpoint 目录总数、抓取数量、与 API 模型匹配数量。
- 可确认 free、非免费/付费、费用未知模型数量。
- 可确认 free 且类型匹配的候选数量、30 天 API 调用量覆盖数量、上架时间覆盖数量、混合 TopN 或回退策略说明。
- 本次实际检测数量，例如“获取 77 个可确认 free 模型；类型匹配候选 77 个；本次检测 20 个模型”。
- 即将检测的模型列表，包含模型 ID、名称、类型、选择池、调用量排名、折算 30 天热度、模型年龄和选择原因。
- 每个模型开始时显示“正在检测 [3/20] xxx”。
- 每个模型完成后显示状态、HTTP 状态、延迟、错误类型，以及累计成功/失败/跳过数量。

示例输出：

```text
Build Free Endpoint 目录: 页面总数=77；已抓取=77；与 API 模型匹配=77。
已拉取模型总数: 121
free 模型统计: 可确认 free=77，非免费/付费=0，费用未知=44
检测计划: 获取 77 个可确认 free 模型；类型匹配候选 77 个；本次检测 20 个模型。
已使用混合 TopN 策略选择候选模型：稳定热门=14，新晋热门=6，新模型保底=0，已选=20。
正在检测 [15/20] z-ai/glm-5.2 | type=chat | select_rank=15 | bucket=trending_new | usage_rank=35 | trend_rank=4 | 30d_calls=1.8M | projected_30d=32.2M | age=1.7d
完成 [15/20] z-ai/glm-5.2 -> status=available http=200 latency=1234ms error=；累计: 已处理 15/20，成功 12，失败 3，跳过 0
```

## 免费模型策略

默认开启“只测试可确认免费模型”：

- 优先使用 NVIDIA Build Free Endpoint 页面识别免费模型，该页面会返回约 77 个 Free Endpoint 搜索结果。
- 如果 API 模型元数据中有 `free`、`is_free`、`free_tier`、`no_cost`、`price: 0` 等明确免费信号，也会被视为免费。
- 如果模型元数据中出现 `paid`、`billable`、`metered`、正价格等信号，会跳过。
- 如果模型既不在 Build Free Endpoint 页面中，也没有明确免费信息，默认跳过，避免误测可能收费模型。
- 报告会输出 `is_free`、`pricing_model`、`free_reason` 字段，方便审计为什么该模型被测试或跳过。

不建议关闭该策略。如你确认当前 API 账户只暴露免费模型，可手动放宽：

```powershell
nvidia-probe run --allow-unknown-cost
```

如果不想抓取 NVIDIA Build 页面，只依赖 API 模型列表中的 free 元数据：

```powershell
nvidia-probe run --no-build-catalog
```

如果要完全关闭免费过滤，需要显式传入：

```powershell
nvidia-probe run --no-free-only
```

## 快速运行

先做 3 个模型的安全预检。默认已经使用 10 到 25 秒随机间隔、0 重试、首次 429 立即停止：

```powershell
nvidia-probe run --top-free-models 3 --cleanup-prompt never
```

或者不安装入口，直接运行模块：

```powershell
python -m nvidia_probe run --top-free-models 3 --cleanup-prompt never
```

## 完整慢速测试

默认完整测试使用 10 到 25 秒随机间隔，兼顾速度和安全：

```powershell
nvidia-probe run --output-dir results --cleanup-prompt never
```

更保守模式会使用至少 60 到 120 秒随机间隔、0 重试、首次 429 立即停止：

```powershell
nvidia-probe run --strict-safe --output-dir results --cleanup-prompt never
```

## 只拉取模型列表，不真实调用

```powershell
nvidia-probe run --dry-run --output-dir results
```

## 断点续跑

默认会在输出目录保存 `probe_state.json`。中断后可继续：

```powershell
nvidia-probe run --resume --output-dir results
```

## 多地区合并

将多个服务器生成的 `probe_state.json` 或 raw JSON 拷贝到一起，然后执行：

```powershell
nvidia-probe merge --inputs jp_probe_state.json de_probe_state.json us_probe_state.json --output-dir merged
```

## 自清理行为

任务结束后默认会询问是否保留程序文件，默认操作是删除程序本体、只保留测试结果。删除程序文件只会卸载工具本体，不会删除刚刚生成的检测结果：

- 只有输入 `y` / `yes`，或在图形窗口中选择“是”，才会保留程序文件。
- 直接回车、输入 `n` / `no`、在最终确认提示时按 Ctrl+C、关闭图形窗口，都会删除 `nvidia_probe` 包、`scripts`、`.venv`、`.git`、`pyproject.toml`、`requirements.txt`、`README.md`、构建目录和安装元数据等程序文件；刚刚生成的检测结果文件会继续保留在结果目录。
- 一键运行脚本会把结果默认放在安装目录外的 `nvidia_probe_results`，因此选择卸载后会先写入卸载标记，再由外层脚本在 Python 进程退出后删除 `.nvidia_probe` 整个安装目录。
- 如果检测过程中按 Ctrl+C 中断，工具会保存当前状态并跳过卸载提示，避免在异常退出时删除正在运行的程序目录并产生 traceback；只有任务正常完成后的最终确认提示里按 Ctrl+C 才会按默认操作删除程序本体。
- 如果你手动运行且把 `--output-dir` 放在项目目录内部，项目根目录会因为包含结果文件而保留，但程序文件仍会被删除。
- 如果想无提示保留程序文件，请使用 `--cleanup-prompt never`。

如果远程环境没有图形界面，会退化为命令行确认。可通过参数控制：

```powershell
nvidia-probe run --cleanup-prompt always
nvidia-probe run --cleanup-prompt never
nvidia-probe run --cleanup-prompt auto
```

## 安全默认值

| 配置 | 默认值 |
|---|---:|
| 并发 | 1 |
| 每模型请求 | 1 次 |
| 请求间隔 | 10 到 25 秒随机 |
| 超时 | 60 秒 |
| 最大输出 token | 8 |
| 重试 | 0 次 |
| 429 后暂停 | 600 秒，仅在显式允许继续时使用 |
| 连续 429 熔断 | 1 次，默认首次 429 立即停止 |
| 连续 403 熔断 | 5 次 |
| 连续网络错误熔断 | 10 次 |
| 默认测试类型 | chat、embedding、reranker |
| 默认测试数量 | 混合 TopN 取免费模型前 20 个，约 14 个稳定热门 + 6 个新晋热门 + 0 个新模型保底，不再使用补位池 |
| 免费模型过滤 | 开启，优先使用 Build Free Endpoint 目录识别约 77 个免费模型 |
| 未知费用模型 | 默认跳过 |

## 输出文件

手动运行时默认输出目录为 `results`；一键运行脚本默认输出到安装目录外的 `nvidia_probe_results`。结果目录包含：

- `probe_state.json`：断点、运行配置、环境信息、完整原始结果；排名、30 天调用量、筛选原因、原始模型响应等审计信息仍保留在这里。
- `nvidia_models_report.csv`：精简调用决策表，只保留调用模型时真正有价值的字段，默认把可用模型排在前面，再按连接延迟从低到高排序。
- `nvidia_models_report.xlsx`：精简 Excel 报告，如果安装 openpyxl。
- `merge_report.csv`：多地区合并结果。
- `merge_report.xlsx`：多地区合并 Excel，如果安装 openpyxl。

Excel 报告包含多个工作表：

- `Summary`：汇总可用数量、失败数量、最快/最慢/平均延迟，以及可用模型中支持图像输入、coding、reasoning、tool/function calling 的数量。
- `Available`：推荐优先查看的工作表，只包含可调用成功的模型，并按 `latency_total_ms` 从低到高排序；用于快速判断当前服务器环境下哪些模型速度更快、最适合调用。
- `All Models`：全部测试结果，仍然优先显示可用模型，再显示失败或跳过模型。
- `Errors`：只列出调用失败、限流、地区阻断、无权限、网络错误等非可用结果。
- `Environment`：服务器公网 IP、国家、系统、Python 版本等环境信息，方便多地区对比。

CSV/XLSX 报告列已经精简为调用决策优先，只保留这些核心字段：

- `model_id` / `display_name` / `provider` / `endpoint_type` / `model_type`：调用时需要识别的模型基础信息。
- `test_status`：模型是否可用，`available` 表示当前服务器、当前 API Key、当前网络环境下调用成功。
- `latency_total_ms`：真实探测请求总延迟，越低代表当前环境连接越快。
- `context_length`：模型上下文长度。
- `max_output_tokens`：模型最大输出 token 数。
- `supports_image_input`：是否支持图像输入或多模态输入。
- `supports_coding`：是否偏向代码生成或 coding 场景。
- `supports_reasoning`：是否带 reasoning、thinking、math 等推理标签。
- `supports_function_calling` / `supports_tools`：是否带 tool use、function calling、agentic 等工具调用标签。
- `supports_json_mode` / `supports_streaming` / `supports_embedding`：JSON、流式、embedding 等调用能力。
- `vector_dimension`：embedding 模型可用时的向量维度。
- `capability_tags` / `usecase_tags`：从 NVIDIA Build 元数据提取的能力和用途标签。
- `error_type` / `error_message` / `http_status` / `skip_reason`：不可用模型的失败或跳过原因。

`selection_rank`、`selection_bucket`、`usage_rank`、`api_calls_30d`、`projected_30d_calls`、`created_at_utc`、`context_length_source`、`max_output_tokens_source` 等审计/来源字段不再写入 CSV/XLSX，避免表格臃肿；如需排查筛选原因或字段来源，可查看完整的 `probe_state.json`。

## 注意事项

- 默认只测试可确认免费的模型，优先通过 NVIDIA Build Free Endpoint 页面识别免费模型集合。
- 每个模型都会先做一次低成本真实调用，`test_status=available` 才代表当前服务器环境下真实可调用成功。
- 上下文长度、最大输出 token、图像、coding、reasoning、tool/function calling 等能力字段主要来自 NVIDIA API 模型元数据、Build Free Endpoint 页面标签、Build 单模型详情页和内置已知规格兜底表；即使某个模型本次不可调用，报告也会尽量保留这些元数据，便于判断是网络/地区/API 权限问题还是模型能力不符合需求。
- 如果能获取 `API calls in the last 30 days` 或 Build 页面中的 `last_month_api_invocation_count`，默认使用混合 TopN 选择前 20 个免费模型，可用 `--top-free-models` 调整总数量。
- 如果完全无法获取 30 天调用量数据，则回退为检测全部可确认免费的候选模型。
- 如果 NVIDIA 模型列表接口不提供费用元数据，工具会先用 Build Free Endpoint 页面补充 free 标记；仍无法确认免费的模型会被标记为 `unknown_cost` 并跳过。
- 默认无重试，避免同一模型失败后短时间重复请求。
- 默认首次 429 立即停止，避免继续请求带来 API 风险。
- 如果连续出现 403，脚本会提前熔断，因为这通常代表地区、账号、权限或风控限制。
- 不要使用高并发测试。
- 不要使用超长 prompt 探测上下文长度。
- 不要默认测试图像、视频、音频生成模型。
- 403 可能是地区、账号、模型权限或 IP 风控导致。
- 429 表示限流，默认会立即停止；不建议使用 `--continue-after-429`。
