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
# 植入 torchcodec 桩模块，防止因 FFmpeg 缺失导致 sentence_transformers 导入崩溃
#
# 做什么：torchcodec（voxcpm 的间接依赖）在模块加载阶段会尝试加载 FFmpeg DLL。
#         如果系统未安装 FFmpeg，会抛出 RuntimeError。而 sentence_transformers 的
#         base/modality_types.py 在导入时 try/except 仅捕获 (ImportError, OSError)，
#         不捕获 RuntimeError，导致整个 Embedding 模型加载链崩溃。
# 为什么这样做：在 sentence_transformers 导入前预先向 sys.modules 注入 torchcodec 存根，
#             使其找到存根后不会触发实际的 native library 加载流程，降低到安静降级。
# 边界条件：仅当 torchcodec 尚未被导入时生效；如果环境中正常安装了 FFmpeg，则不影响。
# ============================================================================
import types as _sys_types
import importlib.machinery as _importlib_machinery
if "torchcodec" not in sys.modules:
    _torchcodec_stub = _sys_types.ModuleType("torchcodec")
    # 设置 __spec__ 防止 sentence_transformers 导入链因 __spec__ is None 而崩溃
    _torchcodec_stub.__spec__ = _importlib_machinery.ModuleSpec(
        "torchcodec", None, is_package=True
    )
    _torchcodec_stub.__path__ = []
    _torchcodec_stub.decoders = _sys_types.ModuleType("torchcodec.decoders")
    _torchcodec_stub.decoders.__spec__ = _importlib_machinery.ModuleSpec(
        "torchcodec.decoders", None
    )
    _torchcodec_stub.decoders.AudioDecoder = None  # type: ignore[attr-defined]
    _torchcodec_stub.decoders.VideoDecoder = None  # type: ignore[attr-defined]
    sys.modules["torchcodec"] = _torchcodec_stub
    sys.modules["torchcodec.decoders"] = _torchcodec_stub.decoders

# ============================================================================
# 植入 transformers / optimum 兼容垫片组，防止旧版 optimum 在新版 transformers 上导入崩溃
#
# 做什么：optimum 2.1.0 依赖 transformers 的一些内部 API，这些 API 在
#         transformers 5.x 中被移除或改名。本区块在 optimum 被实际导入前，将缺失的
#         API 注入到对应的 transformers 子模块命名空间中，使旧版本 optimum 能正常加载。
#
# 已知缺失及其来源：
#   1. is_offline_mode         -> transformers.utils (在 5.x 中仅在 utils.hub 中)
#   2. get_parameter_dtype     -> transformers.modeling_utils (5.x 中已移除)
#   3. _CAN_RECORD_REGISTRY    -> transformers.utils.generic (5.x 中已移除)
#   4. OutputRecorder          -> transformers.utils.generic (5.x 中已移除)
#
# 为什么这样做：在 optimum 被实际导入前，向 transformers 子模块注入必要的兼容垫片，
#              使旧版本 optimum 兼容新版 transformers，避免 ONNX 模型加载链整体降级回退。
# 边界条件：仅当对应属性不存在时注入，不覆盖 transformers 原生实现。
# ============================================================================
import transformers.utils as _transformers_utils
import transformers.utils.hub as _transformers_utils_hub

# 补丁 1：is_offline_mode
if not hasattr(_transformers_utils, "is_offline_mode"):
    _transformers_utils.is_offline_mode = _transformers_utils_hub.is_offline_mode

import transformers.modeling_utils as _transformers_modeling_utils
import torch as _torch

# 补丁 2：get_parameter_dtype
if not hasattr(_transformers_modeling_utils, "get_parameter_dtype"):
    def _get_parameter_dtype(module: _torch.nn.Module) -> _torch.dtype:
        """从模块中推断参数数据类型，等价于旧版 transformers 的 get_parameter_dtype"""
        for param in module.parameters():
            return param.dtype
        for buf in module.buffers():
            return buf.dtype
        return _torch.float32
    _transformers_modeling_utils.get_parameter_dtype = _get_parameter_dtype

import transformers.utils.generic as _transformers_utils_generic

# 补丁 3 & 4：_CAN_RECORD_REGISTRY + OutputRecorder
if not hasattr(_transformers_utils_generic, "_CAN_RECORD_REGISTRY"):
    class _MockRegistry(dict):
        """空操作注册表，替代旧版 transformers 中已移除的 _CAN_RECORD_REGISTRY"""
        def add(self, obj: object, name: str | None = None) -> None:
            pass
    _transformers_utils_generic._CAN_RECORD_REGISTRY = _MockRegistry()

