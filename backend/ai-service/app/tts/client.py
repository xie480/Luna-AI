"""
TTS 客户端模块，用于与 GPT-SoVITS 或 OpenAI-compatible TTS 服务通信。

做什么：封装 TTS API 的 HTTP 调用，支持同步生成音频数据或保存到文件。
为什么这样做：统一 TTS 调用入口，便于切换底层 TTS 引擎（GPT-SoVITS / OpenAI）。
输入输出：
    - synthesize: 输入文本和参数，返回音频字节流 (bytes)
    - synthesize_to_file: 输入文本和参数，返回音频文件的 Path
边界条件：
    - 自动将文本中的 "luna"（大小写不敏感）按语言替换：日语替换为 "ルナ"，其他语言替换为 "露娜"，使 TTS 发音正确
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

    def _map_text_lang(self, lang: str) -> str:
        """
        将语言代码映射为 GPT-SoVITS 服务端支持的中文全称。

        做什么：GPT-SoVITS 服务端期望 text_lang 为中文全称（如"中文"、"英语"），
                而非 ISO 语言代码（如"zh"、"en"）。此方法将常见 ISO 代码或缩写
                映射为服务端接受的格式。
        为什么这样做：避免因语言参数格式不合法导致服务端 index() 越界错误。
        输入：
            lang: 语言标识（ISO 代码或缩写）
        输出：
            映射后的中文全称，未知语言默认为"中文"
        """
        lang_map = {
            "zh": "中文",
            "zh-cn": "中文",
            "zh-chs": "中文",
            "en": "英语",
            "en-us": "英语",
            "ja": "日语",
            "jp": "日语",
            "ko": "韩语",
            "kr": "韩语",
            "yue": "粤语",
            "cantonese": "粤语",
        }
        return lang_map.get(lang.lower(), "中文")

    async def synthesize_speech(
        self,
        text: str,
        emotion: str = "default",
        model: Optional[str] = None,
        voice: Optional[str] = None,
        text_language: str = "zh",
        response_format: Optional[str] = None,
        speed: Optional[float] = None,
        extra_params: Optional[dict] = None,
    ) -> Path:
        """生成 TTS 音频并返回文件路径（兼容旧调用方接口）。

        做什么：`synthesize_speech` 是 `synthesize_to_file` 的兼容别名。
                有些调用方（如 Gating 推送流程）使用此方法名调用 TTS，
                将其委托给 `synthesize_to_file`，保证接口兼容。
        为什么这样做：避免因方法名不匹配导致 AttributeError，同时保持
                      `synthesize_to_file` 作为统一入口。
        输入输出：同 `synthesize_to_file`。
        """
        return await self.synthesize_to_file(
            text=text,
            emotion=emotion,
            model=model,
            voice=voice,
            text_language=text_language,
            response_format=response_format,
            speed=speed,
            extra_params=extra_params,
        )

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
        
        # 根据语言替换 "Luna" 以确保 TTS 发音正确：
        # - 日语 (ja)：替换为片假名 "ルナ"
        # - 其他语言：替换为中文 "露娜"
        luna_replacement = 'ルナ' if text_language.lower() in ('ja', 'jp') else '露娜'
        processed_text = re.sub(r'(?i)luna', luna_replacement, text)
        
        # model 格式: GPT-SoVITS 期望 "GSVI-{version}"（如 "GSVI-v4"）
        # voice 格式: 说话人名称（如 "阿米娅"）
        model_name = model or f"GSVI-{self.cfg.model_version}"
        voice_name = voice or self.cfg.default_voice
        text_lang_cn = self._map_text_lang(text_language)
        
        payload = {
            "model": model_name,
            "input": processed_text,
            "voice": voice_name,
            "response_format": response_format or self.cfg.response_format,
            "speed": speed if speed is not None else self.cfg.speed,
            "other_params": {
                "emotion": emotion,
                "text_lang": text_lang_cn,
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
            logger.error("TTS 服务调用失败: {} (URL: {})", e, url)
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
            logger.debug("TTS 生成成功，保存至: {}", out_path)
            return out_path
        except Exception as e:
            logger.error("TTS 生成到文件失败: {}", e)
            raise

    async def close(self):
        """关闭 HTTP 客户端。"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()


# 全局默认 TTS 客户端实例
# 使用 from_settings() 从 .env / 环境变量读取配置
tts_client = GSVITTSClient(TTSConfig.from_settings())
