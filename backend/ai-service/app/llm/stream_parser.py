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
本类负责在服务端聚合这些碎片，按 `check` -> `thought` -> `emotion` -> `reply` -> `replay_translation` 的顺序依次解析：
- `check` 字段（系统校验推理）被跳过，不作为输出
- `thought` 字段（角色内心独白）被捕获并作为 `"thought_content"` 消息类型输出（用于持久化）
- `emotion` 字段被提取并立即下发（仅首次出现时）
- `reply` 字段被基于标点的语义断句，将完整的句子作为独立的 `reply_chunk` 发送
- `replay_translation` 字段（日语模式下 reply 的日语翻译）被捕获，用于 TTS 日语语音合成

在输出文本分块时增加标点过滤逻辑：
精准去除文本末尾的逗号和句号（包括全角/半角），但必须保留感叹号、省略号、波浪号等表达语气的标点。
"""

from __future__ import annotations

import re
from enum import Enum, auto

# 正则：用于匹配字段起始标记
_CHECK_START_RE = re.compile(r'"check"\s*:\s*"')
_THOUGHT_START_RE = re.compile(r'"thought"\s*:\s*"')
# 正则：用于识别 thought 结束位置（下一个字段起始）
# 增加 reply 作为兜底，防止 emotion 缺失
_THOUGHT_END_RE = re.compile(r'"\s*,\s*"(?:emotion|thought|reply)"')
# 正则：用于识别 reply 字段结束位置（下一个字段起始）
# 在 reply 内容后出现 ","<字段名>":" 模式时，表示 reply 字段已结束，后续文本不应再混入 reply_buffer
# 覆盖 replay_translation 等 reply 之后可能的字段名
_REPLY_END_RE = re.compile(r'"\s*,\s*"\w+"\s*:\s*"')
# 正则：用于一次性捕获 emotion 值（仅第一次出现时返回）
_EMOTION_RE = re.compile(r'"emotion"\s*:\s*"([^"]+)"')
# reply 字段起始标记
_REPLY_START_RE = re.compile(r'"reply"\s*:\s*"')
# replay_translation 字段起始标记（日语模式下 TTS 使用此字段的日语翻译文本）
_REPLAY_TRANSLATION_START_RE = re.compile(r'"replay_translation"\s*:\s*"')
# 句子结束标点：匹配主标点（及其可能的闭合符号），或者连续的逗号/换行，或者省略号
_SENTENCE_BOUNDARY_RE = re.compile(r'([。！？!?]+[”’"\'\)）\]】》]?|(?<!\.)\.(?!\.)[”’"\'\)）\]】》]?|[，,\n]+[”’"\'\)）\]】》]?|……+|…+|\.{2,})')
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

    解析顺序：check（跳过）→ thought（捕获并输出）→ emotion（提取）→ reply（切分）→ replay_translation（捕获）。

    当 disable_sentence_split=True 时，reply 字段不做断句切分，作为完整文本返回。
    此模式用于非流式统一响应场景，后端拿到完整 LLM 回复后只需提取 thought/emotion/reply/replay_translation，
    reply 的语义切分交由前端执行。
    """

    def __init__(self, trace_id: str, disable_sentence_split: bool = False) -> None:
        self.trace_id = trace_id
        self._state: _ParseState = _ParseState.WAITING_CHECK
        self._emotion_sent: bool = False
        self._reply_started: bool = False
        self._reply_finished: bool = False  # 是否已检测到 reply 字段结束标记（如 ","replay_translation":"），之后的内容不再混入 reply_buffer
        self._reply_buffer: str = ""
        self._thought_buffer: str = ""
        self._thought_sent: bool = False
        self._intermediate_buffer: str = ""  # 用于缓冲 thought 结束到 reply 开始之间的碎片
        self._search_buffer: str = ""        # 全局搜索缓冲
        self._pending_prefix: str = ""       # 用于暂存省略号等前缀，避免死循环
        self._disable_sentence_split: bool = disable_sentence_split
            # 禁用 reply 断句时，reply 文本完整返回不做切分
            # thought、emotion 和 replay_translation 的提取逻辑不受此参数影响
        # --- replay_translation 字段提取（日语模式 TTS 用） ---
        self._replay_translation_buffer: str = ""  # 累积 replay_translation 内容
        self._replay_translation_started: bool = False  # 是否已检测到 replay_translation 起始标记
        self._replay_translation_finished: bool = False  # 是否已完成 replay_translation 提取

    def _emit_thought(self) -> list[tuple[str, str]]:
        """返回 thought 内容的输出消息（如果尚未发送且有内容）。"""
        if self._thought_sent or not self._thought_buffer:
            return []
        self._thought_sent = True
        thought_text = self._thought_buffer.strip()
        return [("thought_content", thought_text)]

    def feed(self, chunk: str) -> list[tuple[str, str]]:
        """喂入一个原始 chunk，返回解析得到的消息列表。"""
        if not chunk:
            return []
        msgs: list[tuple[str, str]] = []
        self._search_buffer += chunk

        while self._search_buffer:
            if self._state == _ParseState.WAITING_CHECK:
                m = _CHECK_START_RE.search(self._search_buffer)
                if not m:
                    break
                self._search_buffer = self._search_buffer[m.end():]
                self._state = _ParseState.WAITING_THOUGHT
                continue

            if self._state == _ParseState.WAITING_THOUGHT:
                m = _THOUGHT_START_RE.search(self._search_buffer)
                if not m:
                    break
                self._search_buffer = self._search_buffer[m.end():]
                self._state = _ParseState.READING_THOUGHT
                continue

            if self._state == _ParseState.READING_THOUGHT:
                m = _THOUGHT_END_RE.search(self._search_buffer)
                if not m:
                    # thought 尚未结束，将大部分内容移入 thought_buffer，保留末尾部分以防截断结束标记
                    if len(self._search_buffer) > 30:
                        self._thought_buffer += self._search_buffer[:-30]
                        self._search_buffer = self._search_buffer[-30:]
                    break
                
                self._thought_buffer += self._search_buffer[:m.start()]
                self._search_buffer = self._search_buffer[m.start():]
                self._state = _ParseState.WAITING_EMOTION_REPLY
                continue

            if self._state == _ParseState.WAITING_EMOTION_REPLY:
                msgs.extend(self._process_emotion_reply(self._search_buffer))
                self._search_buffer = ""
                break

        return msgs

    def _process_emotion_reply(self, text: str) -> list[tuple[str, str]]:
        """
        从文本中提取 emotion 和切分 reply，以及 replay_translation（日语翻译文本）。

        内部方法，允许多次调用以处理不同文本片段。

        当 self._disable_sentence_split=True 时：
            reply 文本完整累积到 _reply_buffer，不做断句切分。
            feed() 调用期间不返回任何 reply_chunk，所有 reply 内容由 flush() 一次性返回。

        注意：LLM 返回的 JSON 中 reply 字段之后可能还有 replay_translation 等字段，
            本方法通过 _REPLY_END_RE 检测 reply 字段的结束边界，
            确保 replay_translation 等后续字段的内容不会混入 reply_buffer。
            同时独立提取 replay_translation 内容，供 TTS 日语合成使用。
        """
        msgs: list[tuple[str, str]] = []

        # ---- replay_translation 提取阶段（reply 结束后） ----
        if self._reply_finished and not self._replay_translation_finished:
            # 尚未检测到 replay_translation 起始，尝试在当前文本中定位
            if not self._replay_translation_started:
                m = _REPLAY_TRANSLATION_START_RE.search(text)
                if m:
                    self._replay_translation_started = True
                    # 将起始标记后的内容累积
                    trans_tail = text[m.end():]
                    # 检查是否包含下一个字段的结束标记
                    end_m = _REPLY_END_RE.search(trans_tail)
                    if end_m:
                        self._replay_translation_buffer += trans_tail[:end_m.start()]
                        self._replay_translation_finished = True
                    else:
                        self._replay_translation_buffer += trans_tail
            else:
                # 已进入 replay_translation 内容读取阶段
                end_m = _REPLY_END_RE.search(text)
                if end_m:
                    self._replay_translation_buffer += text[:end_m.start()]
                    self._replay_translation_finished = True
                else:
                    self._replay_translation_buffer += text
            return msgs

        # ---- reply 提取阶段 ----
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
                reply_tail = self._intermediate_buffer[m.end():]
                # 检查 reply 内容中是否已包含结束标记（非流式场景下完整 JSON 中 reply 后紧跟其他字段）
                end_m = _REPLY_END_RE.search(reply_tail)
                if end_m:
                    # reply 结束标记已出现在当前片段中，截断
                    self._reply_buffer += reply_tail[:end_m.start()]
                    self._reply_finished = True
                else:
                    self._reply_buffer += reply_tail
                self._intermediate_buffer = ""  # 释放缓冲池
                # 取消断句时：reply 内容暂不输出，由 flush() 统一返回完整文本
                if not self._disable_sentence_split:
                    msgs.extend(self._pop_sentence())
        elif not self._reply_finished:
            # 已经进入 reply 读取阶段，且尚未检测到 reply 结束标记
            # 先检查当前文本中是否包含 reply 结束标记（下一个 JSON 字段起始）
            end_m = _REPLY_END_RE.search(text)
            if end_m:
                # 发现 reply 结束标记，截断并标记为 finished
                self._reply_buffer += text[:end_m.start()]
                self._reply_finished = True
                # 取消断句时：reply 内容暂不输出，由 flush() 统一返回完整文本
                if not self._disable_sentence_split:
                    msgs.extend(self._pop_sentence())
            else:
                # 未检测到结束标记，正常追加
                self._reply_buffer += text
                # 取消断句时：reply 内容暂不输出，由 flush() 统一返回完整文本
                if not self._disable_sentence_split:
                    msgs.extend(self._pop_sentence())
        # 已检测到 reply 结束标记（_reply_finished = True），
        # 剩余文本交由下一轮处理（replay_translation 提取）
            
        return msgs

    def _pop_sentence(self) -> list[tuple[str, str]]:
        """从 reply 缓存中切分出完整的句子，并过滤末尾平白标点。"""
        msgs: list[tuple[str, str]] = []
        while True:
            m = _SENTENCE_BOUNDARY_RE.search(self._reply_buffer)
            if not m:
                break
            
            # 正则已经贪婪匹配了完整的同类标点（及其闭合符号），直接使用 m.end()
            idx = m.end()
                
            sentence = self._reply_buffer[:idx]
            self._reply_buffer = self._reply_buffer[idx:]

            # 拼接之前暂存的前缀
            full_sentence = self._pending_prefix + sentence
            self._pending_prefix = ""

            sentence_stripped = full_sentence.strip()
            # 移除可能残留的 JSON 结束符
            sentence_stripped = sentence_stripped.replace('"}', '').replace('"', '').replace('}', '')
            sentence_cleaned = _TRAILING_PUNCTUATION_RE.sub('', sentence_stripped)
            
            # 修复死循环：将省略号暂存到 _pending_prefix 中，而不是塞回 _reply_buffer
            if _ELLIPSIS_RE.match(sentence_cleaned) and self._reply_buffer:
                self._pending_prefix = full_sentence
                continue
                
            if sentence_cleaned:
                msgs.append(("reply_chunk", sentence_cleaned))
        return msgs

    def flush(self) -> list[tuple[str, str]]:
        """在流结束时调用，返回 thought、剩余 reply 内容和 replay_translation（日语翻译文本）。

        当 disable_sentence_split=True 时：reply 字段作为完整文本返回，
        仅移除 JSON 结束符，保留原文标点和格式。
        当 disable_sentence_split=False 时：保持现有行为，对末尾内容执行标点过滤。
        """
        if self._state == _ParseState.READING_THOUGHT:
            self._thought_buffer += self._search_buffer
            self._search_buffer = ""
            
        msgs: list[tuple[str, str]] = []
        msgs.extend(self._emit_thought())
        
        # ---- 提取 replay_translation（日语翻译，供 TTS 日语合成使用） ----
        if self._replay_translation_buffer:
            trans = self._replay_translation_buffer.strip()
            # 移除可能的 JSON 结束符
            trans = trans.replace('"}', '').replace('"', '').replace('}', '').strip()
            if trans:
                msgs.append(("replay_translation", trans))
        
        # ---- 提取剩余 reply 内容 ----
        remaining = self._pending_prefix + self._reply_buffer
        if remaining:
            if self._disable_sentence_split:
                # 取消断句模式：仅移除 JSON 结束符，保留原文标点和格式
                sentence = remaining.strip()
                sentence = sentence.replace('"}', '').replace('"', '').replace('}', '')
                # 不执行标点过滤，保留完整原文供前端语义切分
                if sentence:
                    msgs.append(("reply_chunk", sentence))
            else:
                # 流式断句模式：保持现有行为，对末尾内容执行标点过滤
                sentence = remaining.strip()
                sentence = sentence.replace('"}', '').replace('"', '').replace('}', '')
                sentence = _TRAILING_PUNCTUATION_RE.sub('', sentence)
                if sentence:
                    msgs.append(("reply_chunk", sentence))
            self._reply_buffer = ""
            self._pending_prefix = ""
        return msgs

    def reset(self) -> None:
        self._state = _ParseState.WAITING_CHECK
        self._emotion_sent = False
        self._reply_started = False
        self._reply_finished = False
        self._reply_buffer = ""
        self._thought_buffer = ""
        self._thought_sent = False
        self._intermediate_buffer = ""
        self._search_buffer = ""
        self._pending_prefix = ""
        self._replay_translation_buffer = ""
        self._replay_translation_started = False
        self._replay_translation_finished = False
