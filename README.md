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
- 任务正常完成后弹出或提示是否保留程序；默认删除程序文件，仅输入 y/yes 或选择“是”才保留程序文件。
- 任务检测过程中按 Ctrl+C 中断时会保存当前状态并询问是否删除程序；默认不删除，方便稍后断点续跑。

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

默认正常运行结束后会询问是否卸载程序。一键运行时，测试结果默认保存到当前目录的 `nvidia_probe_results`，程序安装目录默认是当前目录的 `.nvidia_probe`。选择卸载时会在 Python 进程退出后删除 `.nvidia_probe` 整个程序目录，只保留 `nvidia_probe_results` 中的测试结果。如果检测过程中按 Ctrl+C 中断，会改为询问是否删除程序，默认不删除。若想运行后不询问卸载，可追加参数：

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

## 完整规则与参数

本节按当前真实代码整理，覆盖 `run`、`merge`、远程一键脚本、模型筛选、请求、限流、输出和自清理规则。

### `run` 命令参数

| 参数 | 默认值 | 规则 |
|---|---:|---|
| `-h` / `--help` | 自动生成 | 显示 `run` 命令帮助并退出。 |
| `--api-key` | 空 | NVIDIA API Key。优先级高于环境变量；不会写入报告或状态文件。 |
| `--base-url` | `https://integrate.api.nvidia.com/v1` | NVIDIA OpenAI-compatible API Base URL；也可用 `NVIDIA_BASE_URL` 覆盖。 |
| `--output-dir` | `results` | 输出目录。会生成 `probe_state.json`、`nvidia_models_report.csv`、`nvidia_models_report.xlsx`。 |
| `--limit` | 空 | 在 TopN/混合筛选之后再截断本次处理模型数量。 |
| `--top-free-models` | `20` | 混合 TopN 或调用量排序策略下最多选择多少个免费候选模型；必须大于 0。 |
| `--only-model` | 空 | 只测试指定模型 ID；仍会走免费/类型规则，除非同时调整相关参数。 |
| `--no-hybrid-topn` | 关闭 | 关闭混合 TopN，退回只按 30 天 API 调用量排序。 |
| `--stable-top-ratio` | `0.7` | 混合 TopN 中稳定热门模型比例；必须在 0 到 1 之间。 |
| `--trending-models` | `6` | 混合 TopN 中新晋热门模型配额；不能为负数。 |
| `--newest-models` | `0` | 混合 TopN 中最近上架模型保底配额；不能为负数。 |
| `--new-model-days` | `14.0` | 多少天内上架视为新模型；必须大于 0。 |
| `--include-types` | `chat,embedding,reranker` | 只允许这些模型类型进入测试，逗号分隔。 |
| `--exclude-types` | `image,video,audio` | 跳过这些模型类型，逗号分隔；排除规则优先于包含规则。 |
| `--delay-min` | `10.0` | 两个模型真实调用之间的随机等待下限，单位秒；不能为负数。 |
| `--delay-max` | `25.0` | 两个模型真实调用之间的随机等待上限，单位秒；不能小于 `--delay-min`。 |
| `--timeout` | `60.0` | 单个 HTTP 请求超时时间，单位秒。 |
| `--retries` | `0` | 单模型失败重试次数；不能为负数。默认 0，避免重复触发限制。 |
| `--max-output-tokens` | `8` | chat 探测请求的 `max_tokens`；必须大于 0。 |
| `--rate-limit-sleep` | `600.0` | 只有显式允许 429 后继续时，遇到 429 的暂停秒数。 |
| `--consecutive-429-breaker` | `1` | 连续 429 熔断阈值。默认配合“首次 429 立即停止”。 |
| `--consecutive-403-breaker` | `5` | 连续 403/地区或权限限制熔断阈值。 |
| `--consecutive-network-breaker` | `10` | 连续网络错误熔断阈值。 |
| `--continue-after-429` | 关闭 | 关闭“首次 429 立即停止”；不建议使用。 |
| `--dry-run` | 关闭 | 只拉取、筛选、导出模型元数据，不真实调用模型。 |
| `--resume` | 关闭 | 读取已有 `probe_state.json` 断点续跑；默认跳过已完成模型。 |
| `--force-retest` | 关闭 | 配合 `--resume` 时，忽略已有结果并重新测试。 |
| `--no-ip-lookup` | 关闭 | 禁用公网 IP 地理信息查询。 |
| `--strict-safe` | 关闭 | 启用更保守安全默认值：请求间隔至少 60–120 秒，重试 0，测试输出 token 不超过 8，429 暂停至少 900 秒，首次 429 停止。 |
| `--no-free-only` | 关闭 | 关闭“只测试可确认免费模型”。不建议使用。 |
| `--allow-unknown-cost` | 关闭 | 允许测试费用未知模型。不建议使用。 |
| `--no-build-catalog` | 关闭 | 不抓取 NVIDIA Build Free Endpoint 页面辅助识别免费模型。不建议使用。 |
| `--build-catalog-url` | `https://build.nvidia.com/models?filters=nimType%3Anim_type_preview` | NVIDIA Build Free Endpoint 目录页 URL。 |
| `--no-model-details` | 关闭 | 不抓取单模型 Build 详情页补全上下文长度和最大输出 token。 |
| `--detail-delay-min` | `1.0` | 单模型 Build 详情页抓取间隔下限，单位秒；不能为负数。 |
| `--detail-delay-max` | `3.0` | 单模型 Build 详情页抓取间隔上限，单位秒；不能小于 `--detail-delay-min`。 |
| `--cleanup-prompt` | `auto` | `auto`/`always` 会在任务完成后询问是否保留程序；`never` 不询问并保留程序。 |

