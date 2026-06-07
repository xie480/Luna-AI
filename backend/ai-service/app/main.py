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
from typing import Optional

# 强制 HuggingFace 离线模式，防止加载本地模型时因网络问题卡死
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["HF_DATASETS_OFFLINE"] = "1"

# ============================================================================
# 并发调度改造 (维度四)：硬件资源调度与 CPU 算力硬限制边界
# 为什么这样做：限制 PyTorch / OpenMP 的底层衍生线程数量，防止其默认的 CPU 抢占策略锁死宿主机，
# 为 UI 交互流（Electron/React）保留至少 2 个独立的逻辑物理核算力。
# ============================================================================
import torch
safe_threads = max(1, os.cpu_count() - 2) if os.cpu_count() else 2
os.environ["OMP_NUM_THREADS"] = str(safe_threads)
os.environ["MKL_NUM_THREADS"] = str(safe_threads)
try:
    torch.set_num_threads(safe_threads)
except Exception as exc:
    os.environ["LUNA_TORCH_THREAD_INIT_ERROR"] = str(exc)

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers.api_config_preset import router as config_preset_router
from app.api.routers.error_log import router as error_log_router
from app.api.routers.prompt import router as prompt_router
from app.api.routers.rag import router as rag_router
from app.api.routers.telemetry import router as telemetry_router
from app.api.http_api import router as http_router
from app.api.sse import router as sse_router
from app.api.memory_api import router as memory_router
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
from app.repository.error_log_pg import ErrorLogPGRepo
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

# ============================================================================
# 并发调度改造 (维度三)：模型内存生命周期管理 (带 TTL 的懒加载与自动卸载器)
# ============================================================================
import time
import gc
import threading

class ModelManager:
    """具备超时自动卸载机制的模型生命周期管理器"""
    def __init__(self, name: str, model_loader_func, ttl_seconds=600):
        self._name = name
        self._loader = model_loader_func
        self._model = None
        self._ttl = ttl_seconds
        self._last_accessed = 0
        self._lock = threading.Lock()
        
        # 启动后台守护线程，用于定期清理超时未使用的内存模型
        self._cleanup_thread = threading.Thread(target=self._auto_unload, daemon=True)
        self._cleanup_thread.start()

    def get_model(self):
        with self._lock:
            self._last_accessed = time.time()
            if self._model is None:
                logger.info(f"[{self._name}] 触发内存加载 (冷启动): 准备加载模型，请耐心等待...")
                self._model = self._loader()
            return self._model

    def _auto_unload(self):
        while True:
            time.sleep(60) # 每 60 秒扫描一次状态
            with self._lock:
                if self._model is not None and (time.time() - self._last_accessed > self._ttl):
                    logger.info(f"[{self._name}] 模型已连续闲置超过 {self._ttl} 秒，执行彻底卸载并回收系统内存...")
                    del self._model
                    self._model = None
                    gc.collect() # 强制执行垃圾回收


def load_embedding_model() -> object | None:
    """加载 Embedding 模型 (优先尝试 ONNX Optimum，回退到 SentenceTransformer)"""
    if not EMBEDDING_MODEL_PATH:
        logger.warning("EMBEDDING_MODEL_PATH 未配置，跳过 Embedding 模型加载")
        return None

    if not os.path.exists(EMBEDDING_MODEL_PATH):
        logger.warning(f"Embedding 模型路径不存在: {EMBEDDING_MODEL_PATH}，跳过加载")
        return None

    onnx_path = os.path.join(EMBEDDING_MODEL_PATH, "onnx")
    if os.path.exists(onnx_path):
        try:
            from optimum.onnxruntime import ORTModelForFeatureExtraction
            from transformers import AutoTokenizer, pipeline
            import onnxruntime as ort
            
            sess_options = ort.SessionOptions()
            sess_options.intra_op_num_threads = safe_threads
            
            logger.info(f"检测到 ONNX 模型目录，准备加载量化版 Embedding 模型: {onnx_path}")
            tokenizer = AutoTokenizer.from_pretrained(onnx_path, local_files_only=True)
            model = ORTModelForFeatureExtraction.from_pretrained(
                onnx_path,
                local_files_only=True,
                session_options=sess_options
            )
            # 使用 transformers pipeline 简化特征提取调用
            pipe = pipeline("feature-extraction", model=model, tokenizer=tokenizer)
            logger.info("ONNX Embedding 模型加载完成")
            # 包装一层使其对外表现类似 SentenceTransformer 的 encode 接口
            class ONNXEmbeddingWrapper:
                def __init__(self, pipe):
                    self.pipe = pipe
                def encode(self, text):
                    # pipeline 返回的是 [[[float, ...], ...]] 格式
                    import numpy as np
                    out = self.pipe(text, truncation=True, max_length=512)
                    # 对 token vectors 进行 mean pooling
                    vecs = np.array(out[0])
                    mean_vec = np.mean(vecs, axis=0)
                    return mean_vec
            return ONNXEmbeddingWrapper(pipe)
        except Exception as e:
            logger.warning(f"加载 ONNX Embedding 失败 ({e})，将回退到原生加载")

    # 回退：使用原生 SentenceTransformer
    try:
        from sentence_transformers import SentenceTransformer
        logger.info(f"正在加载原生 PyTorch Embedding 模型: {EMBEDDING_MODEL_PATH}")
        model = SentenceTransformer(EMBEDDING_MODEL_PATH, local_files_only=True, device="cpu")
        logger.info("Embedding 模型加载完成")
        return model
    except Exception as e:
        logger.error(f"加载 Embedding 模型失败，路径: {EMBEDDING_MODEL_PATH}, 错误: {e}")
        return None