if not hasattr(_transformers_utils_generic, "OutputRecorder"):
    class _MockOutputRecorder:
        """空操作输出记录器，替代旧版 transformers 中已移除的 OutputRecorder"""
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
    _transformers_utils_generic.OutputRecorder = _MockOutputRecorder

# ============================================================================
# 补丁 5：强制阻断 ONNX Runtime 使用 CUDA 执行提供程序
#
# 做什么：optimum.onnxruntime 内部 validate_provider_availability() 会检查
#         providers 列表中每个 provider 是否可用。尽管 from_pretrained 传了
#         provider="CPUExecutionProvider"，但某些导出/回退路径可能覆盖该参数。
#         本补丁在 onnxruntime 层面过滤掉 CUDA/TensorRT 等不可用的 GPU provider，
#         并从 optimum 的验证函数中移除它们，确保模型始终使用 CPU 加载。
# 为什么这样做：三重保障——环境变量层 + onnxruntime 层 + optimum 验证函数层。
# ============================================================================
import os as _os
_os.environ["CUDA_VISIBLE_DEVICES"] = "-1"

import onnxruntime as _ort
# 替换 get_available_providers，只保留 CPU 可用的 provider
_orig_get_available_providers = _ort.get_available_providers
def _patched_get_available_providers():
    """返回仅含 CPU 可用 provider 的列表，过滤掉任何 GPU provider"""
    all_providers = _orig_get_available_providers()
    _gpu_keywords = ["cuda", "tensorrt", "rocm", "openvino"]
    return [p for p in all_providers if not any(kw in p.lower() for kw in _gpu_keywords)]
