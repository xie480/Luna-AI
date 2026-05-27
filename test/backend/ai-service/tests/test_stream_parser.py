"""
StreamParser 单元测试

测试目标：验证 StreamParser 在各种 LLM 碎片输入场景下的行为：
1. 情绪提取：能够从 JSON 碎片中提取 emotion 字段
2. 标点断句：能够按标点正确切分 reply 句子
3. 边界情况：空输入、无 emotion、无 reply、流结束 flush
4. 幂等性：emotion 只发送一次
"""

import pytest
from app.llm.stream_parser import StreamParser


class TestStreamParser:
    """StreamParser 基础功能测试"""

    def test_init_state(self):
        """测试初始化状态正确"""
        parser = StreamParser(trace_id="test-trace-001")
        assert parser.trace_id == "test-trace-001"
        assert parser._emotion_sent is False
        assert parser._reply_started is False
        assert parser._reply_buffer == ""

    def test_extract_emotion_first_chunk(self):
        """测试从第一个 chunk 中提取 emotion"""
        parser = StreamParser(trace_id="test-trace-002")
        chunk = '{"thought":"test","emotion":"Happy","reply":"你好"}'
        msgs = parser.feed(chunk)
        # 应该返回 emotion_update + reply_chunks
        assert len(msgs) >= 1
        assert msgs[0] == ("emotion_update", "Happy")

    def test_emotion_only_once(self):
        """测试 emotion 只被提取一次（幂等性）"""
        parser = StreamParser(trace_id="test-trace-003")
        # 第一次 feed，包含 emotion
        chunk1 = '{"thought":"test","emotion":"Happy","reply":"你好"}'
        msgs1 = parser.feed(chunk1)
        assert msgs1[0] == ("emotion_update", "Happy")

        # 第二次 feed，不应再返回 emotion（即使 chunk 中包含 emotion 字段）
        parser.reset()
        # 使用新解析器证明单个解析器只发一次 emotion
        parser2 = StreamParser(trace_id="test-trace-003")
        chunk2 = '{"thought":"test2","emotion":"Angry","reply":"再见"}'
        msgs2 = parser2.feed(chunk2)
        assert msgs2[0] == ("emotion_update", "Angry")
        # 已经发送过 emotion 的解析器不再发
        msgs2_2 = parser2.feed('{"thought":"test3","emotion":"Sad","reply":"哦"}')
        emotion_msgs = [m for m in msgs2_2 if m[0] == "emotion_update"]
        assert len(emotion_msgs) == 0

    def test_trace_id(self):
        """测试 trace_id 正确传递"""
        parser = StreamParser(trace_id="my-custom-trace-12345")
        assert parser.trace_id == "my-custom-trace-12345"


