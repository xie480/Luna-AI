"""TTS 缓存清理工具。"""

from __future__ import annotations

import time
from pathlib import Path

from app.logger import logger


def cleanup_dir(root: str | Path, keep_hours: int = 24, suffixes: tuple[str, ...] = (".wav", ".mp3", ".ogg")) -> int:
    """清理指定目录下过期的音频文件。"""
    root_path = Path(root)
    if not root_path.exists():
        return 0

    cutoff = time.time() - keep_hours * 3600
    removed = 0

    for p in root_path.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in suffixes:
            continue
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
                removed += 1
                logger.debug("已清理过期 TTS 缓存: {}", p)
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.warning("清理 TTS 缓存失败 {}: {}", p, e)
            
    return removed
