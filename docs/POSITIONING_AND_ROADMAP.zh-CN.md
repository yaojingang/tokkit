# TokLedger 定位与路线图

## 一句话定位

TokLedger 是一个面向 AI 编码工具的本地优先使用量台账。它能够在不要求
SDK 埋点的前提下，把桌面助手、IDE 扩展和本地代理里的 token、成本、
模型、终端和客户端统一记到账本里。

## 产品判断

大多数 LLM observability 产品是为“正在构建 AI 应用的团队”设计的。
TokLedger 更适合“在一台电脑上同时使用多种 AI 编码工具的个人或小团队”。
它首先解决的是本地 AI 使用量的记账问题，而不是通用的 LLMOps 平台问题。

## TokLedger 是什么

- 一个记录 AI 编码工具使用量的本地 SQLite 台账
- 一个把 `exact`、`partial`、`estimated` 来源统一归一的标准层
- 一个面向终端的日报、多日报和趋势查看工作流
- 一个结合日志扫描和本地代理的低接入成本采集层

## TokLedger 不是什么

- 不是通用的云端 LLM observability 平台
- 不是 prompt playground 或 eval 平台
- 不是要求所有应用都先埋点接入的团队控制台
- 不是供应商账单替代品，也不是把所有数字都假装成精确的面板

## 需要持续强化的核心优势

### 1. 默认本地优先

- 数据默认只保留在本机，除非用户主动导出
- 趋势、日报、成本估算在离线时也能工作
- 对隐私敏感的场景，后续可以只保留 usage 元数据而不落具体内容

### 2. 面向桌面 AI 工具和 AI coding assistants

- 优先服务 Codex、Kaku、Warp、Claude Code、Cursor、VS Code 助手、
  Trae、Windsurf 这类工作流
- 在数据模型里把 `app`、`client`、`terminal`、`workspace`、
  `session` 做成一等维度
- 把“今天我在不同 AI 编码工具上的使用画像”做成主体验，而不是附属能力

### 3. 不依赖埋点，接入成本低

- 优先使用已有本地日志做 `log-based adapters`
- 必须拿精确 usage 时，再使用 `proxy-based adapters`
- 尽量避免让用户改造现有工具链或重搭一套架构

### 4. 先把统一记账做深

- 统一 `tokens`、`cost`、`model`、`provider`、`terminal`、
  `client`、`workspace`、`session`、`measurement_method`
- 全产品统一坚持 `exact`、`partial`、`estimated` 三种口径
- 在扩展更大功能前，先把去重、归因、定价和可解释性做好

### 5. 个人用户装完就能用

- `tok today` 必须在第一天就有价值
- 自动扫描、自动日报、shell 补全、趋势图都要尽量零配置
- 产品体验更像一个开发者工具，而不是一套要学习的 SaaS 平台

## 战略切口

TokLedger 应该围绕“AI 编码工具的本地记账层”竞争，而不是去做“通用
LLMOps 平台”。这个切口有护城河，因为更大的 observability 产品通常默认：

- 需要代码级埋点
- 你拥有并控制应用本身
- 流量已经集中在统一链路上
- 目标用户是团队协作和平台治理

而 TokLedger 的前提是：

- 一台电脑上跑着很多客户端
- 本地日志分散
- 数据精度天然不一致
- 用户主要工作在终端和桌面工具里

## 与主流项目的差异化

面对 Langfuse、Phoenix、Helicone、Agenta、OpenLIT 这类项目，
TokLedger 应该强调：

- 本地优先存储和报表
- 面向桌面助手和 AI 编码终端
- 对混合精度数据足够诚实
- 零埋点或低埋点接入
- 面向个人用户的 CLI 工作流

## 产品支柱

### 支柱 A：覆盖面

- 持续扩展更多 AI 编码客户端适配器
- 发布支持矩阵，并明确标出 `exact / partial / estimated`
- 对不支持或部分支持的工具给出明确诊断

### 支柱 B：记账质量

- 提升模型识别、来源归因和 workspace 归因
- 避免日志和代理同时观测时的重复记账
- 持续维护定价表、覆盖机制和可解释的成本估算

### 支柱 C：操作流体验

- 让 `tok` 足够快、足够清楚、足够容易形成习惯
- 让报表直接适合在终端和 Kaku 里消费
- 增加诊断、安装向导和轻量提醒能力

## 近期路线图

### P0：把切口打深

- `tok doctor`：告诉用户哪些适配器已工作、哪些是 partial、哪些没识别到
- `tok setup`：做本地代理和常见适配器的引导式配置
- 支持矩阵文档：按客户端列出 `exact / partial / estimated`
- 更好的 workspace 和 repo 归因
- 扩展更多 AI 编码工具适配器，尤其是 Claude Code、Cursor、
  Windsurf、ChatGPT Desktop

### P1：让记账真正可运营

- 日/周/月预算
- 按模型、按客户端、按终端的预算和告警
- 异常成本、上下文膨胀、超预算提醒
- 更好的导出能力：CSV、JSON、Markdown、定时摘要
- 更强的去重与归因逻辑

### P2：谨慎扩展产品面

- Menu Bar 或 Raycast 集成
- 更细的 session drill-down 和问题回放视图
- 在保持本地优先前提下支持多机器同步
- 只有在单机账本足够强之后，再考虑团队模式

## 产品边界

不要过早把资源投入到这些方向：

- prompt playground
- eval framework
- 托管仪表盘作为主产品
- 在 AI 编码工具覆盖还不强时，优先做通用 LLM 应用埋点平台

这些都可以是相邻能力，但不应该主导路线图。

## 对外表达建议

### 首页适合强调的话

- AI 编码工具的本地优先使用量台账
- 把 token、成本、模型、终端和客户端统一到一个本地账本里
- 对基于日志的数据来源，不要求 SDK 埋点

### 对比竞品时适合强调的话

- 更适合 AI 编码工具用户，而不是只服务 AI 应用团队
- 对 `partial` 和 `estimated` 更诚实，不会把所有数字伪装成同等精确
- 比云端优先的 observability 产品更适合本地桌面工作流

## 成功标准

如果用户能够做到下面这些，就说明 TokLedger 走在正确方向上：

- 很快装好
- 第一天就能看到有价值的数据
- 明白哪些数字是精确、部分可得、还是估算
- 看清自己的 token 和成本主要花在什么模型、终端、客户端上
- 把它变成每天都会查看的操作习惯，而不是一次性的仪表盘