def load_rerank_model() -> object | None:
    """加载 Rerank 模型 (优先尝试 ONNX Optimum，回退到 CrossEncoder)"""
    if not RERANK_MODEL_PATH:
        logger.warning("RERANK_MODEL_PATH 未配置，跳过 Rerank 模型加载")
        return None

    if not os.path.exists(RERANK_MODEL_PATH):
        logger.warning(f"Rerank 模型路径不存在: {RERANK_MODEL_PATH}，跳过加载")
        return None

    onnx_path = os.path.join(RERANK_MODEL_PATH, "onnx")
    if os.path.exists(onnx_path):
        try:
            from optimum.onnxruntime import ORTModelForSequenceClassification
            from transformers import AutoTokenizer, pipeline
            import onnxruntime as ort
            
            sess_options = ort.SessionOptions()
            sess_options.intra_op_num_threads = safe_threads
            
            logger.info(f"检测到 ONNX 模型目录，准备加载量化版 Rerank 模型: {onnx_path}")
            tokenizer = AutoTokenizer.from_pretrained(onnx_path, local_files_only=True)
            model = ORTModelForSequenceClassification.from_pretrained(
                onnx_path,
                local_files_only=True,
                session_options=sess_options
            )
            pipe = pipeline("text-classification", model=model, tokenizer=tokenizer)
            logger.info("ONNX Rerank 模型加载完成")
            
            class ONNXRerankWrapper:
                def __init__(self, pipe):
                    self.pipe = pipe
                def predict(self, pairs):
                    # pairs 是 [[query, doc1], [query, doc2]] 格式
                    import numpy as np
                    texts = [{"text": p[0], "text_pair": p[1]} for p in pairs]
                    results = self.pipe(texts)
                    # pipeline 返回 {"label": ..., "score": ...}，如果是单个特征提取可能是其他形式
                    # 对于 bge-reranker 这种 cross-encoder，通常预测 logits
                    # 由于不同的底层结构，提取 score 即可
                    scores = [r["score"] for r in results]
                    return np.array(scores)
            return ONNXRerankWrapper(pipe)
        except Exception as e:
            logger.warning(f"加载 ONNX Rerank 失败 ({e})，将回退到原生加载")

    # 回退：原生 CrossEncoder
    try:
        from sentence_transformers import CrossEncoder
        logger.info(f"正在加载原生 PyTorch Rerank 模型: {RERANK_MODEL_PATH}")
        model = CrossEncoder(RERANK_MODEL_PATH, max_length=1024, trust_remote_code=True, local_files_only=True, device="cpu")
        logger.info("Rerank 模型加载完成")
        return model
    except Exception as e:
        logger.error(f"加载 Rerank 模型失败，路径: {RERANK_MODEL_PATH}, 错误: {e}")
        return None


embedding_manager = ModelManager("Embedding", load_embedding_model, ttl_seconds=600)
rerank_manager = ModelManager("Rerank", load_rerank_model, ttl_seconds=600)


