"""
Luna AI 推理服务模块

做什么：抽象 Embedding 和 Rerank 等模型推理能力，使其与具体业务逻辑解耦。
为什么这样做：便于在项目的其他模块（如知识库检索、意图识别等）中复用这些基础能力。
"""

import asyncio
import os
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from typing import Any, Dict, List

from app.logger import logger

# ============================================================================
# 并发调度改造 (维度一)：使用进程池隔离 CPU 密集型计算
# 做什么：预先分配独立的线程池/进程池，避免每次请求临时创建引发的开销
# 为什么这样做：SentenceTransformer 等原生 PyTorch 模型推理会严重阻塞 asyncio
# 事件循环。隔离后，即使单次推理长达 500ms，FastAPI 仍能继续处理 WebSocket 和 SSE
# ============================================================================

# 注意: Windows 上使用 ProcessPoolExecutor 可能在处理 PyTorch 模型 Pickling 时遇到问题，
# 为稳妥起见，我们优先使用 ThreadPoolExecutor 搭配底层 OMP_NUM_THREADS 限制来释放主线程。
# 如确认环境支持并且完全隔离，可以改用 ProcessPoolExecutor
_pool_workers = max(1, os.cpu_count() // 2 - 1)
_executor_pool = ThreadPoolExecutor(max_workers=_pool_workers)

def _cpu_bound_embedding(text: str) -> List[float]:
    """隔离在池中执行的纯计算函数"""
    from app.main import embedding_manager
    model = embedding_manager.get_model()
    if model is None:
        raise RuntimeError("Embedding 模型未就绪或未配置")
    
    # 兼容 SentenceTransformer 的 encode 或 Optimum ONNX 的特征提取
    if hasattr(model, 'encode'):
        return model.encode(text).tolist()
    else:
        # TODO: 预留 ONNX 转换后的调用逻辑 (Optimum Pipeline 等)
        pass
    raise NotImplementedError("目前仅支持 SentenceTransformer 模型格式")

def _cpu_bound_rerank(query: str, documents: List[str]) -> List[float]:
    """隔离在池中执行的纯计算函数"""
    from app.main import rerank_manager
    model = rerank_manager.get_model()
    if model is None:
        raise RuntimeError("Rerank 模型未就绪或未配置")
        
    pairs = [[query, d] for d in documents]
    if hasattr(model, 'predict'):
        return model.predict(pairs).tolist()
    else:
        # TODO: 预留 ONNX 转换后的调用逻辑
        pass
    raise NotImplementedError("目前仅支持 CrossEncoder 模型格式")


class InferenceService:
    """通用的推理服务接口实现（异步非阻塞池化版）"""

    def __init__(self):
        pass

    async def get_embedding_vector(self, text: str) -> List[float]:
        """
        获取文本的语义向量
        做什么：将文本编码为稠密向量，并保证不阻塞事件循环
        """
        if not text:
            raise ValueError("需要向量化的文本不能为空")

        loop = asyncio.get_running_loop()
        try:
            # 将阻塞调用推入执行池，彻底释放 FastAPI 主线程
            vec = await loop.run_in_executor(_executor_pool, _cpu_bound_embedding, text)
            logger.info(f"Embedding 向量化完成, text_length={len(text)}, vector_dim={len(vec)}")
            return vec
        except Exception as e:
            logger.exception("Embedding 向量化失败")
            raise RuntimeError(f"Embedding 调用失败: {e}")

    async def rerank_documents(self, query: str, documents: List[str]) -> List[Dict[str, Any]]:
        """
        对候选文档进行相关性重排
        做什么：计算查询与候选文档的相关性分数，并保证不阻塞事件循环
        返回：包含 'index' 和 'score' 的字典列表
        """
        if not query:
            raise ValueError("查询文本不能为空")

        if not documents:
            return []

        loop = asyncio.get_running_loop()
        try:
            scores = await loop.run_in_executor(_executor_pool, _cpu_bound_rerank, query, documents)
            
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
