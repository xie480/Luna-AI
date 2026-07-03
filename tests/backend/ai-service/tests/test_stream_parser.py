"""
StreamParser 单元测试

测试目标：验证 StreamParser 在各种 LLM 碎片输入场景下的行为：
1. 内心独白提取：能够捕获 thought 字段作为 thought_content 输出
2. 情绪提取：能够从 JSON 碎片中提取 emotion 字段
3. 标点断句：能够按标点正确切分 reply 句子
4. 边界情况：空输入、无 emotion、无 reply、流结束 flush
5. 幂等性：emotion 只发送一次
"""

import pytest
from app.llm.stream_parser import StreamParser

# 新 JSON 格式：check -> thought -> emotion -> reply -> (md_content -> summary)
# 用于测试的标准 JSON 片段
JSON_CHECK_THOUGHT_EMOTION_REPLY = '{"check":"test","thought":"inner monologue","emotion":"Happy","reply":"你好。"}'
JSON_LONG_ANSWER = '{"check":"test","thought":"inner","emotion":"Happy","reply":"给你整理好了。","md_content":"# 标题\\n\\n正文内容","summary":"摘要内容"}'


class TestStreamParser:
    """StreamParser 基础功能测试"""

    def test_init_state(self):
        """测试初始化状态正确"""
        parser = StreamParser(trace_id="test-trace-001")
        assert parser.trace_id == "test-trace-001"
        assert parser._emotion_sent is False
        assert parser._reply_started is False
        assert parser._reply_buffer == ""
        assert parser._state.name == "WAITING_CHECK"

    def test_extract_emotion_first_chunk(self):
        """测试从第一个 chunk 中提取 emotion"""
        parser = StreamParser(trace_id="test-trace-002")
        chunk = JSON_CHECK_THOUGHT_EMOTION_REPLY
        msgs = parser.feed(chunk)
        # 应该返回 emotion_update
        emotion_msgs = [m for m in msgs if m[0] == "emotion_update"]
        assert len(emotion_msgs) >= 1
        assert emotion_msgs[0] == ("emotion_update", "Happy")

    def test_emotion_only_once(self):
        """测试 emotion 只被提取一次（幂等性）"""
        parser = StreamParser(trace_id="test-trace-003")
        # 第一次 feed，包含 emotion
        chunk1 = JSON_CHECK_THOUGHT_EMOTION_REPLY
        msgs1 = parser.feed(chunk1)
        emotion_msgs1 = [m for m in msgs1 if m[0] == "emotion_update"]
        assert len(emotion_msgs1) == 1
        assert emotion_msgs1[0] == ("emotion_update", "Happy")

        # 第二次 feed，不应再返回 emotion
        chunk2 = '{"check":"c","thought":"t","emotion":"Sad","reply":"再见。"}'
        msgs2 = parser.feed(chunk2)
        emotion_msgs2 = [m for m in msgs2 if m[0] == "emotion_update"]
        assert len(emotion_msgs2) == 0

    def test_trace_id(self):
        """测试 trace_id 正确传递"""
        parser = StreamParser(trace_id="my-custom-trace-12345")
        assert parser.trace_id == "my-custom-trace-12345"


