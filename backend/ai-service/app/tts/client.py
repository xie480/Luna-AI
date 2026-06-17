"""
TTS 客户端模块，用于与 GPT-SoVITS 或 OpenAI-compatible TTS 服务通信。

做什么：封装 TTS API 的 HTTP 调用，支持同步生成音频数据或保存到文件。
为什么这样做：统一 TTS 调用入口，便于切换底层 TTS 引擎（GPT-SoVITS / OpenAI）。
输入输出：
    - synthesize: 输入文本和参数，返回音频字节流 (bytes)
    - synthesize_to_file: 输入文本和参数，返回音频文件的 Path
边界条件：
    - 自动将文本中的 "luna"（大小写不敏感）替换为 "露娜"，使 TTS 发音正确
    - 缓存目录不存在时自动创建
异常行为：
    - HTTP 请求失败时抛出 RuntimeError
    - TTS 服务不可达时由 httpx 抛出超时/连接异常
"""

from __future__ import annotations

import httpx
from typing import Optional
from pathlib import Path

from app.logger import logger
from app.tts.config import TTSConfig
from app.utils.snowflake import generate_string_id


class GSVITTSClient:
    """
    GPT-SoVITS / OpenAI-compatible TTS 客户端。

    做什么：管理 TTS HTTP 连接，提供文本转语音的核心方法。
    为什么这样做：封装底层 API 差异，使用方只需调用 synthesize 或 synthesize_to_file。
    """
    
    def __init__(self, cfg: TTSConfig):
        """
        初始化 TTS 客户端。

        输入:
            cfg: TTSConfig 实例，包含 API 地址、超时、缓存路径等配置
        边界条件:
            - 如果 cache_dir 不存在，会自动创建
            - HTTP 客户端在首次请求时懒加载
        """
        self.cfg = cfg
        self.cfg.cache_dir.mkdir(parents=True, exist_ok=True)
        # 确保使用 httpx 异步客户端
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.cfg.timeout)
        return self._client

    async def synthesize(
        self,
        text: str,
        emotion: str = "default",
        model: Optional[str] = None,
        voice: Optional[str] = None,
        text_language: str = "zh",
        response_format: Optional[str] = None,
        speed: Optional[float] = None,
        extra_params: Optional[dict] = None,
    ) -> bytes:
        """调用 TTS 服务生成音频流。"""
        import re
        
        # 将各种大小写形式的 luna 替换为“露娜”，使 TTS 发音正确
        processed_text = re.sub(r'(?i)luna', '露娜', text)
        
        payload = {
            "model": model or self.cfg.default_model,
            "input": processed_text,
            "voice": voice or self.cfg.default_voice,
            "response_format": response_format or self.cfg.response_format,
            "speed": speed if speed is not None else self.cfg.speed,
            "other_params": {
                "emotion": emotion,
                "text_lang": text_language,
            },
        }
        if extra_params:
            payload["other_params"].update(extra_params)

        url = f"{self.cfg.base_url}{self.cfg.endpoint}"
        client = await self._get_client()
        
        try:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return resp.content
        except httpx.HTTPError as e:
            logger.error("TTS 服务调用失败: %s (URL: %s)", e, url)
            raise RuntimeError(f"TTS 合成失败: {e}") from e

    async def synthesize_to_file(self, text: str, emotion: str = "default", **kwargs) -> Path:
        """生成音频并保存到本地缓存目录，返回文件路径。"""
        # 生成基于雪花算法的唯一文件名
        file_id = generate_string_id()
        fmt = kwargs.get("response_format") or self.cfg.response_format
        out_name = f"tts_{file_id}.{fmt}"
        
        try:
            data = await self.synthesize(text=text, emotion=emotion, **kwargs)
            out_path = self.cfg.cache_dir / out_name
            out_path.write_bytes(data)
            logger.debug("TTS 生成成功，保存至: %s", out_path)
            return out_path
        except Exception as e:
            logger.error("TTS 生成到文件失败: %s", e)
            raise

    async def close(self):
        """关闭 HTTP 客户端。"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()


# 全局默认 TTS 客户端实例
# 使用 from_settings() 从 .env / 环境变量读取配置
tts_client = GSVITTSClient(TTSConfig.from_settings())
