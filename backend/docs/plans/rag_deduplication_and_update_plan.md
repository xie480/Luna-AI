# 知识库 RAG 文档防重与平滑更新技术方案

## 1. 设计概述

在本地优先的知识库 RAG (Phase 7) 系统中，文档的重复摄入会导致向量空间冗余、检索干扰及存储浪费；而在文档内容发生变更时，如何在不中断用户检索服务的前提下完成底层切片与向量的更新，是保障系统高可用与数据一致性的关键。

本文档基于当前 Python 控制面架构（FastAPI + PostgreSQL + Qdrant + Redis），详细定义**文档重复插入拦截**与**文档平滑更新（Blue-Green Update）**的闭环处理机制。

---

## 2. 核心模块一：文档多级防重与拦截策略

防重机制在文档上传与摄入任务（Ingestion Task）初始化阶段触发，采用从轻到重的三级校验策略，尽早拦截冗余请求。

### 2.1 三级防重校验机制

#### **L1 强一致性校验：物理文件级 Hash 计算**
- **策略**：在前端上传文件或后端下载 URL 资源后，基于文件二进制内容流式计算 `SHA-256` 哈希值。
- **实现**：在 PostgreSQL 的 `rag_documents` 表中增加 `file_hash (VARCHAR(64))` 字段，并建立索引。
- **校验逻辑**：摄入前，根据 `file_hash` 查询数据库。若存在状态为 `ACTIVE` 或 `INGESTING` 且 Hash 完全一致的文档，直接命中 L1 拦截。

#### **L2 语义属性校验：元数据比对**
- **策略**：针对某些文件 Hash 改变但核心内容未变（如仅修改了创建时间或文件名的文件），结合元数据进行辅助判定。
- **比对维度**：`source_type` (如 URL, PDF, TXT) + `filename` + `file_size`。
- **校验逻辑**：若 Hash 不同，但文件名相同且大小差异在一定阈值（如 < 1%）内，标记为高疑似重复，需进入 L3 校验或提示用户确认。

#### **L3 语义特征校验：向量局部探针 (可选/兜底)**
- **策略**：针对纯文本复制粘贴导致的重复。在文档切片（Chunking）后，抽取前部 2-3 个核心切片进行 Embedding 计算。
- **校验逻辑**：将探针切片的向量在 Qdrant 中通过 `Top-1` 检索，若命中现有知识库且余弦相似度极高（如 `score > 0.99`），且归属于同一来源类型的文档，则触发 L3 拦截。

### 2.2 异常拦截与业务流转处理

当触发防重拦截时，系统必须优雅地终止摄入流程，避免产生脏数据，并向前端返回结构化错误。

1. **同步拦截 (API 阶段)**:
   - 若在 HTTP 请求接收阶段（如本地文件上传完毕）即可计算 Hash 并命中 L1，立即拒绝任务。
   - 返回 `HTTP 409 Conflict`，响应结构示例：
     ```json
     {
       "code": "DOCUMENT_ALREADY_EXISTS",
       "message": "该文档已存在于知识库中",
       "data": { "existing_doc_id": "1234567890", "filename": "example.pdf" }
     }
     ```

2. **异步拦截 (Worker 阶段)**:
   - 若在后台摄入 Worker 中发现重复（例如远端 URL 下载后才能拿到内容 Hash），则将当前 `RagIngestionTask` 的状态置为 `FAILED`，并记录 `error_log` 为 `DUPLICATE_DOCUMENT_INTERCEPTED`。
   - 通过 SSE 或 WebSocket 推送事件 `EVT_RAG_INGESTION_FAILED` 通知前端阻断 UI 上的加载状态。

---

## 3. 核心模块二：文档平滑更新策略 (平滑替换与垃圾回收)

文档更新不能采用"先删后插"的粗暴模式，否则在处理长篇巨著期间（耗时可能达数十秒甚至分钟级），知识库该部分的检索将完全瘫痪（即处于不可用真空期），且一旦更新流程异常崩溃会导致数据永久丢失。

### 3.1 核心思想：版本化双写（Blue-Green Update）

采用**文档版本并行**策略。原文档保持在线服务，新版本内容在后台独立进行摄入流程，待全部切片入库且双端（PG/Qdrant）就绪后，通过数据库事务执行原子状态翻转。

### 3.2 闭环处理链路设计

#### **步骤 1：触发更新与新版本准备 (Prepare)**
- 用户发起文档更新请求，指定目标的 `original_doc_id`。
- 系统基于雪花算法生成一个全新的 `new_doc_id`。
- 在 PostgreSQL 的 `rag_documents` 表中插入新记录，并记录来源：
  - `id`: `new_doc_id`
  - `status`: `UPDATING` (或 `INGESTING`)
  - `previous_version_id`: `original_doc_id`