### `merge` 命令参数

| 参数 | 默认值 | 规则 |
|---|---:|---|
| `-h` / `--help` | 自动生成 | 显示 `merge` 命令帮助并退出。 |
| `--inputs` | 必填 | 多个服务器生成的 `probe_state.json` 文件路径。 |
| `--output-dir` | `merged` | 合并报告输出目录，生成 `merge_report.csv` 和可选 `merge_report.xlsx`。 |

### 远程一键脚本环境变量

| 环境变量 | 默认值 | 规则 |
|---|---:|---|
| `NVIDIA_PROBE_REPO_URL` | `https://github.com/royswift2007/nvidia_probe.git` | 一键脚本克隆/更新的仓库地址。 |
| `NVIDIA_PROBE_BRANCH` | `main` | 克隆/更新的分支。 |
| `NVIDIA_PROBE_INSTALL_DIR` | 当前目录下 `.nvidia_probe` | 程序安装目录。 |
| `NVIDIA_PROBE_RESULT_DIR` | 当前目录下 `nvidia_probe_results` | 结果目录，默认在安装目录外，卸载程序时不会删除。 |
| `NVIDIA_PROBE_CLEANUP_MARKER` | 当前目录下 `.nvidia_probe_cleanup_marker` | 一键脚本用于延迟删除安装目录的标记文件。 |
| `PYTHON` | `python3` | 一键脚本使用的 Python 命令。 |
| `NVIDIA_API_KEY` | 空 | API Key；如果未设置且是交互终端，会隐藏提示输入。 |
| `NGC_API_KEY` | 空 | API Key 备用环境变量。 |
| `NVIDIA_BASE_URL` | 空 | 可覆盖默认 API Base URL。 |

### 运行流程规则

1. 收集环境信息：主机名、公网 IP/地区、系统、Python 版本、代理变量等；如传入 `--no-ip-lookup` 则跳过公网 IP 查询。
2. 拉取 NVIDIA API `/models`，失败则保存 `abort_reason` 并停止。
3. 归一化模型：推断模型类型、免费状态、30 天调用量、上架时间、能力标签、token 规格等。
4. 默认抓取 NVIDIA Build Free Endpoint 目录，分页解析约 77 个 Free Endpoint 模型，并把免费标记、30 天调用量、上架时间、能力标签回填到 API 模型。
5. 根据免费规则和类型规则构造候选模型。
6. 默认使用混合 TopN 选择最终候选；如果关闭混合 TopN，则只按 30 天调用量排序。
7. 如果设置 `--limit`，在 TopN/混合筛选之后再截断。
8. 默认对最终候选模型低频抓取单模型 Build 详情页，补全 `context_length` 和 `max_output_tokens`。
9. 如果不是 `--dry-run`，按顺序串行真实调用每个模型，模型之间随机等待 `--delay-min` 到 `--delay-max` 秒。
10. 每个模型完成后立即写入 `probe_state.json`，支持中断后续跑。
11. 任务结束后写出 JSON、CSV、Excel，并按 `--cleanup-prompt` 决定是否卸载程序本体。

