# 长回答处理方案 - 后端架构设计与实施计划

## 1. 文档定位与适用范围

本方案用于规划 Luna 在复杂任务、长篇 RAG 问答和结构化资料整理场景下的后端长回答链路。

本方案只描述后续开发落地方式，不直接修改当前业务代码。

本方案遵循项目根目录 [`agent.md`](agent.md) 中的本地优先、Python 后端统一控制面、接口契约优先、状态可追踪、Snowflake ID 统一生成等要求。

本方案与 [`backend/docs/plans/phase7_backend_plan.md`](backend/docs/plans/phase7_backend_plan.md) 的 RAG 设计保持一致。

本方案也需要与 [`frontend/docs/plans/phase7_frontend_plan.md`](frontend/docs/plans/phase7_frontend_plan.md) 的前端 RAG 展示策略配合。

核心产品语义如下：

1. 短回答是聊天气泡内的自然对话。
2. 短回答不标明来源。
3. 短回答不承担完整资料整理职责。
4. 长回答是结构化正文。
5. 长回答展示在前端左侧磨砂玻璃面板内。
6. 长回答允许 Markdown、标题、表格、代码块和必要引用。
7. 长回答正文不写入现有 `interactions.assistant_content`。
8. 长回答正文不完整进入短聊天上下文。
9. 长回答必须有小总结。
10. 小总结参与上下文压缩和记忆压缩。

---

## 2. 当前源码观察结论

### 2.1 当前主聊天入口

当前 HTTP 聊天入口位于 [`backend/ai-service/app/api/http_api.py`](backend/ai-service/app/api/http_api.py:298)。

当前请求模型 [`ChatRequestPayload`](backend/ai-service/app/api/http_api.py:91) 包含 `sessionId`、`message`、`msgId` 和 `history`。

当前 [`chat_request()`](backend/ai-service/app/api/http_api.py:298) 会先加载 Redis 上下文。

当前 [`chat_request()`](backend/ai-service/app/api/http_api.py:298) 会调用 Input Reconstruction Agent。

当前 [`chat_request()`](backend/ai-service/app/api/http_api.py:298) 会在需要时调用长期记忆混合检索。

当前 [`chat_request()`](backend/ai-service/app/api/http_api.py:298) 会组装 `PromptCategory.CHAT` 对应的 Chat Prompt。

当前 [`chat_request()`](backend/ai-service/app/api/http_api.py:298) 会通过 `asyncio.create_task()` 调用后台流式任务。

当前后台流式任务是 [`_execute_llm_stream()`](backend/ai-service/app/api/http_api.py:509)。

当前持久化函数是 [`_persist_interaction()`](backend/ai-service/app/api/http_api.py:650)。

当前压缩触发函数是 [`_trigger_compression()`](backend/ai-service/app/api/http_api.py:724)。

### 2.2 当前短回答 Prompt

当前主聊天 runtime prompt 位于 [`backend/ai-service/app/prompt/simple/chat/runtime.j2`](backend/ai-service/app/prompt/simple/chat/runtime.j2:1)。

该 prompt 强调情绪、人设、内心独白、傲娇、关系动态和最终单行 JSON 输出。

该 prompt 的输出结构要求包含 `check`、`thought`、`emotion`、`reply`。

当前 [`StreamParser`](backend/ai-service/app/llm/stream_parser.py:55) 正是围绕该 JSON 结构解析。

当前 [`StreamParser`](backend/ai-service/app/llm/stream_parser.py:55) 会丢弃 `check`。

当前 [`StreamParser`](backend/ai-service/app/llm/stream_parser.py:55) 会捕获 `thought` 用于持久化。

当前 [`StreamParser`](backend/ai-service/app/llm/stream_parser.py:55) 会提取 `emotion` 并下发。

当前 [`StreamParser`](backend/ai-service/app/llm/stream_parser.py:55) 会将 `reply` 按标点断句成 `reply_chunk`。

因此当前短回答链路天然适合气泡输出，不适合长篇 Markdown 正文。

### 2.3 当前持久化结构

现有 ORM 模型位于 [`backend/ai-service/app/repository/models.py`](backend/ai-service/app/repository/models.py:1)。

现有 [`InteractionModel`](backend/ai-service/app/repository/models.py:37) 对应 `interactions` 表。

[`InteractionModel`](backend/ai-service/app/repository/models.py:37) 将一次用户问题和一次助手短回复绑定。