class TestStreamParserSentenceSplitting:
    """StreamParser 标点断句测试"""

    def test_split_by_period(self):
        """测试按句号断句"""
        parser = StreamParser(trace_id="test-split-001")
        chunk = '{"check":"c","thought":"t","emotion":"Happy","reply":"你好。今天天气真好啊。"}'
        msgs = parser.feed(chunk)
        reply_chunks = [c for t, c in msgs if t == "reply_chunk"]
        assert len(reply_chunks) >= 1
        # 句号会被 _TRAILING_PUNCTUATION_RE 过滤掉
        assert "你好" in reply_chunks[0]
        assert "你好。" not in reply_chunks[0]

    def test_split_by_chinese_punctuation(self):
        """测试按中文标点断句（问号、感叹号、逗号、省略号）"""
        parser = StreamParser(trace_id="test-split-002")
        chunk = '{"check":"c","thought":"t","emotion":"Happy","reply":"真的吗？太好了！等等，让我想想……嗯。"}'
        msgs = parser.feed(chunk)
        reply_chunks = [c for t, c in msgs if t == "reply_chunk"]
        assert any(c.endswith("？") for c in reply_chunks) or \
               any(c.endswith("!") for c in reply_chunks) or \
               any(c.endswith("！") for c in reply_chunks)

    def test_split_by_newline(self):
        """测试按换行符断句"""
        parser = StreamParser(trace_id="test-split-003")
        chunk = '{"check":"c","thought":"t","emotion":"Sad","reply":"第一行\n第二行\n第三行"}'
        msgs = parser.feed(chunk)
        reply_chunks = [c for t, c in msgs if t == "reply_chunk"]
        # 换行符会被 strip() 过滤掉
        assert "第一行" in reply_chunks
        assert "第二行" in reply_chunks

    def test_partial_reply_single_chunk(self):
        """测试在一个 chunk 中收到完整 reply"""
        parser = StreamParser(trace_id="test-partial-001")
        chunk = '{"check":"c","thought":"t","emotion":"Happy","reply":"好的。"}'
        msgs = parser.feed(chunk)
        reply_chunks = [c for t, c in msgs if t == "reply_chunk"]
        assert len(reply_chunks) >= 1
        # 句号会被过滤掉
        assert "好的" in reply_chunks[0]
        assert "好的。" not in reply_chunks[0]


    def test_json_closing_braces(self):
        """测试 JSON 闭合符不会被输出"""
        parser = StreamParser(trace_id="test-json-close-001")
        chunk = '{"check":"c","thought":"t","emotion":"Happy","reply":"你好\n"\n}'
        msgs = parser.feed(chunk)
        reply_chunks = [c for t, c in msgs if t == "reply_chunk"]
        for c in reply_chunks:
            assert "}" not in c
            assert '"' not in c
            
        flush_msgs = parser.flush()
        flush_reply_chunks = [c for t, c in flush_msgs if t == "reply_chunk"]
        for c in flush_reply_chunks:
            assert "}" not in c
            assert '"' not in c

class TestStreamParserEdgeCases:
    """StreamParser 边界情况测试"""

    def test_empty_chunk(self):
        """测试空 chunk 输入"""
        parser = StreamParser(trace_id="test-edge-001")
        msgs = parser.feed("")
        assert msgs == []

    def test_no_emotion_field(self):
        """测试 reply 中不包含 emotion 字段（兜底）"""
        parser = StreamParser(trace_id="test-edge-002")
        chunk = '{"check":"c","thought":"t","reply":"没有情绪字段。"}'
        msgs = parser.feed(chunk)
        # 不应有 emotion_update
        emotion_msgs = [m for m in msgs if m[0] == "emotion_update"]
        assert len(emotion_msgs) == 0

    def test_no_reply_field(self):
        """测试没有 reply 字段的情况"""
        parser = StreamParser(trace_id="test-edge-003")
        chunk = '{"check":"c","thought":"t","emotion":"Confused"}'
        msgs = parser.feed(chunk)
        # 应该有 emotion_update
        assert any(m[0] == "emotion_update" for m in msgs)
        reply_chunks = [m for m in msgs if m[0] == "reply_chunk"]
        assert len(reply_chunks) == 0

    def test_flush_empty_buffer(self):
        """测试缓冲区为空时 flush 返回空列表"""
        parser = StreamParser(trace_id="test-edge-004")
        msgs = parser.flush()
        # buffer 为空, thought 也为空，返回空列表
        assert msgs == []

    def test_flush_with_content(self):
        """测试有残留内容时 flush 返回正确结果"""
        parser = StreamParser(trace_id="test-edge-005")
        # 先喂入一些数据（不包含结束标点，让内容留在缓冲区）
        chunk = '{"check":"c","thought":"t","emotion":"Soft","reply":"这是一个长句"}'
        msgs = parser.feed(chunk)
        # 应该有的结果
        emotion_msgs = [m for m in msgs if m[0] == "emotion_update"]
        assert len(emotion_msgs) == 1
        assert emotion_msgs[0][1] == "Soft"
        # flush 时返回
        flush_msgs = parser.flush()
        reply_chunks = [c for t, c in flush_msgs if t == "reply_chunk"]
        assert len(reply_chunks) >= 1
        assert "长句" in reply_chunks[0]

    def test_reset_state(self):
        """测试 reset 能正确重置内部状态"""
        parser = StreamParser(trace_id="test-edge-006")
        chunk = '{"check":"c","thought":"t","emotion":"Angry","reply":"哼。"}'
        parser.feed(chunk)
        assert parser._emotion_sent is True

        parser.reset()
        assert parser._emotion_sent is False
        assert parser._reply_started is False
        assert parser._reply_buffer == ""
        assert parser._thought_buffer == ""

    def test_streaming_emotion_before_reply(self):
        """测试在流式场景中 emotion 先于 reply 到达"""
        parser = StreamParser(trace_id="test-stream-001")
        # 模拟流式传输
        chunk1 = '{"check":"c","thought":"t","emotion":"Happy"'
        msgs1 = parser.feed(chunk1)
        emotion_msgs = [m for m in msgs1 if m[0] == "emotion_update"]
        assert len(emotion_msgs) == 1
        assert emotion_msgs[0][1] == "Happy"

        # 第二个碎片包含 reply
        chunk2 = ',"reply":"你好啊。今天怎么样？"}'
        msgs2 = parser.feed(chunk2)
        reply_chunks = [c for t, c in msgs2 if t == "reply_chunk"]
        assert len(reply_chunks) >= 1

    def test_large_text_split(self):
        """测试长文本的多句子切分"""
        parser = StreamParser(trace_id="test-large-001")
        long_text = "第一句。第二句。第三句。第四句。第五句。"
        chunk = '{"check":"c","thought":"t","emotion":"Smile","reply":"' + long_text + '"}'
        msgs = parser.feed(chunk)
        reply_chunks = [c for t, c in msgs if t == "reply_chunk"]
        assert len(reply_chunks) >= 4

    def test_emotion_value_extraction(self):
        """测试各种 emotion 值都能正确提取"""
        emotions = ["Angry", "Annoyed", "Clingy", "Tsundere", "Soft", "Smile", "Sad", "Confused"]
        for emotion in emotions:
            parser = StreamParser(trace_id=f"test-emotion-{emotion}")
            chunk = f'{{"check":"c","thought":"t","emotion":"{emotion}","reply":"test。"}}'
            msgs = parser.feed(chunk)
            emotion_msgs = [m for m in msgs if m[0] == "emotion_update"]
            assert len(emotion_msgs) == 1, f"Failed for emotion {emotion}"
            assert emotion_msgs[0][1] == emotion