### 模型类型与请求规则

| 模型类型 | 测试接口 | 请求内容 |
|---|---|---|
| `chat` 或其他默认文本模型 | `POST /chat/completions` | `messages=[{"role":"user","content":"Reply with exactly: OK"}]`，`temperature=0`，`max_tokens=--max-output-tokens`，`stream=false`。 |
| `embedding` | `POST /embeddings` | `input="hello"`。如果成功，会记录向量维度。 |
| `reranker` | `POST /ranking` | 先尝试 `query` + `documents` 格式；如果 400/404/422，再尝试 `input.query` + `input.documents` 格式。 |

模型类型推断规则：模型元数据或模型 ID 中包含 `embedding`/`embed`/`retrieval` 视为 `embedding`；包含 `rerank`/`ranking`/`ranker` 视为 `reranker`；包含 `vision`/`vlm`/`multimodal`/`ocr` 视为 `vision`；包含 `image`/`diffusion`/`sdxl`/`flux` 视为 `image`；包含 `video` 视为 `video`；包含 `audio`/`speech`/`tts`/`asr` 视为 `audio`；包含 `chat`/`instruct`/`llm`/`language`/`completion`/`reasoning` 或无法识别时按 `chat` 处理。

### 免费模型识别规则

默认 `free_only=true`，只有可确认免费模型才会测试：

- 优先使用 Build Free Endpoint 目录；匹配到目录中的模型会标记为免费。
- API 元数据中出现明确免费键或值也会视为免费，例如 `free`、`is_free`、`free_endpoint`、`free_tier`、`no_cost`、`zero_cost`、`price=0`。
- API 元数据中出现明确付费键或值会视为非免费，例如 `paid`、`billable`、`metered`、`requires_payment`、`requires_billing`、`positive price`。
- 费用未知模型默认跳过；只有传入 `--allow-unknown-cost` 才会测试。
- 传入 `--no-free-only` 会关闭免费过滤，不建议使用。

### 混合 TopN 选择规则

默认 `--top-free-models 20 --stable-top-ratio 0.7 --trending-models 6 --newest-models 0 --new-model-days 14`：

1. 先按 30 天 API 调用量排序，并记录 `usage_rank`。
2. 如果 `--top-free-models` 为空或大于等于候选总数，则检测全部候选。
3. 如果完全没有 30 天调用量数据，则回退为检测全部可确认免费的候选模型。
4. 否则计算三个池的配额：新模型保底池最多 `--newest-models`；新晋热门池最多 `--trending-models`；剩余名额给稳定热门池，同时尽量满足 `--stable-top-ratio`。默认 Top20 会得到 14 个稳定热门池 + 6 个新晋热门池 + 0 个新模型保底。
5. 新晋热门池会先被预留：优先取模型年龄不超过 30 天、且可计算折算 30 天调用量的模型，按折算 30 天调用量排序；这些模型不会再被稳定热门池提前占用。
6. 如果 30 天内可计算热度的新晋候选不足 `--trending-models`，新晋热门池会继续用“较新且有调用量数据”的模型补足，再退回用有调用量排名的候选补足，保证候选总数充足时默认 Top20 仍是 14 个稳定热门池 + 6 个新晋热门池。
7. 新模型保底池也会预留：只取模型年龄不超过 `--new-model-days` 的模型，按年龄更小优先，再按 30 天调用量排序；已预留的新晋热门模型不会重复计入新模型保底池。
8. 稳定热门池按 30 天调用量排序，并跳过已经预留给新晋热门池/新模型保底池的模型，避免新晋热门配额被稳定池吃掉。
9. 传入 `--no-hybrid-topn` 后，如果存在 30 天调用量数据，就只取调用量排名前 `--top-free-models`；如果没有调用量数据，则检测全部候选。

### token 规格与能力标签规则

