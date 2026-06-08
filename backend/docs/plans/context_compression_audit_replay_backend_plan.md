# backend/docs/plans/context_compression_audit_replay_backend_plan.md

## 1. 项目背景与目标

### 1.1 背景

当前 Luna 后端已经具备与长对话治理直接相关的多项基础能力，但这些能力分散在聊天主链路、短期记忆压缩链路、长期记忆写入链路以及遥测链路中，尚未形成围绕“超长聊天冗余裁剪 + Token 压缩率审计 + 压缩过程回放”的统一闭环。

当前可直接复用的真实代码基础包括：

- 聊天主入口 [`chat_request()`](backend/ai-service/app/api/http_api.py)，负责上下文加载、输入重构、长期记忆检索、外部知识检索、用户画像注入与最终 Chat Prompt 组装。
- 上下文窗口截断入口 [`truncate_context()`](backend/ai-service/app/llm/context_manager.py)，已实现基于 Token 上限的历史消息滑动窗口裁剪。
- 短期摘要压缩入口 [`_trigger_compression()`](backend/ai-service/app/api/http_api.py)，已实现 Redis 历史超阈值后的短摘要压缩与裁剪。
- 长期历史压缩入口 [`Manager._compress_and_commit()`](backend/ai-service/app/memory/manager.py)，已实现历史会话压缩为长期记忆并写入 PostgreSQL 与 Qdrant。
- 摘要模型调用入口 [`short_summarize()`](backend/ai-service/app/api/internal_service.py) 与 [`long_summarize()`](backend/ai-service/app/api/internal_service.py)，已提供小模型摘要压缩调用能力。
- Token 计数基础 [`count_tokens()`](backend/ai-service/app/llm/context_manager.py) 与 [`count_messages_tokens()`](backend/ai-service/app/llm/context_manager.py)。
- 遥测能力入口 [`record_audit_log_async()`](backend/ai-service/app/telemetry/worker.py) 与 [`record_span_async()`](backend/ai-service/app/telemetry/worker.py)。
- 结构化检索思维事件基础 [`RAG_EVENT_THOUGHT`](backend/ai-service/app/types/constants.py) 与 [`RagEventPublisher.publish_thought()`](backend/ai-service/app/rag/retrieval.py)。

当前缺口主要体现在三方面：

1. 超长聊天治理仍以“消息级截断 + Redis 阈值压缩”为主，没有形成面向 `memory` 槽位的分阶段压缩治理策略。
2. 压缩前后 Token 变化没有统一审计口径，无法量化压缩收益与定位压缩质量问题。
3. 压缩过程虽然存在零散日志，但无法按结构化事件序列回放，更无法在前端以时间线形式查看。

### 1.2 本方案目标

本方案只聚焦以下三项能力，并要求三项能力共用同一套设计语言、同一套审计口径、同一套回放链路：

1. 超长聊天冗余裁剪
2. Token 压缩率审计
3. 压缩过程可回放、可审计

### 1.3 本方案不覆盖的范围

以下内容不在本轮后端实施范围内，只要求本方案保持兼容：

- LangGraph DAG 编排正式落地
- 全量任务状态机改造
- 通用 Multi-Agent 子图拆分
- 完整 Prompt 原文全文存档
- 实时压缩进度 SSE 广播

本方案遵循“先把现有 Python 主链路上的压缩治理闭环补齐，再为后续 DAG 化保留稳定扩展点”的原则。

---

## 2. 现状分析

### 2.1 已有基础能力

#### 2.1.1 会话消息级裁剪基础已存在

[`truncate_context()`](backend/ai-service/app/llm/context_manager.py) 已实现以下能力：

- 使用 `max_context_tokens - reserved_output` 计算可用输入 Token 空间。
- 始终保留 `system_prompt`。
- 从最旧历史消息开始裁剪，至少保留最近若干轮对话。
- 作为 [`format_messages_for_api()`](backend/ai-service/app/llm/context_manager.py) 的底层核心逻辑复用。

结论：消息级裁剪已有稳定实现，本轮不需要重写，只需补充统计、审计与衔接逻辑。

#### 2.1.2 短期摘要压缩与 Redis 裁剪基础已存在