class TestStreamParserThought:
    """StreamParser 内心独白 (thought) 功能测试"""

    def test_thought_content_captured(self):
        """测试 thought 字段被正确捕获为 thought_content"""
        parser = StreamParser(trace_id="test-thought-001")
        chunk = '{"check":"sys check","thought":"（笨蛋主人又在熬夜了，Luna好担心，但才不要直接说）","emotion":"Tsundere","reply":"哼。又熬夜？"}'
        msgs = parser.feed(chunk)
        # 应该捕获到 reply
        reply_chunks = [c for t, c in msgs if t == "reply_chunk"]
        assert len(reply_chunks) >= 1
        # flush 时返回 thought
        flush_msgs = parser.flush()
        thought_msgs = [c for t, c in flush_msgs if t == "thought_content"]
        assert len(thought_msgs) == 1
        assert "笨蛋主人" in thought_msgs[0]

    def test_thought_accessible_via_flush(self):
        """测试 thought 在流结束时通过 flush 返回"""
        parser = StreamParser(trace_id="test-thought-002")
        # 模拟完整流式输出
        chunks = [
            '{"check":"s',
            'ys check","thought":"（',
            '内心独白内容）","emotion":"Happy","reply":"你好。今天怎么样？"}'
        ]
        for c in chunks:
            parser.feed(c)

        flush_msgs = parser.flush()
        thought_msgs = [c for t, c in flush_msgs if t == "thought_content"]
        assert len(thought_msgs) == 1
        assert "内心独白" in thought_msgs[0]


class TestStreamParserMultiChunk:
    """多 chunk 流式场景测试"""

    def test_three_chunks_flow(self):
        """模拟三个连续的 chunk 流式传输"""
        parser = StreamParser(trace_id="test-multi-001")
        # chunk1: 包含 check
        chunk1 = '{"check":"test'
        msgs1 = parser.feed(chunk1)
        assert len(msgs1) == 0

        # chunk2: 包含 thought + emotion
        chunk2 = '","thought":"t","emotion":"Happy","reply":"'
        msgs2 = parser.feed(chunk2)
        # 应该提取到 emotion
        assert any(m[0] == "emotion_update" and m[1] == "Happy" for m in msgs2)

        # chunk3: reply 内容
        chunk3 = '你好。今天很开心。"}'
        msgs3 = parser.feed(chunk3)
        reply_chunks = [c for t, c in msgs3 if t == "reply_chunk"]
        assert len(reply_chunks) >= 1

    def test_no_punctuation_in_reply(self):
        """测试 reply 中没有标点时的行为"""
        parser = StreamParser(trace_id="test-multi-002")
        chunk = '{"check":"c","thought":"t","emotion":"Happy","reply":"这是个没有标点的长文本"}'
        msgs = parser.feed(chunk)
        # 应该有 emotion_update
        assert any(m[0] == "emotion_update" for m in msgs)
        # flush 时返回
        flush_msgs = parser.flush()
        reply_chunks = [c for t, c in flush_msgs if t == "reply_chunk"]
        assert len(reply_chunks) == 1
        assert "标点" in reply_chunks[0]