_ort.get_available_providers = _patched_get_available_providers

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
from fastapi import FastAPI, Request as FastAPIRequest
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routers.api_config_preset import router as config_preset_router
from app.api.routers.error_log import router as error_log_router
from app.api.routers.long_answer_api import router as long_answer_router
from app.api.routers.gating import router as gating_router
from app.api.routers.prompt import router as prompt_router
from app.api.routers.rag import router as rag_router
from app.api.routers.telemetry import router as telemetry_router
from app.api.routers.user_profile import router as user_profile_router
from app.api.http_api import router as http_router
from app.api.sse import router as sse_router
from app.api.memory_api import router as memory_router
from app.api.routers.mcp_local import router as mcp_local_router
from app.api.routers.mcp_market import router as mcp_market_router
from app.api.routers.mcp_skill import router as mcp_skill_router
from app.api.routers.tool_config import router as tool_config_router
from app.api.routers.workflow_command import router as workflow_command_router
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
from app.repository.user_profile_pg import UserProfilePGRepository
from app.telemetry.worker import Base as TelemetryBase, get_worker, init_worker

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
                session_options=sess_options,
                provider="CPUExecutionProvider"
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
                session_options=sess_options,
                provider="CPUExecutionProvider"
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
        from app.repository.long_answer_cache import LongAnswerSummaryCache
        LongAnswerSummaryCache.set_client(redis_client)
    except Exception as e:
        logger.warning(f"Redis 连接失败，将使用降级模式运行 error={e}")

    # 2. 初始化 PostgreSQL 连接
    pg_client = None
    try:
        pg_client = PostgresClient(settings.postgres_conn_str)

        # 自动迁移数据库表结构 (自动检查并同步缺失的字段/表)
        from sqlalchemy import inspect

        def _sync_schema(sync_conn):
            from sqlalchemy import inspect
            from sqlalchemy import text as from_sqlalchemy_text
            
            # 自增计数器，用于生成唯一 savepoint 名称
            _sp_counter = [0]

            def ddl_execute(sql: str, error_ctx: str) -> None:
                """使用 savepoint 安全执行 DDL，单个 DDL 失败不回滚整个事务。
                
                为什么这样做：PostgreSQL 在 DDL 失败后会将整个事务标记为 aborted，
                后续所有 SQL 都会报 InFailedSQLTransactionError。SAVEPOINT 允许
                我们在单个 DDL 失败时只回滚到该点，不影响事务中其他成功 DDL。
                """
                _sp_counter[0] += 1
                sp_name = f"sp_ddl_{_sp_counter[0]}"
                try:
                    sync_conn.exec_driver_sql(f"SAVEPOINT {sp_name}")
                    sync_conn.execute(from_sqlalchemy_text(sql))
                    sync_conn.exec_driver_sql(f"RELEASE SAVEPOINT {sp_name}")
                except Exception as e:
                    logger.error(f"[Schema Sync] {error_ctx} 失败: {e}")
                    try:
                        sync_conn.exec_driver_sql(f"ROLLBACK TO SAVEPOINT {sp_name}")
                    except Exception:
                        pass
            
            inspector = inspect(sync_conn)
            existing_tables = set(inspector.get_table_names())

            # 收集本地所有定义的表
            local_tables_map = {}
            local_tables_map.update(Base.metadata.tables)
            local_tables_map.update(TelemetryBase.metadata.tables)
            
            # 白名单保护系统表与非 SQLAlchemy ORM 表
            whitelist_tables = {"langgraph_chat_checkpoints"}

            # 1. 动态创建新表（存在则跳过）
            try:
                Base.metadata.create_all(sync_conn)
                TelemetryBase.metadata.create_all(sync_conn)
            except Exception as e:
                logger.error(f"[Schema Sync] 创建新表失败: {e}")

            # 2. 检查并删除多余的表
            for db_table in existing_tables:
                if db_table not in local_tables_map and db_table not in whitelist_tables:
                    drop_stmt = f"DROP TABLE IF EXISTS {db_table} CASCADE"
                    logger.info(f"[Schema Sync] 检测到废弃表，执行删除: {drop_stmt}")
                    ddl_execute(drop_stmt, f"删除表 {db_table}")

            existing_tables = set(inspector.get_table_names())

            # 3. 字段级差异比对与同步
            for table_name, table in local_tables_map.items():
                if table_name in existing_tables:
                    db_columns_info = inspector.get_columns(table_name)
                    db_columns = {col['name']: col for col in db_columns_info}
                    
                    local_col_names = {col.name for col in table.columns}
                    
                    # a. 删除数据库中多余的字段
                    for db_col_name in db_columns:
                        if db_col_name not in local_col_names:
                            drop_col_stmt = f'ALTER TABLE {table_name} DROP COLUMN "{db_col_name}" CASCADE'
                            logger.info(f"[Schema Sync] 表 {table_name} 检测到废弃字段，执行删除: {drop_col_stmt}")
                            ddl_execute(drop_col_stmt, f"表 {table_name} 删除字段 {db_col_name}")

                    # b. 新增字段或修改字段属性
                    for col in table.columns:  # 遍历本地定义的列
                        col_name = col.name
                        if col_name not in db_columns:  # 检查数据库中是否缺少该字段
                            # 使用 dialect 编译类型，确保 PostgreSQL 兼容（DateTime -> TIMESTAMP WITH TIME ZONE）
                            col_type = str(col.type.compile(sync_conn.dialect))
                            nullable_str = "" if col.nullable else " NOT NULL"
                            
                            # 构建默认值子句，防止 NOT NULL 且无默认导致错误
                            default_clause = ""
                            if col.default is not None or col.server_default is not None:
                                # timestamp 类型用 NOW() 作默认值，其他类型用空字符串
                                if "timestamp" in col_type.lower():
                                    default_clause = " DEFAULT NOW()"
                                else:
                                    default_clause = " DEFAULT ''"
                            alter_stmt = f'ALTER TABLE {table_name} ADD COLUMN "{col_name}" {col_type} {nullable_str}{default_clause}'
                            logger.info(f"[Schema Sync] 表 {table_name} 检测到缺失字段，执行: {alter_stmt}")
                            ddl_execute(alter_stmt, f"表 {table_name} 添加列 {col_name}")

                            # 添加新字段对应的索引
                            if getattr(col, 'index', False):
                                index_name = f"ix_{table_name}_{col_name}"
                                index_stmt = f'CREATE INDEX IF NOT EXISTS {index_name} ON {table_name} ("{col_name}")'
                                logger.info(f"[Schema Sync] 为新字段创建索引: {index_stmt}")
                                ddl_execute(index_stmt, f"创建索引 ix_{table_name}_{col_name}")
                        else:
                            # 字段属性与类型差异比对
                            db_col = db_columns[col_name]
                            db_nullable = db_col.get('nullable', True)
                            if col.nullable != db_nullable:
                                alter_null_stmt = f'ALTER TABLE {table_name} ALTER COLUMN "{col_name}" {"DROP" if col.nullable else "SET"} NOT NULL'
                                logger.info(f"[Schema Sync] 表 {table_name} 字段 {col_name} Nullable 变更，执行: {alter_null_stmt}")
                                ddl_execute(alter_null_stmt, f"表 {table_name} 字段 {col_name} 修改 Nullable")
                            
                            # 类型比对
                            expected_type_str = str(col.type.compile(sync_conn.dialect)).lower()
                            db_type_str = str(db_col['type']).lower()
                            
                            exp_base_type = expected_type_str.split('(')[0].strip()
                            db_base_type = db_type_str.split('(')[0].strip()
                            
                            # 类型等价映射（注意：timestamp with/without time zone 必须严格区分）
                            # 不要将 TIMESTAMPTZ 和 TIMESTAMP 混为一谈，否则会导致时区信息丢失
                            type_equivalents = {
                                'character varying': 'varchar',
                                'integer': 'int',
                                'boolean': 'bool',
                            }
                            exp_base_type = type_equivalents.get(exp_base_type, exp_base_type)
                            db_base_type = type_equivalents.get(db_base_type, db_base_type)

                            # 特殊处理：timestamp without time zone -> timestamp with time zone
                            # 如果 ORM 模型期望带时区但实际库中不带，必须修复（否则时间少 8 小时）
                            if (exp_base_type == 'timestamp with time zone' and db_base_type == 'timestamp without time zone'):
                                # 使用 AT TIME ZONE 'UTC' 确保已有数据被正确解释为 UTC
                                fix_tz_stmt = (
                                    f'ALTER TABLE {table_name} ALTER COLUMN "{col_name}" '
                                    f"TYPE TIMESTAMP WITH TIME ZONE USING \"{col_name}\" AT TIME ZONE 'UTC'"
                                )
                                logger.warning(
                                    f"[Schema Sync] 表 {table_name} 字段 {col_name} 缺少时区"
                                    f"（当前: {db_type_str}，期望: {expected_type_str}），"
                                    f"执行转换: {fix_tz_stmt}"
                                )
                                ddl_execute(fix_tz_stmt, f"表 {table_name} 字段 {col_name} 时区转换")
                                # 跳过下方的通用 ALTER（类型已匹配，无需二次转换）
                                continue

                            # 忽略 JSON 相关类型的复杂差异，只对基础类型的不同进行 ALTER
                            if exp_base_type != db_base_type and "json" not in exp_base_type and "json" not in db_base_type:
                                alter_type_stmt = f'ALTER TABLE {table_name} ALTER COLUMN "{col_name}" TYPE {expected_type_str} USING "{col_name}"::{expected_type_str}'
                                logger.info(f"[Schema Sync] 表 {table_name} 字段 {col_name} 类型变更 ({db_type_str} -> {expected_type_str})，执行: {alter_type_stmt}")
                                ddl_execute(alter_type_stmt, f"表 {table_name} 字段 {col_name} 修改类型")

        from sqlalchemy import text as from_sqlalchemy_text

        async with pg_client.engine.begin() as conn:
            await conn.run_sync(_sync_schema)
            await conn.execute(from_sqlalchemy_text(
                "CREATE TABLE IF NOT EXISTS langgraph_chat_checkpoints ("
                "checkpoint_id VARCHAR(64) PRIMARY KEY, "
                "thread_id VARCHAR(64) NOT NULL, "
                "checkpoint_ns VARCHAR(255) NOT NULL, "
                "trace_id VARCHAR(64) NOT NULL, "
                "interaction_id VARCHAR(64) NOT NULL, "
                "node_type VARCHAR(100) NOT NULL, "
                "payload JSONB NOT NULL, "
                "created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()"
                ")"
            ))
            await conn.execute(from_sqlalchemy_text(
                "CREATE INDEX IF NOT EXISTS idx_langgraph_chat_checkpoints_trace "
                "ON langgraph_chat_checkpoints (trace_id)"
            ))
            await conn.execute(from_sqlalchemy_text(
                "CREATE INDEX IF NOT EXISTS idx_langgraph_chat_checkpoints_thread_ns "
                "ON langgraph_chat_checkpoints (thread_id, checkpoint_ns, created_at)"
            ))
        logger.info("自动同步数据库表结构（含字段增量）与 Chat Workflow checkpoint 表成功")

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

        # 自动同步向量数据库集合（严格比对：删除废弃集合）
        try:
            logger.info("[Schema Sync] 开始同步 Qdrant 向量数据库集合...")
            from app.infrastructure.qdrant import QDRANT_COLLECTION_LONG_TERM_MEMORIES
            from app.types.constants import RAG_QDRANT_COLLECTION
            
            local_collections = {QDRANT_COLLECTION_LONG_TERM_MEMORIES, RAG_QDRANT_COLLECTION}
            
            await qdrant_client._ensure_client()
            db_collections_response = await qdrant_client.client.get_collections()
            db_collections = {col.name for col in db_collections_response.collections}
            
            for db_col in db_collections:
                if db_col not in local_collections:
                    logger.info(f"[Schema Sync] Qdrant 检测到废弃集合，执行删除: {db_col}")
                    await qdrant_client.client.delete_collection(db_col)
                    
            logger.info("[Schema Sync] Qdrant 向量数据库集合同步完成")
        except Exception as e:
            logger.error(f"[Schema Sync] Qdrant 向量数据库同步失败: {e}")

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
        rag_retrieval_orchestrator = RagRetrievalOrchestrator(
            rag_pg_repo,
            rag_qdrant_repo,
            inference_svc,
            prompt_manager=prompt_manager,
        )

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

    # 12. 初始化用户画像仓库与缓存服务
    user_profile_service = None
    if pg_client:
        from app.user_profile.cache import UserProfileCache
        from app.user_profile.conflict_resolver import UserProfileConflictResolver
        from app.user_profile.extractor import UserProfileExtractor
        from app.user_profile.service import UserProfileService
        from app.user_profile.summarizer import UserProfileSummarizer

        user_profile_pg_repo = UserProfilePGRepository(pg_client)
        try:
            await user_profile_pg_repo.create_indexes()
        except Exception as e:
            logger.warning(f"用户画像索引初始化失败 error={e}")

        profile_cache = UserProfileCache(redis_client) if redis_client else None
        profile_extractor = UserProfileExtractor(prompt_manager)
        profile_summarizer = UserProfileSummarizer(prompt_manager)
        profile_conflict_resolver = UserProfileConflictResolver()
        user_profile_service = UserProfileService(
            repo=user_profile_pg_repo,
            cache=profile_cache,
            extractor=profile_extractor,
            summarizer=profile_summarizer,
            conflict_resolver=profile_conflict_resolver,
        )

        app.state.user_profile_pg_repo = user_profile_pg_repo
        app.state.user_profile_service = user_profile_service

        # 依赖注入：将 user_profile_service 提供给 memory_manager
        if memory_manager:
            memory_manager.user_profile_service = user_profile_service

    # 13. 初始化 Phase 8.5 Chat Workflow 服务
    # 做什么：初始化 ChatWorkflowService 及其依赖的四种聊天模式图。
    # 为什么这样做：使用 try/except 包裹每个图的构建，单个图构建失败不影响其他图。
    #              之前整个 ChatWorkflowService 初始化被一个 try/except 包裹，
    #              任何图构建失败都会导致 chat_workflow_service = None，前端收到 503。
    # 边界条件：至少 daily_chat 图必须构建成功，否则服务降级为 None。
    try:
        from app.workflow.events import ChatWorkflowEventPublisher
        from app.workflow.service import ChatWorkflowService

        app.state.chat_workflow_service = ChatWorkflowService(
            redis_repo=redis_repo,
            pg_repo=pg_repo,
            pg_client=pg_client,
            prompt_manager=prompt_manager,
            memory_manager=memory_manager,
            rag_orchestrator=rag_retrieval_orchestrator,
            user_profile_service=user_profile_service,
            event_publisher=ChatWorkflowEventPublisher(),
            # 注入 RAG 知识库 PG 仓库，供 InputReconstructionNode 加载 KNOWLEDGE_DOCS
            rag_pg_repo=rag_pg_repo,
        )
        logger.info("Phase 8.5 ChatWorkflowService 初始化完成")
    except Exception as e:
        app.state.chat_workflow_service = None
        logger.error(f"Phase 8.5 ChatWorkflowService 初始化失败 error={e}", exc_info=True)

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

    # 4. Phase 12/13: 注册 MCP 工具并初始化配置管理器
    # 做什么：初始化 ServerManager 加载外部 toolbox 配置 -> 注册内置工具 -> 从 PG 加载已有工具 -> 启动后台发现任务
    try:
        from app.mcp.server_manager import MCPServerManager
        from app.mcp.discovery_sync import DiscoverySyncEngine
        
        # 4.1 加载 Toolbox 配置到内存并执行全量发现 (阻塞式，确保 DB 最新)
        logger.info("开始加载外部 MCP Toolbox 配置并执行全量同步...")
        mcp_manager = MCPServerManager.get_instance()
        await mcp_manager.initialize(pg_client)
        
        discovery_engine = DiscoverySyncEngine.get_instance()
        await discovery_engine.sync_everything(pg_client)

        # 4.2 注册内置工具
        from app.mcp.registry import MCPToolRegistry
        from app.mcp.types import MCPToolSchema, ToolRiskLevel
        from app.repository.mcp_tool_pg import MCPToolPGRepo
        from app.skills.web_search.search_tool import (
            WEB_SEARCH_MEMORY_SCHEMA,
            build_web_search_schema,
            handle_searxng_search,
        )

        mcp_registry = MCPToolRegistry()

        # 构建搜索工具 Schema（一维搜索词数组，多策略并发由 handler 层自动处理）
        web_search_schema = build_web_search_schema()

        # 注册 SearXNG 网络搜索工具（L0 级低危只读工具，通过环境变量配置 SearXNG 地址）
        # 支持 memory_schema 多轮搜索记忆 + 多策略并发搜索（中文通用、中文新闻、英文通用）
        mcp_registry.register(
            name="web_search",
            schema=MCPToolSchema(
                name="web_search",
                description="通过 SearXNG 元搜索引擎执行网络搜索，获取最新互联网信息。"
                            "自动以多策略（中文通用、中文新闻、英文通用）并发搜索，结果去重合并。",
                core_purpose="搜索互联网获取最新信息",
                final_deliverable="格式化的搜索结果列表，包含标题、摘要、来源 URL 和引擎信息，"
                                 "以及知识卡片和相关搜索建议",
                tags=["search", "web", "internet", "搜索", "互联网", "网络", "信息检索"],
                category="utility",
                use_case_examples=[
                    "帮我搜索一下最近的科技新闻",
                    "查一下今天的天气",
                    "搜索 Python 异步编程教程",
                    "最近有什么关于 AI 的新闻",
                    "查找 2024 年诺贝尔奖获得者",
                ],
                parameters_schema=web_search_schema,
                risk_level=ToolRiskLevel.L0,
                memory_schema=WEB_SEARCH_MEMORY_SCHEMA,
            ),
            handler=handle_searxng_search,
        )
        logger.info("MCP 内置工具注册完成（web_search 多策略并发）")

        # 从 PG 加载已注册的工具（如果在 PG 中有额外的动态注册工具）
        if pg_client and hasattr(pg_client, 'session_factory') and pg_client.session_factory:
            from sqlalchemy.ext.asyncio import AsyncSession
            async with pg_client.session() as session:
                mcp_pg_repo = MCPToolPGRepo(session)
                pg_tools = await mcp_pg_repo.load_all()
            await mcp_registry.load_from_pg(pg_tools)

            # 将内存中所有工具持久化到 PG（内置工具写入 PG）
            # 注意：persist_to_pg 需要在同一个 session 中执行
            await mcp_registry.persist_to_pg(mcp_pg_repo)
            logger.info("MCP 工具 PG 持久化同步完成")

        # 4.3 启动后台异步任务，定期拉取更新
        mcp_sync_task = asyncio.create_task(
            discovery_engine.start_background_sync(pg_client, interval_seconds=3600)
        )
        app.state.mcp_sync_task = mcp_sync_task
        logger.info("MCP Toolbox 后台同步任务已启动")

        # 初始化 SkillRegistry：从 PG 加载所有 Skill 到内存缓存
        try:
            from app.mcp.skill_registry import SkillRegistry

            if pg_client and hasattr(pg_client, 'session_factory') and pg_client.session_factory:
                async with pg_client.session() as session:
                    skill_registry = SkillRegistry()
                    await skill_registry.load_from_pg(session)
                    logger.info("MCP Skill 注册中心初始化完成")
        except Exception as exc:
            logger.warning(f"MCP Skill 注册中心初始化失败: {exc}")

        # 初始化 ToolConfigManager：从 PG 加载工具配置到内存缓存
        # 做什么：加载 tool_configs 表的所有 ACTIVE 配置到内存。
        # 为什么这样做：工具在运行时通过 ToolConfigManager 读取配置，
        #              而不是直接读取 .env 环境变量。
        try:
            from app.config.tool_config_manager import ToolConfigManager
            from app.repository.tool_config_pg import ToolConfigPGRepo

            async with pg_client.session() as session:
                tool_cfg_repo = ToolConfigPGRepo(session)
                all_configs = await tool_cfg_repo.load_all()

            config_mgr = ToolConfigManager()
            config_mgr.load_from_pg(all_configs)
            app.state.tool_config_manager = config_mgr
            logger.info("MCP 工具配置管理器初始化完成")
        except Exception as exc:
            logger.warning(f"MCP 工具配置管理器初始化失败: {exc}")

    except Exception as exc:
        logger.warning(f"MCP 工具注册失败: {exc}")

    # 16. 启动 MCP 市场定时采集调度器
    # 做什么：每天一次从远程 Registry 采集 MCP Server 列表并持久化到 PG。
    # 为什么这样做：采集逻辑存在但从未被调用，需通过调度器接入运行生命周期。
    # mcp_discovery_scheduler = None
    # if pg_client:
    #     try:
    #         from app.mcp.market.scheduler import MarketDiscoveryScheduler
    #         mcp_discovery_scheduler = MarketDiscoveryScheduler(pg_client)
    #         await mcp_discovery_scheduler.start()
    #         app.state.mcp_discovery_scheduler = mcp_discovery_scheduler
    #         logger.info("MCP 市场定时采集调度器初始化完成（每天执行一次）")
    #     except Exception as e:
    #         logger.warning(f"MCP 市场定时采集调度器初始化失败 error={e}")
    # else:
    #     logger.warning("PG 客户端不可用，MCP 市场定时采集调度器跳过启动")

    # ============================================================
    # 内存守护进程：启动后台线程监控系统内存使用率
    # ============================================================
    # 做什么：启动独立线程运行 memory_guardian 轮询循环，监测系统内存使用率，
    #          超过阈值时触发 Windows 计划任务执行内存清理。
    # 为什么这样做：AI 模型长期运行可能产生内存泄漏，守护进程防止系统内存不足。
    # 边界条件：
    #   - 非 Windows 系统自动跳过
    #   - 通过 threading.Event 实现优雅停止
    #   - 线程启动失败不阻断服务启动（降级为仅记录警告）
    guardian_stop_event = threading.Event()
    guardian_thread = None
    try:
        from scripts.memory_guardian import GuardianConfig, run_guardian_loop
        guardian_cfg = GuardianConfig(
            task_name=settings.memory_guardian_task_name,
            threshold=settings.memory_guardian_threshold,
            release=settings.memory_guardian_release,
            interval=settings.memory_guardian_interval,
            cooldown=settings.memory_guardian_cooldown,
        )
        guardian_thread = threading.Thread(
            target=run_guardian_loop,
            args=(guardian_cfg, guardian_stop_event),
            name="memory-guardian",
            daemon=True,
        )
        guardian_thread.start()
        logger.info(
            f"内存守护线程已启动: "
            f"threshold={guardian_cfg.threshold:.1f}% "
            f"interval={guardian_cfg.interval}s"
        )
    except Exception as exc:
        logger.warning(f"内存守护线程启动失败（将降级运行）: {exc}")

    # ============================================================
    # Phase 13：Gating 权限治理服务初始化
    # ============================================================
    # 做什么：初始化 GatingService，包括审计日志仓储、SSE 推送通道、
    #         后台超时检测调度器。GatingService 是工具调用权限审批的核心服务。
    # 为什么这样做：必须在所有 MCP 工具注册完成后初始化，确保 GatingService
    #              能够在工具调用时正确拦截高危操作。
    # 边界条件：
    #   - 依赖 pg_client 提供数据库会话
    #   - 依赖 sse_manager 提供前端推送通道
    #   - 依赖 redis_client 提供缓存加速（可选）
    #   - 初始化失败不阻断主流程（降级为仅记录警告）
    gating_service = None
    if pg_client:
        try:
            from app.gating.service import GatingService
            from app.repository.audit_log_pg import AuditLogPGRepo
            from app.api.sse import sse_manager

            # AuditLogPGRepo 遵循与其他 repo 相同的构造模式，接收 PostgresClient 实例
            audit_repo = AuditLogPGRepo(pg_client)
            gating_service = GatingService(
                audit_repo=audit_repo,
                redis_client=redis_client,
                sse_manager=sse_manager,
                timeout_seconds=300,  # 5 分钟超时
            )

            # 启动后台超时检测调度器
            await gating_service.start_timeout_scheduler()

            app.state.gating_service = gating_service
            logger.info("[Gating] Phase 13 GatingService 初始化完成（5 分钟超时检测已启动）")
        except Exception as e:
            app.state.gating_service = None
            logger.warning(f"[Gating] GatingService 初始化失败（将降级运行）: {e}")

    # ============================================================
    # Phase 10：任务状态机与中断恢复服务初始化
    # ============================================================
    # 做什么：初始化 SnapshotManager、StateTransitionManager 和 RecoveryCoordinator。
    #         这些服务用于任务级状态管理、快照持久化和中断恢复。
    # 为什么这样做：Phase 10 要求任务级别生命周期管理，与 DAG 节点级状态分离。
    # 边界条件：
    #   - pg_client 存在时使用 PG 持久化，否则仅使用 Redis
    #   - redis_client 存在时使用 Redis 快速检查点，否则降级
    #   - 初始化失败不阻断主流程（降级为仅记录警告）
    # ============================================================
    try:
        from app.state import SnapshotManager, StateTransitionManager

        # 初始化快照管理器（Redis + PG 双写）
        pg_pool_for_state = None
        if pg_client:
            # 使用 pg_client.engine 作为连接池
            pg_pool_for_state = pg_client

        snapshot_manager = SnapshotManager(
            pg_pool=pg_pool_for_state,
            redis_client=redis_client,
            checkpoint_ttl=86400,       # 24h
            snapshot_ttl=604800,        # 7d
        )

        # 初始化状态跃迁管理器
        transition_log_pool = None
        if pg_client:
            transition_log_pool = pg_client

        state_transition_manager = StateTransitionManager(
            pg_pool=transition_log_pool,
        )

        # 初始化恢复协调器
        from app.state import RecoveryCoordinator
        recovery_coordinator = RecoveryCoordinator(
            snapshot_manager=snapshot_manager,
            checkpoint_manager=None,  # 需要时由上层注入
        )

        # 注册到 app.state
        app.state.snapshot_manager = snapshot_manager
        app.state.state_transition_manager = state_transition_manager
        app.state.recovery_coordinator = recovery_coordinator

        logger.info("[Phase 10] 任务状态机与中断恢复服务初始化完成")
    except Exception as e:
        app.state.snapshot_manager = None
        app.state.state_transition_manager = None
        app.state.recovery_coordinator = None
        logger.warning(f"[Phase 10] 任务状态机与中断恢复服务初始化失败（将降级运行）: {e}")

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
    
    # 停止 MCP 后台同步任务
    mcp_sync_task = getattr(app.state, "mcp_sync_task", None)
    if mcp_sync_task:
        mcp_sync_task.cancel()
        logger.info("MCP Toolbox 后台同步任务已停止")

    # Phase 13：停止 Gating 超时检测调度器
    gating_svc = getattr(app.state, "gating_service", None)
    if gating_svc:
        try:
            await gating_svc.stop_timeout_scheduler()
            logger.info("[Gating] Gating 超时检测调度器已停止")
        except Exception as e:
            logger.warning(f"[Gating] 停止 Gating 超时检测调度器异常 error={e}")

    if rollover_task:
        rollover_task.cancel()

    # 停止内存守护进程线程
    # 做什么：发送停止信号给 guardian 线程，等待其优雅退出。
    # 为什么这样做：防止守护线程在服务关闭后仍在后台运行，造成资源泄露。
    if guardian_thread is not None and guardian_thread.is_alive():
        try:
            guardian_stop_event.set()
            guardian_thread.join(timeout=5)
            if guardian_thread.is_alive():
                logger.warning("内存守护线程未能在 5 秒内停止，将被强制回收")
            else:
                logger.info("内存守护线程已停止")
        except Exception as e:
            logger.warning(f"停止内存守护线程异常 error={e}")

    # 停止 MCP 市场定时采集调度器
    if getattr(app.state, "mcp_discovery_scheduler", None):
        try:
            await app.state.mcp_discovery_scheduler.stop()
            logger.info("MCP 市场定时采集调度器已停止")
        except Exception as e:
            logger.warning(f"MCP 市场定时采集调度器停止异常 error={e}")

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
from fastapi.exceptions import RequestValidationError
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

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """捕获 Pydantic 校验失败（422）并输出详细错误到日志"""
    errors = exc.errors()
    body = await request.body()
    logger.error(f"[422 校验失败] path={request.url.path} method={request.method} errors={errors}")
    logger.error(f"[422 校验失败] request_body={body.decode('utf-8', errors='replace')}")
    return JSONResponse(
        status_code=422,
        content={
            "code": 422,
            "msg": "请求参数校验失败",
            "data": {"detail": errors, "body": body.decode('utf-8', errors='replace')},
            "trace_id": request.headers.get("X-Trace-ID", ""),
        },
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "*",
            "Access-Control-Allow-Headers": "*",
        },
    )


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
#               （包括错误响应）都包含正确的 CORS 头。
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
app.include_router(long_answer_router)
app.include_router(prompt_router)
app.include_router(rag_router)
app.include_router(telemetry_router)
app.include_router(http_router)
app.include_router(sse_router)
app.include_router(memory_router)
app.include_router(user_profile_router)
app.include_router(mcp_market_router)
app.include_router(mcp_local_router)
app.include_router(mcp_skill_router)
app.include_router(tool_config_router)
app.include_router(gating_router)
app.include_router(workflow_command_router)

# 导入 health 路由 (避免循环导入)
from app.api.health import router as health_router
app.include_router(health_router)


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=settings.ai_service_port, reload=False)