[`_trigger_compression()`](backend/ai-service/app/api/http_api.py) 已实现：

- 读取 Redis 中的 [`ChatSummary`](backend/ai-service/app/repository/chat_history_redis.py) 与历史 [`Interaction`](backend/ai-service/app/repository/chat_history_redis.py)。
- 组装 [`PromptCategory.SHORT_SUMMARY`](backend/ai-service/app/prompt/types.py) 压缩提示词。
- 调用 [`short_summarize()`](backend/ai-service/app/api/internal_service.py)。
- 调用 [`update_summary_and_trim()`](backend/ai-service/app/repository/chat_history_redis.py) 完成摘要更新和历史裁剪。

结论：摘要压缩级裁剪已有主链路，可直接扩展为“带审计的压缩动作”。

#### 2.1.3 历史会话长期压缩基础已存在

[`Manager._compress_and_commit()`](backend/ai-service/app/memory/manager.py) 已实现：

- 从 Redis 读取完整上下文。
- 组装 [`PromptCategory.LONG_SUMMARY`](backend/ai-service/app/prompt/types.py) 提示词。
- 调用 [`long_summarize()`](backend/ai-service/app/api/internal_service.py)。
- 写入 PostgreSQL 长期记忆与 Qdrant 向量库。

结论：历史会话终局压缩已经稳定，但缺少压缩率审计与回放快照。

#### 2.1.4 模型压缩调用能力已存在

[`CompressionLLMClient`](backend/ai-service/app/llm/client.py) 已提供：

- 单次压缩调用入口
- 限流与连接异常重试入口
- 动态模型配置读取逻辑

结论：本方案不需要新增新的模型客户端，只需要在上层新增压缩治理编排逻辑。

#### 2.1.5 遥测基础设施已存在

[`AuditLog`](backend/ai-service/app/telemetry/worker.py) 与 [`TraceSpan`](backend/ai-service/app/telemetry/worker.py) 已提供：

- 异步审计日志落盘
- 异步 Span 落盘
- 审计日志查询接口 [`get_audit_logs()`](backend/ai-service/app/api/routers/telemetry.py)
- Span 查询接口 [`get_traces()`](backend/ai-service/app/api/routers/telemetry.py)

结论：本轮应优先复用既有遥测能力，而不是独立新建一套完全平行的审计基础设施。

### 2.2 当前缺口

#### 2.2.1 缺少面向 `memory` 槽位的压缩治理层

当前聊天主链路会在 [`chat_request()`](backend/ai-service/app/api/http_api.py) 中把以下变量直接注入最终 Chat Prompt：

- 短期摘要相关变量
- 近期会话片段变量
- 长期记忆变量
- 外部知识变量
- 用户画像变量

这些变量共同属于 `memory` 槽位的主要膨胀来源，但当前没有一个统一的治理层在最终 Prompt 装配前对这些变量进行独立压缩治理。

#### 2.2.2 缺少统一 Token 审计口径

虽然项目已有 [`count_tokens()`](backend/ai-service/app/llm/context_manager.py) 与 [`count_messages_tokens()`](backend/ai-service/app/llm/context_manager.py)，但当前没有统一定义：

- 原始 Token 数
- 裁剪后 Token 数
- 摘要后 Token 数
- 总压缩率
- 分阶段压缩率
- 触发原因
- 模型信息
- 关联请求标识

#### 2.2.3 缺少最小回放快照集合

当前零散日志无法回答以下问题：

- 本次压缩为什么触发
- 哪一段内容被压缩
- 是消息级裁剪、摘要压缩还是槽位级压缩
- 压缩前后 Token 如何变化
- 失败发生在哪一步
- 最终注入 Prompt 的上下文属于哪个降级层级

---

## 3. 问题定义

### 3.1 需要解决的核心问题

在保持现有 `system / memory / runtime` 三槽位 Prompt 结构不被破坏的前提下，需要解决以下三类问题：

1. 当上下文整体过长时，如何优先治理 `memory` 槽位，而不是粗暴截断整个 Prompt。
2. 每一次压缩、裁剪、降级都如何产出统一口径的 Token 审计数据。
3. 在不保存完整敏感原文的前提下，如何让一次压缩链路可以被结构化回放与审计。

### 3.2 本方案中的术语定义

