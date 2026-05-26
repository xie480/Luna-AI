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
    # LLM 接入配置
    # ============================================================

    # OpenAI 兼容 API 的 Base URL
    # 本地 Ollama: http://localhost:11434/v1
    # 本地 vLLM:   http://localhost:8000/v1
    # OpenAI:     https://api.openai.com/v1
    openai_api_base: str = "https://api.openai.com/v1"

    # API Key（本地模型可设为 "dummy" 或 "not-needed"）
    openai_api_key: str = ""

    # 模型名称
    # OpenAI: gpt-4o, gpt-4o-mini, gpt-3.5-turbo
    # Ollama: llama3.1, qwen2.5, deepseek-r1
    # vLLM:   Qwen/Qwen2.5-7B-Instruct
    model_name: str = "gpt-3.5-turbo"

    # ============================================================
    # 压缩模型配置 (用于后台摘要压缩)
    # ============================================================

    compression_model_name: str = "gpt-4o-mini"
    compression_api_base: str = "https://api.openai.com/v1"
    compression_api_key: str = ""

    # ============================================================
    # 上下文管理配置
    # ============================================================

    # 最大上下文 Token 总数（包含 System Prompt + 历史 + 当前消息 + 输出预留）
    # 此值需根据使用的模型调整：
    #   - GPT-3.5-turbo: 16384
    #   - GPT-4o: 128000
    #   - Qwen2.5-7B: 32768
    max_context_tokens: int = 8192

    # 为模型输出预留的 Token 数
    reserved_output_tokens: int = 2048

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
