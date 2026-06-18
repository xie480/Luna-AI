"""
TTS 配置文件。

做什么：定义 TTS 客户端连接参数的数据结构。
        提供 from_settings 工厂方法，从全局 Settings 实例构建配置，
        使所有 TTS 参数均从 .env 或环境变量读取，消除硬编码。
为什么这样做：遵循 agent.md 禁止硬编码魔法字符串的规范，统一配置入口。
输入输出：
    - TTSConfig: 包含 TTS API 连接参数、缓存路径、清理策略的 dataclass
边界条件：
    - tts_service_outputs_dir 为空字符串时，service_outputs_dir 属性返回 None
    - cache_dir 默认使用 data/tts_cache（相对路径，相对于进程工作目录）
异常行为：
    - 如果 .env 中的路径无法创建目录，在首次访问时由调用方处理异常
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class TTSConfig:
    """
    TTS 客户端配置。

    做什么：存储 GPT-SoVITS 或 OpenAI-compatible TTS 服务的连接参数。
    属性：
        - base_url: TTS 服务 HTTP 基础地址
        - endpoint: API 端点路径
        - model_version: GPT-SoVITS 模型版本号（如 "v4"），用于构建 "GSVI-{version}" 格式的 model 参数
        - default_model / default_voice: 默认模型/音色名称
        - response_format: 输出音频格式
        - speed: 语速倍率
        - timeout: HTTP 请求超时秒数
        - cache_dir: 本地缓存目录
        - service_outputs_dir: GPT-SoVITS 服务端输出目录（可选）
        - cleanup_keep_hours: 缓存文件保留时长
    """

    # TTS API 基础地址，例如 http://127.0.0.1:8999（GPT-SoVITS）或云 API 地址
    base_url: str = "http://127.0.0.1:8999"
    # TTS API 端点路径，例如 /v1/audio/speech（OpenAI-compatible）或 /tts
    endpoint: str = "/v1/audio/speech"
    # GPT-SoVITS 模型版本号，用于构建 model="GSVI-{version}" 格式
    # GPT-SoVITS 服务端通过 model.split("-")[1] 解析版本号，错误格式会导致 IndexError
    model_version: str = "v4"
    # 默认模型/角色名称，如"阿米娅"
    default_model: str = "阿米娅"
    # 默认音色名称
    default_voice: str = "阿米娅"
    # 输出音频格式：mp3 / wav / ogg
    response_format: str = "mp3"
    # 语速倍率，1.0 为正常语速
    speed: float = 1.0
    # HTTP 请求超时时间（秒）
    timeout: float = 120.0
    # 缓存目录，存放已生成的音频文件
    cache_dir: Path = field(default_factory=lambda: Path("data/tts_cache"))
    # GPT-SoVITS 服务端输出目录，用于同步备份已生成的音频（可选，为空则不使用）
    service_outputs_dir: Optional[Path] = None
    # 缓存文件保留时长（小时），超过此时间的缓存将被清理
    cleanup_keep_hours: int = 24

    @classmethod
    def from_settings(cls) -> "TTSConfig":
        """
        从全局 Settings 实例构建 TTSConfig。

        做什么：读取 app.config.settings.settings 单例中所有 tts_* 前缀的配置项，
                将字符串路径自动转换为 Path 对象，并返回完整的 TTSConfig 实例。
        为什么这样做：全局 Settings 已从 .env 和环境变量加载配置，
                     避免 TTSConfig 重复实现配置加载逻辑，保持单一配置入口。
        输入输出：
            - 返回: TTSConfig 实例，所有字段已从 Settings 赋值
        边界条件：
            - tts_service_outputs_dir 为空字符串时，service_outputs_dir 设为 None
            - tts_model_version 未配置时默认为 "v4"
        """
        # 延迟导入，避免循环依赖
        from app.config.settings import settings

        service_outputs: Optional[Path] = None
        if settings.tts_service_outputs_dir:
            service_outputs = Path(settings.tts_service_outputs_dir)

        return cls(
            base_url=settings.tts_base_url,
            endpoint=settings.tts_endpoint,
            model_version=settings.tts_model_version,
            default_model=settings.tts_default_model,
            default_voice=settings.tts_default_voice,
            response_format=settings.tts_response_format,
            speed=settings.tts_speed,
            timeout=settings.tts_timeout,
            cache_dir=Path(settings.tts_cache_dir),
            service_outputs_dir=service_outputs,
            cleanup_keep_hours=settings.tts_cleanup_keep_hours,
        )