[`InteractionModel.assistant_content`](backend/ai-service/app/repository/models.py:48) 当前用于保存助手气泡回复。

[`InteractionModel.thought`](backend/ai-service/app/repository/models.py:50) 当前用于保存内心独白。

[`ChatHistoryPGRepo.save_interaction()`](backend/ai-service/app/repository/chat_history_pg.py:31) 当前只负责写入 Interaction。

Redis 交互模型 [`Interaction`](backend/ai-service/app/repository/chat_history_redis.py:26) 当前也只包含用户内容、助手内容、thought、emotion、error 和 timestamp。

当前 Redis 历史 key 使用 [`ChatHistoryRedisRepo._build_history_key()`](backend/ai-service/app/repository/chat_history_redis.py:56) 生成。

当前 Redis 摘要 key 使用 [`ChatHistoryRedisRepo._build_summary_key()`](backend/ai-service/app/repository/chat_history_redis.py:59) 生成。

### 2.4 当前 SSE 机制

当前 SSE 管理器位于 [`backend/ai-service/app/api/sse.py`](backend/ai-service/app/api/sse.py:39)。

当前事件推送函数位于 [`_publish_sse_event()`](backend/ai-service/app/api/http_api.py:137)。

当前后端通过 `CHAT_STREAM` 事件向前端推送聊天流。

当前 [`ChatStreamPayload`](backend/ai-service/app/api/http_api.py:69) 包含 `type`、`chunk`、`is_finished`、`node_id`、`error`。

当前前端依赖 `type=reply_chunk` 来驱动气泡输出。

长回答链路不应复用 `reply_chunk` 做正文输出。

长回答链路应新增独立事件类型，避免污染短回答气泡机制。

---

## 3. 产品语义与职责边界

### 3.1 短回答定义

短回答是 Luna 在主聊天气泡中自然地对用户说的话。

短回答继续使用 [`backend/ai-service/app/prompt/simple/chat/runtime.j2`](backend/ai-service/app/prompt/simple/chat/runtime.j2:1)。

短回答继续允许情绪、人设、撒娇、轻微抱怨和亲密互动。

短回答继续输出 JSON，由 [`StreamParser`](backend/ai-service/app/llm/stream_parser.py:55) 解析。

短回答不显示来源。

短回答不渲染引用列表。

短回答不承载长篇资料正文。

短回答可以告知用户“我整理好啦”。

短回答可以对整理过程做轻微自然互动。

短回答应写入 [`InteractionModel.assistant_content`](backend/ai-service/app/repository/models.py:48)。

### 3.2 长回答定义

长回答是结构化正文，专门用于左侧长回答面板。

长回答不使用当前 chat runtime prompt。

长回答需要新增专用 prompt。

长回答 prompt 不需要复杂情绪设定。

长回答 prompt 只保留 Luna 基础身份、表达边界、事实性和格式规范。

长回答输出应是 Markdown 正文，而不是当前 chat JSON。

长回答正文需要支持流式输出。

长回答正文可以包含标题、分段、列表、表格和代码块。

长回答正文可以包含必要引用，但引用展示只在长回答面板内发生。

长回答正文不应进入 [`InteractionModel`](backend/ai-service/app/repository/models.py:37)。

长回答正文应进入新表。

长回答正文只通过关联字段与对应聊天交互互相追溯。

---

## 4. 长回答判定入口设计

### 4.1 判定入口位置

推荐在 [`chat_request()`](backend/ai-service/app/api/http_api.py:298) 中 Input Reconstruction 之后、组装 Chat Prompt 之前增加长回答判定。

原因如下：

1. Input Reconstruction 已经完成意图消歧。
2. 长期记忆或 RAG 检索条件已经基本明确。
3. 判定结果可以决定走短回答还是长回答编排。
4. 仍然可以复用当前 HTTP 立即返回、后台 Task 推流的生命周期。

### 4.2 判定信号来源

判定可以使用多源信号，但实现时必须先使用可解释规则，避免过度依赖模型。

规则信号包括：

1. 用户问题包含“详细”、“完整”、“整理”、“方案”、“文档”、“分析”、“对比”、“步骤”、“代码实现”等词。
2. Input Reconstruction 的 `dag_route_hint` 为复杂任务或多源检索。
3. Input Reconstruction 的 `retrieval_routing.external_knowledge.trigger` 为真。
4. RAG 召回证据片段数量超过阈值。
5. 预计回答字符数超过阈值。
6. 用户明确要求 Markdown、表格、代码块或结构化输出。
7. 用户问题需要多步骤推理。

