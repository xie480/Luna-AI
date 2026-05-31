# 聊天记录展示功能后端实施计划

## 1. 需求概述
本计划旨在为前端的聊天记录展示功能提供底层数据支持与 WebSocket 路由。核心要求是严格区分数据源：日历面板的日期高亮状态（元数据）必须从 Redis 获取以保证高性能；而具体的聊天记录详情必须从 PostgreSQL 获取以保证数据的完整性与持久化，绝对禁止从 Redis 获取详细记录。Go Runtime 作为唯一调度权威（SSOT），负责统筹这两种数据源的查询与下发。

## 2. 数据结构与存储设计

### 2.1 Redis 日历元数据存储
为了支持前端快速判断某个月份中有哪些天存在聊天记录，需要在 Redis 中维护一个轻量级的元数据映射。
- **Key 结构**: `luna:chat:meta:{agent_id}:{YYYY-MM}` (例如: `luna:chat:meta:123456:2026-05`)
- **数据类型**: `Set`。存储该月有记录的具体日期字符串（如 `"01"`, `"15"`）。
- **写入时机**: 每次有新的聊天记录落盘到 PostgreSQL 时，异步更新对应的 Redis 元数据 Key，将当天的日期加入 Set 中。
- **TTL (过期时间)**: 设置合理的过期时间（例如 30 天或 60 天），避免冷数据永久占用 Redis 内存。每次更新或访问时可选择性续期。
- **缓存重建策略 (Cache Miss)**: 当 Redis 中不存在该 Key（过期被删或 Redis 重启丢失）且前端发起查询请求时，Go Runtime 必须拦截该 Cache Miss 事件，主动向 PostgreSQL 发起聚合查询（例如 `SELECT DISTINCT TO_CHAR(created_at, 'DD') FROM chat_history WHERE agent_id = ? AND TO_CHAR(created_at, 'YYYY-MM') = ?`），将查询结果重新写入 Redis 并设置 TTL，最后再返回给前端。

### 2.2 PostgreSQL 详细聊天记录查询
现有的 `chat_history` 表（由 `chat_history_pg.go` 管理）已包含详细记录。
- **查询逻辑**: 根据前端传入的特定日期（如 `2026-05-15`），构建 SQL 查询，获取该日 `00:00:00` 至 `23:59:59` 的所有消息记录。
- **排序**: 按时间戳升序排列。

## 3. WebSocket 接口与协议设计

在 `backend/shared/schemas/` 或对应的常量定义中新增事件类型，并定义 JSON Schema。

### 3.1 日历元数据接口
- **Event**: `REQ_GET_CALENDAR_METADATA`
- **Payload**:
  ```json
  {
    "year_month": "2026-05"
  }
  ```
- **Response Event**: `RES_CALENDAR_METADATA`
- **Response Payload**:
  ```json
  {
    "year_month": "2026-05",
    "active_dates": ["2026-05-01", "2026-05-15", "2026-05-31"]
  }
  ```

### 3.2 详细聊天记录接口
- **Event**: `REQ_GET_CHAT_HISTORY`
- **Payload**:
  ```json
  {
    "date": "2026-05-15"
  }
  ```
- **Response Event**: `RES_CHAT_HISTORY`
- **Response Payload**:
  ```json
  {
    "date": "2026-05-15",
    "messages": [
      {
        "id": "712345678901234567", // 必须为 Snowflake ID
        "role": "user",
        "content": "你好",
        "created_at": "2026-05-15T10:00:00Z"
      },
      {
        "id": "712345678901234568",
        "role": "assistant",
        "content": "你好！今天过得怎么样？",
        "created_at": "2026-05-15T10:00:05Z"
      }
    ]
  }
  ```

## 4. 核心逻辑实现步骤

1. **Phase 1: Redis 元数据维护逻辑**
   - 修改现有的聊天记录落盘逻辑（`chat_history_pg.go` 或对应的 Worker）。
   - 在成功写入 PostgreSQL 后，增加一步 Redis 操作：将当前消息的日期（DD）加入到 `luna:chat:meta:{agent_id}:{YYYY-MM}` 的 Set 中。
   - 编写历史数据迁移脚本（可选）：扫描 PG 中现有的历史记录，重建 Redis 中的元数据，确保旧数据也能在日历上高亮。

2. **Phase 2: WebSocket 路由与 Handler 实现**
   - 在 `backend/runtime/internal/api/ws_server.go` 中注册新的事件路由。
   - 实现 `HandleGetCalendarMetadata`：
     - 解析请求中的 `year_month`。
     - 从 Redis 查询对应的 Set。
     - **缓存未命中处理**: 如果 Redis 返回空或 Key 不存在，触发缓存重建逻辑，从 PostgreSQL 聚合查询该月的活跃日期，回写 Redis 并设置 TTL。
     - 组装并返回 `RES_CALENDAR_METADATA`。
   - 实现 `HandleGetChatHistory`：
     - 解析请求中的 `date`。
     - 调用 `chat_history_pg.go` 中的方法，执行 `SELECT * FROM chat_history WHERE DATE(created_at) = ? ORDER BY created_at ASC`。
     - 组装并返回 `RES_CHAT_HISTORY`。

3. **Phase 3: 错误处理与可观测性**
   - 所有 WS 请求必须携带并透传 `TraceID`。
   - 记录详细的日志，例如：`[TraceID:xxx] Fetching chat history for date 2026-05-15 from PG`。
   - 如果 Redis 查询失败，应有降级策略（例如临时从 PG 聚合查询当月元数据，并回写 Redis）。

## 5. 规范约束检查
- **SSOT 原则**: Go 严格控制数据流向，作为唯一调度权威。
- **ID 规范**: 确保返回给前端的所有消息 ID 均为 Snowflake 算法生成的字符串，禁止使用 UUID。
- **日志规范**: 使用 `log.Logger`，日志信息必须为简体中文，包含必要的上下文（TraceID, TaskID 等）。
- **无 Emoji**: 文档与代码注释中严禁使用 Emoji。
- **数据源隔离**: 严格遵守日历状态查 Redis，详细记录查 PG 的原则。