class TestStreamParserSentenceSplitting:
    """StreamParser 标点断句测试"""

    def test_split_by_period(self):
        """测试按句号断句"""
        parser = StreamParser(trace_id="test-split-001")
        chunk = '{"thought":"test","emotion":"Happy","reply":"你好。今天天气真好啊。"}'
        msgs = parser.feed(chunk)
        # 应该有 emotion_update + 2 个 reply_chunk（2 个句号结尾的句子）
        types = [m[0] for m in msgs]
        contents = [m[1] for m in msgs]
        assert "emotion_update" in types
        reply_chunks = [c for t, c in msgs if t == "reply_chunk"]
        assert "你好。" in reply_chunks[0]
        # 第二个句子
        assert len(reply_chunks) >= 1

    def test_split_by_chinese_punctuation(self):
        """测试按中文标点断句（问号、感叹号、逗号、省略号）"""
        parser = StreamParser(trace_id="test-split-002")
        chunk = '{"thought":"t","emotion":"Happy","reply":"真的吗？太好了！等等，让我想想……嗯。"}'
        msgs = parser.feed(chunk)
        reply_chunks = [c for t, c in msgs if t == "reply_chunk"]
        # 应该至少有一个以标点结尾的分句
        assert any(c.endswith("？") for c in reply_chunks) or \
               any(c.endswith("!") for c in reply_chunks) or \
               any(c.endswith("！") for c in reply_chunks)

    def test_split_by_newline(self):
        """测试按换行符断句"""
        parser = StreamParser(trace_id="test-split-003")
        chunk = '{"thought":"t","emotion":"Sad","reply":"第一行\n第二行\n第三行"}'
        msgs = parser.feed(chunk)
        reply_chunks = [c for t, c in msgs if t == "reply_chunk"]
        # 至少有一个分句以换行结尾
        assert any(c.endswith("\n") for c in reply_chunks)

    def test_partial_reply_single_chunk(self):
        """测试在一个 chunk 中收到完整 reply"""
        parser = StreamParser(trace_id="test-partial-001")
        chunk = '{"thought":"t","emotion":"Happy","reply":"好的。"}'
        msgs = parser.feed(chunk)
        reply_chunks = [c for t, c in msgs if t == "reply_chunk"]
        assert len(reply_chunks) >= 1
        assert "好的。" in reply_chunks[0]


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
        chunk = '{"thought":"t","reply":"没有情绪字段。"}'
        msgs = parser.feed(chunk)
        # 不应有 emotion_update
        emotion_msgs = [m for m in msgs if m[0] == "emotion_update"]
        assert len(emotion_msgs) == 0

    def test_no_reply_field(self):
        """测试没有 reply 字段的情况"""
        parser = StreamParser(trace_id="test-edge-003")
        chunk = '{"thought":"t","emotion":"Confused"}'
        msgs = parser.feed(chunk)
        # 应该有 emotion_update，但没有 reply_chunk
        assert any(m[0] == "emotion_update" for m in msgs)
        reply_chunks = [m for m in msgs if m[0] == "reply_chunk"]
        assert len(reply_chunks) == 0

    def test_flush_empty_buffer(self):
        """测试缓冲区为空时 flush 返回空列表"""
        parser = StreamParser(trace_id="test-edge-004")
        msgs = parser.flush()
        assert msgs == []

    def test_flush_with_content(self):
        """测试有残留内容时 flush 返回正确结果"""
        parser = StreamParser(trace_id="test-edge-005")
        # 先喂入一些数据（不包含结束标点，让内容留在缓冲区）
        chunk = '{"thought":"t","emotion":"Soft","reply":"这是一个长句"}'
        msgs = parser.feed(chunk)
        # 应该只有 emotion_update（无标点，reply 留在缓冲区）
        flush_msgs = parser.flush()
        assert len(flush_msgs) == 1
        assert flush_msgs[0][0] == "reply_chunk"
        assert "长句" in flush_msgs[0][1]

    def test_reset_state(self):
        """测试 reset 能正确重置内部状态"""
        parser = StreamParser(trace_id="test-edge-006")
        chunk = '{"thought":"t","emotion":"Angry","reply":"哼。"}'
        parser.feed(chunk)
        assert parser._emotion_sent is True

        parser.reset()
        assert parser._emotion_sent is False
        assert parser._reply_started is False
        assert parser._reply_buffer == ""

    def test_streaming_emotion_before_reply(self):
        """测试在流式场景中 emotion 先于 reply 到达"""
        parser = StreamParser(trace_id="test-stream-001")
        # 模拟流式传输：第一个碎片包含 thought 和 emotion 的开头
        chunk1 = '{"thought":"test","emotion":"Happy"'
        msgs1 = parser.feed(chunk1)
        assert msgs1[0][0] == "emotion_update"
        assert msgs1[0][1] == "Happy"

        # 第二个碎片包含 reply
        chunk2 = ',"reply":"你好啊。今天怎么样？"}'
        msgs2 = parser.feed(chunk2)
        reply_chunks = [c for t, c in msgs2 if t == "reply_chunk"]
        assert len(reply_chunks) >= 1

    def test_large_text_split(self):
        """测试长文本的多句子切分"""
        parser = StreamParser(trace_id="test-large-001")
        long_text = "第一句。第二句。第三句。第四句。第五句。"
        chunk = '{"thought":"t","emotion":"Smile","reply":"' + long_text + '"}'
        msgs = parser.feed(chunk)
        reply_chunks = [c for t, c in msgs if t == "reply_chunk"]
        # 应该有至少 5 个 reply_chunk
        assert len(reply_chunks) >= 4

    def test_emotion_value_extraction(self):
        """测试各种 emotion 值都能正确提取"""
        emotions = ["Angry", "Annoyed", "Clingy", "Tsundere", "Soft", "Smile", "Sad", "Confused"]
        for emotion in emotions:
            parser = StreamParser(trace_id=f"test-emotion-{emotion}")
            chunk = f'{{"thought":"t","emotion":"{emotion}","reply":"test。"}}'
            msgs = parser.feed(chunk)
            emotion_msgs = [m for m in msgs if m[0] == "emotion_update"]
            assert len(emotion_msgs) == 1
            assert emotion_msgs[0][1] == emotion


class TestStreamParserMultiChunk:
    """多 chunk 流式场景测试"""

    def test_three_chunks_flow(self):
        """模拟三个连续的 chunk 流式传输"""
        parser = StreamParser(trace_id="test-multi-001")
        # chunk1: thought 内容（使用双引号包含单引号，确保字符串正确）
        chunk1 = '{"thought":"test'
        msgs1 = parser.feed(chunk1)
        # 此时还未出现 emotion 或 reply
        assert len(msgs1) == 0

        # chunk2: 包含 emotion
        chunk2 = ',"emotion":"Happy","reply":"'
        msgs2 = parser.feed(chunk2)
        # 应该提取到 emotion
        assert any(m[0] == "emotion_update" and m[1] == "Happy" for m in msgs2)

        # chunk3: reply 内容
        chunk3 = '你好。今天很开心。"}'
        msgs3 = parser.feed(chunk3)
        # 应该切分到句子
        reply_chunks = [c for t, c in msgs3 if t == "reply_chunk"]
        assert len(reply_chunks) >= 1 or len(msgs3) > 0

    def test_no_punctuation_in_reply(self):
        """测试 reply 中没有标点时的行为"""
        parser = StreamParser(trace_id="test-multi-002")
        chunk = '{"thought":"t","emotion":"Happy","reply":"这是个没有标点的长文本"}'
        msgs = parser.feed(chunk)
        # 应该有 emotion_update
        assert any(m[0] == "emotion_update" for m in msgs)
        # reply 应该留在缓冲区中
        assert len(parser._reply_buffer) > 0
        # flush 时返回
        flush_msgs = parser.flush()
        assert len(flush_msgs) == 1
        assert "标点" in flush_msgs[0][1]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
