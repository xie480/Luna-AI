"""
Luna AI 全局配置模块

做什么：使用 Pydantic Settings 管理系统配置，支持从环境变量和 .env 文件加载。
        配置项涵盖 AI 服务端口、gRPC 端口、LLM 接入参数和上下文管理参数。
为什么这样做：集中管理所有配置项，避免硬编码，满足 agent.md 中禁止硬编码魔法字符串的规范。
输入输出：
    - settings: 全局配置单例
边界条件：
    - 环境变量优先级高于 .env 文件
    - 缺失的配置项使用默认值
异常行为：
    - .env 文件不存在时不影响启动（使用默认值）
    - 配置加载失败时抛出 Pydantic 校验异常
"""

from pathlib import Path
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

# .env 文件位于项目根目录（../../../ 相对于 backend/ai-service/app/config/）
# settings.py 的路径为 backend/ai-service/app/config/settings.py
# 需要向上 5 层才能到达项目根目录
# Path(__file__).parent -> config/
# Path(__file__).parent.parent -> app/
# Path(__file__).parent.parent.parent -> ai-service/
# Path(__file__).parent.parent.parent.parent -> backend/
# Path(__file__).parent.parent.parent.parent.parent -> Luna-AI/ (项目根目录，存放 .env)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
_ENV_FILE_PATH = str(_PROJECT_ROOT / '.env')


class Settings(BaseSettings):
    """
    全局配置结构

    做什么：定义 Luna AI 服务的所有可配置参数。
    为什么这样做：集中管理配置，便于维护和调试。
    """

    # ============================================================
    # 服务端口配置
    # ============================================================

    # HTTP/FastAPI 服务端口
    ai_service_port: int = 8000
    # gRPC 服务端口
    grpc_port: int = 50051

    # ============================================================
    # 日志配置
    # ============================================================

    # 日志级别：DEBUG / INFO / WARNING / ERROR
    log_level: str = "INFO"

    # ============================================================
    # AI 服务配置
    # ============================================================
    ai_service_address: str = "localhost:50051"

    # ============================================================
    # Redis 配置
    # ============================================================
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str = ""
    redis_db: int = 0

    # ============================================================
    # PostgreSQL 配置
    # ============================================================
    db_host: str = "localhost"
    db_port: int = 5432
    db_user: str = "postgres"
    db_password: str = "postgres"
    db_name: str = "luna"

    # ============================================================
    # Qdrant 配置
    # ============================================================
    qdrant_address: str = "localhost:6333"

    # ============================================================
    # 上下文管理配置
    # ============================================================

    # 最大上下文 Token 总数（包含 System Prompt + 历史 + 当前消息 + 输出预留）
    # 此值需根据使用的模型调整：
    #   - GPT-3.5-turbo: 16384
    #   - GPT-4o: 128000
    #   - Qwen2.5-7B: 32768
    max_context_tokens: int = 128000

    # 为模型输出预留的 Token 数
    reserved_output_tokens: int = 60000

    # ============================================================
    # 模型路径配置（支持从 .env 文件读取）
    # 例如：
    #   EMBEDDING_MODEL_PATH=D:/AI_Models/bge-base-zh-v1.5-model
    #   RERANK_MODEL_PATH=D:/AI_Models/bge-reranker-v2-m3-model
    # 如果未配置，则跳过模型加载（仅影响记忆检索功能，不阻断其他服务）
    # ============================================================

    # Embedding 模型路径，用于向量化文本
    # 使用 bge-base-zh-v1.5 或其他 SentenceTransformer 模型
    embedding_model_path: str = ""
    # Rerank 模型路径，用于重排序检索结果
    # 使用 bge-reranker-v2-m3 或其他 CrossEncoder 模型
    rerank_model_path: str = ""

    # ============================================================
    # 检索配置
    # ============================================================
    retrieval_top_k: int = 5

    # ============================================================
    # Pydantic Settings 配置
    # ============================================================

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE_PATH,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def redis_addr(self) -> str:
        """返回 Redis 连接地址字符串"""
        return f"{self.redis_host}:{self.redis_port}"

    @property
    def postgres_conn_str(self) -> str:
        """返回 PostgreSQL 连接字符串"""
        return f"postgresql+asyncpg://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"


# 全局单例
settings = Settings()

import asyncio

class GlobalConfigContainer:
    """
    全局动态配置容器
    
    做什么：维护动态配置状态，接收 Go 的 gRPC 推送时更新配置并触发底层 LLM Client 的重新初始化。
    """
    def __init__(self):
        self._large_model: dict[str, Any] = {}
        self._medium_model: dict[str, Any] = {}
        self._small_model: dict[str, Any] = {}
        self._lock = asyncio.Lock()
        
    async def update_preset_config(self, large_model: dict[str, Any], medium_model: dict[str, Any], small_model: dict[str, Any]):
        """
        更新预设配置并触发重载
        """
        async with self._lock:
            self._large_model = large_model
            self._medium_model = medium_model
            self._small_model = small_model
            
            # 触发 LLM Client 重载
            from app.llm.client import compression_llm_client, llm_client
            llm_client.reload_config()
            compression_llm_client.reload_config()
            
            # 使用 loguru logger（app.logger 仅导出 logger 实例，没有 get_logger 函数）
            from app.logger import logger
            logger.info("API 配置预设已更新，LLM Client 已重载")

    def get_model_config(self, size: str) -> dict[str, Any]:
        """
        获取指定规格的模型配置
        """
        if size == "large":
            return self._large_model
        elif size == "medium":
            return self._medium_model
        elif size == "small":
            return self._small_model
        return self._medium_model # 默认返回中模型

global_config_container = GlobalConfigContainer()
