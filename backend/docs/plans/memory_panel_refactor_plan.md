# 记忆面板后端重构设计方案

## 1. 目标
配合前端记忆面板的重构，提供底层数据接口支持。主要包括：获取 Redis 中积压的未压缩会话记录、执行单日会话的压缩入库操作，以及针对 PostgreSQL 中 `long_term_memories` 表的完整 CRUD（增删改查）业务接口。

## 2. 接口设计

为了保持业务逻辑的清晰，建议新增一个专门的路由模块 `backend/ai-service/app/api/memory_api.py`，并在 `main.py` 中注册该路由。

### 2.1 手动记忆相关接口

#### 2.1.1 获取未压缩会话列表
- **路由**: `GET /api/memory/uncompressed`
- **功能**: 扫描 Redis 中的历史会话，排除当天的记录，返回积压的未压缩会话 ID 列表及天数。
- **逻辑**:
  1. 调用 `redis_repo.get_all_session_ids()`。
  2. 获取当前日期 `today = datetime.now().strftime("%Y%m%d")`。
  3. 过滤掉等于 `today` 的 `session_id`。
  4. 返回过滤后的列表和总数。
- **响应**:
  ```json
  {
    "type": "RES_UNCOMPRESSED_SESSIONS",
    "trace_id": "...",
    "payload": {
      "count": 5,
      "session_ids": ["20231001", "20231002", ...]
    }
  }
  ```

#### 2.1.2 执行单日会话压缩
- **路由**: `POST /api/memory/compress`
- **功能**: 接收一个 `session_id`，调用底层的压缩逻辑将其转化为长期记忆并入库，随后清理 Redis 数据。
- **请求体**:
  ```json
  {
    "session_id": "20231001"
  }
  ```
- **逻辑**:
  1. 调用 `memory_manager._compress_and_commit(session_id)`。
  2. 压缩成功后，调用 `redis_repo.delete_session(session_id)` 清理缓存。
- **响应**: 成功或失败的状态信息。

### 2.2 长期记忆 CRUD 接口

#### 2.2.1 分页查询长期记忆 (Read)
- **路由**: `GET /api/memory/long_term`
- **参数**: `page` (默认 1), `page_size` (默认 20)
- **功能**: 从 PostgreSQL 的 `long_term_memories` 表中分页获取记录。
- **逻辑**: 在 `LongTermMemoryPGRepo` 中新增分页查询方法，按 `created_at` 倒序排列。

#### 2.2.2 新增长期记忆 (Create)
- **路由**: `POST /api/memory/long_term`
- **请求体**:
  ```json
  {
    "session_id": "20231001",
    "summary": "用户今天询问了关于..."
  }
  ```
- **逻辑**:
  1. 生成新的 `memory_id`。
  2. 存入 PostgreSQL。
  3. 调用推理服务获取 `summary` 的 Embedding 向量。
  4. 存入 Qdrant 向量库。

#### 2.2.3 修改长期记忆 (Update)
- **路由**: `PUT /api/memory/long_term/{id}`
- **请求体**:
  ```json
  {
    "summary": "修改后的记忆摘要内容..."
  }
  ```
- **逻辑**:
  1. 更新 PostgreSQL 中的 `summary` 和 `updated_at`。
  2. 重新计算新 `summary` 的 Embedding 向量。
  3. 更新 Qdrant 中的向量数据（调用 `qdrant_client.upsert`）。

#### 2.2.4 删除长期记忆 (Delete)
- **路由**: `DELETE /api/memory/long_term/{id}`
- **功能**: 删除指定的长期记忆。
- **逻辑**:
  1. 在 PostgreSQL 中执行软删除（更新 `status` 为 `DELETED`）或硬删除。
  2. 同步在 Qdrant 中删除对应的向量数据，保证双库一致性。

## 3. Repository 层改造需求

需要在 `backend/ai-service/app/repository/long_term_memory_pg.py` 中补充以下方法：
1. `get_paginated(page: int, page_size: int)`: 返回分页数据和总条数。
2. `update_summary(id: str, new_summary: str)`: 更新指定 ID 的摘要。
3. `delete_hard(id: str)`: 如果业务需要彻底删除，提供硬删除方法。

需要在 `backend/ai-service/app/repository/long_term_memory_qdrant.py` 中补充：
1. `delete_vector(memory_id: str)`: 删除指定 ID 的向量。

## 4. 注意事项
- **并发控制**: 前端在调用 `/api/memory/compress` 时必须串行调用，后端接口本身不加锁，依赖前端的串行控制来避免大模型并发限流。
- **双写一致性**: CRUD 操作中的增、改、删都涉及 PG 和 Qdrant 两个数据库，必须确保两者的数据一致性，若 Qdrant 写入失败需记录 Error Log 并允许后续补偿。
