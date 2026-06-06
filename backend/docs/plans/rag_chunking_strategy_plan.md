# 长期记忆 RAG 细粒度切片与分组检索方案 (RAG Chunking & Collapsing Plan)

## 1. 目标与背景

**现状与问题：**
当前 Luna 系统的长期记忆存储机制中，会话级的长篇摘要（`long_summary`）在执行落盘时，是将包含"梗概"与多条"关键事实"的完整文本作为单一实体直接进行 Embedding 向量化，并全量存入 Qdrant 与 PostgreSQL 中。
这种粗粒度的 Chunking（切片）策略存在以下缺陷：
1. **语义模糊**：长文本包含太多不相关的事实，导致特定问题查询时，向量检索的精确度（Precision）下降。
2. **上下文污染**：单挑事实难以被高分命中，而大块文本容易淹没真正相关的局部事实。

**本方案目标：**
实施细粒度的记忆拆分策略。将大语言模型生成的 `long_summary` 拆分为独立的"梗概"片段与单条"关键事实"片段，分别进行向量化。同时，在检索端（Retriever）引入 **Qdrant 向量库原生的 Search Groups (Collapsing) 分组折叠策略**，解决同一条 PostgreSQL 记录的多个 Chunk 同时挤占 `Top-K` 检索名额的问题，从而兼顾高召回率与上下文连贯性。

---

## 2. 核心技术设计 (方案二：Qdrant 分组折叠)

本方案采用**父文档检索策略 (Parent Document Retriever)** 变体，并依托 Qdrant 原生能力进行检索名额治理。

### 2.1 写入链路 (Write Path) - 细粒度拆分
1. Python 层拦截到 `long_summarize` 的输出文本后，通过正则或字符串规则，按约定格式（`梗概：... 关键事实：1...;2...`）对其进行精确拆分。
2. 生成 1 个梗概 Chunk 和 $N$ 个关键事实 Chunk。
3. 对这 $N+1$ 个 Chunk 分别调用 Embedding 模型，生成对应的特征向量。
4. **统一归属**：所有的 Chunk 在写入 Qdrant 时，其 Payload 均绑定相同的 `memory_id` (指向同一个 PostgreSQL 实体)，但采用相互独立的 Qdrant Point ID。
5. PostgreSQL 层面保持不变，依然存储完整的长摘要，充当父文档。

### 2.2 检索链路 (Read Path) - 原生折叠去重
为了防止查询时命中的结果全是某一个 `memory_id` 旗下的不同事实，从而消耗光 `RETRIEVAL_TOP_K` 的配额：
1. 采用 Qdrant 客户端原生的 `search_groups` API。
2. 检索时按 Payload 中的 `memory_id` 字段进行分组（Group By）。
3. 设定每个分组中仅保留 1 个得分最高的 Chunk。
4. 返回 `LIMIT = K` 个独立的分组，即确保拿到 $K$ 条不重复的 PG `memory_id`。
5. 拿着去重后的 `memory_id` 列表，去 PostgreSQL 拉取完整的历史记忆文本供给 LLM 推理。

---

## 3. 数据结构与接口协议

### 3.1 Qdrant 向量载荷 (Payload) Schema
原有的 Payload 可能仅存储业务 ID，现需要显式标明归属关系与 Chunk 属性。

```json
{
  "memory_id": "string, 对应的 PostgreSQL long_term_memories 表的主键ID",
  "session_id": "string, 所属会话ID",
  "chunk_type": "string, 枚举值: 'SUMMARY' | 'FACT'",
  "content": "string, 切片的原文内容"
}
```

*约束：* `Qdrant Point ID` 必须使用项目的 Snowflake 算法单独生成，或者使用 `${memory_id}_${chunk_index}` 形式确保全局唯一，**禁止使用 UUID**。

### 3.2 长期记忆切片解析器 (Chunker)
在  `app/rag/chunker.py` 内部引入解析方法：