- 上下文长度和最大输出 token 先从 API `/models` 元数据递归扫描。
- Build Free Endpoint 目录描述中如果出现 `1M`、`256K`、`262,144` 等上下文信息，也会回填。
- 默认对最终候选模型抓取单模型 Build 详情页，解析文本中的 context 信息，以及 schema 中的 `max_tokens.maximum`。
- 如果仍无法获取，会使用内置已知模型规格兜底表；例如 `z-ai/glm-5.2` 可补 `context_length=1000000` 和 `max_output_tokens=32768`。
- 能力标签来自 API/Build 元数据里的 `general`、`usecase`、`cloudPartnerType`、`playgroundType`。包含 `vision`、`vlm`、`ocr`、`multimodal` 等视为图像/视觉；包含 `coding`/`code` 视为 coding；包含 `reasoning`/`thinking`/`math` 视为 reasoning；包含 `tool use`/`function calling`/`agentic`/`agent` 视为工具调用。

### 响应状态与错误分类规则

| HTTP/异常 | `test_status` | `error_type` |
|---|---|---|
| 2xx | `available` | 空 |
| 请求超时异常或 HTTP 408 | `timeout` | `timeout` |
| 连接异常 | `network_error` | `network_error` |
| 400 | `invalid_request` | `bad_request` |
| 401 | `unauthorized` | `unauthorized` |
| 403 | `forbidden_or_region_block` | `forbidden_or_region_block` |
| 404 | `model_not_found_or_not_exposed` | `not_found` |
| 429 | `rate_limited` | `rate_limited` |
| 5xx | `server_error` | `server_error` |
| 其他请求异常 | `request_error` 或 `unknown_error` | 对应异常类型 |

重试规则：每个模型最多请求 `--retries + 1` 次；遇到 `available`、401、403、429、400、404 时立即停止该模型后续重试，避免重复打同一个受限接口。

### 熔断与限流规则

- 默认首次 429 立即停止整个任务。
- 如果传入 `--continue-after-429`，则遇到 429 后暂停 `--rate-limit-sleep` 秒，并继续依赖连续 429 熔断阈值。
- 连续 401 达到 2 次，停止任务。
- 连续 429 达到 `--consecutive-429-breaker`，停止任务。
- 连续 403 达到 `--consecutive-403-breaker`，停止任务。
- 连续限制类错误达到 6 次，停止任务。限制类包括 403、429、401 或对应错误类型。
- 连续网络错误达到 `--consecutive-network-breaker`，停止任务。
- 已测试超过 10 个模型且失败率大于等于 90%，停止任务，视为疑似地区、IP、DNS、代理或 API Key 权限问题。

### 输出规则

- `probe_state.json` 保存完整状态、环境、配置、原始模型列表、Build 目录、选择摘要、详情页补全摘要和完整结果字段。
- CSV/XLSX 是精简调用决策表，只保留模型 ID、可用性、延迟、上下文、最大输出 token、能力标签和错误原因等字段。
- CSV/XLSX 默认把可用模型排在前面，再按 `latency_total_ms` 从低到高排序。
- Excel 包含 `Summary`、`Available`、`All Models`、`Errors`、`Environment` 工作表。
- `Available` 只包含 `test_status=available` 的模型，并按延迟从低到高排序，同延迟时上下文更大的模型更靠前。
- 如果没有安装 `openpyxl`，只生成 JSON 和 CSV，不生成 Excel。

### 自清理规则

- `--cleanup-prompt auto` 和 `--cleanup-prompt always` 会在任务正常完成后询问“任务已完成。是否保留程序文件？”。
- 正常完成后的提示中，只有输入 `y`/`yes` 或图形窗口选择“是”才保留程序。
- 正常完成后的提示中，直接回车、输入 `n`/`no`、最终确认时 Ctrl+C、关闭图形窗口，都会删除程序本体，但不会删除结果文件。
- 检测过程中按 Ctrl+C 中断时，会先保存当前状态，再询问“检测已被 Ctrl+C 中断。是否删除程序文件？”。此时默认不删除程序，只有输入 `y`/`yes` 或图形窗口选择“是”才删除程序。
- 中断后的删除提示中，直接回车、输入 `n`/`no`、再次 Ctrl+C、关闭图形窗口，都会保留程序本体，方便稍后断点续跑。
- 非交互式终端下：正常完成时默认删除程序本体、保留测试结果；Ctrl+C 中断时默认不删除程序文件。
- `--cleanup-prompt never` 不询问并保留程序。
- 手动运行时会删除 `nvidia_probe`、`scripts`、`pyproject.toml`、`requirements.txt`、`README.md`、`.venv`、`.git`、`build`、`dist`、`__pycache__` 和 `*.egg-info`，但会保护已有结果文件路径。
- 一键脚本默认结果目录在安装目录外；如果需要删除整个安装目录，会通过 `NVIDIA_PROBE_CLEANUP_MARKER` 延迟到 Python 进程退出后由外层 shell 删除。

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

