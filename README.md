# 扫地机器人 Agent 项目

这是一个基于 Streamlit、LangChain、Chroma 和 DashScope 的中文智能客服项目，面向扫地机器人与扫拖一体机场景，支持知识库问答、故障排查、维护建议、天气辅助判断和用户使用报告生成。

项目当前已经从简单 Demo 演进到”可持续维护”的版本，重点补了多轮对话、真实工具接入、知识库增量同步、来源展示、前端运维能力和情绪识别规则引擎。

## 主要能力

- 支持多轮对话，历史消息会一起传入 Agent，而不是只看当前一句。
- **会话记忆压缩**：自动识别冗余信息并过滤，定期生成对话摘要，保留关键事实，避免长对话 token 超限。
- 基于本地知识库进行 RAG 检索与总结。
- 支持报告场景的动态提示词切换。
- 支持读取外部用户记录，生成个人使用报告。
- 支持查询真实天气，辅助给出使用建议。
- 支持展示知识库引用来源，并可展开查看命中的本地知识片段。
- 支持在页面中直接清空会话、重建知识库。
- 支持知识库文本清洗、FAQ 问答切分、结构化切块和增量同步。
- 检测到 Chroma 索引异常时可自动重建。
- 启动前会进行运行环境自检，缺少关键配置时直接阻止应用启动。
- **情绪识别规则引擎**：RAG 检索前对用户 query 进行情绪分析，命中高危规则（投诉、法律、安全事故等）直接转人工介入；低风险情绪标签注入 RAG 提示词，引导 LLM 调整回答语气。
- **Trace 追踪与置信度评估**：记录每次对话的完整链路（情绪分析、工具调用、RAG 检索分数、LLM 耗时），计算综合置信度，低置信度时主动追问用户以获取更多信息。
- **加入订单客服mcp server**：包含订单查询、物流查询、退款规则检查等工具，并将订单状态、退款规则文档作为 Resources 提供给 Agent，避免把所有业务数据塞进 Prompt，提升工具调用稳定性和可维护性。
## 会话记忆压缩机制

为解决长对话 token 超限问题，项目实现了会话记忆压缩机制。

### 工作流程

```
用户输入
    │
    ▼
┌──────────────────────────────────────┐
│  SessionMemoryManager               │
│                                      │
│  1. 冗余过滤                         │
│     - 移除填充词（"你好"、"好的"等）   │
│     - 移除精确重复消息                │
│     - 合并近似重复消息（Jaccard>0.7） │
│                                      │
│  2. Token窗口检查                    │
│     - 估算消息token数量              │
│     - 超过阈值(16000)触发压缩        │
│     - 消息数超过20条触发压缩          │
│                                      │
│  3. 摘要生成                         │
│     - 保留最近10条消息（5轮对话）      │
│     - 旧消息压缩为摘要                │
│     - LLM生成简洁摘要                 │
│                                      │
│  4. 事实提取                         │
│     - 城市/位置                       │
│     - 用户ID                          │
│     - 产品类型                        │
│     - 主要关注点                      │
│                                      │
│  5. 注入系统提示词                   │
│     - 历史对话摘要                    │
│     - 已知会话事实                    │
└──────────────────────────────────────┘
```

### 配置参数（config/memory.yaml）

| 参数 | 默认值 | 说明 |
|------|--------|------|
| token_threshold | 16000 | Token阈值，超过触发压缩 |
| message_threshold | 20 | 消息数阈值，超过触发压缩 |
| keep_recent_count | 10 | 保留最近N条消息不压缩 |
| max_summary_length | 2000 | 最大摘要长度（字符） |
| min_messages_before_compress | 10 | 首次压缩前最小消息数 |
| enable_redundancy_filter | true | 是否启用冗余过滤 |
| redundancy_jaccard_threshold | 0.7 | 近似重复检测阈值 |

### 相关文件