需要在实现前确认：当前 [`InputReconstructorAgent`](backend/ai-service/app/agent/input_reconstructor.py) 输出结构中是否已有足够字段直接表达“长回答意图”。

如果没有，则应扩展 Input Reconstruction 的结构化输出，而不是在前端自行判断。

### 4.3 判定结果结构

建议新增内部模型：

```python
class LongAnswerDecision(BaseModel):
    enabled: bool
    reason: str
    mode: str
    estimated_complexity: str
    evidence_count: int = 0
```

`enabled=false` 时走现有短回答链路。

`enabled=true` 时走长回答编排链路。

`mode` 可为 `long_answer`、`rag_long_answer`、`task_long_answer`。

所有枚举值必须进入 [`backend/ai-service/app/types/constants.py`](backend/ai-service/app/types/constants.py:1)。

---

## 5. 新增长回答 Prompt 设计

### 5.1 Prompt 分类建议

当前 [`PromptCategory`](backend/ai-service/app/prompt/types.py:19) 包含 `CHAT`、`SHORT_SUMMARY`、`LONG_SUMMARY`、`INPUT_RECONSTRUCTION`。

建议新增 `LONG_ANSWER = "long_answer"`。

新增后需要补齐 prompt 模板目录：

1. `backend/ai-service/app/prompt/simple/long_answer/system.j2`
2. `backend/ai-service/app/prompt/simple/long_answer/memory.j2`
3. `backend/ai-service/app/prompt/simple/long_answer/runtime.j2`

如果项目现有 prompt 迁移脚本依赖固定目录，需要同步调整迁移脚本。

需要在实现前确认 [`backend/ai-service/scripts/migrate_prompts.py`](backend/ai-service/scripts/migrate_prompts.py) 的扫描规则。

### 5.2 长回答 Prompt 职责

长回答 Prompt 只做正文生成。

长回答 Prompt 不输出 `check` 字段。

长回答 Prompt 不输出 `thought` 字段。

长回答 Prompt 不输出 `emotion` 字段。

长回答 Prompt 不输出 `reply` 字段。

长回答 Prompt 不输出 JSON。

长回答 Prompt 输出纯 Markdown。

长回答 Prompt 需要要求：

1. 不虚构未提供事实。
2. 不把 RAG 证据伪装成模型自身见闻。
3. 引用只用于长回答正文。
4. 如果证据不足，明确标注“不足以确定”。
5. 保持段落清晰。
6. 表格只在确有必要时使用。
7. 代码块必须带语言标识。
8. 不使用撒娇、人设表演、括号动作描写。
9. 仍遵守 Luna 的基础身份边界。
10. 语言使用简体中文。

### 5.3 长回答 Prompt 输入变量

建议变量包括：

1. `CURRENT_TIME`
2. `USER_INPUT`
3. `DISAMBIGUATED_TEXT`
4. `CORE_SUMMARY`
5. `KEY_FACTS`
6. `RECENT_SHORT_CONTEXT`
7. `RAG_EVIDENCE_BLOCKS`
8. `LONG_ANSWER_STYLE_RULES`
9. `OUTPUT_FORMAT_RULES`
10. `CITATION_RULES`

注意：`RECENT_SHORT_CONTEXT` 只能提供近期短上下文和小总结，不提供完整长回答正文。

---

## 6. 长回答生成编排流程

### 6.1 总体流程

```text
用户发送消息
-> /api/chat 接收
-> 加载 Redis 摘要与近期 Interaction
-> Input Reconstruction 消歧与路由
-> 判定是否需要长回答
-> 如果不需要：走现有短回答链路
-> 如果需要：创建长回答记录
-> 推送长回答开始事件
-> 使用 long_answer prompt 流式生成 Markdown 正文
-> 持续写入缓存与推送正文 chunk
-> 完成后生成小总结
-> 写入 Redis 小总结
-> 更新长回答表为 completed
-> 再调用 chat prompt 生成短回答通知
-> 持久化 Interaction 短回答
-> 推送短回答气泡
```

### 6.2 为什么长回答先生成

产品体验要求 Luna 先在左侧面板认真整理长回答。

长回答完成后，再在主聊天气泡里自然通知用户。

这要求后台任务顺序必须是：

1. 长回答正文流式输出。
2. 小总结生成与存储。
3. 短回答二次调用。
4. 短回答气泡输出和 Interaction 保存。

### 6.3 与现有 `_execute_llm_stream()` 的关系

