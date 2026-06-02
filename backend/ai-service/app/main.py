import asyncio
import os
import sys
from contextlib import asynccontextmanager

import grpc
import uvicorn
from fastapi import FastAPI

# 注意：sentence_transformers 是重依赖（含 PyTorch），不在模块级导入。
# 在 load_embedding_model() 和 load_rerank_model() 函数内部延迟导入，
# 这样即使包未安装或模型路径无效，也不会阻断整个服务启动。
# 将 app/api 目录添加到 sys.path，解决 gRPC 生成文件的绝对导入问题
sys.path.append(os.path.join(os.path.dirname(__file__), 'api'))

from app.api import communication_pb2_grpc
from app.api.grpc_service import CommunicationServiceServicer, set_embedding_model, set_rerank_model
from app.api.health import router as health_router
from app.api.interceptor import TelemetryInterceptor
from app.config.settings import settings
from app.logger import logger

# ============================================================
# 模型路径通过 app.config.settings 统一管理（自动读取 .env 文件）
# 配置项：
#   embedding_model_path: Embedding 模型路径（对应 .env 中的 EMBEDDING_MODEL_PATH）
#   rerank_model_path: Rerank 模型路径（对应 .env 中的 RERANK_MODEL_PATH）
# 如果未配置，则跳过模型加载（仅影响记忆检索功能，不阻断其他服务）
# ============================================================
EMBEDDING_MODEL_PATH = settings.embedding_model_path
RERANK_MODEL_PATH = settings.rerank_model_path


def load_embedding_model() -> object | None:
    """
    加载 Embedding 模型（SentenceTransformer）

    做什么：从配置路径加载 BGE-base-zh-v1.5 或其他 SentenceTransformer 模型。
    为什么这样做：模型加载开销大（数百MB），必须在启动时一次性加载并复用。
    输入：无（从环境变量 EMBEDDING_MODEL_PATH 读取路径）
    输出：SentenceTransformer 实例或 None（路径未配置时 / 路径无效时 / 包未安装时）
    边界条件：
        - 路径为空时跳过加载，不阻断服务启动
        - 路径无效或模型损坏时捕获异常并返回 None，不阻断服务启动
        - sentence-transformers 包未安装时捕获 ImportError 并返回 None
    """
    if not EMBEDDING_MODEL_PATH:
        logger.warning("EMBEDDING_MODEL_PATH 未配置，跳过 Embedding 模型加载")
        return None

    if not os.path.exists(EMBEDDING_MODEL_PATH):
        logger.warning(f"Embedding 模型路径不存在: {EMBEDDING_MODEL_PATH}，跳过加载")
        return None

    try:
        # 延迟导入：避免 sentence-transformers 未安装时阻断服务启动
        from sentence_transformers import SentenceTransformer
    except ImportError:
        logger.error(
            "sentence-transformers 包未安装，无法加载 Embedding 模型。"
            "请执行: pip install sentence-transformers"
        )
        return None

    try:
        logger.info(f"正在加载 Embedding 模型: {EMBEDDING_MODEL_PATH}")
        model = SentenceTransformer(EMBEDDING_MODEL_PATH)
        logger.info("Embedding 模型加载完成")
        return model
    except Exception as e:
        logger.error(
            f"加载 Embedding 模型失败，路径: {EMBEDDING_MODEL_PATH}, 错误: {type(e).__name__}: {e}"
        )
        return None


def load_rerank_model() -> object | None:
    """
    加载 Rerank 模型（CrossEncoder）

    做什么：从配置路径加载 BGE-reranker-v2-m3 或其他 CrossEncoder 模型。
    为什么这样做：模型加载开销大，必须在启动时一次性加载并复用。
    输入：无（从环境变量 RERANK_MODEL_PATH 读取路径）
    输出：CrossEncoder 实例或 None（路径未配置时 / 路径无效时 / 包未安装时）
    边界条件：
        - 路径为空时跳过加载，不阻断服务启动
        - 路径无效或模型损坏时捕获异常并返回 None，不阻断服务启动
        - trust_remote_code=True 支持自定义模型架构
        - max_length=1024 平衡性能与精度
    """
    if not RERANK_MODEL_PATH:
        logger.warning("RERANK_MODEL_PATH 未配置，跳过 Rerank 模型加载")
        return None

    if not os.path.exists(RERANK_MODEL_PATH):
        logger.warning(f"Rerank 模型路径不存在: {RERANK_MODEL_PATH}，跳过加载")
        return None

    try:
        # 延迟导入：避免 sentence-transformers 未安装时阻断服务启动
        from sentence_transformers import CrossEncoder
    except ImportError:
        logger.error(
            "sentence-transformers 包未安装，无法加载 Rerank 模型。"
            "请执行: pip install sentence-transformers"
        )
        return None

    try:
        logger.info(f"正在加载 Rerank 模型: {RERANK_MODEL_PATH}")
        model = CrossEncoder(RERANK_MODEL_PATH, max_length=1024, trust_remote_code=True)
        logger.info("Rerank 模型加载完成")
        return model
    except Exception as e:
        logger.error(
            f"加载 Rerank 模型失败，路径: {RERANK_MODEL_PATH}, 错误: {type(e).__name__}: {e}"
        )
        return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用程序生命周期管理"""
    # 启动时：加载 Embedding 和 Rerank 模型
    embedding_model = load_embedding_model()
    rerank_model = load_rerank_model()
    if embedding_model is not None:
        set_embedding_model(embedding_model)
    if rerank_model is not None:
        set_rerank_model(rerank_model)

    asyncio.create_task(serve_grpc())
    yield

app = FastAPI(title="Luna AI Service", lifespan=lifespan)

app.include_router(health_router)

async def serve_grpc():
    """启动 gRPC 服务"""
    server = grpc.aio.server(interceptors=[TelemetryInterceptor()])
    communication_pb2_grpc.add_CommunicationServiceServicer_to_server(
        CommunicationServiceServicer(), server
    )
    # 使用 0.0.0.0 绑定 IPv4 地址，确保 Windows 下 Go 客户端能正常连接
    listen_addr = f"0.0.0.0:{settings.grpc_port}"
    server.add_insecure_port(listen_addr)
    logger.info(f"gRPC 服务启动，监听地址: {listen_addr}")
    await server.start()
    await server.wait_for_termination()

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.ai_service_port,
        reload=True,
        log_level=settings.log_level.lower()
    )
