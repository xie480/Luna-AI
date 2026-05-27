"""
StreamParser 用于解析 LLM 流式输出的 JSON 结构化文本。

在流式对话中，LLM 会按 token 块返回 JSON 字符串碎片，例如:

```json
{"check": "...",
 "thought": "...",
 "emotion": "Happy",
 "reply": "你好，主人！"
}
```

模型的输出是逐字符/逐 Token 的，直接转发会导致前端无法解析。
本类负责在服务端聚合这些碎片，按 `check` -> `thought` -> `emotion` -> `reply` 的顺序依次解析：
- `check` 字段（系统校验推理）被跳过，不作为输出
- `thought` 字段（角色内心独白）被捕获并作为 `"thought_content"` 消息类型输出（用于持久化）
- `emotion` 字段被提取并立即下发（仅首次出现时）
- `reply` 字段被基于标点的语义断句，将完整的句子作为独立的 `reply_chunk` 发送

【问题2优化】在输出文本分块时增加标点过滤逻辑：
精准去除文本末尾的逗号和句号（包括全角/半角），但必须保留感叹号、省略号、波浪号等表达语气的标点。
"""

from __future__ import annotations

import re
from enum import Enum, auto
from typing import List, Tuple

# 正则：用于匹配字段起始标记
_CHECK_START_RE = re.compile(r'"check"\s*:\s*"')
_THOUGHT_START_RE = re.compile(r'"thought"\s*:\s*"')
# 正则：用于识别 thought 结束位置（下一个字段起始）
_THOUGHT_END_RE = re.compile(r'"\s*,\s*"(?:emotion|thought)"')
# 正则：用于一次性捕获 emotion 值（仅第一次出现时返回）
_EMOTION_RE = re.compile(r'"emotion"\s*:\s*"([^"]+)"')
# reply 字段起始标记
_REPLY_START_RE = re.compile(r'"reply"\s*:\s*"')
# 句子结束标点
_SENTENCE_BOUNDARY_RE = re.compile(r'[。！？……,，\n]')
# 【问题2优化】末尾标点过滤：精准剔除末尾的逗号和句号，保留！、？、～、……
_TRAILING_PUNCTUATION_RE = re.compile(r'[，,。\.]+$')
# 匹配连续的省略号
_ELLIPSIS_RE = re.compile(r'^[…\.]+$')


class _ParseState(Enum):
    WAITING_CHECK = auto()          # 等待 check 字段起始
    WAITING_THOUGHT = auto()        # 等待 thought 字段起始
    READING_THOUGHT = auto()        # 正在读取 thought 内容
    WAITING_EMOTION_REPLY = auto()  # 等待 emotion 和 reply


