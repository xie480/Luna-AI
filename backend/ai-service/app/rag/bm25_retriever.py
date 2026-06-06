"""
Luna AI BM25 稀疏检索器模块（PostgreSQL FTS 实现）

做什么：基于 PostgreSQL 内建全文检索（FTS）的 tsvector/tsquery/ts_rank 机制，
        实现真正的 BM25 风格稀疏检索，替代原先的内存 BM25Okapi 实现。
为什么这样做：PostgreSQL 的 ts_rank 排名算法基于标准的 BM25 变体，
             配合 GIN 索引可处理更大规模的文本集。无需在内存中维护全量索引，
             写入即检，无需手动失效缓存。
输入输出：
    - PGTextSearch: PG FTS 检索器类
      - search(query_text, top_k) -> List[LongTermMemory]
异常行为：
    - PG 查询失败时降级返回空列表
"""

from typing import List, Optional

from app.logger import logger
from app.repository.long_term_memory_pg import LongTermMemoryPGRepo
from app.repository.models import LongTermMemory


class PGTextSearch:
    """
    PostgreSQL 全文检索器

    做什么：封装 LongTermMemoryPGRepo.search_by_text()，
            提供与旧版 BM25Okapi.search() 一致的接口签名。
    为什么这样做：统一检索接口，让 hybrid_retriever.py 的调用方式保持不变。
    """

    def __init__(self, ltm_pg_repo: Optional[LongTermMemoryPGRepo]):
        """
        初始化 PG 全文检索器

        :param ltm_pg_repo: 长期记忆 PG 仓库（必须实现 search_by_text 方法）
        """
        self.ltm_pg_repo = ltm_pg_repo

    async def search(self, query_text: str, top_k: int) -> List[LongTermMemory]:
        """
        执行 PostgreSQL FTS 检索

        做什么：将查询文本委托给 PG 仓库的 search_by_text() 方法，
                后者使用 to_tsvector('simple', summary) @@ plainto_tsquery('simple', :query)
                进行检索，并按 ts_rank 得分降序返回。
        返回：List[LongTermMemory]，按相关性得分降序排列。

        :param query_text: 用户查询文本
        :param top_k: 返回的 Top-K 结果数
        """
        if not query_text or not self.ltm_pg_repo:
            return []

        try:
            results = await self.ltm_pg_repo.search_by_text(query_text, top_k)
            return results
        except Exception as e:
            logger.warning(f"PG FTS 检索失败（降级返回空） query=\"{query_text[:50]}...\" error={e}")
            return []

    @property
    def is_available(self) -> bool:
        """检索器是否可用"""
        return self.ltm_pg_repo is not None