- `utils/memory_manager.py` — 记忆管理器核心，负责压缩、摘要生成、事实提取
- `utils/message_filter.py` — 冗余信息过滤模块（去重、填充词移除）
- `config/memory.yaml` — 记忆配置参数
- `prompts/memory_summary.txt` — 摘要生成提示词模板

## 情绪识别规则引擎

在 RAG 检索前，系统会对用户 query 做一层情绪分析，用于识别高风险场景和引导回答语气。

### 工作流程

```
用户 query
    │
    ▼
┌──────────────────────────────────────┐
│  SentimentEngine.analyze()           │
│                                      │
│  1. need_human_rules 优先匹配        │── 命中 ──→ 直接返回人工介入文案
│     (投诉/法律/安全事故/辱骂/媒体)    │              (不走 RAG)
│                                      │
│  2. scoring_rules 累加分数           │
│     (愤怒/焦虑/失望/讽刺/满意…)      │
│                                      │
│  3. 按分数区间判定等级               │
│     ≥80   need_human                 │
│     60~79  强烈负面 → soft_answer    │
│     30~59  一般负面 → soft_answer    │
│     10~29  轻微负面 → normal         │
│     -10~10 中性    → normal          │
│     < -10  积极    → normal          │
│                                      │
│  4. 情绪标签注入 RAG 提示词          │── LLM 据此调整回答语气
└──────────────────────────────────────┘
```

### 人工介入规则（命中即转人工，不走 RAG）

| 规则名称 | 匹配示例           |
|----------|----------------|
| 投诉举报 | 投诉、举报、315、消协、工商局 |
| 法律维权 | 律师、法院、起诉、赔偿、打官司 |
| 安全事故 | 着火、爆炸、漏电、触电、冒烟、伤人 |
| 人身攻击 | 垃圾产品、骗钱、黑心、无良商家 |
| 媒体曝光 | 媒体、记者、曝光、电视台、微博曝光 |
| 强烈辱骂 | shit ……        |

### 情绪计分规则

| 规则名称 | 分数 | 匹配示例 |
|----------|------|----------|
| 强烈不满 | +35 | 太差了、气死了、忍无可忍 |
| 抱怨售后 | +30 | 售后差、客服没人、推诿 |
| 抱怨质量 | +25 | 质量差、用了就坏、品控差 |
| 反复故障 | +25 | 又坏了、老是坏、修了又坏 |
| 讽刺/阴阳怪气 | +20 | 呵呵、真厉害啊 |
| 担心安全 | +20 | 害怕、担心、会不会爆炸 |
| 催促/不耐烦 | +15 | 快点、赶紧、怎么还没 |
| 焦虑急切 | +15 | 急死、着急、十万火急 |
| 失望无奈 | +15 | 算了、认倒霉、没办法 |
| 轻微不满 | +10 | 不太满意、一般般、有点差 |
| 正面满意 | -10 | 谢谢、不错、好用、满意 |
| 中性咨询 | -5 | 请问、咨询一下、想知道 |

### 相关文件

- `config/sentiment_rules.yaml` — 规则配置（关键词、正则、分数、阈值、回复模板），**可独立修改，无需改代码**
- `utils/sentiment_engine.py` — 规则引擎核心，支持 `engine.reload()` 热重载
- `rag/rag_service.py` — 在 `rag_summarize()` 入口调用情绪识别
- `app.py` — 前端识别人工介入消息，渲染特殊样式（金色边框 + 🔴 已转人工介入）

## Trace 追踪与置信度评估

为解决回答质量不可控、无法离线分析的问题，项目实现了结构化 Trace 追踪和置信度评估机制。

### 工作流程

