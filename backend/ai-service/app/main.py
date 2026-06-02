"""
Luna AI 服务入口

做什么：FastAPI 应用入口、生命周期管理（Lifespan）、依赖注入装配。
为什么这样做：作为整个 Python 后端服务的启动点，负责初始化所有基础设施、存储库、管理器和路由。
"""

import asyncio
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime

import grpc
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# 将 app/api 目录添加到 sys.path，解决 gRPC 生成文件的绝对导入问题
sys.path.append(os.path.join(os.path.dirname(__file__), 'api'))

from app.api import communication_pb2_grpc
from app.api.grpc_client import AIClient
from app.api.grpc_service import CommunicationServiceServicer, set_embedding_model, set_rerank_model
from app.api.interceptor import TelemetryInterceptor
from app.api.routers.api_config_preset import router as config_preset_router
from app.api.routers.prompt import router as prompt_router
from app.api.routers.telemetry import router as telemetry_router
from app.api.ws_server import router as ws_router, ws_server, WSServer
from app.config.crypto import CryptoService
from app.config.event_bus import event_bus
from app.config.settings import settings
from app.infrastructure.postgres import PostgresClient
from app.infrastructure.qdrant import QdrantClientWrapper
from app.infrastructure.redis import RedisClient
from app.logger import logger
from app.memory.manager import Manager as MemoryManager
from app.prompt.manager import Manager as PromptManager
from app.repository.chat_history_pg import ChatHistoryPGRepo
from app.repository.chat_history_redis import ChatHistoryRedisRepo
from app.repository.config_preset_pg import ConfigPresetPGRepo
from app.repository.long_term_memory_pg import LongTermMemoryPGRepo
from app.repository.long_term_memory_qdrant import LongTermMemoryQdrantRepo
from app.repository.models import Base
from app.repository.prompt_pg import PromptPGRepo
from app.telemetry.worker import get_worker, init_worker

# ============================================================
# 模型路径通过 app.config.settings 统一管理（自动读取 .env 文件）
# ============================================================
EMBEDDING_MODEL_PATH = settings.embedding_model_path
RERANK_MODEL_PATH = settings.rerank_model_path


def load_embedding_model() -> object | None:
    """加载 Embedding 模型（SentenceTransformer）"""
    if not EMBEDDING_MODEL_PATH:
        logger.warning("EMBEDDING_MODEL_PATH 未配置，跳过 Embedding 模型加载")
        return None

    if not os.path.exists(EMBEDDING_MODEL_PATH):
        logger.warning(f"Embedding 模型路径不存在: {EMBEDDING_MODEL_PATH}，跳过加载")
        return None

    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        logger.error("sentence-transformers 包未安装，无法加载 Embedding 模型。")
        return None

    try:
        logger.info(f"正在加载 Embedding 模型: {EMBEDDING_MODEL_PATH}")
        model = SentenceTransformer(EMBEDDING_MODEL_PATH)
        logger.info("Embedding 模型加载完成")
        return model
    except Exception as e:
        logger.error(f"加载 Embedding 模型失败，路径: {EMBEDDING_MODEL_PATH}, 错误: {e}")
        return None