为保证文档、代码与审计展示一致，本方案统一使用以下术语：

- **会话消息级裁剪**：针对 `history` 消息列表执行的滑动窗口裁剪。
- **摘要压缩级裁剪**：对 Redis 短期历史或历史会话文本执行模型摘要压缩。
- **槽位级压缩治理**：针对 `memory` 槽位中变量注入内容的治理动作。
- **统一历史背景降级**：当分变量压缩后仍超限时，把允许合并的历史背景类变量压缩为单一 `HISTORICAL_CONTEXT` 变量。
- **压缩动作**：一次可审计的治理单元，包含触发、测量、执行、输出、应用五个阶段。
- **回放快照**：可用于重建压缩过程的最小脱敏数据集合。

---

## 4. 设计原则

### 4.1 先复用已有模块，不重写主链路

优先复用：

- [`truncate_context()`](backend/ai-service/app/llm/context_manager.py)
- [`_trigger_compression()`](backend/ai-service/app/api/http_api.py)
- [`short_summarize()`](backend/ai-service/app/api/internal_service.py)
- [`long_summarize()`](backend/ai-service/app/api/internal_service.py)
- [`update_summary_and_trim()`](backend/ai-service/app/repository/chat_history_redis.py)
- [`record_audit_log_async()`](backend/ai-service/app/telemetry/worker.py)
- [`record_span_async()`](backend/ai-service/app/telemetry/worker.py)

### 4.2 优先治理 `memory` 槽位，不对 `system` 槽位做压缩

原因：

- `system` 槽位承载角色、约束与边界，不能在本轮压缩治理中被改写。
- `runtime` 槽位通常较短，主要保存当前输入和少量运行时变量。
- 当前实际最容易膨胀的是 `memory` 槽位中的历史、长期记忆、外部知识、用户画像等变量注入。

### 4.3 先做确定性冗余识别，再做模型压缩

本轮优先采用低风险、可解释的冗余识别策略：

- 空值过滤
- 完全重复过滤
- 前缀包含过滤
- 固定阈值压缩

不在 MVP 中引入复杂语义聚类与多模型比对。

### 4.4 不保存完整敏感原文，只保存最小必要脱敏快照

本方案不以“完整 Prompt 原文落盘”为目标，而是保留：

- Token 统计
- 来源范围
- 触发原因
- 脱敏预览
- 模型信息
- 阶段结果

### 4.5 显式区分 MVP 与增强项

本轮必须完成：

- 槽位级压缩治理入口
- Token 压缩率审计
- 压缩过程回放所需最小快照与事件序列

本轮不强制完成：

- 实时 SSE 压缩进度提示
- 单独数据库专表改造
- 全文级回放
- DAG 节点级压缩图谱

---

## 5. 详细方案

### 5.1 总体架构

本轮新增“压缩治理层”，位于最终 Chat Prompt 组装之前，整体流程如下：

1. 维持现有 [`chat_request()`](backend/ai-service/app/api/http_api.py) 的输入重构、长期记忆检索、外部知识检索、用户画像读取流程不变。
2. 在 `prompt_variables` 初步组装完成后，新增 `memory` 槽位压缩治理编排。
3. 编排按顺序执行：
   - 会话消息级裁剪统计
   - 摘要压缩级裁剪统计
   - 冗余内容识别
   - 分变量压缩
   - 统一历史背景降级
   - 强制硬截断保护
4. 每一步产生压缩动作审计记录与 Span。
5. 最终把治理后的变量映射继续传给 [`PromptCategory.CHAT`](backend/ai-service/app/prompt/types.py) 的模板装配。

### 5.2 会话消息级裁剪

#### 5.2.1 复用位置

直接复用：

- [`truncate_context()`](backend/ai-service/app/llm/context_manager.py)
- [`format_messages_for_api()`](backend/ai-service/app/llm/context_manager.py)

#### 5.2.2 增量设计

建议在 [`backend/ai-service/app/llm/context_manager.py`](backend/ai-service/app/llm/context_manager.py) 新增只读统计函数，而不是改变现有函数返回值，避免破坏主链路：

- `measure_truncate_context()`
- `ContextTrimMetrics`

建议数据结构：

