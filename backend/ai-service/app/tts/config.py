"""TTS 配置文件。"""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TTSConfig:
    """TTS 客户端配置。"""

    base_url: str = "http://127.0.0.1:9880"
    endpoint: str = "/tts"
    default_model: str = "" # 在GPT-SoVITS V4 API中，通常通过 reference_audio 或角色映射来指定
    default_voice: str = ""
    response_format: str = "wav"  # mp3 / wav / ogg
    speed: float = 1.0
    timeout: float = 120.0
    cache_dir: Path = field(default_factory=lambda: Path("data/tts_cache"))
    # service_outputs_dir: Path = field(default_factory=lambda: Path(r"E:\modelscope\dir\GPT-SoVITS-1007-cu128\GPT-SoVITS-1007-cu124\outputs"))
    cleanup_keep_hours: int = 24