现有 [`_execute_llm_stream()`](backend/ai-service/app/api/http_api.py:509) 专用于短回答 JSON 流式解析。

不建议在该函数内部硬塞长回答正文逻辑。

建议新增服务层方法，例如 `LongAnswerService.generate_long_answer_then_short_reply()`。

[`chat_request()`](backend/ai-service/app/api/http_api.py:298) 根据判定结果创建不同后台 Task。

短回答继续调用 [`_execute_llm_stream()`](backend/ai-service/app/api/http_api.py:509)。

长回答调用新增编排服务。

---

## 7. 流式输出协议设计

### 7.1 新增 SSE 事件类型

当前所有聊天正文都通过 `CHAT_STREAM` 事件传输。

长回答应新增独立事件类型，建议：

1. `EVT_LONG_ANSWER_CREATED`
2. `EVT_LONG_ANSWER_CHUNK`
3. `EVT_LONG_ANSWER_STATUS`
4. `EVT_LONG_ANSWER_SUMMARY`
5. `EVT_LONG_ANSWER_FAILED`
6. `EVT_LONG_ANSWER_COMPLETED`

这些常量应写入 [`backend/ai-service/app/types/constants.py`](backend/ai-service/app/types/constants.py:14)。

前端常量应同步写入 [`frontend/src/shared/enum.ts`](frontend/src/shared/enum.ts:36)。

### 7.2 事件 Payload 建议

`EVT_LONG_ANSWER_CREATED`：

```json
{
  "schema_version": "1.0",
  "long_answer_id": "snowflake-string",
  "interaction_message_id": "assistant-msg-id",
  "session_id": "20260606",
  "status": "GENERATING",
  "title": "Luna正在整理中……"
}
```

`EVT_LONG_ANSWER_CHUNK`：

```json
{
  "schema_version": "1.0",
  "long_answer_id": "snowflake-string",
  "interaction_message_id": "assistant-msg-id",
  "seq": 12,
  "chunk": "Markdown正文片段",
  "is_finished": false
}
```

`EVT_LONG_ANSWER_COMPLETED`：

```json
{
  "schema_version": "1.0",
  "long_answer_id": "snowflake-string",
  "interaction_message_id": "assistant-msg-id",
  "status": "COMPLETED",
  "title": "本次整理概要",
  "short_summary": "本次回答主要整理了……"
}
```

所有 Payload 必须包含 `schema_version`。

所有 Payload 必须包含可追踪 ID。

所有状态迁移必须记录日志。

### 7.3 长回答正文流式 Parser

长回答正文是纯 Markdown，不需要当前 [`StreamParser`](backend/ai-service/app/llm/stream_parser.py:55)。

建议新增 `LongAnswerStreamAccumulator`。

该组件只负责：

1. 累积完整 Markdown 正文。
2. 给 chunk 添加自增序号。
3. 周期性保存草稿到数据库或 Redis。
4. 不做断句气泡切分。
5. 不解析 emotion。
6. 不解析 thought。

---

## 8. 数据库建模方案

### 8.1 不修改 InteractionModel 的原则

长回答正文不应放入 [`InteractionModel.assistant_content`](backend/ai-service/app/repository/models.py:48)。

原因如下：

1. `assistant_content` 语义是短聊天回复。
2. 当前历史展示和近期记忆都依赖该字段。
3. 长正文进入该字段会污染聊天历史。
4. 长正文进入该字段会污染 Redis 压缩上下文。
5. 长正文体积可能远大于短回答。

### 8.2 新表建议

建议新增表 `long_answers`。

DDL 建议：

```sql
CREATE TABLE long_answers (
    id VARCHAR(64) PRIMARY KEY,
    interaction_id VARCHAR(64),
    interaction_message_id VARCHAR(64) NOT NULL,
    session_id VARCHAR(64) NOT NULL,
    user_message_id VARCHAR(64),
    title VARCHAR(255) NOT NULL DEFAULT '',
    content_markdown TEXT NOT NULL DEFAULT '',
    short_summary TEXT NOT NULL DEFAULT '',
    status VARCHAR(30) NOT NULL,
    answer_type VARCHAR(50) NOT NULL DEFAULT 'long_answer',
    source_mode VARCHAR(50) NOT NULL DEFAULT '',
    token_count INTEGER NOT NULL DEFAULT 0,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT NOT NULL DEFAULT '',
    meta_payload JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    completed_at TIMESTAMP WITH TIME ZONE
);
```

