"""
Luna AI 推理服务模块

做什么：抽象 Embedding 和 Rerank 等模型推理能力，使其与具体业务逻辑解耦。
为什么这样做：便于在项目的其他模块（如知识库检索、意图识别等）中复用这些基础能力。
"""

import json
from typing import Any, Dict, List

from app.logger import logger


class InferenceService:
    """通用的推理服务接口实现"""

    def __init__(self):
        pass

    async def get_embedding_vector(self, text: str) -> List[float]:
        """
        获取文本的语义向量
        做什么：将文本编码为稠密向量
        """
        if not text:
            raise ValueError("需要向量化的文本不能为空")

        from app.main import _embedding_model
        if _embedding_model is None:
            raise RuntimeError("Embedding 模型未加载，无法处理向量化请求")

        try:
            # 使用 SentenceTransformer 编码文本
            vec = _embedding_model.encode(text).tolist()
            logger.info(f"Embedding 向量化完成, text_length={len(text)}, vector_dim={len(vec)}")
            return vec
        except Exception as e:
            logger.exception("Embedding 向量化失败")
            raise RuntimeError(f"Embedding 调用失败: {e}")

    async def rerank_documents(self, query: str, documents: List[str]) -> List[Dict[str, Any]]:
        """
        对候选文档进行相关性重排
        做什么：计算查询与候选文档的相关性分数，并按分数降序排列
        返回：包含 'index' 和 'score' 的字典列表
        """
        if not query:
            raise ValueError("查询文本不能为空")

        if not documents:
            return []

        from app.main import _rerank_model
        if _rerank_model is None:
            raise RuntimeError("Rerank 模型未加载，无法处理重排请求")

        try:
            # 构造 (query, doc) 对并预测分数
            pairs = [[query, d] for d in documents]
            scores = _rerank_model.predict(pairs).tolist()
            
            if len(scores) != len(documents):
                raise RuntimeError(f"Rerank 返回分数数量不匹配: 期望 {len(documents)}, 实际 {len(scores)}")

            # 构造结果
            results = [
                {"index": i, "score": score}
                for i, score in enumerate(scores)
            ]

            # 按分数降序排序
            results.sort(key=lambda x: x["score"], reverse=True)

            logger.info(f"Rerank 重排完成 文档数={len(documents)} 最高分={results[0]['score'] if results else 0}")
            return results
        except Exception as e:
            logger.exception("Rerank 重排失败")
            raise RuntimeError(f"Rerank 调用失败: {e}")