#### **步骤 2：切片与向量化入库 (Process)**
- 使用 `chunker.py` 将新文档切片，每个 `ChunkUnit` 绑定的都是新的 `new_doc_id`。
- 将切片文本与元数据写入 PostgreSQL (`rag_chunks` 表)。
- 结合 Embedding 引擎生成向量，并写入 Qdrant (`luna_rag_index` 集合)，关联 payload: `{"chunk_id": "...", "doc_id": "<new_doc_id>"}`。
- **高可用保障**：在此摄入期间，查询接口（`RagSearchRequest`）依旧通过正常过滤 `status = 'ACTIVE'` 命中 `original_doc_id` 的旧切片数据，检索服务保持完全可用。

#### **步骤 3：状态原子切换 (Commit)**
- 在确认新文档全部写入完毕后，于 PostgreSQL 中执行原子级的本地事务：
  ```sql
  BEGIN;
  -- 新文档正式上线对外暴露
  UPDATE rag_documents SET status = 'ACTIVE' WHERE id = '<new_doc_id>';
  -- 老文档正式下线隐藏
  UPDATE rag_documents SET status = 'DEPRECATED' WHERE id = '<original_doc_id>';
  COMMIT;
  ```
- **数据一致性保障**：由于状态在 PG 中是原子翻转的，下一次查询请求到来时，通过过滤 `status = 'ACTIVE'` 会立刻无缝切换到新版本。Qdrant 检索回表时，业务层也可过滤掉属于 `DEPRECATED` 状态 doc_id 的向量命中，由此从逻辑侧根绝脏数据。

#### **步骤 4：安全清理机制 (Garbage Collection & 回滚)**
- **成功更新后的清理 (GC)**：
  系统投递内部异步事件 `EVT_RAG_DOC_DEPRECATED`，触发 GC Worker：
  1. 调用 `RagQdrantRepository.delete_chunks(old_chunk_ids)` 删除 Qdrant 中关联 `original_doc_id` 的旧向量数据。
  2. 从 PG 中硬删除 `original_doc_id` 及对应的旧文本记录。
- **更新失败时的回滚机制**：
  若在"步骤 2"中出现切片失败或向量服务断联崩溃，系统捕获异常并执行：
  1. 将 `new_doc_id` 在 PG 中的状态置为 `FAILED`。
  2. 触发专门的回滚 Worker，清理 `new_doc_id` 已经注入 Qdrant 的部分废弃向量与 PG 中的临时 chunks。
  3. 原有的 `original_doc_id` 一直保持 `ACTIVE`，服务未发生任何降级或中断。

### 3.3 业务流转伪代码示例

```python
from app.utils.snowflake import generate_string_id
from app.types.constants import RagDocumentStatus

async def update_rag_document(original_doc_id: str, new_content: str, metadata: dict) -> str:
    """平滑更新文档闭环流程"""
    new_doc_id = generate_string_id()
    
    # 1. 准备阶段
    await pg_repo.create_document(
        doc_id=new_doc_id, 
        status=RagDocumentStatus.INGESTING,
        previous_doc_id=original_doc_id
    )
    
    try:
        # 2. 切片与向量化 (耗时操作，期间不影响原文档查询)
        chunks = chunker.chunk(document_id=new_doc_id, text=new_content, metadata=metadata)
        vectors = await embedding_service.embed_chunks([c.text for c in chunks])
        
        # 写入双端存储 (PG存结构化正文 + Qdrant存向量及轻量映射)
        await pg_repo.save_chunks(chunks)
        await qdrant_repo.upsert_chunks(chunks, vectors)
        
        # 3. 状态原子切换 (Commit)
        async with pg_repo.transaction() as tx:
            await tx.update_doc_status(new_doc_id, RagDocumentStatus.ACTIVE)
            await tx.update_doc_status(original_doc_id, RagDocumentStatus.DEPRECATED)
            
        # 4. 触发异步垃圾回收，清理旧文档释放空间
        event_bus.publish(RagDocumentDeprecatedEvent(doc_id=original_doc_id))
        
        return new_doc_id
        
    except Exception as e:
        # 失败回滚机制
        logger.error(f"文档更新失败，执行局部回滚 doc_id={new_doc_id}, error={e}")
        await pg_repo.update_doc_status(new_doc_id, RagDocumentStatus.FAILED)
        event_bus.publish(RagIngestionFailedEvent(doc_id=new_doc_id))
        raise
```

### 3.4 进阶：巨型文档的切片级增量更新 (Chunk-Level Incremental Update)

旧文档拥有数百乃至上千 Chunk，但新版本仅修改了少量内容（如修正几个错别字或增删几个段落）。如果仍执行全量切片和全量 Embedding 计算，其成本与时间消耗几乎等同于重新摄入一份新文档，性价比极低。