字段说明：

1. `id`：长回答 ID，Snowflake 字符串。
2. `interaction_id`：关联 [`InteractionModel.id`](backend/ai-service/app/repository/models.py:44)，短回答持久化后回填。
3. `interaction_message_id`：关联当前前端 assistant 消息 ID，即 [`ChatRequestPayload.msgId`](backend/ai-service/app/api/http_api.py:95)。
4. `session_id`：会话 ID。
5. `user_message_id`：需要实现前确认当前用户消息 ID 是否传入后端；若未传入，后端需要扩展请求模型。
6. `title`：完成态标题或小总结标题。
7. `content_markdown`：完整长回答正文。
8. `short_summary`：小总结。
9. `status`：长回答状态。
10. `answer_type`：普通长答、RAG 长答、任务长答。
11. `source_mode`：是否含 RAG、记忆、工具来源。
12. `token_count`：正文估算 token 数。
13. `chunk_count`：流式 chunk 数。
14. `error_message`：失败原因。
15. `meta_payload`：引用、检索片段 ID、模型参数、trace 信息等。

### 8.3 索引建议

```sql
CREATE INDEX idx_long_answers_interaction_message_id ON long_answers(interaction_message_id);
CREATE INDEX idx_long_answers_session_id_created_at ON long_answers(session_id, created_at DESC);
CREATE INDEX idx_long_answers_status ON long_answers(status);
CREATE INDEX idx_long_answers_interaction_id ON long_answers(interaction_id);
```

如果需要快速通过问答记录查找长回答，`interaction_message_id` 必须唯一或准唯一。

建议增加唯一约束：

```sql
CREATE UNIQUE INDEX uniq_long_answers_interaction_message_id ON long_answers(interaction_message_id);
```

### 8.4 ORM 模型建议

在 [`backend/ai-service/app/repository/models.py`](backend/ai-service/app/repository/models.py:1) 中新增 `LongAnswerModel`。

该模型不替代 [`InteractionModel`](backend/ai-service/app/repository/models.py:37)。

该模型只负责长回答正文和元信息。

注意：如果加入 SQLAlchemy Relationship，需要确认当前项目是否统一使用轻量显式查询。

当前代码风格中 [`ChatHistoryPGRepo`](backend/ai-service/app/repository/chat_history_pg.py:25) 使用显式 `select()`，所以建议先不引入复杂 relationship。

---

## 9. 状态流转设计

### 9.1 状态枚举

建议新增长回答状态枚举：

1. `PENDING`
2. `GENERATING`
3. `SUMMARY_GENERATING`
4. `COMPLETED`
5. `FAILED`
6. `CANCELLED`
7. `RECOVERABLE_FAILED`

这些状态应集中定义在 [`backend/ai-service/app/types/constants.py`](backend/ai-service/app/types/constants.py:1) 或模型枚举区。

### 9.2 状态迁移

正常流程：

```text
PENDING -> GENERATING -> SUMMARY_GENERATING -> COMPLETED
```

长回答正文生成失败：

```text
PENDING -> GENERATING -> FAILED
```

正文生成成功但小总结失败：

```text
PENDING -> GENERATING -> SUMMARY_GENERATING -> COMPLETED
```

这里小总结失败时可以使用正文前若干字符生成兜底摘要。

用户取消：

```text
GENERATING -> CANCELLED
```

服务崩溃：

```text
GENERATING -> RECOVERABLE_FAILED
```

### 9.3 日志要求

每次状态变更必须记录：

1. `trace_id`
2. `session_id`
3. `interaction_message_id`
4. `long_answer_id`
5. `from_status`
6. `to_status`
7. `reason`
8. `latency_ms`

符合 [`agent.md`](agent.md:134) 的状态迁移记录要求。

---

## 10. Repository 与 Service 分层建议

### 10.1 Repository 层

建议新增文件：

1. `backend/ai-service/app/repository/long_answer_pg.py`

职责：

1. `create_long_answer(record)`
2. `append_content(long_answer_id, chunk)` 或 `update_content(long_answer_id, full_content)`
3. `update_status(long_answer_id, status, error_message="")`
4. `update_summary(long_answer_id, short_summary, title="")`
5. `bind_interaction(long_answer_id, interaction_id)`
6. `get_by_id(long_answer_id)`
7. `get_by_interaction_message_id(message_id)`
8. `list_by_session_id(session_id, limit, offset)`

Repository 不调用 LLM。

Repository 不推送 SSE。

