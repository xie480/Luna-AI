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

from app.types.constants import ModelSize

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
    ai_service_port: int = 8001
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
    reserved_output_tokens: int = 2048

    # memory 槽位压缩治理开关。
    # 做什么：控制聊天主链路是否在最终 Prompt 装配前执行 memory 槽位压缩治理。
    # 为什么这样做：上下文压缩治理属于增强能力，需要能在联调与回滚时快速关闭。
    memory_slot_compression_enabled: bool = True

    # memory 槽位总 Token 上限。
    # 做什么：限制 LONG_TERM_MEMORY、EXTERNAL_KNOWLEDGE、USER_PROFILE、会话摘要等变量的总 Token 体积。
    # 为什么这样做：当前 Prompt 最易膨胀的部分是 memory 槽位，必须独立治理而不是等最终 Prompt 超限后再整体截断。
    memory_slot_max_tokens: int = 12000

    # 单个 memory 变量的 Token 上限。
    # 做什么：当某一类变量单独过长时，优先对该变量执行定向压缩。
    # 为什么这样做：便于区分究竟是哪一类上下文导致膨胀，也更符合现有 Prompt 模板结构。
    memory_slot_single_variable_max_tokens: int = 4000

    # 统一历史背景最终上限。
    # 做什么：限制历史背景降级后的统一文本上限，并作为硬截断保护目标。
    # 为什么这样做：统一合并后的历史背景仍可能过长，需要最终可控的单字段上限。
    historical_context_max_tokens: int = 3000

    # 压缩回放预览最大字符数。
    # 做什么：限制审计中 preview_before / preview_after 的长度。
    # 为什么这样做：回放只需要最小可解释片段，不能让 audit_logs.details 因预览过长而膨胀。
    compression_replay_preview_max_chars: int = 400

    # 压缩审计开关。
    # 做什么：控制上下文压缩相关审计日志与 Span 是否写入既有 telemetry 链路。
    # 为什么这样做：联调或问题回滚时需要快速停写压缩审计，但不能影响聊天主链路。
    compression_audit_enabled: bool = True

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
    rerank_top_k: int = 3

    # ============================================================
    # MCP 工具执行配置
    # ============================================================
    # 工具执行默认超时（秒）
    mcp_tool_timeout: float = 30.0
    # 工具执行最大重试次数
    mcp_tool_max_retries: int = 2

    # ============================================================
    # Skill 三阶段 Agent 执行配置
    # ============================================================
    # 最大执行步长
    skill_max_execution_steps: int = 30
    # 最大退回次数
    skill_max_fallback_count: int = 2

    # ============================================================
    # 内存守护进程配置 (memory_guardian)
    # ============================================================
    # Windows 计划任务名称（用于触发内存清理）
    memory_guardian_task_name: str = "MemoryBoost"
    # 内存占用率触发阈值（百分比，达到此值时触发计划任务）
    memory_guardian_threshold: float = 90.0
    # 释放阈值（百分比，内存回落到此值以下后允许再次触发）
    memory_guardian_release: float = 80.0
    # 轮询间隔（秒）
    memory_guardian_interval: int = 5
    # 触发后冷却时间（秒）
    memory_guardian_cooldown: int = 120

    # ============================================================
    # LLM 调用频率限制配置
    # ============================================================
    # 调用大模型间隔时间(秒)
    llm_call_interval_seconds: float = 0.0

    # LLM 响应模式：streaming（流式） / unified（统一非流式）
    # unified 模式下后端一次性调用 LLM 获取完整回复，经 StreamParser 解析后，
    # 通过单个 ChatUnifiedResponsePayload 将所有内容（回复文本、思考、情绪、音频 URI）
    # 统一推送给前端，前端再按语义切分后逐气泡渲染并同步 TTS 口型
    llm_response_mode: str = "unified"

    # ============================================================
    # TTS 服务配置
    # ============================================================
    # TTS 服务启动脚本路径（如配置，主程序启动时将自动拉起）
    tts_bat_path: str = ""

    # TTS API 基础地址（GPT-SoVITS 或 OpenAI-compatible TTS 服务的 HTTP 地址）
    tts_base_url: str = "http://127.0.0.1:8999"
    # TTS API 端点路径
    tts_endpoint: str = "/v1/audio/speech"
    # TTS 默认模型名称（角色名，如"阿米娅"）
    tts_default_model: str = "阿米娅"
    # TTS 默认音色名称
    tts_default_voice: str = "阿米娅"
    # TTS 输出音频格式：mp3 / wav / ogg
    tts_response_format: str = "mp3"
    # TTS 语速倍率（1.0 为正常语速）
    tts_speed: float = 1.0
    # TTS HTTP 请求超时时间（秒）
    tts_timeout: float = 120.0
    # TTS 缓存目录（存放生成的音频文件）
    tts_cache_dir: str = "data/tts_cache"
    # GPT-SoVITS 服务端输出目录（用于同步备份已生成的音频）
    tts_service_outputs_dir: str = ""
    # TTS 缓存文件保留时长（小时），超过此时间的缓存将被清理
    tts_cleanup_keep_hours: int = 24

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

    def get_model_config(self, size: ModelSize) -> dict[str, Any]:
        """
        获取指定规格的模型配置
        """
        if size == ModelSize.LARGE:
            return self._large_model
        elif size == ModelSize.MEDIUM:
            return self._medium_model
        elif size == ModelSize.SMALL:
            return self._small_model
        return self._medium_model # 默认返回中模型

global_config_container = GlobalConfigContainer()
