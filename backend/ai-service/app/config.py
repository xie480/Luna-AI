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

from pydantic_settings import BaseSettings, SettingsConfigDict


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
    # LLM 接入配置 (已废弃，由 Go 端通过 gRPC 动态推送预设)
    # ============================================================
    # 彻底移除对 .env 中 LLM 配置的依赖

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
    # 模型配置
    # ============================================================

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


# 全局单例
settings = Settings()

import asyncio
from typing import Dict, Any

class GlobalConfigContainer:
    """
    全局动态配置容器
    
    做什么：维护动态配置状态，接收 Go 的 gRPC 推送时更新配置并触发底层 LLM Client 的重新初始化。
    """
    def __init__(self):
        self._large_model: Dict[str, Any] = {}
        self._medium_model: Dict[str, Any] = {}
        self._small_model: Dict[str, Any] = {}
        self._lock = asyncio.Lock()
        
    async def update_preset_config(self, large_model: Dict[str, Any], medium_model: Dict[str, Any], small_model: Dict[str, Any]):
        """
        更新预设配置并触发重载
        """
        async with self._lock:
            self._large_model = large_model
            self._medium_model = medium_model
            self._small_model = small_model
            
            # 触发 LLM Client 重载
            from app.llm.client import llm_client, compression_llm_client
            llm_client.reload_config()
            compression_llm_client.reload_config()
            
            # 使用 loguru logger（app.logger 仅导出 logger 实例，没有 get_logger 函数）
            from app.logger import logger
            logger.info("API 配置预设已更新，LLM Client 已重载")

    def get_model_config(self, size: str) -> Dict[str, Any]:
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