```
用户输入
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│  ReactAgent.execute_stream()                                │
│                                                             │
│  1. start_trace() 创建 TraceRecord                          │
│                                                             │
│  2. 中间件层记录                                            │
│     - monitor_tool: 工具调用耗时/成功率                      │
│     - rag_service: 情绪分数、RAG检索分数                     │
│     - record_llm_latency: LLM调用耗时                       │
│                                                             │
│  3. end_trace() 获取完整 Trace                              │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│  置信度计算 (ConfidenceEngine)                               │
│                                                             │
│  情绪置信度:                                                 │
│    - need_human=True => 0.5                                 │
│    - 中性分数[-10,10] => 0.9                                │
│    - 负面情绪 => max(0.1, 0.8 - score/100)                 │
│    - 正面情绪 => 0.85                                       │
│                                                             │
│  RAG置信度:                                                  │
│    - base = top_rerank * 0.6 + avg_rerank * 0.4             │
│    - 候选<3 => base *= 0.7                                  │
│    - 最高分<0.25 => base *= 0.5                             │
│                                                             │
│  综合置信度 = 情绪 * 0.3 + RAG * 0.7                        │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│  追问决策                                                    │
│                                                             │
│  综合置信度 < 0.45 => 触发追问                               │
│                                                             │
│  追问策略:                                                   │
│    - RAG相关性低: "能否具体描述遇到的问题？"                  │
│    - RAG覆盖度低: "能否提供更多细节？"                       │
│    - 情绪负面: "理解您的心情，能否详细说明？"                 │
│                                                             │
│  前端渲染追问卡片，用户选择:                                 │
│    - "回答这个问题" => 追问内容作为新输入重新执行              │
│    - "跳过" => 使用当前回答                                  │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│  Trace 持久化                                                │
│                                                             │
│  存储路径: storage/traces/YYYY-MM-DD.jsonl                   │
│  格式: 每行一个 JSON 对象                                    │
│  支持按 session_id 或日期查询                                │
└─────────────────────────────────────────────────────────────┘
```

### 配置参数（config/confidence.yaml）

| 参数 | 默认值 | 说明 |
|------|--------|------|
| follow_up_threshold | 0.45 | 综合置信度低于此值触发追问 |
| weights.sentiment | 0.3 | 情绪置信度权重 |
| weights.rag | 0.7 | RAG置信度权重 |
| rag.low_relevance_threshold | 0.25 | RAG低相关性阈值 |
| max_follow_up_rounds | 1 | 最大追问次数 |
| enabled | true | 是否启用追问功能 |



### 相关文件

- `config/confidence.yaml` — 置信度配置（阈值、权重、追问参数）
- `utils/trace_context.py` — Trace 数据结构和 contextvars 上下文管理
- `utils/trace_store.py` — Trace 持久化存储（JSONL 格式）
- `utils/confidence.py` — 置信度计算引擎
- `utils/follow_up.py` — 低置信度追问生成器
- `rag/rag_service.py` — 埋点记录情绪和 RAG 分数
- `agent/tools/middleware.py` — 埋点记录工具调用耗时
- `agent/react_agent.py` — 启动 Trace 生命周期
- `app.py` — 置信度检查、追问卡片渲染、Trace 持久化

## 当前项目结构

- `app.py`
  Streamlit 前端入口，负责聊天界面、引用展示、会话管理、知识库运维按钮和人工介入消息特殊渲染。

- `agent/react_agent.py`
  Agent 构建入口，封装模型、提示词、中间件和工具注册。

- `agent/tools/agent_tools.py`
  业务工具定义，包括：
  - 知识库检索总结（支持 query_type 枚举）
  - 实时天气查询
  - 用户 ID / 城市读取
  - 用户画像、可用月份、最近一期记录、指定月份报告读取
  - 时间范围查询（支持 TimeRange 枚举和自定义区间）
  - 所有工具返回统一 ToolResult 结构

- `agent/tools/tool_schema.py`
  工具公共数据模型：
  - ToolStatus 枚举（success / not_found / degraded / error / no_data）
  - QueryType 枚举（fault / maintenance / purchase / usage / general）
  - DataCategory 枚举（feature / efficiency / consumable / comparison / all）
  - TimeRange 枚举（latest / last_3 / last_6 / all）
  - ToolResult dataclass（status / message / evidence / next_step）

- `agent/tools/middleware.py`
  中间件逻辑，包括工具监控、模型调用前日志、报告场景的动态提示词切换和会话摘要注入。

