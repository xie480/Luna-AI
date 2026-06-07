"""
LLM 结构化输出能力探测测试。

做什么：验证 LLMClient 在 DeepSeek 等不支持原生 response_format 的供应商下，
        能够提前切换到 Prompt Schema 降级模式，避免请求层 400 Bad Request。
为什么这样做：InputReconstructor 依赖结构化 JSON，如果每次都先发送 DeepSeek 不支持的
          response_format=json_schema，会造成无效报错、重试噪声和用户侧延迟。
"""

from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from app.llm.client import LLMClient


class DemoStructuredOutput(BaseModel):
    """
    结构化输出测试模型。

    做什么：提供最小 Pydantic Schema，用于验证 generate_structured 的请求构造和解析。
    输入输出：value 为模型返回的字符串字段。
    边界条件：缺失 value 时 Pydantic 会抛出校验错误。
    """

    value: str


class FakeChatCompletions:
    """
    OpenAI Chat Completions 的测试替身。

    做什么：记录每一次 create 调用参数，并按配置返回内容或抛出异常。
    为什么这样做：避免测试访问真实网络，同时精确断言 response_format 是否被发送。
    输入输出：create 接收任意关键字参数，返回带 choices[0].message.content 的对象。
    异常行为：当 side_effects 包含异常对象时，按顺序抛出该异常。
    """

    def __init__(self, contents: list[str], side_effects: list[Exception] | None = None) -> None:
        """
        初始化测试替身。

        做什么：保存响应内容队列和异常队列。
        边界条件：响应内容不足时复用最后一条内容。
        """
        self.calls: list[dict] = []
        self.contents = contents
        self.side_effects = side_effects or []

    async def create(self, **kwargs):
        """
        模拟异步模型调用。

        做什么：记录请求参数，并返回 OpenAI SDK 兼容的最小响应对象。
        异常行为：如果当前调用序号存在 side_effect，则抛出对应异常。
        """
        self.calls.append(kwargs)
        call_index = len(self.calls) - 1
        if call_index < len(self.side_effects):
            raise self.side_effects[call_index]
        content_index = min(call_index, len(self.contents) - 1)
        message = SimpleNamespace(content=self.contents[content_index])
        choice = SimpleNamespace(message=message)
        return SimpleNamespace(choices=[choice])


def build_test_client(fake_completions: FakeChatCompletions, base_url: str) -> LLMClient:
    """
    构造带测试替身的 LLMClient。

    做什么：复用真实 LLMClient 的请求构造逻辑，但替换底层 OpenAI 客户端为内存替身。
    输入输出：输入 fake_completions 和 base_url，输出可直接调用的 LLMClient 实例。
    """
    llm_client = LLMClient()
    llm_client.base_url = base_url
    llm_client.client = SimpleNamespace(
        chat=SimpleNamespace(completions=fake_completions)
    )
    return llm_client


@pytest.mark.asyncio
async def test_generate_structured_skips_response_format_for_deepseek() -> None:
    """
    验证 DeepSeek 接入会直接跳过原生 response_format。

    做什么：模拟 base_url 包含 deepseek 的场景，断言请求中不包含 response_format。
    为什么这样做：DeepSeek 当前会返回 response_format type unavailable 的 400 错误。
    """
    fake_completions = FakeChatCompletions(contents=['{"value":"ok"}'])
    llm_client = build_test_client(fake_completions, "https://api.deepseek.com")

    result = await llm_client.generate_structured(
        model="deepseek-chat",
        messages=[{"role": "system", "content": "返回 JSON"}],
        response_format=DemoStructuredOutput,
    )

    assert result.value == "ok"
    assert len(fake_completions.calls) == 1
    assert "response_format" not in fake_completions.calls[0]
    assert "JSON Schema" in fake_completions.calls[0]["messages"][0]["content"]


@pytest.mark.asyncio
async def test_generate_structured_uses_native_response_format_for_openai() -> None:
    """
    验证 OpenAI 接入仍使用原生 json_schema response_format。

    做什么：模拟 OpenAI base_url，断言请求包含 response_format=json_schema。
    为什么这样做：不能因为 DeepSeek 降级而破坏支持原生结构化输出的模型能力。
    """
    fake_completions = FakeChatCompletions(contents=['{"value":"ok"}'])
    llm_client = build_test_client(fake_completions, "https://api.openai.com/v1")

    result = await llm_client.generate_structured(
        model="gpt-4o-mini",
        messages=[{"role": "system", "content": "返回 JSON"}],
        response_format=DemoStructuredOutput,
    )

    assert result.value == "ok"
    assert len(fake_completions.calls) == 1
    assert fake_completions.calls[0]["response_format"]["type"] == "json_schema"


@pytest.mark.asyncio
async def test_generate_structured_falls_back_after_native_failure() -> None:
    """
    验证原生结构化输出失败后会移除 response_format 并降级重试。

    做什么：第一次调用抛出异常，第二次返回 JSON，断言第二次请求不再携带 response_format。
    异常行为：失败不会向 Agent 泄漏为最终异常，除非降级响应也无法解析。
    """
    fake_completions = FakeChatCompletions(
        contents=['{"value":"ok"}', '{"value":"fallback"}'],
        side_effects=[RuntimeError("模拟原生结构化输出失败")],
    )
    llm_client = build_test_client(fake_completions, "https://api.openai.com/v1")

    result = await llm_client.generate_structured(
        model="gpt-4o-mini",
        messages=[{"role": "system", "content": "返回 JSON"}],
        response_format=DemoStructuredOutput,
    )

    assert result.value == "fallback"
    assert len(fake_completions.calls) == 2
    assert "response_format" in fake_completions.calls[0]
    assert "response_format" not in fake_completions.calls[1]