```python
from pydantic import BaseModel
from typing import List, Literal

class MemoryChunk(BaseModel):
    chunk_type: Literal["SUMMARY", "FACT"]
    content: str
    
def parse_long_summary_to_chunks(full_summary: str) -> List[MemoryChunk]:
    """
    做什么：将大模型按 prompt_template 输出的结构化长摘要拆分为独立的语义块。
    输入：符合 '梗概：... \\n 关键事实：1.xxx;2.xxx' 格式的字符串。
    异常行为：若格式不合规或未找到特征符，降级为将 full_summary 作为一个单独的 SUMMARY Chunk 返回。
    """
    # 具体正则与字符串 split 实现...
```

---

## 4. 关键流程改造指导

### 4.1 修改向量持久化逻辑 (Repository)
修改 `backend/ai-service/app/repository/long_term_memory_qdrant.py`：

```python
async def save_chunks_with_vectors(
    self, 
    memory_id: str, 
    session_id: str, 
    chunks: List[MemoryChunk], 
    vectors: List[List[float]],
    status: str
) -> None:
    """
    做什么：批量将拆分后的 Chunk 及其向量存入 Qdrant。
    """
    # 遍历 chunks 和 vectors，为每个 chunk 构造唯一的 point_id
    # 将 memory_id 和 chunk_type 注入 payload
    # 调用 self.client.upsert() 进行批量存储
```

### 4.2 修改向量检索逻辑 (Hybrid Retriever)
修改 `backend/ai-service/app/rag/hybrid_retriever.py`：

```python
async def _search_qdrant_groups(self, query_vector: List[float], top_k: int) -> List[str]:
    """
    做什么：利用 Qdrant search_groups 获取去重后的 memory_id 列表。
    """
    results = await self.client.search_groups(
        collection_name=QDRANT_COLLECTION_LONG_TERM_MEMORIES,
        query_vector=query_vector,
        group_by="memory_id",
        limit=top_k,
        group_size=1,  # 确保每个 PG 记录只贡献最高分的一个 Chunk
        with_payload=True
    )
    # 解析出 memory_id 并返回
    return [group.id for group in results.groups]
```

---

## 5. 编码规范与纪律约束 (参照 AGENT.md)

1. **唯一标识符**：所有的 ID 生成（如每个 Point 的 UUID 替代方案）强制调用 `app/utils/snowflake.py`，**严禁使用 `uuid.uuid4()`**。
2. **魔法字符串抽离**：Payload 中的键名（如 `"memory_id"`, `"chunk_type"`）以及枚举值必须统一定义在 `app/types/constants.py` 中。
3. **中文详细注释**：在拆分 `parse_long_summary_to_chunks` 方法及调用 Qdrant `search_groups` 接口处，强制按照要求书写"做什么 / 为什么 / 边界条件"的中文注释。
4. **安全与降级**：如果因为大模型幻觉导致未按模板返回带有分号`;`的关键事实格式，拆分正则必须提供 `try-except` 并在 `except` 块中捕获。降级策略为：将整个文本作为一个 Chunk 进行 Embedding，不要直接向上抛出异常导致图节点中断。
5. **日志可观测性**：拆分完成后，应当通过 `logger.info` 记录 `[TraceID:xxx] 记忆拆分完成 memory_id=xxx, chunks_count=N`。

---

## 6. 实施路径 (Implementation Phases)

*   **Step 1**：在 `app/types/constants.py` 增加 Chunk 相关的枚举定义。
*   **Step 2**：在 `app/rag` 模块下实现并单测 `MemoryChunker`，确保其能鲁棒地解析 `runtime.j2` 定义的梗概与关键事实格式。
*   **Step 3**：调整 `LongTermMemoryQdrantRepository` 的 `save` 接口，支持接受 `List[MemoryChunk]` 及多向量写入。
*   **Step 4**：修改 `HybridRetriever`，全面切入 `qdrant_client.search_groups` API 代替原有的普通 `search` API。
*   **Step 5**：整合到 `app/memory/manager.py`，将原本获取单条向量的逻辑改为调用批量 embedding 服务并调用新版存储接口。
*   **Step 6**：编写/执行单元测试，验证相同的会话记忆不会在检索结果中重复出现，并且查回的 `memory_id` 确实命中最高相关度的短事实。