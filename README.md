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
- 输出 CSV、JSON，安装 openpyxl 后输出 Excel。
- 执行完成后弹出或提示是否保留程序；选择不保留时删除程序文件，仅保留结果文件。

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

默认不会测试全部免费模型，而是：

1. 拉取模型列表。
2. 只保留可确认免费的模型。
3. 从模型元数据中尽量提取 `API calls in the last 30 days`。
4. 按 30 天 API 调用量全局排序。
5. 默认只测试前 20 个免费模型。

这样可以显著减少测试请求数量，降低触发 429 或风控限制的风险。

如果 NVIDIA 模型列表接口没有返回任何 30 天调用量字段，工具会把调用量标记为 `unknown`，并回退为检测全部可确认免费的候选模型。

可以自定义测试数量：

```powershell
nvidia-probe run --top-free-models 10 --cleanup-prompt never
```

如果确实要测试更多免费模型：

```powershell
nvidia-probe run --top-free-models 50 --cleanup-prompt never
```

## 免费模型策略

默认开启“只测试可确认免费模型”：

- 如果模型元数据中有 `free`、`is_free`、`free_tier`、`no_cost`、`price: 0` 等明确免费信号，才会真实调用测试。
- 如果模型元数据中出现 `paid`、`billable`、`metered`、正价格等信号，会跳过。
- 如果模型元数据没有费用信息，默认跳过，避免误测可能收费模型。
- 报告会输出 `is_free`、`pricing_model`、`free_reason` 字段，方便审计为什么该模型被测试或跳过。

不建议关闭该策略。如你确认当前 API 账户只暴露免费模型，可手动放宽：

```powershell
nvidia-probe run --allow-unknown-cost
```

如果要完全关闭免费过滤，需要显式传入：

```powershell
nvidia-probe run --no-free-only
```

## 快速运行

先做 3 个模型的安全预检。默认已经使用 30 到 75 秒随机间隔、0 重试、首次 429 立即停止：

```powershell
nvidia-probe run --top-free-models 3 --cleanup-prompt never
```

或者不安装入口，直接运行模块：

```powershell
python -m nvidia_probe run --top-free-models 3 --cleanup-prompt never
```

## 完整慢速测试

默认完整测试已经偏保守：

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

任务结束后默认会询问是否保留程序文件：

- 选择保留：不删除任何程序文件。
- 选择不保留：删除 `nvidia_probe` 包、`pyproject.toml`、`requirements.txt`、`README.md` 等程序文件，只保留结果文件。

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
| 请求间隔 | 30 到 75 秒随机 |
| 超时 | 60 秒 |
| 最大输出 token | 8 |
| 重试 | 0 次 |
| 429 后暂停 | 600 秒，仅在显式允许继续时使用 |
| 连续 429 熔断 | 1 次，默认首次 429 立即停止 |
| 连续 403 熔断 | 5 次 |
| 连续网络错误熔断 | 10 次 |
| 默认测试类型 | chat、embedding、reranker |
| 默认测试数量 | 按 30 天调用量取免费模型前 20 个 |
| 免费模型过滤 | 开启，只测试可确认免费模型 |
| 未知费用模型 | 默认跳过 |

## 输出文件

默认输出目录为 `results`，包含：

- `probe_state.json`：断点和完整原始结果。
- `nvidia_models_report.csv`：表格结果。
- `nvidia_models_report.xlsx`：Excel 报告，如果安装 openpyxl。
- `merge_report.csv`：多地区合并结果。
- `merge_report.xlsx`：多地区合并 Excel，如果安装 openpyxl。

## 注意事项

- 默认只测试可确认免费的模型。
- 每个模型会先测试是否可调用；只有调用成功后，才在报告中填充上下文长度、最大输出 token、能力支持等详细字段。
- 如果模型不可调用，报告只保留基础元数据、筛选依据、错误状态和错误原因，不再填充详细能力字段。
- 如果能获取 `API calls in the last 30 days`，默认按该指标排名测试前 20 个免费模型，可用 `--top-free-models` 调整数量。
- 如果完全无法获取 30 天调用量数据，则回退为检测全部可确认免费的候选模型。
- 如果 NVIDIA 模型列表接口不提供费用元数据，模型会被标记为 `unknown_cost` 并跳过。
- 默认无重试，避免同一模型失败后短时间重复请求。
- 默认首次 429 立即停止，避免继续请求带来 API 风险。
- 如果连续出现 403，脚本会提前熔断，因为这通常代表地区、账号、权限或风控限制。
- 不要使用高并发测试。
- 不要使用超长 prompt 探测上下文长度。
- 不要默认测试图像、视频、音频生成模型。
- 403 可能是地区、账号、模型权限或 IP 风控导致。
- 429 表示限流，默认会立即停止；不建议使用 `--continue-after-429`。