```python
class ContextTrimMetrics(BaseModel):
    before_tokens: int
    after_tokens: int
    removed_history_count: int
    reserved_output_tokens: int
    max_context_tokens: int
    is_over_limit_after_trim: bool
```

#### 5.2.3 作用范围

此阶段只解决 `history` 消息列表过长的问题，不处理 `LONG_TERM_MEMORY`、`EXTERNAL_KNOWLEDGE`、`USER_PROFILE` 等注入变量本身的膨胀。

### 5.3 摘要压缩级裁剪

#### 5.3.1 短期摘要压缩

继续由 [`_trigger_compression()`](backend/ai-service/app/api/http_api.py) 驱动，新增以下能力：

- 压缩前消息文本 Token 统计
- 摘要输出 Token 统计
- `CompressionAuditPayload` 生成
- 审计日志落盘
- Span 落盘

#### 5.3.2 长期历史压缩

继续由 [`Manager._compress_and_commit()`](backend/ai-service/app/memory/manager.py) 驱动，新增以下能力：

- 历史会话压缩前 Token 统计
- 长摘要输出 Token 统计
- 与 `memory_id` 关联
- 作为可回放事件链的一部分持久化

### 5.4 冗余内容识别策略

#### 5.4.1 MVP 策略

针对 `memory` 槽位中即将注入的文本变量，按以下顺序处理：

1. **空值过滤**：空字符串直接跳过。
2. **完全重复过滤**：内容完全一致且来源相同的文本只保留一份。
3. **包含关系过滤**：若同来源变量中 A 完整包含 B，则丢弃被完整覆盖的短文本。
4. **单变量超限识别**：任一变量超过 `memory_slot_single_variable_max_tokens` 时，优先对该变量单独压缩。
5. **来源标签保留**：所有压缩动作保留原变量键名，便于审计与回放。

#### 5.4.2 后续增强项

- 语义近似去重
- 基于当前意图的相关性筛除
- 基于时间新鲜度的保留优先级

### 5.5 触发阈值与降级策略

#### 5.5.1 建议新增配置项

建议位置：[`backend/ai-service/app/config/settings.py`](backend/ai-service/app/config/settings.py)

建议新增：

- `memory_slot_max_tokens`
- `memory_slot_single_variable_max_tokens`
- `historical_context_max_tokens`
- `compression_replay_preview_max_chars`
- `compression_audit_enabled`

#### 5.5.2 触发条件

在 [`chat_request()`](backend/ai-service/app/api/http_api.py) 中完成 `prompt_variables` 初步组装后，统计以下变量的总 Token：

- `MEMORY_SNIPPETS`
- `LONG_TERM_MEMORY`
- `EXTERNAL_KNOWLEDGE`
- `USER_PROFILE`
- 其他属于 `memory` 槽位的大文本变量

若总量不超过 `memory_slot_max_tokens`，则跳过槽位级压缩治理。

若总量超过阈值，则进入分级治理。

#### 5.5.3 分级治理顺序

##### 一级：分变量压缩

对超过单变量阈值的变量分别压缩，保持变量名不变：

- `MEMORY_SNIPPETS`
- `LONG_TERM_MEMORY`
- `EXTERNAL_KNOWLEDGE`
- `USER_PROFILE`

优势：

- 不破坏现有模板结构
- 容易定位是哪一类上下文导致膨胀
- 审计与回放粒度更清晰

##### 二级：统一历史背景降级

若一级压缩后总量仍超限：

- 把允许合并的历史背景类变量合并为单一 `HISTORICAL_CONTEXT`
- 原变量清空
- 保留来源标签块

建议格式：

```text
[长期记忆]
...

[外部知识]
...

[用户画像]
...

[近期摘要]
...
```

然后调用压缩模型生成统一历史背景文本。

##### 三级：强制硬截断保护

若统一历史背景压缩后仍超限：

- 对 `HISTORICAL_CONTEXT` 执行最终 Token 级硬截断
- 记录为 `FORCED_HARD_TRUNCATION`
- 必须保留压缩失败或硬截断原因到审计中

### 5.6 与现有 `context_manager` 和 `memory_manager` 的衔接

#### 5.6.1 与 [`context_manager`](backend/ai-service/app/llm/context_manager.py) 的衔接