class StreamParser:
    """LLM 流式输出的状态机解析器。

    解析顺序：check（跳过）→ thought（捕获并输出）→ emotion（提取）→ reply（切分）。
    """

    def __init__(self, trace_id: str) -> None:
        self.trace_id = trace_id
        self._state: _ParseState = _ParseState.WAITING_CHECK
        self._emotion_sent: bool = False
        self._reply_started: bool = False
        self._reply_buffer: str = ""
        self._thought_buffer: str = ""
        self._thought_sent: bool = False
        self._intermediate_buffer: str = ""  # 新增：用于缓冲 thought 结束到 reply 开始之间的碎片

    def _flush_thought_to_emotion_reply(self) -> Tuple[bool, str]:
        """
        检查 thought_buffer 是否已结束（遇到下一个字段），
        如果是，设置状态为 WAITING_EMOTION_REPLY 并返回 thought 之后的内容。

        返回：(是否切换状态, thought 之后的内容)
        """
        m = _THOUGHT_END_RE.search(self._thought_buffer)
        if m:
            self._state = _ParseState.WAITING_EMOTION_REPLY
            after_thought = self._thought_buffer[m.start():]
            # 截断 thought_buffer 只保留 thought 内容
            self._thought_buffer = self._thought_buffer[:m.start()]
            return True, after_thought
        return False, ""

    def _emit_thought(self) -> List[Tuple[str, str]]:
        """返回 thought 内容的输出消息（如果尚未发送且有内容）。"""
        if self._thought_sent or not self._thought_buffer:
            return []
        self._thought_sent = True
        thought_text = self._thought_buffer.strip()
        return [("thought_content", thought_text)]

    def feed(self, chunk: str) -> List[Tuple[str, str]]:
        """喂入一个原始 chunk，返回解析得到的消息列表。"""
        if not chunk:
            return []
        msgs: List[Tuple[str, str]] = []
        remaining = chunk

        # ========== Phase 1: 等待并跳过 check 字段 ==========
        if self._state == _ParseState.WAITING_CHECK:
            m = _CHECK_START_RE.search(remaining)
            if not m:
                return msgs
            # 跳过 check 起始标记
            remaining = remaining[m.end():]
            # 检查同一个 chunk 中是否紧跟了 thought 起始
            m2 = _THOUGHT_START_RE.search(remaining)
            if m2:
                # 进入 thought 读取
                self._state = _ParseState.READING_THOUGHT
                self._thought_buffer += remaining[m2.end():]
                # 检查 thought 是否已结束
                switched, after = self._flush_thought_to_emotion_reply()
                if switched:
                    msgs.extend(self._process_emotion_reply(after))
                return msgs
            else:
                # thought 在后续 chunk 中
                self._state = _ParseState.WAITING_THOUGHT
                return msgs

        # ========== Phase 2: 等待 thought 字段 ==========
        if self._state == _ParseState.WAITING_THOUGHT:
            m = _THOUGHT_START_RE.search(remaining)
            if not m:
                return msgs
            self._state = _ParseState.READING_THOUGHT
            self._thought_buffer += remaining[m.end():]
            # 检查 thought 是否已结束
            switched, after = self._flush_thought_to_emotion_reply()
            if switched:
                msgs.extend(self._process_emotion_reply(after))
            return msgs

        # ========== Phase 3: 读取 thought 内容 ==========
        if self._state == _ParseState.READING_THOUGHT:
            self._thought_buffer += remaining
            switched, after = self._flush_thought_to_emotion_reply()
            if switched:
                msgs.extend(self._process_emotion_reply(after))
            return msgs

        # ========== Phase 4: 处理 emotion 和 reply ==========
        if self._state == _ParseState.WAITING_EMOTION_REPLY:
            msgs.extend(self._process_emotion_reply(remaining))
            return msgs

        return msgs

    def _process_emotion_reply(self, text: str) -> List[Tuple[str, str]]:
        """
        从文本中提取 emotion 和切分 reply。
        内部方法，允许多次调用以处理不同文本片段。
        """
        msgs: List[Tuple[str, str]] = []
        
        if not self._reply_started:
            # 将碎片追加到缓冲池中，防止 JSON 键值对被 chunk 截断
            self._intermediate_buffer += text
            
            # 提取 emotion（仅第一次）
            if not self._emotion_sent:
                m = _EMOTION_RE.search(self._intermediate_buffer)
                if m:
                    self._emotion_sent = True
                    msgs.append(("emotion_update", m.group(1)))
            
            # 寻找 reply 起始标记
            m = _REPLY_START_RE.search(self._intermediate_buffer)
            if m:
                self._reply_started = True
                # 将 reply 起始标记之后的内容放入 reply_buffer
                self._reply_buffer += self._intermediate_buffer[m.end():]
                self._intermediate_buffer = ""  # 释放缓冲池
                msgs.extend(self._pop_sentence())
        else:
            # 已经进入 reply 读取阶段，直接追加并切分
            self._reply_buffer += text
            msgs.extend(self._pop_sentence())
            
        return msgs

    def _extract_emotion(self, chunk: str) -> str | None:
        if self._emotion_sent:
            return None
        m = _EMOTION_RE.search(chunk)
        if m:
            self._emotion_sent = True
            return m.group(1)
        return None

    def _feed_reply(self, chunk: str) -> None:
        if not self._reply_started:
            m = _REPLY_START_RE.search(chunk)
            if m:
                self._reply_started = True
                self._reply_buffer += chunk[m.end():]
        else:
            self._reply_buffer += chunk

    def _pop_sentence(self) -> List[Tuple[str, str]]:
        """从 reply 缓存中切分出完整的句子，并过滤末尾平白标点。"""
        msgs: List[Tuple[str, str]] = []
        while True:
            m = _SENTENCE_BOUNDARY_RE.search(self._reply_buffer)
            if not m:
                break
            idx = m.end()
            sentence = self._reply_buffer[:idx]
            self._reply_buffer = self._reply_buffer[idx:]

            # 【问题2优化】标点过滤逻辑：剔除末尾的逗号和句号，保留！、？、～、……
            sentence = sentence.strip()
            sentence = _TRAILING_PUNCTUATION_RE.sub('', sentence)
            
            # 修复首字符重复追加问题：如果切分出来的句子全是省略号，且后续还有内容，
            # 则将其合并到下一个句子中，避免单独作为一个 chunk 发送
            if _ELLIPSIS_RE.match(sentence) and self._reply_buffer:
                self._reply_buffer = sentence + self._reply_buffer
                continue
                
            if sentence:
                msgs.append(("reply_chunk", sentence))
        return msgs

    def flush(self) -> List[Tuple[str, str]]:
        """在流结束时调用，返回 thought 和剩余 reply 内容。"""
        msgs: List[Tuple[str, str]] = []
        msgs.extend(self._emit_thought())
        if self._reply_buffer:
            # 【问题2优化】对末尾剩余内容同样执行标点过滤
            sentence = self._reply_buffer.strip()
            sentence = _TRAILING_PUNCTUATION_RE.sub('', sentence)
            if sentence:
                msgs.append(("reply_chunk", sentence))
            self._reply_buffer = ""
        return msgs

    def reset(self) -> None:
        self._state = _ParseState.WAITING_CHECK
        self._emotion_sent = False
        self._reply_started = False
        self._reply_buffer = ""
        self._thought_buffer = ""
        self._thought_sent = False
        self._intermediate_buffer = ""  # 重置缓冲池