Repository 只做数据库读写。

### 10.2 Service 层

建议新增文件：

1. `backend/ai-service/app/long_answer/service.py`
2. `backend/ai-service/app/long_answer/decision.py`
3. `backend/ai-service/app/long_answer/summary_cache.py`

`LongAnswerService` 职责：

1. 创建长回答记录。
2. 组装长回答 prompt。
3. 调用 LLM 流式生成正文。
4. 推送 SSE 长回答事件。
5. 累积正文并写入 PG。
6. 生成小总结。
7. 写入 Redis 小总结。
8. 调用短回答 prompt。
9. 调用 Interaction 持久化。
10. 处理失败恢复。

`LongAnswerDecisionService` 职责：

1. 根据输入和重构结果判定是否需要长回答。
2. 输出结构化判定结果。
3. 不做 UI 判断。

`LongAnswerSummaryCache` 职责：

1. 生成 Redis key。
2. 写入小总结。
3. 读取小总结。
4. 与压缩链路对接。

### 10.3 Controller 层

短期可继续挂载在 [`backend/ai-service/app/api/http_api.py`](backend/ai-service/app/api/http_api.py:1)。

但为了保持可读性，建议新增路由文件：

1. `backend/ai-service/app/api/long_answer_api.py`

新增接口：

1. `GET /api/long_answer/{long_answer_id}`
2. `GET /api/long_answer/by_message/{message_id}`
3. `POST /api/long_answer/{long_answer_id}/retry`
4. `POST /api/long_answer/{long_answer_id}/cancel`

需要在 [`backend/ai-service/app/main.py`](backend/ai-service/app/main.py:37) 注册该 router。

---

## 11. Redis 小总结缓存方案

### 11.1 为什么需要小总结

完整长回答正文不能进入短聊天上下文。

但上下文压缩仍需要知道该轮问答发生过什么。

小总结提供低 token 成本的语义代理。

小总结应与关联问答一起参与压缩。

小总结可以让 Luna 后续知道“我之前整理过一份关于 X 的长文”。

### 11.2 Redis Key 设计

建议 key：

```text
luna:long_answer:{session_id}:{interaction_message_id}:summary
```

值类型建议 Hash：

```text
long_answer_id -> Snowflake
interaction_message_id -> assistant message id
session_id -> session id
summary -> 小总结正文
title -> 标题
status -> COMPLETED
updated_at -> unix timestamp
```

另建议建立会话级索引 List：

```text
luna:long_answer:{session_id}:summary_index
```

List 元素为 `interaction_message_id`。

这样压缩时可以按 Interaction 的 `msgId` 查找对应小总结。

### 11.3 TTL 策略

短期建议不设置 TTL。

原因：Redis 当前短期上下文本身承担工作窗口缓存，长回答小总结需要参与后续压缩。

压缩完成并写入 PG 长期摘要后，可以裁剪对应小总结。

如果必须设置 TTL，建议与 session history 的生命周期保持一致。

需要在实现前确认当前 Redis 会话历史是否有统一过期策略。

当前 [`ChatHistoryRedisRepo`](backend/ai-service/app/repository/chat_history_redis.py:50) 代码未看到 TTL 设置。

因此小总结也先不设置 TTL。

### 11.4 与数据库同步

PG 表 `long_answers.short_summary` 是小总结的持久化事实来源。

Redis 小总结是压缩链路读取优化缓存。

写入顺序建议：

1. 小总结生成成功。
2. 先写 PG `short_summary`。
3. 再写 Redis summary hash。
4. 两者都成功后推送 `EVT_LONG_ANSWER_COMPLETED`。

如果 Redis 写入失败，长回答仍可视为完成，但需要记录警告。

压缩时如果 Redis 缺失，可以按 `interaction_message_id` 回查 PG。

---

## 12. 与上下文压缩链路衔接

当前压缩函数为 [`_trigger_compression()`](backend/ai-service/app/api/http_api.py:724)。

当前压缩输入会拼接 `interaction.assistantContent`。

长回答模式下，`interaction.assistantContent` 只保存短回答通知。

因此必须在压缩拼接时额外读取长回答小总结。

建议逻辑：

1. 遍历待压缩 Interaction。
2. 对每条 Interaction 使用 `msgId` 查询 Redis 小总结。
3. 如果存在小总结，拼接到该轮问答下方。
4. 不拼接完整长回答正文。
5. 如果 Redis 不存在但 PG 存在，回查 `long_answers.short_summary`。
6. 如果都不存在，跳过小总结。

