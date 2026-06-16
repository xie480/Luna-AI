"""TTS 模块初始化。"""

from app.tts.client import tts_client, GSVITTSClient
from app.tts.config import TTSConfig
from app.tts.emotion_map import map_emotion
from app.tts.cleanup import cleanup_dir

__all__ = ["tts_client", "GSVITTSClient", "TTSConfig", "map_emotion", "cleanup_dir"]