- `rag/vector_store.py`
  知识库入库和向量库管理，负责：
  - 文档加载
  - 文本清洗
  - FAQ 问答拆分
  - 切块
  - 向量化
  - manifest 增量同步
  - 陈旧切片清理
  - 向量库重建

- `rag/rag_service.py`
  RAG 检索和总结服务，负责：
  - **情绪识别拦截**：RAG 检索前先做情绪分析，命中高危规则直接转人工，情绪标签注入提示词引导 LLM 语气
  - 查询改写
  - 扩召回
  - 轻量重排
  - 参考来源整理
  - 检索异常恢复

- `utils/sentiment_engine.py`
  情绪识别规则引擎，YAML 驱动，支持关键词 + 正则匹配、累加评分、等级判定、need_human 人工介入、热重载。

- `utils/memory_manager.py`
  会话记忆管理器，负责：
  - Token窗口管理和压缩决策
  - 冗余信息过滤（去重、填充词移除）
  - LLM摘要生成
  - 事实提取（城市、用户ID、产品类型、关注点）

- `utils/message_filter.py`
  冗余信息过滤模块，支持：
  - 填充词/确认词识别和移除
  - 精确重复检测
  - 近似重复检测（Jaccard相似度）
  - 保留对话流程

- `utils/trace_context.py`
  Trace 数据结构和 contextvars 上下文管理，支持：
  - TraceRecord、SentimentTrace、RAGTrace、ToolCallTrace 数据结构
  - 使用 contextvars 实现请求级别的 Trace 数据传递
  - 便捷写入函数：record_sentiment、record_rag、record_tool_call、record_llm_latency

- `utils/trace_store.py`
  Trace 持久化存储，支持：
  - 按日期存储为 JSONL 文件（storage/traces/YYYY-MM-DD.jsonl）
  - 按 session_id 查询历史 Trace
  - 按日期查询所有 Trace

- `utils/confidence.py`
  置信度计算引擎，支持：
  - 情绪置信度计算（基于规则命中数和分数区间）
  - RAG 置信度计算（基于检索分数和候选数量）
  - 综合置信度计算（加权平均）

- `utils/follow_up.py`
  低置信度追问生成器，支持：
  - 根据置信度最弱维度生成追问内容
  - 多种追问模板（RAG相关性低、覆盖度低、情绪负面等）
  - 追问次数限制

- `config/`
  项目配置目录：
  - `rag.yaml`：模型配置
  - `chroma.yaml`：向量库和切块配置
  - `prompt.yaml`：提示词路径配置
  - `agent.yaml`：外部用户数据配置
  - `sentiment_rules.yaml`：情绪识别规则配置（关键词、正则、分数、等级区间、人工介入回复模板）
  - `memory.yaml`：会话记忆配置（Token阈值、消息阈值、保留数量、冗余过滤参数）
  - `confidence.yaml`：置信度配置（阈值、权重、追问参数）

- `prompts/`
  提示词目录：
  - `main_prompt.txt`
  - `rag_summarize.txt`
  - `report_prompt.txt`
  - `memory_summary.txt`：会话摘要生成提示词

- `data/`
  本地知识库目录，支持递归扫描子目录。

- `data/external/records.csv`
  用户使用记录数据源，用于报告类场景。

- `storage/`
  向量库存储目录。

- `storage/knowledge_manifest.json`
  知识库 manifest 文件，记录每个来源文件的 md5、切片数和更新时间。

- `logs/`
  运行日志目录。

## 知识库机制

当前知识库不是简单“把 txt 扔进去就结束”，而是有一套基本可维护的入库流程。

### 入库流程

1. 递归扫描 `data/` 目录下的可用文件。
2. 根据文件类型读取内容。
3. 对文本做清洗，统一换行和空白。
4. 对 FAQ / `100问` 类文档优先按“问题-答案”结构切分。
5. 按 `txt/pdf` 使用不同的切块参数。
6. 为每个 chunk 生成稳定 ID：
   `source + chunk_index + content_hash`