class TestStreamParserReplayTranslation:
    """replay_translation 字段隔离测试：确保 reply 之后的其他字段不会混入 reply_buffer"""

    REPLAY_JSON = (
        '{"check":"[感知] 意图识别：直球表白。","thought":"（内心独白）",'
        '"emotion":"Flustered","reply":"你、你突然说这个干嘛……Luna才不是因为你夸了就开心呢！",'
        '"replay_translation":"急にそんなこと言わないでよ……Luna、褒められて嬉しいわけじゃないんだからね！"}'
    )

    def test_replay_translation_not_in_reply_feed(self):
        """测试 feed 阶段 reply 内容不包含 replay_translation"""
        parser = StreamParser(trace_id="test-replay-001")
        msgs = parser.feed(self.REPLAY_JSON)
        reply_chunks = [c for t, c in msgs if t == "reply_chunk"]
        # reply 内容应该只包含中文回复，不包含日文翻译
        for chunk in reply_chunks:
            assert "急に" not in chunk, f"reply_chunk 不应包含 replay_translation 内容: {chunk}"
            assert "褒められて" not in chunk, f"reply_chunk 不应包含 replay_translation 内容: {chunk}"

    def test_replay_translation_not_in_reply_flush(self):
        """测试 flush 阶段 reply 内容不包含 replay_translation"""
        parser = StreamParser(trace_id="test-replay-002")
        parser.feed(self.REPLAY_JSON)
        flush_msgs = parser.flush()
        flush_reply = [c for t, c in flush_msgs if t == "reply_chunk"]
        for chunk in flush_reply:
            assert "replay_translation" not in chunk
            assert "急に" not in chunk, f"flush reply 不应包含 replay_translation 内容: {chunk}"

    def test_replay_translation_disable_split(self):
        """测试 disable_sentence_split=True 模式下 reply 也不包含 replay_translation"""
        parser = StreamParser(trace_id="test-replay-003", disable_sentence_split=True)
        msgs = parser.feed(self.REPLAY_JSON)
        # 禁用断句模式下，feed 不返回 reply_chunk
        feed_reply = [c for t, c in msgs if t == "reply_chunk"]
        assert len(feed_reply) == 0

        flush_msgs = parser.flush()
        flush_reply = [c for t, c in flush_msgs if t == "reply_chunk"]
        assert len(flush_reply) == 1
        # 确认 flush 返回的完整 reply 不包含 replay_translation 内容
        full_reply = flush_reply[0]
        assert "急に" not in full_reply, f"disable_split 模式下 reply 不应包含 replay_translation: {full_reply}"
        assert "Luna、褒められて" not in full_reply
        # 确认正常的 reply 内容被保留
        assert "Luna" in full_reply
        assert "突然" in full_reply

    def test_replay_translation_no_emotion_field(self):
        """测试 reply 后接 replay_translation 但没有 emotion 字段时依然正确截断"""
        parser = StreamParser(trace_id="test-replay-004")
        chunk = '{"check":"c","thought":"t","reply":"你好。","replay_translation":"こんにちは。"}'
        msgs = parser.feed(chunk)
        reply_chunks = [c for t, c in msgs if t == "reply_chunk"]
        flush_msgs = parser.flush()
        flush_reply = [c for t, c in flush_msgs if t == "reply_chunk"]
        all_reply = reply_chunks + flush_reply
        for chunk in all_reply:
            assert "replay_translation" not in chunk
            assert "こんにちは" not in chunk, f"reply 不应包含 replay_translation 内容: {chunk}"

    def test_replay_translation_streaming_chunks(self):
        """模拟流式场景下 reply 和 replay_translation 在不同 chunk 中到达"""
        parser = StreamParser(trace_id="test-replay-005")
        # chunk1: 包含 check、thought、emotion 和 reply 内容
        chunk1 = '{"check":"c","thought":"t","emotion":"Happy","reply":"今天天气真好啊。'
        msgs1 = parser.feed(chunk1)
        reply_chunks1 = [c for t, c in msgs1 if t == "reply_chunk"]
        assert len(reply_chunks1) >= 1
        assert all("replay_translation" not in c for c in reply_chunks1)

        # chunk2: 包含 reply 剩余部分 + replay_translation
        chunk2 = '明天也要出去玩。","replay_translation":"今日はいい天気ですね。明日も遊びに行こう。"}'
        msgs2 = parser.feed(chunk2)
        reply_chunks2 = [c for t, c in msgs2 if t == "reply_chunk"]
        for c in reply_chunks2:
            assert "replay_translation" not in c
            assert "今日は" not in c, f"reply_chunk 不应包含 replay_translation: {c}"
            assert "明日も" not in c

        # flush 后确认
        flush_msgs = parser.flush()
        flush_reply = [c for t, c in flush_msgs if t == "reply_chunk"]
        for c in flush_reply:
            assert "replay_translation" not in c
            assert "今日は" not in c


    def test_replay_translation_content_extracted_flush(self):
        """测试 flush 阶段能正确提取 replay_translation 的日语翻译内容（非流式单次 feed 场景）"""
        parser = StreamParser(trace_id="test-replay-006")
        parser.feed(self.REPLAY_JSON)
        flush_msgs = parser.flush()
        replay_trans = [c for t, c in flush_msgs if t == "replay_translation"]
        # flush 后必须提取到 replay_translation 内容
        assert len(replay_trans) == 1, (
            f"flush 应提取到 replay_translation 内容，实际 msgs={flush_msgs}"
        )
        assert "褒められて" in replay_trans[0], (
            f"replay_translation 应包含日语翻译文本，实际内容={replay_trans[0]}"
        )
        assert "Luna" in replay_trans[0], (
            f"replay_translation 应包含日语人称，实际内容={replay_trans[0]}"
        )

    def test_replay_translation_content_extracted_disable_split(self):
        """测试 disable_sentence_split=True 模式下 flush 阶段也能正确提取 replay_translation"""
        parser = StreamParser(trace_id="test-replay-007", disable_sentence_split=True)
        parser.feed(self.REPLAY_JSON)
        flush_msgs = parser.flush()
        replay_trans = [c for t, c in flush_msgs if t == "replay_translation"]
        assert len(replay_trans) == 1, (
            f"disable_split 模式下 flush 应提取到 replay_translation，实际 msgs={flush_msgs}"
        )
        assert "褒められて" in replay_trans[0]

    def test_replay_translation_single_feed_no_emotion(self):
        """测试没有 emotion 字段的 JSON 中 replay_translation 也能被正确提取（单次 feed）"""
        parser = StreamParser(trace_id="test-replay-008")
        chunk = '{"check":"c","thought":"t","reply":"你好呀～","replay_translation":"こんにちは～"}'
        parser.feed(chunk)
        flush_msgs = parser.flush()
        replay_trans = [c for t, c in flush_msgs if t == "replay_translation"]
        assert len(replay_trans) == 1, (
            f"无 emotion 字段时也应提取到 replay_translation，实际 msgs={flush_msgs}"
        )
        assert "こんにちは" in replay_trans[0]