针对此场景，系统在"步骤 2：切片与向量化入库"引入**切片级增量比对与向量复用**机制，核心思想：仅在 Chunk 粒度做 Diff，未变更的 Chunk 在原地切换 `doc_id` 归属即可。

---

#### **3.4.1 数据结构基础：引入 Chunk Hash**

在 PostgreSQL 的 `rag_chunks` 表中增加 `chunk_hash (VARCHAR(64))` 字段：

```sql
ALTER TABLE rag_chunks ADD COLUMN chunk_hash VARCHAR(64) NOT NULL DEFAULT '';
CREATE INDEX idx_rag_chunks_doc_hash ON rag_chunks (document_id, chunk_hash);
```

**生成规则**：对每个 ChunkUnit 的拼接字符串 `text + metadata.summary`（如适用）做 `SHA-256` 计算，确保 Hash 值忠实反映该 Chunk 的内容语义。

**业务价值**：Chunk Hash 是增量比对的最小不可分原子（Hash 一致意味着该切片内容与旧版本完全相同，其 Embedding 向量无需重算）。

---

#### **3.4.2 增量比对逻辑 (Diffing)**

```text
输入: original_doc_id, new_document_text
输出: reused_chunks (旧向量直接复用) + new_chunks (需重新 Embedding)

步骤:
1. 使用 chunker.py 对新文档全文切片，生成 new_chunks 列表
2. 计算每个 new_chunk 的 chunk_hash
3. 查询 PG 获取 original_doc_id 的全部旧切片 Hash 集合:
   SELECT chunk_id, chunk_hash FROM rag_chunks WHERE document_id = '<original_doc_id>'
4. 遍历 new_chunks，判定每个 Chunk 的归属:
   - 若 chunk_hash 在旧 Hash 集合中存在:
     → 标记为 "unchanged" 切片
     → 找出对应 chunk_hash 的旧 chunk_id
     → 从 Qdrant 按 old_chunk_id retrieve 出已有向量
     → 直接复用，免去 Embedding 调用
   - 若 chunk_hash 在旧 Hash 集合中不存在:
     → 标记为 "changed/new" 切片
     → 加入 new_chunks 列表，等待统一调用 Embedding API
5. 将两部分合并后统一写入: reused_vectors + new_vectors → Qdrant (payload doc_id = new_doc_id)
```

**边界情况处理**：
- **旧文档 Chunk 数量 >> 新文档 Chunk 数量**（内容大幅精简）：未被任何 `new_chunk` 匹配的旧 Chunk 被视为"已删除"，待原子切换后由 GC 统一清理。
- **旧文档 Chunk 数量 << 新文档 Chunk 数量**（内容大幅扩充）：大量新 Chunk 会自动进入 `changed/new` 列表，按正常流程生成 Embedding。
- **Hash 碰撞防御**：`SHA-256` 碰撞概率极低，但在业务层依然加一层兜底——如果 Hash 匹配但 Chunk 数量分布出现严重异常（如旧文档 1000 Chunk，新文档 100 Chunk，但 Unchanged 标记了 990 个），触发全量 Fallback 回退到 3.2 的常规全量更新。

---

#### **3.4.3 向量复用的落地实现**

未变更 Chunk 的向量复用直接通过 Qdrant 的 `retrieve`（按 ID 批量拉取点）API 完成，无需重新经过 Embedding 模型：

```
从 Qdrant 批量拉取:
POST /collections/luna_rag_index/points
{ "ids": [old_chunk_id_1, old_chunk_id_2, ...] }

返回:
{
  "result": [
    { "id": old_chunk_id_1, "vector": [0.1, 0.2, ...], "payload": {...} },
    { "id": old_chunk_id_2, "vector": [0.3, 0.4, ...], "payload": {...} },
  ]
}
```

**组装伪代码**：

