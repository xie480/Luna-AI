"""
Luna AI 推理服务模块

做什么：抽象 Embedding 和 Rerank 等模型推理能力，使其与具体业务逻辑解耦。
为什么这样做：便于在项目的其他模块（如知识库检索、意图识别等）中复用这些基础能力。
"""

import json
from typing import Any, Dict, List

from app.api import communication_pb2
from app.api.grpc_client import AIClient
from app.logger import logger


class InferenceService:
    """通用的推理服务接口实现"""

    def __init__(self, ai_client: AIClient):
        self.ai_client = ai_client

    async def get_embedding_vector(self, text: str) -> List[float]:
        """
        获取文本的语义向量
        做什么：调用 Python AI 服务的 Embedding 方法，将文本编码为稠密向量
        """
        if not self.ai_client:
            raise RuntimeError("AI 客户端不可用，无法获取向量")

        if not text:
            raise ValueError("需要向量化的文本不能为空")

        req = communication_pb2.EmbeddingRequest(text=text)

        try:
            resp = await self.ai_client.embedding(req)
        except Exception as e:
            raise RuntimeError(f"Embedding 调用失败: {e}")

        if not resp.success:
            raise RuntimeError(f"Embedding 返回错误: {resp.error_message}")

        try:
            vector = json.loads(resp.vector_json)
        except Exception as e:
            raise RuntimeError(f"解析向量 JSON 失败: {e}")

        if not vector:
            raise RuntimeError("Embedding 返回空向量")

        return vector

    async def rerank_documents(self, query: str, documents: List[str]) -> List[Dict[str, Any]]:
        """
        对候选文档进行相关性重排
        做什么：调用 Python AI 服务的 Rerank 方法，计算查询与候选文档的相关性分数，并按分数降序排列
        返回：包含 'index' 和 'score' 的字典列表
        """
        if not self.ai_client:
            raise RuntimeError("AI 客户端不可用，无法进行重排")

        if not query:
            raise ValueError("查询文本不能为空")

        if not documents:
            return []

        req = communication_pb2.RerankRequest(
            query=query,
            documents=documents
        )

        try:
            resp = await self.ai_client.rerank(req)
        except Exception as e:
            raise RuntimeError(f"Rerank 调用失败: {e}")

        if not resp.success:
            raise RuntimeError(f"Rerank 返回错误: {resp.error_message}")

        if len(resp.scores) != len(documents):
            raise RuntimeError(f"Rerank 返回分数数量不匹配: 期望 {len(documents)}, 实际 {len(resp.scores)}")

        # 构造结果
        results = [
            {"index": i, "score": score}
            for i, score in enumerate(resp.scores)
        ]

        # 按分数降序排序
        results.sort(key=lambda x: x["score"], reverse=True)

        logger.info(f"Rerank 重排完成 文档数={len(documents)} 最高分={results[0]['score'] if results else 0}")
        return results