7. 写入 Chroma 向量库。
8. 同步更新 `storage/knowledge_manifest.json`。

### 增量同步逻辑

- 文件未变化：跳过入库。
- 文件已更新：删除旧切片，重新切块并写入。
- 文件已删除：清理向量库中残留的旧切片。
- 首次运行或 manifest 缺失：自动按当前文件状态重建同步信息。

### 检索增强逻辑

当前 RAG 已做的增强包括：

- 查询规范化
- 常见口语问法扩展
- 扩召回
- 轻量重排
- 引用来源整理

适合的问题类型包括：

- 选购建议
- 故障排查
- 使用技巧
- 维护保养
- 场景适配

## 已接入工具

所有工具返回统一的 `ToolResult` 结构（`agent/tools/tool_schema.py`）：

| 字段 | 类型 | 说明 |
|------|------|------|
| `status` | ToolStatus 枚举 | `success` / `not_found` / `degraded` / `error` / `no_data` |
| `message` | str | 给 LLM 消费的自然语言结果 |
| `evidence` | dict | 结构化数据（供 Trace 和调试） |
| `next_step` | str | 建议的下一步操作 |

### 1. 知识库工具

- `rag_summarize(query, query_type="general")`
  从本地知识库检索资料并总结返回。
  - `query_type` 枚举：`fault`(故障排查)、`maintenance`(维护保养)、`purchase`(选购建议)、`usage`(使用技巧)、`general`(通用咨询)

### 2. 天气工具

- `get_weather(city)`
  基于 Open-Meteo 查询实时天气，不需要额外 API Key。

### 3. 会话/用户信息工具

- `get_user_location()`
  读取当前会话绑定城市。

- `get_user_id()`
  读取当前会话绑定用户 ID。

默认不会随机编造城市或用户 ID。

### 4. 报告相关工具

- `get_current_month()`
  获取当前月份。

- `list_report_months(user_id)`
  获取某个用户有哪些可查询月份。

- `fetch_latest_external_data(user_id, data_category="all")`
  获取某个用户最近一期记录。
  - `data_category` 枚举：`feature`(特征)、`efficiency`(效率)、`consumable`(耗材)、`comparison`(对比)、`all`(全部)

- `get_user_profile(user_id)`
  获取某个用户的基础画像和最近记录摘要。

- `fetch_external_data(user_id, month)`
  严格查询指定月份记录（格式 `YYYY-MM`），不存在返回 `not_found`（不做降级）。

- `fetch_external_data_range(user_id, time_range="latest", start_month="", end_month="", data_category="all", max_months=6)`
  按时间范围查询用户使用记录。
  - `time_range` 枚举：`latest`(最近一期)、`last_3`(最近3个月)、`last_6`(最近6个月)、`all`(全部)
  - `start_month` / `end_month`：自定义区间（`YYYY-MM`），指定后 `time_range` 被忽略
  - `max_months`：最大返回月数，硬上限 12

- `fill_context_for_report()`
  为报告生成场景注入上下文标记。

## 前端交互能力

当前页面支持以下能力：

- 聊天输入
- 快捷问题按钮
- 历史消息展示
- 结构化引用来源展示
- 来源片段预览
- 清空会话
- 重建知识库
- **人工介入提示**：情绪识别命中高危规则时，前端以金色边框特殊样式展示转人工提示，并标注触发的规则名称

## 运行环境要求

### Python 与环境

- Python `3.10+`
- 推荐使用 Conda
- 当前约定环境名：`agent310`

### 编码要求

- 源码文件统一使用 `UTF-8`
- 提示词文件统一使用 `UTF-8`
- 知识库文本文件建议统一使用 `UTF-8`

### 必需环境变量

- `DASHSCOPE_API_KEY`
  DashScope 模型调用所需。

### 可选环境变量

- `AGENT_USER_CITY`
  为当前会话绑定城市，供 `get_user_location()` 使用。

- `AGENT_USER_ID`
  为当前会话绑定用户 ID，供报告场景使用。

