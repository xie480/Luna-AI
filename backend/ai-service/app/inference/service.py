"""
Luna AI 推理服务模块

做什么：抽象 Embedding 和 Rerank 等模型推理能力，使其与具体业务逻辑解耦。
为什么这样做：便于在项目的其他模块（如知识库检索、意图识别等）中复用这些基础能力。
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List

from app.logger import logger

# ============================================================================
# 并发调度改造 (维度一)：使用线程池隔离模型推理，避免阻塞 asyncio 事件循环
# 做什么：预先分配独立的线程池，避免每次请求临时创建引发的开销。
# 为什么使用 ThreadPoolExecutor 而非 ProcessPoolExecutor：
#   1. ONNX Runtime 和 PyTorch CrossEncoder 在推理时会释放 GIL，
#      ThreadPoolExecutor 可以正确地并行执行而不阻塞事件循环。
#   2. ProcessPoolExecutor 的子进程需要重新 import app.main，
#      会触发 ModelManager 初始化、守护线程创建等副作用，
#      导致子进程状态不可预测，容易引发 BrokenProcessPool。
#   3. ThreadPoolExecutor 共享主进程的模型内存，避免每个子进程重复加载模型。
# 生命周期：由 FastAPI lifespan 创建，进程退出时自动回收。
# ============================================================================

_executor_pool = None

def _get_executor():
    """获取全局线程池执行器（懒初始化）。"""
    global _executor_pool
    if _executor_pool is None:
        import os
        workers = max(1, os.cpu_count() // 2 - 1) if os.cpu_count() else 1
        _executor_pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="inference")
    return _executor_pool


def _do_embedding(text: str) -> List[float]:
    """在线程池中执行的 Embedding 推理函数。

    做什么：从 embedding_manager 懒加载模型并执行向量化推理。
    为什么这样做：ThreadPoolExecutor 在主进程中执行，共享 ModelManager 实例，
                  无需跨进程传递模型对象，避免 ProcessPoolExecutor 的子进程初始化副作用。
    """
    from app.main import embedding_manager
    model = embedding_manager.get_model()
    if model is None:
        raise RuntimeError("Embedding 模型未就绪或未配置")

    # 兼容 SentenceTransformer 与 ONNXEmbeddingWrapper 的 encode 接口
    if hasattr(model, 'encode'):
        encoded = model.encode(text)
        return encoded.tolist() if hasattr(encoded, "tolist") else list(encoded)
    raise NotImplementedError("Embedding 模型必须提供 encode(text) 接口")


def _do_rerank(query: str, documents: List[str]) -> List[float]:
    """在线程池中执行的 Rerank 推理函数。

    做什么：从 rerank_manager 懒加载模型并执行重排推理。
    """
    from app.main import rerank_manager
    model = rerank_manager.get_model()
    if model is None:
        raise RuntimeError("Rerank 模型未就绪或未配置")

    pairs = [[query, d] for d in documents]
    if hasattr(model, 'predict'):
        predicted = model.predict(pairs)
        return predicted.tolist() if hasattr(predicted, "tolist") else list(predicted)
    raise NotImplementedError("Rerank 模型必须提供 predict(pairs) 接口")


class InferenceService:
    """通用的推理服务接口实现（异步非阻塞线程池版）"""

    def __init__(self):
        """
        初始化推理服务。

        做什么：声明推理服务实例生命周期。
        为什么这样做：Embedding 与 Rerank 推理会释放 GIL，使用 ThreadPoolExecutor
                      在不阻塞 asyncio 事件循环的前提下执行，共享主进程模型内存。
        输入输出：无输入，实例方法提供异步向量化与重排能力。
        边界条件：模型路径未配置时具体调用会抛出可解释 RuntimeError。
        异常行为：初始化阶段不加载模型，推理阶段懒加载失败会向调用方抛出错误。
        """
        self.service_name = "luna_inference_service"

    async def get_embedding_vector(self, text: str) -> List[float]:
        """
        获取文本的语义向量。
        做什么：将文本编码为稠密向量，并保证不阻塞事件循环。
        为什么这样做：Embedding 推理可能耗时数百毫秒，必须通过线程池隔离。
        """
        if not text:
            raise ValueError("需要向量化的文本不能为空")

        try:
            loop = asyncio.get_running_loop()
            vec = await loop.run_in_executor(_get_executor(), _do_embedding, text)
            logger.info(f"Embedding 向量化完成, text_length={len(text)}, vector_dim={len(vec)}")
            return vec
        except Exception as e:
            logger.exception("Embedding 向量化失败")
            raise RuntimeError(f"Embedding 调用失败: {e}")

    async def rerank_documents(self, query: str, documents: List[str]) -> List[Dict[str, Any]]:
        """
        对候选文档进行相关性重排。
        做什么：计算查询与候选文档的相关性分数，并保证不阻塞事件循环。
        返回：包含 'index' 和 'score' 的字典列表，按分数降序排列。
        """
        if not query:
            raise ValueError("查询文本不能为空")

        if not documents:
            return []

        try:
            loop = asyncio.get_running_loop()
            scores = await loop.run_in_executor(_get_executor(), _do_rerank, query, documents)

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
