# mem

`mem` 是一个极简指令的完整内存与活跃度查看 CLI。默认直接输入 `mem`，会先展示健康摘要和诊断优先级，再展示内存分类、GPU/显卡统计、软件活跃度，以及完整进程明细。

报告末尾会给出 3 个下一步引导命令：AI 建议、优化指令、持续观察。

## 设计参考

本工具综合借鉴了几个开源项目的思路：

- `fluidtop` / `asitop`: Apple Silicon 上的硬件采样分层，区分 CPU/GPU/ANE、RAM、swap、power/thermal。
- `Glances` / `btop`: 先给健康摘要，再按热点排序展示进程和系统资源。
- `NVTOP` / `nvitop`: GPU 监控应显式区分整体 GPU 指标和进程级 GPU 指标，能力不足时要降级说明。
- `Entropic` / `ccboard`: 自动发现 AI CLI 生态，把 Codex、Claude、Gemini、OpenCode 等工具作为可接入的本地能力，而不是复制账号密钥。

因此 `mem` 的默认 UI 是：

1. `健康摘要`: 内存、交换区、GPU、内存压力的 OK/WARN/CRIT 状态。
2. `诊断优先级`: 先指出最可能造成卡顿的信号。
3. `内存分类`: 活跃、固定、压缩、缓存/可回收、空闲、其他。
4. `显卡/GPU`: 当前权限下能读取的 GPU 整体信息和统一内存。
5. `软件活跃度`: 按软件聚合进程，标出 HOT/WARN/OK。
6. `进程明细`: 按 RSS 排序的完整进程记录。
7. `下一步引导`: AI 建议、优化指令、持续观察。

如果需要持续盯盘，可以使用 `mem tui` 进入全屏交互式界面。

## 安装

```bash
cd "/Users/laoyao/AI Coding/yao-cli-tools/tools/mem"
pipx install -e .
```

如果在虚拟环境中开发，也可以使用：

```bash
python3 -m pip install -e .
```

## 使用

```bash
mem
```

常用参数：

```bash
mem                  # 完整显示全部进程和软件活跃度
mem guide            # 只显示 3 个下一步引导命令
mem ai               # 调用当前 AI CLI 登录态生成优化建议，优先 Codex
mem optimize         # 生成下一步优化命令清单，不自动执行
mem tui              # 启动全屏交互式 TUI
mem completion zsh   # 输出 zsh 补全脚本
mem top 15           # 只展示内存占用最高的 15 条进程/软件记录
mem no processes     # 隐藏软件活跃度和进程明细
mem json             # 输出 JSON，方便脚本读取
mem watch 2          # 每 2 秒刷新一次
```

AI CLI 选择：

```bash
mem ai cli auto       # 自动检测，优先 codex
mem ai cli codex      # 使用 Codex CLI 当前登录态
mem ai cli none       # 不调用模型，只使用本地规则建议
mem ai timeout 60     # 最多等待 AI CLI 60 秒
```

`mem ai` 不读取或复制账号密钥，只是调用本机已安装的 AI CLI，例如 `codex exec`，由该 CLI 自己复用当前登录态。如果 AI CLI 不可用、未登录或超时，会退回本地规则建议。

## TUI 交互模式

```bash
mem tui
```

TUI 模式会自动刷新当前内存、交换区、GPU、软件活跃度和进程明细。常用按键：

- `Tab` 或 `1`-`4`: 切换软件、进程、GPU、优化指令视图。
- `↑` / `↓` 或 `j` / `k`: 滚动列表。
- `r`: 立即刷新。
- `q`: 退出。

也可以组合限制展示行数：

```bash
mem tui top 30
```

## Shell 补全

zsh 下可以启用 `mem` 的常见指令补全：

```bash
eval "$(mem completion zsh)"
```

建议把上面这一行加入 `~/.zshrc`。启用后：

- 输入 `mem ` 后按 Tab，可以看到 `top`、`watch`、`ai`、`optimize` 等候选。
- 如果当前 zsh 已安装 `zsh-autosuggestions`，输入 `mem `、`mem a`、`mem top` 时会出现灰色候选提示，例如 `mem top 20`。
- 没安装 `zsh-autosuggestions` 时，Tab 补全仍然可用，只是不显示灰色 ghost text。

## 输出说明

macOS 下会优先使用系统自带的 `vm_stat`、`sysctl` 和 `ps`，按以下类别展示：

- `活跃`: 正在被系统和应用使用的活跃页。
- `固定`: wired memory，不能被压缩或换出的内存。
- `压缩占用`: 压缩器实际占用的物理内存。
- `缓存/可回收`: inactive 与 speculative 页，通常可被系统回收。
- `空闲`: 当前未使用的内存。
- `其他`: 系统统计中未落入上述队列的差值。

状态标签：

- `OK`: 当前指标处于可接受范围。
- `WARN`: 指标偏高，需要关注趋势或热点软件。
- `CRIT`: 指标已明显紧张，通常会造成卡顿或响应变慢。
- `HOT`: 软件级别热点，通常由高 RSS 或高 CPU 触发。

## 软件活跃度与进程明细

默认 `mem` 会显示所有可读取进程，并按 RSS 内存占用排序。字段包括：

- `RSS`: 进程实际驻留物理内存。
- `VSZ`: 进程虚拟地址空间。
- `MEM%`: 系统 `ps` 给出的内存占比。
- `CPU%`: 当前采样 CPU 活跃度。
- `状态`: 进程状态，例如 running、sleeping 或 macOS `ps` 状态码。
- `软件`: 优先按 `.app` 包名聚合，例如 Chrome 的多个 helper 会归入 `Google Chrome`。

`软件活跃度` 会把同一软件下的进程聚合，展示总 RSS、总 VSZ、CPU 合计、进程数和活跃进程数。

## GPU/显卡

macOS 下会读取 `system_profiler SPDisplaysDataType` 和 `ioreg`，展示：

- GPU 型号、核心数、Vendor、Metal 支持。
- 显示器记录。
- Apple Silicon 可读到的整体 GPU 利用率、Renderer/Tiler 利用率、统一内存分配与正在使用量。
- 最近一次 GPU 提交 PID，如果系统暴露该字段。

macOS 普通权限通常不能稳定读取“每个进程的 GPU/显存占用”。这类进程级 GPU 采样一般需要 `sudo powermetrics`，所以 `mem` 会展示当前权限下能拿到的完整 GPU 记录，并在输出里标注限制。

## 优化指令

`mem optimize` 会生成下一步可执行命令清单，例如：

- `mem ai top 30`: 让 AI 读取当前快照并排序建议。
- `sudo powermetrics --show-process-gpu -n 1 -i 1000`: 进一步采样进程级 GPU 活跃度。
- `osascript -e "tell application \"Google Chrome\" to quit"`: 针对明确来自 `.app` 应用包的高内存软件生成退出命令。

这些命令只展示，不会自动执行。退出应用前应先确认未保存内容。

Linux 下会读取 `/proc/meminfo`，以 `已用`、`可回收/缓存`、`空闲` 为主分类。