## 依赖说明

项目依赖以 [requirements.txt](/D:/pycharmprojects/agent/requirements.txt) 为准，当前主要分为几类：

- LLM 与 Agent 相关依赖
- 向量库与检索相关依赖
- 文档解析依赖
- Web 应用与配置依赖
- DashScope 模型服务依赖

项目也使用了部分 Python 标准库，不需要写入 `requirements.txt`，例如：

- `json`
- `csv`
- `hashlib`
- `datetime`
- `urllib`
- `threading`
- `re`

## 安装方式

### 1. 创建 Conda 环境

```powershell
conda create -n agent310 python=3.10 -y
```

### 2. 激活环境

```powershell
conda activate agent310
```

### 3. 安装依赖

```powershell
pip install -r requirements.txt
```

### 4. 配置环境变量

```powershell
$env:DASHSCOPE_API_KEY="your_api_key_here"
```

可选：

```powershell
$env:AGENT_USER_CITY="上海"
$env:AGENT_USER_ID="1001"
```

## 启动方式

### 启动应用

```powershell
streamlit run app.py
```

### 可选：预构建知识库

```powershell
python -m rag.vector_store
```

## 启动前自检项

应用启动时会自动检查以下内容：

- `DASHSCOPE_API_KEY` 是否存在
- prompt 文件是否存在
- prompt 文件是否为 UTF-8
- 知识库目录是否存在
- 外部数据文件是否存在
- 情绪规则文件 `config/sentiment_rules.yaml` 是否存在（缺失时情绪识别降级为中性，不阻断启动）
- 关键配置项是否缺失

如果这些检查不通过，应用会直接停止启动。

## 知识来源展示

当回答命中知识库内容时，前端会：

1. 在回答下方显示 `参考来源`
2. 以标签形式展示命中的来源文件
3. 支持展开查看本地知识片段预览

目前支持的预览类型：

- `txt`
- `pdf`

## 常见操作

### 清空会话

在页面顶部点击 `清空会话` 按钮即可。

### 重建知识库

在页面顶部点击 `重建知识库` 按钮即可。

该操作会：

- 清空当前向量库
- 重新扫描 `data/`
- 重新切块并入库
- 重建 manifest

## 当前限制

- 天气工具依赖网络；网络不可用时会返回失败信息。
- `get_user_location` 和 `get_user_id` 目前仍主要依赖环境变量绑定，不是完整的用户体系。
- 当前知识库仍以本地静态文件为主，缺少在线知识管理后台。
- FAQ 切分目前基于规则，复杂格式文档仍可能拆分不理想。
- 来源预览目前只展示局部片段，不支持高亮命中词。
- 情绪识别基于规则引擎（关键词 + 正则），无法理解复杂语境和隐晦表达，存在误判可能。
- need_human 人工介入目前仅返回固定提示文案，未真正对接人工客服系统。
- 会话记忆压缩基于启发式方法，摘要质量依赖 LLM 能力，极端情况下可能丢失细节。

## 建议的后续工作

- 增加知识库管理面板，展示：
  - 当前文档总数
  - 当前 chunk 数
  - manifest 状态
  - 最后更新时间

- 补充自动化测试：
  - 工具层测试
  - RAG 检索测试
  - 入库同步测试
  - 报告流程测试

- 引入更强的知识来源：
  - 产品说明书
  - 故障码手册
  - 客服工单 FAQ
  - 机型差异表
  - 维修经验库

- 增强知识检索：
  - 更细粒度的 query rewrite
  - rerank 模型
  - 更强的 FAQ 结构化切分
  - 引用片段高亮

- 优化会话记忆机制：
  - 基于实际使用调优压缩阈值
  - 增加更多事实类型提取（如设备型号、固件版本）
  - 支持跨会话记忆共享

## 备注

如果后续继续扩展知识库，建议优先补这三类内容：

- 机型级知识
- 故障排查知识
- 真实客服案例知识

比单纯继续堆更多纯文本，更能提升实际回答质量。
