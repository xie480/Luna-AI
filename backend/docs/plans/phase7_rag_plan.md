# Phase 6 到 Phase 7 过渡：混合检索 RAG 机制与长期记忆注入规划

## 1. 架构演进背景
根据 `agent.md` 的规范，系统正从 Phase 6（长期记忆写入与恢复）向 Phase 7（RAG 知识检索增强）过渡。Phase 7 的核心目标是让系统能够基于外部知识（长期记忆）回答问题，并且答案能引用检索结果，低相关结果不会污染最终回答。
为此，本阶段将引入**向量检索与 PostgreSQL FTS 全文检索结合的混合检索方案**，并通过 Rerank 模型进行重排，最终将高价值的长期记忆严格格式化后注入到 Chat Prompt 中。

## 2. 模块划分与职责边界
为避免职责混淆，RAG 检索能力被拆分为独立的模块，与记忆管理器（`manager.py`）解耦：

### 2.1 模块文件清单
| 文件 | 职责 | 关键类/函数 |
|------|------|-------------|
| `app/rag/__init__.py` | RAG 模块入口 | - |
| `app/rag/bm25_retriever.py` | PG FTS 稀疏检索器（封装 PostgreSQL tsvector/ts_rank） | `PGTextSearch` 类 |
| `app/rag/hybrid_retriever.py` | 混合检索编排器：协调 PG FTS + 向量检索 + Rerank 全流程 | `HybridRetriever` 类 |

### 2.2 职责边界
- **`rag/bm25_retriever.py`**：封装 `LongTermMemoryPGRepo.search_by_text()`，对外提供 `PGTextSearch.search(query_text, top_k)` 接口。底层使用 PostgreSQL 的 `to_tsvector('simple', summary) @@ plainto_tsquery('simple', :query)` 进行 BM25 风格文本检索。
- **`rag/hybrid_retriever.py`**：编排检索全流程，依赖 `PGTextSearch` 做 FTS，依赖 `LongTermMemoryPGRepo`/`LongTermMemoryQdrantRepo` 做数据源，依赖 `InferenceService` 做 Embedding 和 Rerank。
- **`memory/manager.py`**：记忆生命周期管理（压缩、提交、会话流转），检索工作直接委托 `HybridRetriever`，不再包含任何检索逻辑。
- **`repository/long_term_memory_pg.py`**：在仓库层实现 `search_by_text()` 原始 SQL 调用 PG FTS，以及 `create_fts_index()` 创建 GIN 索引。

### 2.3 数据流
```
http_api.py (RAG 触发)
    │
    └─ memory_manager.retrieve_and_format_memories()
        │
        └─ HybridRetriever.retrieve_and_format()    ← app/rag/hybrid_retriever.py
            │
            ├─ _vector_retrieve()   # Qdrant 向量检索
            │       │
            │       └─ ltm_qdrant_repo.search_by_vector()
            │                └─ PG: get_by_ids(memory_ids)
            │
            ├─ _fts_retrieve()      # PG FTS 稀疏检索（BM25 变体）
            │       │
            │       └─ PGTextSearch.search()
            │                └─ ltm_pg_repo.search_by_text()    ← SQL: tsvector @@ tsquery
            │                         └─ ts_rank() 排序 → LIMIT RETRIEVAL_TOP_K
            │
            ├─ 合并去重 (按 memory_id)
            │
            └─ _rerank_and_truncate()   # CrossEncoder 重排 → 截断 rerank_top_k 条
```

## 3. 环境变量与配置变更
为了精确控制注入到 Prompt 中的记忆数量，避免上下文污染，新增重排截断配置：
- **`.env` 文件**：新增 `RERANK_TOP_K` 配置项（例如 `RERANK_TOP_K=3`）。
- **`settings.py`**：在 `Settings` 类中新增 `rerank_top_k: int = 3`，并从环境变量读取。
- **`main.py`**：创建 `MemoryManager` 时传入 `settings.rerank_top_k`。
- **现有配置**：保留 `RETRIEVAL_TOP_K` 作为初步召回的数量上限（例如 `RETRIEVAL_TOP_K=20`）。

## 4. 混合检索 RAG 机制设计
在 `backend/ai-service/app/rag/hybrid_retriever.py` 中编排混合检索全流程，两路召回互不阻塞：

### 4.1 向量稠密检索 (Dense Retrieval)
- **数据源**：Qdrant 向量库 + PostgreSQL 回查完整记录
- **算子**：`lm_qdrant_repo.search_by_vector()`，余弦相似度
- **候选数**：`RETRIEVAL_TOP_K × 3`（上限 50），为 Rerank 提供充足候选

### 4.2 PG FTS 稀疏检索 (BM25 风格 / PostgreSQL tsvector)
- **数据源**：PostgreSQL `long_term_memories` 表的 summary 字段
- **算子**：`to_tsvector('simple', summary) @@ plainto_tsquery('simple', :query)`
  - `simple` 配置将所有汉字作为独立 token（与中文单字粒度分词一致）
  - `ts_rank()` 排名函数基于 BM25 变体算法
  - 配合 GIN 索引（`idx_ltm_summary_fts`）实现高效检索
- **索引策略**：无需内存缓存，写入即检；首次部署时调用 `create_fts_index()` 创建 GIN 索引
- **候选数**：`RETRIEVAL_TOP_K`
- **为什么选择 PG FTS**：相比内存 BM25，PG FTS 具有以下优势：
  - 写入即检，无需手动失效缓存
  - 支持更大规模数据（GIN 索引优化）
  - 数据库原生，无额外依赖
  - `ts_rank` 实现基于标准 BM25 变体