- `context_manager` 继续负责消息列表裁剪。
- 本方案新增的槽位级压缩治理不替代 `truncate_context()`，而是在其上层补治理闭环。
- `truncate_context()` 的前后 Token 统计应纳入统一压缩审计口径。

#### 5.6.2 与 [`memory_manager`](backend/ai-service/app/memory/manager.py) 的衔接

- [`Manager._compress_and_commit()`](backend/ai-service/app/memory/manager.py) 继续作为长期历史压缩入口。
- [`_trigger_compression()`](backend/ai-service/app/api/http_api.py) 继续作为短期摘要压缩入口。
- 本方案只在这两个函数周围补动作记录、快照与审计，不改变其职责边界。

### 5.7 新增模块建议

建议新增目录：[`backend/ai-service/app/context/`](backend/ai-service/app)

建议新增文件：

- `compression_governor.py`
- `compression_types.py`
- `compression_replay.py`

建议职责：

#### 5.7.1 `compression_governor.py`

负责：

- 统计 `memory` 槽位 Token
- 冗余过滤
- 分变量压缩
- 统一历史背景降级
- 返回最终变量映射与动作序列

#### 5.7.2 `compression_types.py`

负责定义：

- `CompressionStage`
- `CompressionScope`
- `CompressionTriggerReason`
- `CompressionAuditPayload`
- `CompressionActionRecord`
- `CompressionReplaySnapshot`
- `CompressionGovernanceResult`

#### 5.7.3 `compression_replay.py`

负责：

- 从审计日志聚合压缩动作
- 重建压缩时间线
- 生成前端详情页可消费的数据结构

---

## 6. 数据结构与接口变更

### 6.1 新增枚举建议

建议位置：[`backend/ai-service/app/types/constants.py`](backend/ai-service/app/types/constants.py)

```python
class CompressionStage(str, Enum):
    MESSAGE_TRIM = "message_trim"
    SHORT_SUMMARY = "short_summary"
    LONG_SUMMARY = "long_summary"
    MEMORY_SLOT_VARIABLE = "memory_slot_variable"
    HISTORICAL_CONTEXT_MERGE = "historical_context_merge"
    HARD_TRUNCATION = "hard_truncation"


class CompressionTriggerReason(str, Enum):
    REDIS_WINDOW_OVERFLOW = "redis_window_overflow"
    HISTORY_SESSION_ROLLOVER = "history_session_rollover"
    MEMORY_SLOT_TOKEN_OVER_LIMIT = "memory_slot_token_over_limit"
    SINGLE_VARIABLE_TOKEN_OVER_LIMIT = "single_variable_token_over_limit"
    FINAL_PROMPT_TOKEN_OVER_LIMIT = "final_prompt_token_over_limit"


class CompressionScope(str, Enum):
    SESSION_HISTORY = "session_history"
    LONG_TERM_MEMORY = "long_term_memory"
    EXTERNAL_KNOWLEDGE = "external_knowledge"
    USER_PROFILE = "user_profile"
    MEMORY_SLOT = "memory_slot"
    HISTORICAL_CONTEXT = "historical_context"
```

### 6.2 Token 审计口径定义

本方案统一定义以下字段：

- **原始 Token 数**：压缩动作开始前的 Token 数。
- **裁剪后 Token 数**：执行消息级裁剪或硬截断后的 Token 数。
- **摘要后 Token 数**：调用压缩模型后输出文本的 Token 数。
- **最终 Token 数**：该动作应用后的最终 Token 数。
- **总压缩率**：`final_tokens / raw_tokens`。
- **分阶段压缩率**：`stage_after_tokens / stage_before_tokens`。
- **触发原因**：来自 [`CompressionTriggerReason`](backend/ai-service/app/types/constants.py)。
- **模型信息**：`provider/base_url/model_id` 摘要信息。
- **关联标识**：`trace_id`、`session_id`、`message_id`、可选 `memory_id`。
- **时间戳**：毫秒时间戳和 ISO 时间。
- **是否成功**：动作执行结果。
- **失败原因**：简短错误描述。

### 6.3 新增审计载荷结构建议

