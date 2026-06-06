"""
Luna AI RAG（检索增强生成）模块

做什么：提供混合检索 RAG 的核心组件，包括 PG FTS 稀疏检索器和混合检索编排器。
         向量稠密检索（Qdrant）由 repository/long_term_memory_qdrant.py 提供底层能力，
         BM25 风格稀疏检索由本模块中的 PGTextSearch 封装 PostgreSQL tsvector/ts_rank 实现。
         混合检索编排器（HybridRetriever）协调多路召回、去重、Rerank 重排与格式化。
为什么这样做：遵循单一职责原则，将 RAG 检索逻辑从记忆管理器（manager.py）中解耦，
             使系统各层职责清晰：manager 负责记忆生命周期，rag/ 模块负责检索策略。
"""