```python
async def process_chunk_diff(original_doc_id: str, new_doc_id: str, new_chunks: list[ChunkUnit]) -> None:
    """切片级增量更新主流程"""
    old_chunk_map = await pg_repo.get_chunk_hash_map(original_doc_id)
    reused_chunks: list[ChunkUnit] = []
    needs_embed_chunks: list[ChunkUnit] = []
    old_to_new_id_map: dict[str, str] = {}  # old_chunk_id → new_chunk_id

    for new_chunk in new_chunks:
        if new_chunk.chunk_hash in old_chunk_map:
            # 未变更：记录旧 chunk_id → 新 chunk_id 的映射关系
            old_chunk_id = old_chunk_map[new_chunk.chunk_hash]
            old_to_new_id_map[old_chunk_id] = new_chunk.chunk_id
            reused_chunks.append(new_chunk)
        else:
            # 变更/新增：需要重新 Embedding
            needs_embed_chunks.append(new_chunk)

    # Step A: 从 Qdrant 批量拉取旧向量（已缓存算力结果）
    old_chunk_ids = list(old_to_new_id_map.keys())
    old_vectors = await qdrant_repo.batch_retrieve_vectors(old_chunk_ids)

    # Step B: 为变更切片计算新向量
    new_vectors = await embedding_service.embed_chunks(
        [c.text for c in needs_embed_chunks]
    )

    # Step C: 转换旧向量为新 doc_id 关联 (payload 替换 doc_id)
    reused_points = []
    for old_cid, new_cid in old_to_new_id_map.items():
        vector = old_vectors[old_cid]
        reused_points.append(
            UpsertPoint(id=int(new_cid), vector=vector,
                        payload={"chunk_id": new_cid, "doc_id": new_doc_id})
        )

    # Step D: 新向量组装
    new_points = []
    for chunk, vec in zip(needs_embed_chunks, new_vectors):
        new_points.append(
            UpsertPoint(id=int(chunk.chunk_id), vector=vec,
                        payload={"chunk_id": chunk.chunk_id, "doc_id": new_doc_id})
        )

    # Step E: 一次性写入 PG 与 Qdrant
    await pg_repo.save_chunks(new_chunks)  # 所有 Chunk 的文本记录入库
    await qdrant_repo.bulk_upsert(reused_points + new_points)

    # Step F: 原子切换 (同 3.2 Step 3)
    # ...
```

---

#### **3.4.4 查询高可用保障**

增量更新期间，查询层的行为与全量更新完全一致：

- 旧版本文档 `original_doc_id` 状态保持 `ACTIVE`，检索请求（`RagSearchRequest`）命中旧切片的向量仍可正常回表提取正文。
- 新版本文档 `new_doc_id` 的状态未切到 `ACTIVE` 之前，其在 Qdrant 中存在的向量不会通过 Post-filtering 流入真实用户请求。
- 直至 `Step F` 原子切换完成，查询流量才会瞬间迁移至新版本，对用户完全透明。

---

#### **3.4.5 性能收益估算**

| 场景 | 全量更新耗时 (Embedding) | 增量更新耗时 (Embedding) | 节省比例 |
|:----|:------------------------:|:------------------------:|:--------:|
| 1000 Chunk 更改 10 个 Chunk | ~1000 次调用 | ~10 次调用 | 99% |
| 1000 Chunk 更改 200 个 Chunk | ~1000 次调用 | ~200 次调用 | 80% |
| 1000 Chunk 完全重写 | ~1000 次调用 | ~1000 次调用 | 0% (退化到全量) |

**注**：增量更新在极低变更率场景下收益极为显著，但完全重写场景自动退化为全量更新，不会产生额外开销。

---

### 3.5 版本选择策略（全量更新 vs 增量更新）

| 判定条件 | 推荐策略 | 依据 |
|:---------|:---------|:-----|
| 首次摄入 / 源文件 Hash 完全不存在 | 全量更新 | 无旧版本可 Diff |
| 旧 Chunk 数量 <= 50 | 全量更新 | Diff 开销不值得，直接全量更简单可靠 |
| 旧 Chunk 数量 > 50 且变更率 < 30% | 增量更新 | 高效避免冗余 Embedding 调用 |
| 旧 Chunk 数量 > 50 且变更率 >= 30% | 全量更新 | 大量 Chunk 被修改时，Diff 复杂度和全量接近 |
| 增量更新过程中检测到 Hash 分布异常 | 回退全量更新 | 防止脏标记影响数据一致性 |

---

## 4. 架构约束与工程准则

1. **全局唯一事实来源 (SSOT)**: 
   文档在线状态的最高权威必须收口在 PostgreSQL 的 `rag_documents` 表。由于 Qdrant 和 PG 是分布式双写，Qdrant 中可能暂时残留过期向量。因此从 Qdrant 检索出来的 `RagVectorHit` 在回表提取正文文本时，**务必在 Python 逻辑层增加后置校验 (Post-filtering)**，丢弃非 `ACTIVE` 状态的命中结果。
2. **Qdrant Payload 精简与解耦**: 
   Qdrant 的 Payload 设计极简化，仅允许存放 `chunk_id` 和 `doc_id` 的外键映射。严禁将大段正文和繁杂元数据注入 Qdrant Payload，以防止 GC 清理时产生沉重的内存回收开销，也避免了向量引擎变质为全能文档库。所有查询最终通过 Snowflake ID 统一。
3. **Snowflake ID 全覆盖**: 
   新旧文档 ID、新旧切片 ID 全部强制使用 `snowflake.py` 的算法生成 `VARCHAR(64)` 纯数字形态字符串。保证在双写或高频更新覆盖场景下数据绝对互斥、不可碰撞，杜绝 UUID 带来的索引体积膨胀和顺序写入低效问题。