```python
class CompressionAuditPayload(BaseModel):
    schema_version: str = "compression.audit.v1"
    trace_id: str
    session_id: str
    message_id: str = ""
    memory_id: str = ""
    stage: CompressionStage
    scope: CompressionScope
    trigger_reason: CompressionTriggerReason
    raw_tokens: int
    after_trim_tokens: int = 0
    after_summary_tokens: int = 0
    final_tokens: int
    total_compression_ratio: float
    stage_compression_ratio: float
    model_provider: str = ""
    model_base_url: str = ""
    model_id: str = ""
    is_success: bool
    failure_reason: str = ""
    timestamp_ms: int
    preview_before: str = ""
    preview_after: str = ""
    replay_snapshot_id: str = ""
```

### 6.4 新增回放快照结构建议

```python
class CompressionReplaySnapshot(BaseModel):
    schema_version: str = "compression.replay.v1"
    snapshot_id: str
    trace_id: str
    session_id: str
    message_id: str = ""
    stage: CompressionStage
    scope: CompressionScope
    source_keys: list[str]
    preview_before: str
    preview_after: str
    raw_tokens: int
    final_tokens: int
    is_success: bool
    failure_reason: str = ""
    created_at_ms: int
```

### 6.5 审计日志接入方式

#### 6.5.1 MVP 方案

本轮不强制修改 [`AuditLog`](backend/ai-service/app/telemetry/worker.py) 表结构，先采用“结构化 JSON 写入 `details`”策略：

- `action_type = "CONTEXT_COMPRESSION"`
- `status = "SUCCESS" | "FAILED" | "SKIPPED"`
- `details = CompressionAuditPayload.model_dump_json()`

优势：

- 改动最小
- 复用现有查询链路
- 后续若要拆专表可平滑迁移

#### 6.5.2 后续增强项

若压缩查询量明显增大，再新增专用表：

- `compression_audit_logs`
- `compression_replay_snapshots`

本轮不作为必做项。

### 6.6 Span 接入方式

建议为每个压缩动作写一条 Span：

- `name = "ContextCompression"`
- `service = "python_ai"`
- `attributes` 包含：
  - `stage`
  - `scope`
  - `raw_tokens`
  - `final_tokens`
  - `compression_ratio`
  - `trigger_reason`
  - `model_id`
  - `is_success`

### 6.7 新增查询接口建议

建议在 [`backend/ai-service/app/api/routers/telemetry.py`](backend/ai-service/app/api/routers/telemetry.py) 新增：

- `GET /api/v1/telemetry/compression_audits`
- `GET /api/v1/telemetry/compression_replays/{trace_id}`

返回内容：

- 压缩动作列表
- 聚合统计
- 阶段时间线
- 脱敏前后预览

---

## 7. 审计与可观测性方案

### 7.1 压缩动作事件序列

每个压缩动作至少产出以下事件顺序：

1. `COMPRESSION_TRIGGERED`
2. `COMPRESSION_INPUT_MEASURED`
3. `COMPRESSION_EXECUTED`
4. `COMPRESSION_OUTPUT_MEASURED`
5. `COMPRESSION_APPLIED`
6. `COMPRESSION_COMPLETED` 或 `COMPRESSION_FAILED`

### 7.2 日志规范

所有压缩相关日志必须使用 `logger`，且为简体中文，符合 [`agent.md`](agent.md) 约束。

建议日志最少携带：

- `trace_id`
- `session_id`
- `message_id`
- `stage`
- `scope`
- `raw_tokens`
- `final_tokens`
- `compression_ratio`
- `trigger_reason`
- `retry_count`

### 7.3 压缩失败策略

压缩失败时遵循以下策略：

- 单变量压缩失败：记录失败审计，继续尝试其它变量。
- 统一历史背景压缩失败：记录失败审计，进入最终硬截断保护。
- 审计写入失败：只记录降级日志，不阻断聊天主链路。
- Span 写入失败：只记录降级日志，不阻断主链路。

---

## 8. 回放机制设计

### 8.1 回放目标

本方案中的“可回放”不等于“保存完整原文后原样重播”，而是要求能够重建一次压缩链路的结构化过程：

- 为什么触发
- 作用于哪个范围
- 经过了哪些阶段
- 每阶段 Token 如何变化
- 使用了哪个模型
- 最终是否成功
- 采用了哪一级降级策略

