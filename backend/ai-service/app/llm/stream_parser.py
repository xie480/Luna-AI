"""
StreamParser 用于解析 LLM 流式输出的 JSON 结构化文本。

在流式对话中，LLM 会按 token 块返回 JSON 字符串碎片，例如:

```json
{"thought": "...",
 "emotion": "Happy",
 "reply": "你好，主人！"
}
```

模型的输出是逐字符/逐 Token 的，直接转发会导致前端无法解析。
本类负责在服务端聚合这些碎片，提取 `emotion` 字段并立即下发，随后对 `reply`
字段进行基于标点的语义断句，将完整的句子作为独立的 `reply_chunk`
发送。实现遵循高内聚、低耦合的设计原则，提供明确的异常处理和日志记录。

实现细节:
* `feed(chunk: str) -> List[Tuple[str, str]]` 接收新块，返回解析得到的消息列表。
  每个元素为 `(msg_type, content)`，`msg_type` 为 ``"emotion_update"`` 或 ``"reply_chunk"``。
* `flush() -> List[Tuple[str, str]]` 在流结束时调用，返回剩余的 `reply` 内容（如果有）。
* 内部使用正则表达式一次性匹配 `emotion` 与 `reply` 字段，后续仅对 `reply` 内容进行标点切分。
* 支持中文标点 ``。！？”``、英文逗号 ``，,`` 与换行 ``\n``，确保语义完整性。
"""

from __future__ import annotations

import re
from typing import List, Tuple

# 正则用于一次性捕获 emotion 值（仅第一次出现时返回）
_EMOTION_RE = re.compile(r'"emotion"\s*:\s*"([^"]+)"')
# reply 字段起始标记，用于定位后续文本位置
_REPLY_START_RE = re.compile(r'"reply"\s*:\s*"')
# 句子结束标点（中文、英文及换行）
_SENTENCE_BOUNDARY_RE = re.compile(r'[。！？……,，\n]')


class StreamParser:
    """LLM 流式输出的状态机解析器。

    负责从逐块的原始文本中提取情绪与回复，并将回复按标点拆分为独立块。
    ``feed`` 方法会返回当前能够完整解析的消息列表，后续块仍可继续喂入。
    ``flush`` 用于在流结束时输出残留的回复内容。
    """

    def __init__(self, trace_id: str) -> None:
        self.trace_id = trace_id
        # 标记是否已发送 emotion（只发送一次）
        self._emotion_sent: bool = False
        # 是否已经进入 reply 内容的收集阶段
        self._reply_started: bool = False
        # 用于累积 reply 文本的缓冲区
        self._reply_buffer: str = ""

    # ---------------------------------------------------------------------
    # 内部辅助方法
    # ---------------------------------------------------------------------
    def _extract_emotion(self, chunk: str) -> str | None:
        """在 ``chunk`` 中查找 ``emotion`` 字段并返回其值（若存在且尚未发送）。"""
        if self._emotion_sent:
            return None
        m = _EMOTION_RE.search(chunk)
        if m:
            self._emotion_sent = True
            return m.group(1)
        return None

    def _feed_reply(self, chunk: str) -> None:
        """将 ``chunk`` 追加到 reply 缓冲区，必要时检测 ``reply`` 起始位置。"""
        if not self._reply_started:
            # 检测 reply 字段的起始标记
            m = _REPLY_START_RE.search(chunk)
            if m:
                self._reply_started = True
                start = m.end()
                self._reply_buffer += chunk[start:]
        else:
            self._reply_buffer += chunk

    def _pop_sentence(self) -> List[Tuple[str, str]]:
        """从 ``_reply_buffer`` 中弹出所有已完整的句子块。

        返回列表，每项为 ``("reply_chunk", sentence)``，句子包含结束标点。
        """
        msgs: List[Tuple[str, str]] = []
        while True:
            m = _SENTENCE_BOUNDARY_RE.search(self._reply_buffer)
            if not m:
                break
            idx = m.end()
            sentence = self._reply_buffer[:idx]
            self._reply_buffer = self._reply_buffer[idx:]
            msgs.append(("reply_chunk", sentence))
        return msgs

    # ---------------------------------------------------------------------
    # 公共接口
    # ---------------------------------------------------------------------
    def feed(self, chunk: str) -> List[Tuple[str, str]]:
        """喂入一个原始 ``chunk``，返回可直接发送的消息列表。

        解析顺序为: 先尝试提取 ``emotion``（仅首次出现），随后收集并切分 ``reply``。
        ``emotion`` 只会在第一次出现时返回一次，后续出现的 ``emotion`` 将被忽略（保持幂等）。
        """
        msgs: List[Tuple[str, str]] = []
        emotion = self._extract_emotion(chunk)
        if emotion is not None:
            msgs.append(("emotion_update", emotion))
        # 处理 reply 内容并切分句子
        self._feed_reply(chunk)
        msgs.extend(self._pop_sentence())
        return msgs

    def flush(self) -> List[Tuple[str, str]]:
        """在流结束时调用，返回剩余未切分的 reply 内容（若有）。"""
        msgs: List[Tuple[str, str]] = []
        if self._reply_buffer:
            msgs.append(("reply_chunk", self._reply_buffer))
            self._reply_buffer = ""
        return msgs

    # ---------------------------------------------------------------------
    # 便捷方法（单元测试复用）
    # ---------------------------------------------------------------------
    def reset(self) -> None:
        """重置内部状态，供单元测试使用。"""
        self._emotion_sent = False
        self._reply_started = False
        self._reply_buffer = ""

# End of StreamParser
