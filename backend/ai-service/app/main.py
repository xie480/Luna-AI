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

# 强制 HuggingFace 离线模式，防止加载本地模型时因网络问题卡死
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["HF_DATASETS_OFFLINE"] = "1"

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers.api_config_preset import router as config_preset_router
from app.api.routers.prompt import router as prompt_router
from app.api.routers.telemetry import router as telemetry_router
from app.api.http_api import router as http_router
from app.api.sse import router as sse_router
from app.config.crypto import CryptoService
from app.config.event_bus import event_bus
from app.config.settings import settings
from app.logger import logger, setup_logger

# ============================================================
# 在应用启动的最早期初始化日志系统
# 必须在 Uvicorn 启动和大量业务模块加载前执行，以确保接管标准 logging
# ============================================================
setup_logger(level=settings.log_level)

from app.infrastructure.postgres import PostgresClient
from app.infrastructure.qdrant import QdrantClientWrapper
from app.infrastructure.redis import RedisClient
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
        model = SentenceTransformer(EMBEDDING_MODEL_PATH, local_files_only=True, device="cpu")
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
        model = CrossEncoder(RERANK_MODEL_PATH, max_length=1024, trust_remote_code=True, local_files_only=True, device="cpu")
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

    # 8. 初始化推理服务
    from app.inference.service import InferenceService
    inference_svc = InferenceService()

    # 9. 初始化长期记忆管理器并执行启动时兜底检测
    memory_manager = None
    if ltm_pg_repo:
        memory_manager = MemoryManager(
            redis_repo=redis_repo,
            ltm_pg_repo=ltm_pg_repo,
            ltm_qdrant_repo=ltm_qdrant_repo,
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
    app.state.crypto_svc = crypto_svc
    app.state.prompt_manager = prompt_manager
    app.state.memory_manager = memory_manager
    
    if pg_client:
        preset_repo = ConfigPresetPGRepo(pg_client)
        app.state.config_preset_repo = preset_repo
        
        from app.router.model_router import ModelRouter
        model_router = ModelRouter(preset_repo)
        app.state.model_router = model_router
# 11. 注入仓库实例到 app.state（供 HTTP API 依赖注入使用）
app.state.pg_repo = pg_repo
app.state.redis_repo = redis_repo


    # 12. 加载 Embedding 和 Rerank 模型
    global _embedding_model, _rerank_model
    _embedding_model = None
    _rerank_model = None

    def _load_models_bg():
        global _embedding_model, _rerank_model
        _embedding_model = load_embedding_model()
        _rerank_model = load_rerank_model()

    # 在后台线程加载模型，避免阻塞服务器启动
    loop = asyncio.get_running_loop()
    loop.run_in_executor(None, _load_models_bg)

    # 14. 启动监控指标收集器
    from app.telemetry.metrics import init_metrics, start_metrics_collector, stop_metrics_collector
    init_metrics()
    await start_metrics_collector()

    # 15. 启动会话流转定时检测
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
        
    await stop_metrics_collector()
    
    worker = get_worker()
    if worker:
        await worker.stop()
        
    if pg_client:
        await pg_client.close()
        
    if redis_client:
        await redis_client.close()
        
    logger.info("服务器已退出")


app = FastAPI(title="Luna AI Service", lifespan=lifespan)

from fastapi import Request
from app.logger import trace_id_var
from app.utils.snowflake import generate_string_id

@app.middleware("http")
async def trace_id_middleware(request: Request, call_next):
    trace_id = request.headers.get("X-Trace-ID", generate_string_id())
    token = trace_id_var.set(trace_id)
    try:
        response = await call_next(request)
        response.headers["X-Trace-ID"] = trace_id
        return response
    finally:
        trace_id_var.reset(token)

# 允许所有跨域请求，开发阶段方便调试
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_origin_regex=".*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(config_preset_router)
app.include_router(prompt_router)
app.include_router(telemetry_router)
app.include_router(http_router)
app.include_router(sse_router)

# 导入 health 路由 (避免循环导入)
from app.api.health import router as health_router
app.include_router(health_router)


if __name__ == "__main__":
    # 禁用 Uvicorn 的默认日志配置，让我们的 InterceptHandler 完全接管
    log_config = uvicorn.config.LOGGING_CONFIG
    
    # 移除 Uvicorn 默认 handler 中不兼容的参数 (如 stream/strm)
    for handler_name in ["default", "access"]:
        if handler_name in log_config["handlers"]:
            for key in ["stream", "strm"]:
                if key in log_config["handlers"][handler_name]:
                    del log_config["handlers"][handler_name][key]
        
    log_config["handlers"]["default"]["class"] = "app.logger.InterceptHandler"
    log_config["handlers"]["access"]["class"] = "app.logger.InterceptHandler"

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.ai_service_port,
        reload=True,
        log_config=log_config
    )