### 8.2 回放所需最小快照集合

每次压缩动作必须至少保留：

1. `trace_id`
2. `session_id`
3. `message_id`
4. `stage`
5. `scope`
6. `trigger_reason`
7. `source_keys`
8. `raw_tokens`
9. `final_tokens`
10. `stage_compression_ratio`
11. `preview_before`
12. `preview_after`
13. `model_info`
14. `is_success`
15. `failure_reason`
16. `timestamp_ms`

### 8.3 敏感内容脱敏策略

本方案不保存完整上下文正文，只保存经过脱敏和摘要化的预览内容。建议新增脱敏工具文件：

- [`backend/ai-service/app/telemetry/redaction.py`](backend/ai-service/app)

建议脱敏规则：

- 邮箱替换为 `[REDACTED_EMAIL]`
- 密钥与 Token 替换为 `[REDACTED_SECRET]`
- URL 查询参数脱敏
- 超长文本只保留前后若干字符
- 统一换行与空白折叠
- 对 Unicode 异常字符使用既有清洗工具链进行保护性处理

### 8.4 如何从审计记录重建一次压缩链路

重建流程：

1. 以 `trace_id + session_id + message_id` 查询 `action_type = CONTEXT_COMPRESSION` 的审计记录。
2. 解析 `details` 中的 `CompressionAuditPayload`。
3. 按时间戳排序并分组到同一请求链路下。
4. 把同一请求中的多条动作整理成阶段时间线。
5. 结合 `TraceSpan.duration_ms` 生成耗时视角。
6. 输出供前端展示的回放结构：
   - 总览摘要
   - 阶段列表
   - 每阶段前后 Token
   - 预览前后片段
   - 失败原因与降级路径

### 8.5 最低可用回放接口设计

建议返回结构：

```json
{
  "trace_id": "...",
  "session_id": "...",
  "message_id": "...",
  "summary": {
    "raw_tokens": 0,
    "final_tokens": 0,
    "total_compression_ratio": 0.0,
    "final_strategy": "memory_slot_variable"
  },
  "events": [],
  "snapshots": []
}
```

---

## 9. 前后端协作点

### 9.1 后端需要稳定输出的能力

后端需向前端稳定提供：

1. 压缩审计列表查询能力
2. 压缩回放详情查询能力
3. 统一的结构化字段命名
4. 基于 `trace_id` 的聚合查询能力

### 9.2 与前端当前结构的映射关系

前端已有：

- 诊断面板入口 [`DebugPanelInner`](frontend/src/renderer/components/Settings/DebugPanel/index.tsx)
- 审计日志查看器 [`AuditLogViewer`](frontend/src/renderer/components/Settings/DebugPanel/AuditLogViewer.tsx)
- 遥测 Store [`useTelemetryStore`](frontend/src/renderer/stores/telemetryStore.ts)
- 共享消息与枚举文件 [`frontend/src/shared/enum.ts`](frontend/src/shared/enum.ts)

后端应确保压缩审计结果可以被前端以“列表 + 详情回放”的方式消费，而不要求前端自行推导阶段语义。

### 9.3 本轮不做的协作点

- 不要求后端实时通过 SSE 推送压缩事件
- 不要求与 [`RAG_EVENT_THOUGHT`](backend/ai-service/app/types/constants.py) 合并为同一时间线
- 不要求把压缩回放直接嵌入聊天消息气泡

---

## 10. 实施步骤

### 10.1 MVP 必做

#### 步骤一：补统一类型与常量

建议改动位置：

- [`backend/ai-service/app/types/constants.py`](backend/ai-service/app/types/constants.py)
- 新增 [`backend/ai-service/app/context/compression_types.py`](backend/ai-service/app)

输出：

- 压缩阶段枚举
- 作用域枚举
- 触发原因枚举
- 审计载荷结构
- 回放快照结构

#### 步骤二：补 Token 统计与压缩治理编排器

建议改动位置：

- 新增 [`backend/ai-service/app/context/compression_governor.py`](backend/ai-service/app)
- 复用 [`backend/ai-service/app/llm/context_manager.py`](backend/ai-service/app/llm/context_manager.py)

输出：