拼接格式建议：

```text
用户: <userContent>
Luna短回复: <assistantContent>
关联长回答小总结: <short_summary>
```

这样压缩模型知道该轮有长回答，但不会被完整正文淹没。

### 12.1 避免污染短聊天上下文

Redis `Interaction.assistantContent` 不存完整长回答。

近期记忆面板只显示短回复。

上下文注入只显示短回复和小总结。

长回答正文只在按需打开面板时读取。

---

## 13. 最终短回复二次调用流程

### 13.1 二次调用必要性

长回答正文生成完成后，用户需要在聊天区域得到自然反馈。

该反馈应使用当前 chat prompt，保留 Luna 的亲密与情绪表达。

该反馈不能显示来源。

该反馈不能输出长篇正文。

### 13.2 二次调用输入

短回复 prompt 可输入：

1. 用户原始问题。
2. 长回答是否完成。
3. 长回答小总结。
4. 长回答标题。
5. 当前情绪变量。
6. 最近上下文。

但不能把完整长回答正文塞入短回复 prompt。

短回复可引导为：

```text
你刚刚已经在左侧面板整理完成一份长回答。
现在请用 Luna 的聊天语气，用一句到三句话自然告诉主人。
不要标明来源。
不要复述长回答正文。
```

### 13.3 持久化语义

最终短回复写入 [`InteractionModel.assistant_content`](backend/ai-service/app/repository/models.py:48)。

长回答表通过 `interaction_message_id` 关联该短回复。

如果短回复生成失败，仍应持久化一条兜底短回复，例如：

```text
我整理好了，主人可以看左边那份。
```

兜底短回复不应包含来源。

---

## 14. 事务边界与幂等策略

### 14.1 创建阶段

收到长回答请求后，先创建 `long_answers` 记录。

创建应以 `interaction_message_id` 作为幂等键。

如果同一个 `interaction_message_id` 已存在记录：

1. `COMPLETED`：直接返回已有记录并通知前端打开。
2. `GENERATING`：不要重复生成，只恢复订阅状态。
3. `FAILED`：允许用户显式 retry。

### 14.2 正文流式阶段

不建议每个 chunk 都 commit 到 PG。

建议每隔一定字符数或间隔写一次草稿。

例如：

1. 每 1000 字更新一次 `content_markdown`。
2. 每 2 秒更新一次 `content_markdown`。
3. 结束时强制最终写入。

这样兼顾恢复能力和数据库压力。

### 14.3 完成阶段事务

完成阶段建议一个事务内完成：

1. 更新 `content_markdown`。
2. 更新 `short_summary`。
3. 更新 `title`。
4. 更新 `status=COMPLETED`。
5. 更新 `completed_at`。

之后再写 Redis。

最后再进行短回复持久化并回填 `interaction_id`。

如果短回复持久化失败，不应回滚已完成的长回答正文。

### 14.4 失败恢复

如果服务在 `GENERATING` 状态崩溃，重启时扫描 `long_answers` 中超时未更新的 `GENERATING` 记录。

将其标为 `RECOVERABLE_FAILED`。

前端打开时显示“整理中断，可重试”。

用户点击重试后复用原始 `interaction_message_id` 或创建新版本需要产品确认。

建议初版直接覆盖原记录并增加 `retry_count`。

---

## 15. 并发控制与资源保护

长回答可能比短回答消耗更多 token 和时间。

必须增加并发控制。

建议单会话同时只允许一个长回答生成。

全局同时生成数量可设为 1 到 2。

可以使用 `asyncio.Semaphore` 控制。

Redis 可记录锁：

```text
luna:long_answer:lock:{session_id}
```

锁值为 `long_answer_id`。

锁需要设置合理过期，防止崩溃死锁。

如果同会话已有长回答生成中，新的长回答请求应排队或降级为短回复提示。

所有异步任务必须声明取消、回收、超时和降级策略，符合 [`agent.md`](agent.md:124)。

---

## 16. 数据库迁移建议

当前项目中未确认 Alembic 目录。

需要在实现前确认是否已有迁移工具。

如果无 Alembic，可沿用当前 `Base.metadata.create_all` 初始化模式，但长期建议补迁移脚本。

迁移步骤：

1. 新增 `LongAnswerModel`。
2. 新增 `long_answers` 表。
3. 新增索引。
4. 新增状态枚举常量。
5. 新增 repository。
6. 应用启动时确保表存在。