async def _initialize_fts_indexes(ltm_pg_repo: Optional[LongTermMemoryPGRepo]) -> None:
    """
    初始化全文检索（FTS）GIN 索引

    做什么：为所有需要全文检索的表创建或确认 GIN 索引（幂等操作，IF NOT EXISTS）。
            当前索引列表：
              - long_term_memories.summary → idx_ltm_summary_fts
            后续如果有其他表需要 FTS 支持，直接在此函数中追加即可。
    为什么这样做：GIN 索引是 PG FTS 高效执行的必备条件，必须在服务启动时确保索引存在。
    边界条件：
        - 依赖 PG 仓库实例可用，不可用时静默跳过
        - 索引创建为幂等操作（CREATE INDEX IF NOT EXISTS），重复调用安全
    """
    if not ltm_pg_repo:
        logger.warning("长期记忆 PG 仓库不可用，跳过 FTS 索引初始化")
        return

    try:
        await ltm_pg_repo.create_fts_index()
        logger.info("全文检索 GIN 索引初始化完成")
    except Exception as e:
        # 索引创建失败不阻断启动，检索降级为全表扫描（性能下降但功能可用）
        logger.warning(f"全文检索 GIN 索引初始化失败（检索将降级为全表扫描） error={e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用程序生命周期管理"""
    app.state.is_ready = False
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
    error_log_repo = None
    if pg_client:
        pg_repo = ChatHistoryPGRepo(pg_client)
        error_log_repo = ErrorLogPGRepo(pg_client)

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

    # 8.2 初始化 Phase 7 RAG 知识库仓库与编排服务
    rag_pg_repo = None
    rag_qdrant_repo = None
    rag_ingestion_service = None
    rag_retrieval_orchestrator = None
    if pg_client:
        from app.repository.rag_pg import RagPGRepository
        rag_pg_repo = RagPGRepository(pg_client)
        try:
            await rag_pg_repo.create_indexes()
        except Exception as e:
            logger.warning(f"RAG PostgreSQL 索引初始化失败 error={e}")
    if qdrant_client:
        from app.repository.rag_qdrant import RagQdrantRepository
        from app.types.constants import RAG_DEFAULT_VECTOR_SIZE
        rag_qdrant_repo = RagQdrantRepository(qdrant_client)
        try:
            await rag_qdrant_repo.ensure_collection(RAG_DEFAULT_VECTOR_SIZE)
        except Exception as e:
            logger.warning(f"RAG Qdrant 集合初始化失败 error={e}")
    if rag_pg_repo:
        from app.rag.ingestion import RagIngestionService
        from app.rag.retrieval import RagRetrievalOrchestrator
        rag_ingestion_service = RagIngestionService(rag_pg_repo, rag_qdrant_repo, inference_svc)
        rag_retrieval_orchestrator = RagRetrievalOrchestrator(rag_pg_repo, rag_qdrant_repo, inference_svc)

        # 注册知识库文档废弃 GC 事件处理器
        from app.config.event_bus import EventType
        from app.config.event_bus import RagDocumentDeprecatedEvent
        
        async def on_document_deprecated(event: RagDocumentDeprecatedEvent) -> None:
             logger.info(f"收到文档废弃事件，启动后台 GC 任务 doc_id={event.doc_id}")
             try:
                 # 获取待清理的旧 chunks 并从 PG 硬删除
                 chunk_ids_to_delete = await rag_pg_repo.delete_document(event.doc_id)
                 if rag_qdrant_repo and chunk_ids_to_delete:
                     await rag_qdrant_repo.delete_chunks(chunk_ids_to_delete)
                 logger.info(f"后台文档 GC 任务完成，成功回收旧文档空间 doc_id={event.doc_id}")
             except Exception as exc:
                 logger.error(f"后台文档 GC 任务异常 doc_id={event.doc_id} error={exc}")
                 
        await event_bus.subscribe(EventType.RAG_DOCUMENT_DEPRECATED, on_document_deprecated)

    # 8.5 初始化全局配置容器
    if pg_client:
        preset_repo = ConfigPresetPGRepo(pg_client)
        app.state.config_preset_repo = preset_repo
        
        from app.router.model_router import ModelRouter
        model_router = ModelRouter(preset_repo)
        app.state.model_router = model_router

        try:
            active_preset = await preset_repo.get_active()
            if active_preset:
                from app.config.settings import global_config_container
                from app.api.routers.api_config_preset import _decrypt_model_config
                import json
                
                def _get_json_str(cfg):
                    return json.dumps(cfg) if isinstance(cfg, dict) else cfg

                large_cfg = _decrypt_model_config(_get_json_str(active_preset.large_model_config), crypto_svc)
                medium_cfg = _decrypt_model_config(_get_json_str(active_preset.medium_model_config), crypto_svc)
                small_cfg = _decrypt_model_config(_get_json_str(active_preset.small_model_config), crypto_svc)
                
                await global_config_container.update_preset_config(large_cfg, medium_cfg, small_cfg)
                logger.info(f"已加载激活的 API 配置预设: {active_preset.name}")
            else:
                logger.warning("未找到激活的 API 配置预设")
        except Exception as e:
            logger.error(f"加载激活的 API 配置预设失败: {e}")

    # 8.5 初始化全文检索（FTS）GIN 索引
    # 为什么放在这里：PG 连接已就绪，ltm_pg_repo 已初始化完成
    if ltm_pg_repo:
        await _initialize_fts_indexes(ltm_pg_repo)

    # 8.8 提示大模型进入懒加载模式
    logger.info("AI 模型加载策略: 按需懒加载并应用 TTL 自动卸载机制")

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
            rerank_top_k=settings.rerank_top_k,
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
    app.state.rag_pg_repo = rag_pg_repo
    app.state.rag_qdrant_repo = rag_qdrant_repo
    app.state.rag_ingestion_service = rag_ingestion_service
    app.state.rag_retrieval_orchestrator = rag_retrieval_orchestrator

    # 11. 注入仓库实例到 app.state（供 HTTP API 依赖注入使用）
    app.state.pg_repo = pg_repo
    app.state.redis_repo = redis_repo
    app.state.error_log_repo = error_log_repo
    app.state.ltm_pg_repo = ltm_pg_repo
    app.state.ltm_qdrant_repo = ltm_qdrant_repo


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

    # 标记服务已完全就绪
    app.state.is_ready = True
    logger.info("Luna AI Service 所有核心资源初始化完成，服务已就绪")
    
    # 尝试通过 SSE 广播就绪事件（如果有早期连接的客户端）
    try:
        from app.api.sse import sse_manager
        await sse_manager.publish({
            "type": "SERVER_READY",
            "trace_id": "system",
            "payload": {"status": "ready", "timestamp": int(datetime.now().timestamp() * 1000)}
        })
    except Exception as e:
        logger.warning(f"广播 SERVER_READY 事件失败: {e}")

    yield

    # Shutdown: 优雅关闭
    app.state.is_ready = False
    logger.info("正在关闭服务器...")
    
    if rollover_task:
        rollover_task.cancel()
        
    await stop_metrics_collector()
    
    worker = get_worker()
    if worker:
        await worker.stop()
        
    if getattr(app.state, "rag_ingestion_service", None):
        await app.state.rag_ingestion_service.shutdown()

    if pg_client:
        await pg_client.close()
        
    if redis_client:
        await redis_client.close()
        
    logger.info("服务器已退出")


app = FastAPI(title="Luna AI Service", lifespan=lifespan)

from fastapi import Request
from fastapi.responses import JSONResponse
from app.logger import trace_id_var
from app.utils.snowflake import generate_string_id

@app.middleware("http")
async def trace_id_middleware(request: Request, call_next):
    """TraceID 注入中间件：从请求头提取或生成 TraceID，注入上下文变量"""
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

# ============================================================
# 全局异常处理器
# 做什么：捕获所有未处理的异常，确保返回 JSON 格式且包含 CORS 头。
#         当路由处理函数中抛出异常（如 create_error_response 传入 int 类型
#         导致的 AttributeError），FastAPI 默认异常处理器不会附加 CORS 头，
#         导致前端收到 "No 'Access-Control-Allow-Origin' header" 的 CORS 错误。
# 为什么这样做：前端开发时通过 localhost:5173 访问，必须确保所有响应
#              （包括错误响应）都包含正确的 CORS 头。
# ============================================================
from starlette.responses import JSONResponse as StarletteJSONResponse
from starlette.requests import Request as StarletteRequest

@app.exception_handler(Exception)
async def global_exception_handler(request: StarletteRequest, exc: Exception):
    """全局异常处理器：统一返回 JSON 错误响应，确保包含 CORS 头"""
    trace_id = request.headers.get("X-Trace-ID", generate_string_id())
    logger.error(f"全局异常捕获 path={request.url.path} error={exc}")
    return StarletteJSONResponse(
        status_code=500,
        content={
            "code": 500,
            "msg": f"服务器内部错误: {str(exc)}",
            "data": None,
            "trace_id": trace_id,
        },
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "*",
            "Access-Control-Allow-Headers": "*",
        },
    )

# 注册路由
app.include_router(config_preset_router)
app.include_router(error_log_router)
app.include_router(prompt_router)
app.include_router(rag_router)
app.include_router(telemetry_router)
app.include_router(http_router)
app.include_router(sse_router)
app.include_router(memory_router)

# 导入 health 路由 (避免循环导入)
from app.api.health import router as health_router
app.include_router(health_router)