def load_rerank_model() -> object | None:
    """加载 Rerank 模型（CrossEncoder）"""
    if not RERANK_MODEL_PATH:
        logger.warning("RERANK_MODEL_PATH 未配置，跳过 Rerank 模型加载")
        return None

    if not os.path.exists(RERANK_MODEL_PATH):
        logger.warning(f"Rerank 模型路径不存在: {RERANK_MODEL_PATH}，跳过加载")
        return None

    try:
        from sentence_transformers import CrossEncoder
    except ImportError:
        logger.error("sentence-transformers 包未安装，无法加载 Rerank 模型。")
        return None

    try:
        logger.info(f"正在加载 Rerank 模型: {RERANK_MODEL_PATH}")
        model = CrossEncoder(RERANK_MODEL_PATH, max_length=1024, trust_remote_code=True)
        logger.info("Rerank 模型加载完成")
        return model
    except Exception as e:
        logger.error(f"加载 Rerank 模型失败，路径: {RERANK_MODEL_PATH}, 错误: {e}")
        return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用程序生命周期管理"""
    logger.info(f"正在启动 Luna 运行时服务 port={settings.ai_service_port}")

    # 1. 初始化 Redis 连接
    redis_client = None
    try:
        redis_client = RedisClient(settings.redis_addr, settings.redis_password, settings.redis_db)
    except Exception as e:
        logger.warning(f"Redis 连接失败，将使用降级模式运行 error={e}")

    # 2. 初始化 PostgreSQL 连接
    pg_client = None
    try:
        pg_client = PostgresClient(settings.postgres_conn_str)
        
        # 自动迁移数据库表结构
        async with pg_client.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("自动迁移数据库表结构成功")
        
        # 初始化 Telemetry Worker
        init_worker(pg_client)
        worker = get_worker()
        if worker:
            await worker.start()
            
    except Exception as e:
        logger.warning(f"PostgreSQL 连接失败，将使用降级模式运行 error={e}")

    # 3. 初始化 CryptoService
    crypto_svc = CryptoService()

    # 4. 初始化 AI 客户端 (gRPC)
    ai_client = None
    try:
        ai_client = AIClient(settings.ai_service_address)
    except Exception as e:
        logger.error(f"初始化 AI 客户端失败 error={e}")

    # 5. 初始化 PromptManager
    prompt_manager = None
    if pg_client:
        prompt_repo = PromptPGRepo(pg_client)
        from app.prompt.cache import CacheManager
        prompt_cache = CacheManager(redis_client, prompt_repo)
        prompt_manager = PromptManager(prompt_repo, prompt_cache)

    # 6. 初始化基础设施仓库
    redis_repo = None
    if redis_client:
        redis_repo = ChatHistoryRedisRepo(redis_client)
        
    pg_repo = None
    if pg_client:
        pg_repo = ChatHistoryPGRepo(pg_client)

    # 7. 初始化长期记忆仓库
    ltm_pg_repo = None
    if pg_client:
        ltm_pg_repo = LongTermMemoryPGRepo(pg_client)
        
    qdrant_client = None
    ltm_qdrant_repo = None
    if settings.qdrant_address:
        qdrant_client = QdrantClientWrapper(settings.qdrant_address)
        ltm_qdrant_repo = LongTermMemoryQdrantRepo(qdrant_client)

    # 8. 初始化推理服务 (这里简化，实际应实现 InferenceService 接口)
    inference_svc = None

    # 9. 初始化长期记忆管理器并执行启动时兜底检测
    memory_manager = None
    if ltm_pg_repo:
        memory_manager = MemoryManager(
            redis_repo=redis_repo,
            ltm_pg_repo=ltm_pg_repo,
            ltm_qdrant_repo=ltm_qdrant_repo,
            ai_client=ai_client,
            prompt_mgr=prompt_manager,
            qdrant_client=qdrant_client,
            inference_svc=inference_svc,
            retrieval_top_k=settings.retrieval_top_k,
        )
        try:
            await memory_manager.init()
        except Exception as e:
            logger.error(f"长期记忆系统初始化失败 error={e}")

    # 10. 依赖注入装配 (存入 app.state 供路由使用)
    app.state.pg_client = pg_client
    app.state.redis_client = redis_client
    app.state.ai_client = ai_client
    app.state.crypto_svc = crypto_svc
    app.state.prompt_manager = prompt_manager
    app.state.memory_manager = memory_manager
    
    if pg_client:
        app.state.config_preset_repo = ConfigPresetPGRepo(pg_client)

    # 11. 初始化 WebSocket 服务
    global ws_server
    ws_server = WSServer(
        ai_client=ai_client,
        redis_repo=redis_repo,
        pg_repo=pg_repo,
        prompt_mgr=prompt_manager,
        memory_manager=memory_manager,
    )

    # 12. 加载 Embedding 和 Rerank 模型
    embedding_model = load_embedding_model()
    rerank_model = load_rerank_model()
    if embedding_model is not None:
        set_embedding_model(embedding_model)
    if rerank_model is not None:
        set_rerank_model(rerank_model)

    # 13. 启动 gRPC 服务
    grpc_task = asyncio.create_task(serve_grpc())

    # 14. 启动会话流转定时检测
    rollover_task = None
    if memory_manager:
        async def _rollover_loop():
            current_session_id = datetime.now().strftime("%Y%m%d")
            while True:
                await asyncio.sleep(60) # 每分钟检查
                try:
                    new_session_id = await memory_manager.rollover_session(current_session_id)
                    current_session_id = new_session_id
                except Exception as e:
                    logger.error(f"会话流转检测失败 error={e}")
                    
        rollover_task = asyncio.create_task(_rollover_loop())

    yield

    # Shutdown: 优雅关闭
    logger.info("正在关闭服务器...")
    
    if rollover_task:
        rollover_task.cancel()
        
    grpc_task.cancel()
    
    worker = get_worker()
    if worker:
        await worker.stop()
        
    if ai_client:
        await ai_client.close()
        
    if pg_client:
        await pg_client.close()
        
    if redis_client:
        await redis_client.close()
        
    logger.info("服务器已退出")


app = FastAPI(title="Luna AI Service", lifespan=lifespan)

# 允许所有跨域请求，开发阶段方便调试
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(config_preset_router)
app.include_router(prompt_router)
app.include_router(telemetry_router)
app.include_router(ws_router)

# 导入 health 路由 (避免循环导入)
from app.api.health import router as health_router
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