## 常用运行方式

完整规则和参数见上面的“完整规则与参数”。下面只列常用命令。

默认开启“只测试可确认免费模型”。费用审计字段会保留在 `probe_state.json`，CSV/XLSX 只输出精简调用决策字段。

如你确认当前 API 账户只暴露免费模型，可手动允许费用未知模型：

```powershell
nvidia-probe run --allow-unknown-cost
```

如果不想抓取 NVIDIA Build 页面，只依赖 API 模型列表中的 free 元数据：

```powershell
nvidia-probe run --no-build-catalog
```

如果要完全关闭免费过滤，需要显式传入；不建议使用：

```powershell
nvidia-probe run --no-free-only
```

### 快速运行

先做 3 个模型的安全预检。默认已经使用 10 到 25 秒随机间隔、0 重试、首次 429 立即停止：

```powershell
nvidia-probe run --top-free-models 3 --cleanup-prompt never
```

或者不安装入口，直接运行模块：

```powershell
python -m nvidia_probe run --top-free-models 3 --cleanup-prompt never
```

### 完整慢速测试

默认完整测试使用 10 到 25 秒随机间隔，兼顾速度和安全：

```powershell
nvidia-probe run --output-dir results --cleanup-prompt never
```

更保守模式会使用至少 60 到 120 秒随机间隔、0 重试、首次 429 立即停止：

```powershell
nvidia-probe run --strict-safe --output-dir results --cleanup-prompt never
```

### 只拉取模型列表，不真实调用

```powershell
nvidia-probe run --dry-run --output-dir results
```

### 断点续跑

默认会在输出目录保存 `probe_state.json`。中断后可继续：

```powershell
nvidia-probe run --resume --output-dir results
```

### 多地区合并

将多个服务器生成的 `probe_state.json` 或 raw JSON 拷贝到一起，然后执行：

```powershell
nvidia-probe merge --inputs jp_probe_state.json de_probe_state.json us_probe_state.json --output-dir merged
```

## 自清理行为

任务正常结束后默认会询问是否保留程序文件，默认操作是删除程序本体、只保留测试结果。删除程序文件只会卸载工具本体，不会删除刚刚生成的检测结果：

- 正常完成后的提示中，只有输入 `y` / `yes`，或在图形窗口中选择“是”，才会保留程序文件。
- 正常完成后的提示中，直接回车、输入 `n` / `no`、在最终确认提示时按 Ctrl+C、关闭图形窗口，都会删除 `nvidia_probe` 包、`scripts`、`.venv`、`.git`、`pyproject.toml`、`requirements.txt`、`README.md`、构建目录和安装元数据等程序文件；刚刚生成的检测结果文件会继续保留在结果目录。
- 如果检测过程中按 Ctrl+C 中断，工具会保存当前状态并询问“检测已被 Ctrl+C 中断。是否删除程序文件？”。这时默认操作是不删除程序；只有输入 `y` / `yes`，或在图形窗口中选择“是”，才会删除程序本体。
- 中断后的删除提示中，直接回车、输入 `n` / `no`、再次按 Ctrl+C、关闭图形窗口，都会保留程序文件，方便稍后使用 `--resume` 断点续跑。
- 一键运行脚本会把结果默认放在安装目录外的 `nvidia_probe_results`，因此选择卸载后会先写入卸载标记，再由外层脚本在 Python 进程退出后删除 `.nvidia_probe` 整个安装目录。
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
| 默认测试数量 | 混合 TopN 取免费模型前 20 个，候选充足时固定为 14 个稳定热门 + 6 个新晋热门 + 0 个新模型保底；新晋热门严格候选不足时会在新晋热门池内部补足 |
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