### 4.3 合并去重
- 两路召回结果按 `memory.id` 去重合并，确保同一条记忆不会被重复计入

### 4.4 Rerank 重排与严格截断
- **CrossEncoder 重排**：使用 `InferenceService.rerank_documents()` 对所有候选记忆进行交叉打分
- **严格截断**：按得分降序排列，取前 `RERANK_TOP_K` 条
- **降级策略**：
  - Rerank 服务不可用 → 按原始顺序截断 `RERANK_TOP_K` 条
  - 一路召回失败 → 使用剩余可用路的结果
  - 两路都失败 → 返回空

## 5. Prompt 模板与注入格式 (`memory.j2`)

### 5.1 模板占位符
`backend/ai-service/app/prompt/simple/chat/memory.j2` 中已有 `{{LONG_TERM_MEMORY}}` 占位符。

### 5.2 格式化规范
每条记忆严格采用以下格式（便于 LLM 解析时间语义）：
```
date: 2025-12-01
content: 用户昨晚提到喜欢吃火锅，偏好麻辣口味。

date: 2025-11-28
content: 用户今天心情不太好，因为工作项目延期了。
```

### 5.3 注入时机（`http_api.py`）
在 `chat_request` 函数中，RAG 检索插入在 InputReconstructor 消歧之后、Chat Prompt 组装之前：

```
步骤 1-4: 加载上下文 → 组装 InputRecon Prompt → 调用 InputReconstructor
步骤 5:   【新增】混合检索 RAG → 注入 prompt_variables["LONG_TERM_MEMORY"]
步骤 6:   组装完整 Chat Prompt（包含 LONG_TERM_MEMORY 变量）
步骤 7:   后台流式调用 LLM
```

## 6. 核心代码变更汇总

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| `.env` | 修改 | 新增 `RERANK_TOP_K=3` |
| `backend/ai-service/app/config/settings.py` | 修改 | `Settings` 类新增 `rerank_top_k: int = 3` |
| `backend/ai-service/app/main.py` | 修改 | 实例化 `MemoryManager` 时传入 `settings.rerank_top_k` |
| `backend/ai-service/app/repository/long_term_memory_pg.py` | 修改 | 新增 `search_by_text()`（PG FTS）、`create_fts_index()`（GIN 索引） |
| `backend/ai-service/app/rag/__init__.py` | **新建** | RAG 模块入口 |
| `backend/ai-service/app/rag/bm25_retriever.py` | **新建** | PG FTS 检索器封装（`PGTextSearch`），代理调用 `search_by_text()` |
| `backend/ai-service/app/rag/hybrid_retriever.py` | **新建** | 混合检索编排器（PG FTS + 向量 + Rerank） |
| `backend/ai-service/app/memory/manager.py` | 重构 | 移除内联 BM25 和检索逻辑，委托给 `HybridRetriever`；删除 `invalidate_bm25_index()` |
| `backend/ai-service/app/api/http_api.py` | 修改 | 在步骤 5 插入 RAG 检索和 Prompt 变量注入 |
| `backend/ai-service/app/prompt/simple/chat/memory.j2` | 无变动 | `{{LONG_TERM_MEMORY}}` 占位符已存在 |

## 7. 架构演进示意

```
Phase 6 (写入能力)                            Phase 7 (检索能力)
┌─────────────────────┐                      ┌─────────────────────────────┐
│  MemoryManager      │                      │  MemoryManager              │
│                     │  (refactor)          │  - 压缩/提交/会话流转    ←──┼── 保持不变
│  - 压缩/提交/会话流转│  ──────────→        │  - 检索: 委托 HybridRetriever│
│  - 内联 BM25 逻辑  │                      └──────────┬──────────────────┘
│  - 内联检索逻辑    │                                 │ 委托
└─────────────────────┘                                 ▼
                                               ┌─────────────────────────────┐
                                               │  rag/ 模块 (新增)            │
                                               │                             │
                                               │  ┌───────────────────────┐  │
                                               │  │ PGTextSearch          │  │
                                               │  │ (PG tsvector/ts_rank) │  │
                                               │  └───────────┬───────────┘  │
                                               │              │ 委托          │
                                               │              ▼              │
                                               │  ┌───────────────────────┐  │
                                               │  │ ltm_pg_repo          │  │
                                               │  │ .search_by_text()    │  │
                                               │  │ → to_tsvector @@     │  │
                                               │  │   plainto_tsquery    │  │
                                               │  │ → ts_rank ORDER BY   │  │
                                               │  └───────────────────────┘  │
                                               │                             │
                                               │  ┌───────────────────────┐  │
                                               │  │ HybridRetriever       │  │
                                               │  │ (编排器: FTS+向量+    │  │
                                               │  │  Rerank重排)          │  │
                                               │  └───────────────────────┘  │
                                               └─────────────────────────────┘
```

## 8. 首次部署注意事项
1. 启动系统前需调用 `ltm_pg_repo.create_fts_index()` 创建 GIN 索引 `idx_ltm_summary_fts`
2. 该索引创建为幂等操作（`IF NOT EXISTS`），可在 `main.py` 的应用启动生命周期中调用一次
3. PG FTS 对中文使用 `simple` 配置（单字符粒度），如需更精确的中文分词可调整 PG 的文本搜索配置