- `memory` 槽位 Token 统计
- 分变量压缩
- 统一历史背景降级
- 最终硬截断保护

#### 步骤三：在现有压缩入口补审计与 Span

建议改动位置：

- [`backend/ai-service/app/api/http_api.py`](backend/ai-service/app/api/http_api.py)
- [`backend/ai-service/app/memory/manager.py`](backend/ai-service/app/memory/manager.py)
- [`backend/ai-service/app/api/internal_service.py`](backend/ai-service/app/api/internal_service.py)

输出：

- 短期摘要压缩审计
- 长期摘要压缩审计
- 槽位级压缩审计
- 压缩 Span

#### 步骤四：补压缩回放查询接口

建议改动位置：

- [`backend/ai-service/app/api/routers/telemetry.py`](backend/ai-service/app/api/routers/telemetry.py)
- 新增 [`backend/ai-service/app/context/compression_replay.py`](backend/ai-service/app)

输出：

- 压缩审计列表接口
- 压缩回放详情接口

### 10.2 后续增强项

- 审计专表化
- 压缩事件 SSE 化
- 语义冗余识别增强
- DAG 节点级压缩治理视图
- 前端与 RAG 思维事件统一时间线

---

## 11. 风险与回滚

### 11.1 主要风险

1. 压缩治理过度，导致关键信息丢失。
2. `memory` 槽位压缩后影响现有 Prompt 模板稳定性。
3. 审计明细过长，导致 `audit_logs.details` 膨胀。
4. 脱敏策略不足，存在敏感信息泄露风险。
5. 一次性改动过多，影响聊天主链路稳定性。

### 11.2 风险控制措施

- 压缩治理入口增加配置开关。
- 先只对 `memory` 槽位生效，不改 `system` 与 `runtime`。
- 先采用 JSON 写入 `details` 的 MVP 方案，不立即改表。
- 预览文本长度严格受限。
- 所有压缩异常均允许主链路降级继续执行。

### 11.3 回滚方案

若出现问题，按以下顺序回滚：

1. 关闭 `compression_audit_enabled` 与 `memory_slot_compression_enabled`。
2. 保留现有 [`truncate_context()`](backend/ai-service/app/llm/context_manager.py) 与 Redis 短摘要压缩逻辑。
3. 新增的查询接口可保留但返回空数据，不影响主链路。
4. 若审计详情过长，先停写压缩快照，仅保留汇总指标。

---

## 12. 验收标准

### 12.1 超长聊天冗余裁剪

满足以下条件视为通过：

1. 长对话场景下，系统优先对 `memory` 槽位执行压缩治理，而不是直接整体截断最终 Prompt。
2. 会话消息级裁剪、摘要压缩级裁剪、槽位级压缩三类动作能够在审计中区分。
3. 分变量压缩失败后可以继续执行统一历史背景降级。
4. 最终硬截断只作为最后保护，不作为默认路径。

### 12.2 Token 压缩率审计

满足以下条件视为通过：

1. 每次压缩动作都能记录原始 Token 数、裁剪后 Token 数、摘要后 Token 数、最终 Token 数。
2. 每次压缩动作都能记录总压缩率与分阶段压缩率。
3. 每次压缩动作都能记录触发原因、模型信息、关联标识、时间戳、成功状态与失败原因。
4. 审计数据可通过现有遥测查询链路读取。

### 12.3 压缩过程可回放、可审计

满足以下条件视为通过：

1. 同一 `trace_id` 下可以查询出完整压缩动作序列。
2. 可以基于审计记录重建压缩阶段时间线。
3. 每个阶段都有最小脱敏快照，能说明“压缩了什么”和“压缩后变成什么级别”。
4. 不保存完整敏感原文，但足以让开发者定位压缩问题。

### 12.4 与现有主链路兼容

满足以下条件视为通过：

1. 不破坏 [`chat_request()`](backend/ai-service/app/api/http_api.py) 当前主流程。
2. 不破坏 [`_trigger_compression()`](backend/ai-service/app/api/http_api.py) 与 [`Manager._compress_and_commit()`](backend/ai-service/app/memory/manager.py) 既有职责。
3. 审计与 Span 写入失败时不阻断聊天主链路。
4. 新增功能可以通过配置开关快速关闭。