class TestStreamParserLongAnswer:
    """长回答字段解析测试"""

    def test_long_answer_feed(self):
        """测试 feed 过程中正确提取 md_content 碎片"""
        parser = StreamParser(trace_id="test-long-001")
        msgs = parser.feed('{"check":"c","thought":"t","emotion":"Smile","reply":"好了。","md_content":"# Title')
        
        reply_chunks = [c for t, c in msgs if t == "reply_chunk"]
        md_chunks = [c for t, c in msgs if t == "long_answer_chunk"]
        
        assert len(reply_chunks) >= 1
        assert "好了" in reply_chunks[0]
        assert len(md_chunks) == 1
        assert md_chunks[0] == "# Title"

    def test_long_answer_flush(self):
        """测试 flush 时正确提取 md_content 剩余部分和 summary"""
        parser = StreamParser(trace_id="test-long-002")
        parser.feed(JSON_LONG_ANSWER)
        flush_msgs = parser.flush()
        
        md_chunks = [c for t, c in flush_msgs if t == "long_answer_chunk"]
        summary = [c for t, c in flush_msgs if t == "summary"]
        
        assert len(summary) == 1
        assert summary[0] == "摘要内容"
        
    def test_long_answer_disable_split(self):
        """测试非流式模式下长回答的提取"""
        parser = StreamParser(trace_id="test-long-003", disable_sentence_split=True)
        parser.feed(JSON_LONG_ANSWER)
        flush_msgs = parser.flush()
        
        reply_chunks = [c for t, c in flush_msgs if t == "reply_chunk"]
        md_chunks = [c for t, c in flush_msgs if t == "long_answer_chunk"]
        summary = [c for t, c in flush_msgs if t == "summary"]
        
        assert len(reply_chunks) == 1
        assert reply_chunks[0] == "给你整理好了。"
        assert len(summary) == 1
        assert summary[0] == "摘要内容"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