需要注意：不要修改 `interactions` 现有字段语义。

---

## 17. 与 RAG 证据和引用的关系

短回答不展示来源。

长回答可以展示来源。

引用信息不应放进短回复。

引用信息可以写入 `long_answers.meta_payload`。

例如：

```json
{
  "citations": [
    {"idx": 1, "doc_id": "...", "chunk_id": "...", "title": "..."}
  ]
}
```

正文中的引用标记可以为 `[1]`。

前端面板根据 `meta_payload.citations` 渲染引用区。

如果没有 RAG 证据，长回答仍可无引用。

---

## 18. 可观测性与审计

每次长回答生成必须记录：

1. 判定原因。
2. Prompt 分类。
3. 长回答 ID。
4. 关联 message ID。
5. 首块延迟。
6. 总耗时。
7. token 估算。
8. chunk 数量。
9. 状态迁移。
10. 错误信息。

日志必须使用 [`logger`](backend/ai-service/app/logger.py) 而不是 `print`。

注意：当前 [`chat_request()`](backend/ai-service/app/api/http_api.py:321) 存在 `print` 调试输出，后续实施长回答时应一并清理。

所有日志消息使用简体中文。

敏感内容不应完整打印。

---

## 19. 测试方案

### 19.1 单元测试

1. 长回答判定规则测试。
2. 长回答状态迁移测试。
3. Redis 小总结 key 构造测试。
4. Repository 创建、更新、查询测试。
5. Prompt 组装变量缺失测试。
6. 幂等重复请求测试。

### 19.2 集成测试

1. `/api/chat` 短回答仍走原链路。
2. 长回答请求创建 `long_answers` 记录。
3. 长回答流式 chunk 能通过 SSE 下发。
4. 完成后 Redis 存在小总结。
5. 完成后短回答气泡正常下发。
6. `interactions.assistant_content` 只包含短回复。
7. `long_answers.content_markdown` 包含完整正文。

### 19.3 失败测试

1. LLM 长回答中途失败。
2. 小总结生成失败。
3. Redis 写入失败。
4. PG 写入失败。
5. SSE 客户端断开。
6. 重复点击重试。
7. 服务重启后恢复未完成记录。

---

## 20. 实施 Roadmap

* [ ] **Step 1：定义常量与模型**
  - 新增长回答状态枚举。
  - 新增 SSE 事件常量。
  - 新增 `LongAnswerModel`。

* [ ] **Step 2：新增数据库表与 Repository**
  - 新建 `long_answers` 表。
  - 新增 `LongAnswerPGRepo`。
  - 增加按 `interaction_message_id` 查询方法。

* [ ] **Step 3：新增 Prompt 分类与模板**
  - 扩展 [`PromptCategory`](backend/ai-service/app/prompt/types.py:19)。
  - 新增 `long_answer` prompt 三槽位。
  - 设计 Markdown 输出规则。

* [ ] **Step 4：新增判定服务**
  - 基于 Input Reconstruction 和规则判断是否进入长回答。
  - 输出结构化判定结果。

* [ ] **Step 5：新增长回答生成服务**
  - 独立流式生成 Markdown。
  - 推送 `EVT_LONG_ANSWER_*` 事件。
  - 保存正文草稿和最终正文。

* [ ] **Step 6：新增小总结缓存服务**
  - 生成小总结。
  - 写入 PG 和 Redis。
  - 与压缩链路对接。

* [ ] **Step 7：接入最终短回复**
  - 长回答完成后调用 chat prompt。
  - 生成自然短回复。
  - 持久化 Interaction。

* [ ] **Step 8：历史查询接口**
  - 提供通过 message ID 查询长回答。
  - 支持前端点击图标打开历史长回答。

* [ ] **Step 9：测试与压测**
  - 补单元测试和端到端测试。
  - 验证短回答体验不受影响。

---

## 21. 架构原则符合性说明

该方案保持 Python 后端为唯一控制权威。

该方案不让 Electron 直接调度长回答生成。

该方案不让前端直接访问数据库或 Redis。

该方案不让长回答正文污染 `InteractionModel`。

该方案使用 Snowflake 作为所有新实体 ID。

该方案通过独立 SSE 事件保持跨层通信版本化。

该方案为长回答状态迁移提供显式日志。

该方案为失败场景提供恢复和重试入口。

该方案在短回答与长回答之间建立清晰职责边界。

该方案适合与 Phase 7 RAG 知识检索增强继续组合落地。
