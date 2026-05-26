"""
Luna AI LLM 客户端封装模块

做什么：封装 AsyncOpenAI 客户端，提供统一的流式对话接口，集成上下文管理器进行历史记录
        管理和 Token 截断，实现流式输出缓冲平滑机制，以及全面的异常分类容错处理。
为什么这样做：确保所有 LLM 调用经过统一的入口，满足 agent.md 中关于结构化输出校验、
         重试机制、流式输出规范的要求。同时提供流畅的用户体验和健壮的错误处理。
输入输出：
    - stream_chat(): 异步生成器，yield Pydantic 校验后的 StreamChunkModel dict
    - llm_client: 全局单例
边界条件：
    - 支持自定义 system_prompt
    - 支持自定义 max_tokens / temperature 等 API 参数
    - Token 超限时静默截断
    - 流式输出使用 buffer 合并后输出，减少前端渲染频率
异常行为：
    - APIError: 记录错误日志并返回结构化错误响应
    - RateLimitError: 触发 tenacity 重试（最多 3 次，指数退避）
    - APIConnectionError: 触发 tenacity 重试
    - 未知异常: 返回通用错误响应，防止崩溃传播到 Go 端
"""

import asyncio
from typing import AsyncGenerator, Dict, List, Optional, Any

from openai import AsyncOpenAI, APIError, RateLimitError, APIConnectionError
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)
from pydantic import BaseModel, ValidationError

from app.config import settings
from app.logger import get_logger
from app.agent.prompts import get_system_prompt, render_runtime_prompt
from app.constants import Role
from app.llm.context_manager import (
    format_messages_for_api,
    should_flush_buffer,
    MAX_CONTEXT_TOKENS,
    RESERVED_OUTPUT_TOKENS,
)

logger = get_logger(__name__)


# ============================================================
# 数据结构模型
# ============================================================

class StreamChunkModel(BaseModel):
    """
    流式输出数据结构校验模型

    做什么：使用 Pydantic 对流式输出的每个 Chunk 进行结构化校验。
    为什么这样做：确保输出数据结构的一致性和正确性，满足 agent.md 规范要求。
    输入输出：
        - chunk: 文本块内容（经过缓冲合并后的语义单元）
        - is_finished: 是否结束标志
        - finish_reason: 结束原因（stop / length / error）
        - error: 错误信息（可选）
    边界条件：finish_reason 和 error 可为 None。
    异常行为：如果数据不符合模型定义，Pydantic 会抛出 ValidationError。
    """
    chunk: str
    is_finished: bool
    finish_reason: Optional[str] = None
    error: Optional[str] = None


class LLMStreamBuffer:
    """
    流式输出缓冲器，用于合并小 Token 为语义完整的输出块

    做什么：内部维护缓冲区，将多个小 chunk 合并后再统一输出。
    为什么这样做：LLM 生成的单次 token 可能只有 1-3 个字符，逐字推送会增加前端渲染压力。
              通过缓冲合并，输出语义更完整的短语或短句，提升用户体验。
    输入输出：
        - add(): 添加新文本到缓冲区
        - flush(): 返回并清空缓冲区内容
        - should_flush(): 判断是否需要刷新
    边界条件：
        - 空文本不会被添加到缓冲区
        - 收到结束信号时必须强制 flush 剩余内容
    异常行为：无。
    """

    def __init__(self) -> None:
        """初始化缓冲区"""
        self._buffer: List[str] = []

    def add(self, text: str) -> None:
        """
        添加文本块到缓冲区

        做什么：将 LLM 返回的小 chunk 添加到内部缓冲区。
        输入输出：
            - 输入：text 文本块
        边界条件：空文本不处理。
        """
        if text:
            self._buffer.append(text)

    def should_flush(self) -> bool:
        """
        判断是否需要刷新缓冲区

        做什么：根据缓冲区内容和阈值判断是否应该输出。
        为什么这样做：避免逐 Token 输出，合并为语义完整的短句后输出。
        输入输出：
            - 输出：True 表示需要刷新，False 表示继续累积
        边界条件：
            - 空缓冲区不刷新
            - 遇句子结束符优先刷新
        """
        current_text = "".join(self._buffer)
        need_flush, _ = should_flush_buffer(current_text)
        return need_flush

    def flush(self) -> str:
        """
        刷新缓冲区，返回累积文本并清空

        做什么：返回当前缓冲区中所有文本的拼接，然后清空缓冲区。
        输入输出：
            - 输出：缓冲区累积的文本字符串
        边界条件：空缓冲区返回空字符串。
        """
        result = "".join(self._buffer)
        self._buffer.clear()
        return result

    def peek(self) -> str:
        """
        查看缓冲区当前内容（不消耗）

        做什么：返回当前缓冲区中的文本拼接但不清空。
        输入输出：
            - 输出：缓冲区累积的文本字符串
        """
        return "".join(self._buffer)

    @property
    def is_empty(self) -> bool:
        """缓冲区是否为空"""
        return len(self._buffer) == 0


# ============================================================
# LLM 客户端主类
# ============================================================

class CompressionLLMClient:
    """
    专门用于后台摘要压缩的 LLM 客户端
    """

    def __init__(self) -> None:
        self.client = AsyncOpenAI(
            api_key=settings.compression_api_key or "dummy",
            base_url=settings.compression_api_base,
        )
        self.model_name = settings.compression_model_name

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((RateLimitError, APIConnectionError)),
        reraise=True,
        before_sleep=before_sleep_log(logger, 20),
    )
    async def summarize(self, messages: List[Dict[str, str]], **kwargs: Any) -> str:
        logger.info(f"正在调用压缩模型 API: {self.model_name}")
        response = await self.client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            stream=False,
            **kwargs
        )
        return response.choices[0].message.content or ""


class LLMClient:
    """
    LLM 客户端封装，提供统一的流式对话接口、重试机制和上下文管理

    做什么：封装 AsyncOpenAI 客户端，集成上下文截断、流式输出缓冲和异常容错。
    为什么这样做：作为 LLM 调用的唯一入口，确保所有调用经过统一的校验、重试和审计流程。
    """

    def __init__(self) -> None:
        """初始化 AsyncOpenAI 客户端"""
        self.client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_api_base,
        )
        self.model_name = settings.model_name

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((RateLimitError, APIConnectionError)),
        reraise=True,
        before_sleep=before_sleep_log(logger, 20),
    )
    async def _call_api_with_retry(
        self,
        prompt: str,
        **kwargs: Any
    ) -> Any:
        logger.info("正在调用 LLM API（带重试机制）")
        # 内部统一封装为单体 user 消息
        messages = [{"role": Role.USER.value, "content": prompt}]
        return await self.client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            stream=True,
            **kwargs
        )

    async def stream_chat(
        self,
        prompt: str,
        trace_id: str,
        **kwargs: Any
    ) -> AsyncGenerator[Dict[str, Any], None]:
        logger.info(f"[TraceID:{trace_id}] 开始调用 LLM API, model: {self.model_name}")
        buffer = LLMStreamBuffer()

        try:
            response = await self._call_api_with_retry(prompt, **kwargs)

            async for chunk in response:
                # 检查是否收到结束信号（流结束且无 choices）
                if chunk.choices is None or len(chunk.choices) == 0:
                    # 部分 API 实现会在流结束时返回空 choices
                    continue

                delta = chunk.choices[0].delta
                finish_reason = chunk.choices[0].finish_reason

                # 提取内容（可能为 None）
                content = delta.content if delta.content else ""
                is_finished = finish_reason is not None

                # 将新内容添加到缓冲区
                buffer.add(content)

                # 如果流结束，强制刷新缓冲区
                if is_finished:
                    remaining = buffer.flush()
                    if remaining:
                        try:
                            chunk_model = StreamChunkModel(
                                chunk=remaining,
                                is_finished=False,
                                finish_reason=None,
                                error=None,
                            )
                            yield chunk_model.model_dump()
                        except ValidationError as ve:
                            logger.error(
                                f"[TraceID:{trace_id}] 最终块 Pydantic 校验失败: {ve}"
                            )

                    # 发送结束标记
                    try:
                        finish_model = StreamChunkModel(
                            chunk="",
                            is_finished=True,
                            finish_reason=finish_reason or "stop",
                            error=None,
                        )
                        yield finish_model.model_dump()
                    except ValidationError as ve:
                        logger.error(
                            f"[TraceID:{trace_id}] 结束标记 Pydantic 校验失败: {ve}"
                        )
                    break

                # 判断是否应该刷新缓冲区
                if buffer.should_flush():
                    flushed_text = buffer.flush()
                    if flushed_text:
                        try:
                            chunk_model = StreamChunkModel(
                                chunk=flushed_text,
                                is_finished=False,
                                finish_reason=None,
                                error=None,
                            )
                            yield chunk_model.model_dump()
                        except ValidationError as ve:
                            logger.error(
                                f"[TraceID:{trace_id}] 块校验失败: {ve}"
                            )

            # 循环结束前，确保缓冲区被清空（兜底）
            if not buffer.is_empty:
                remaining = buffer.flush()
                if remaining:
                    try:
                        chunk_model = StreamChunkModel(
                            chunk=remaining,
                            is_finished=True,
                            finish_reason="stop",
                            error=None,
                        )
                        yield chunk_model.model_dump()
                    except ValidationError as ve:
                        logger.error(
                            f"[TraceID:{trace_id}] 兜底块校验失败: {ve}"
                        )

            logger.info(f"[TraceID:{trace_id}] LLM API 调用完成")

        except (RateLimitError, APIConnectionError) as e:
            # Tenacity 重试耗尽后仍失败的异常
            logger.error(
                f"[TraceID:{trace_id}] LLM API 重试耗尽后仍失败: {type(e).__name__}: {e}"
            )
            error_model = StreamChunkModel(
                chunk="",
                is_finished=True,
                finish_reason="error",
                error=f"AI 服务暂时不可用（{type(e).__name__}），请稍后重试",
            )
            yield error_model.model_dump()

        except APIError as e:
            # OpenAI API 返回的异常（如 400/500 等）
            logger.error(
                f"[TraceID:{trace_id}] LLM API 返回错误: "
                f"status_code={e.status_code}, message={e.message}"
            )
            error_model = StreamChunkModel(
                chunk="",
                is_finished=True,
                finish_reason="error",
                error=f"AI 服务返回错误（{e.status_code}）: {e.message}",
            )
            yield error_model.model_dump()

        except asyncio.CancelledError:
            # 调用被取消（如用户中断、超时等）
            logger.warning(f"[TraceID:{trace_id}] LLM API 调用被取消")
            # flush 剩余缓冲
            remaining = buffer.flush()
            if remaining:
                try:
                    chunk_model = StreamChunkModel(
                        chunk=remaining,
                        is_finished=True,
                        finish_reason="cancelled",
                        error=None,
                    )
                    yield chunk_model.model_dump()
                except ValidationError:
                    pass
            else:
                error_model = StreamChunkModel(
                    chunk="",
                    is_finished=True,
                    finish_reason="cancelled",
                    error="对话已被取消",
                )
                yield error_model.model_dump()

        except Exception as e:
            # 其他未知异常，绝对不能崩溃传播
            logger.error(
                f"[TraceID:{trace_id}] LLM API 发生未知错误: {type(e).__name__}: {e}"
            )
            # 尝试发送缓冲的剩余内容
            remaining = buffer.flush()
            if remaining:
                try:
                    chunk_model = StreamChunkModel(
                        chunk=remaining,
                        is_finished=True,
                        finish_reason="error",
                        error=f"未知错误: {type(e).__name__}",
                    )
                    yield chunk_model.model_dump()
                except ValidationError:
                    pass
            else:
                error_model = StreamChunkModel(
                    chunk="",
                    is_finished=True,
                    finish_reason="error",
                    error=f"AI 服务发生未知错误（{type(e).__name__}），请稍后重试",
                )
                yield error_model.model_dump()

    async def stream_chat_with_context(
        self,
        system_prompt: str,
        history: List[Dict[str, str]],
        current_message: str,
        trace_id: str,
        core_summary: str = "",
        key_facts: str = "",
        **kwargs: Any
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        带上下文管理和 runtime 模板渲染的流式对话接口（外部调用推荐入口）

        做什么：
            1. 将 current_message 通过 render_runtime_prompt() 渲染，
               注入 runtime.j2 模板中的思维链要求和 JSON 输出格式约束。
            2. 使用 context_manager 进行 Token 截断。
            3. 调用 LLM API 并流式返回。

        为什么这样做：runtime.j2 包含输出格式规范（thought/emotion/reply JSON结构）
                    和四维思维链要求，必须显式渲染后作为 user message 传入 API。

        输入输出：
            - 输入：
                system_prompt: 系统提示词（为空时使用默认值）
                history: 历史消息列表
                current_message: 当前用户消息
                trace_id: 追踪 ID
                **kwargs: 其他 API 参数
            - 输出：AsyncGenerator，yield StreamChunkModel 的 dict
        边界条件：
            - system_prompt 为空时使用 app/agent/prompts.py 中的默认提示词
            - history 可为空列表
        异常行为：
            - 截断失败时使用未截断的 messages（兜底策略）
            - LLM 调用异常由 stream_chat 内部处理
        """
        # 使用默认 System Prompt
        effective_system_prompt = system_prompt if system_prompt else get_system_prompt()

        # 渲染 runtime 提示词：将当前用户输入注入 runtime.j2 模板
        # 输出包含思维链要求和 JSON 输出格式约束的完整 user message
        rendered_user_message = render_runtime_prompt(
            current_message=current_message,
            core_summary=core_summary,
            key_facts=key_facts,
        )

        # 1. 尝试进行 Token 截断 (复用现有逻辑获取截断后的列表)
        try:
            truncated_messages = format_messages_for_api(
                system_prompt=effective_system_prompt,
                history=history,
                current_message=rendered_user_message,
                model_name=self.model_name,
            )
        except Exception as e:
            logger.error(f"[TraceID:{trace_id}] 上下文截断失败，使用原始消息: {e}")
            truncated_messages = [
                {"role": Role.SYSTEM.value, "content": effective_system_prompt},
                *history,
                {"role": Role.USER.value, "content": rendered_user_message},
            ]

        # 2. 将截断后的结构化消息合并为单体完整提示词文本
        combined_prompt_parts = []
        for msg in truncated_messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == Role.SYSTEM.value:
                combined_prompt_parts.append(content)
            elif role == Role.USER.value:
                combined_prompt_parts.append(content)
            elif role == Role.ASSISTANT.value:
                combined_prompt_parts.append(content)

        full_combined_prompt = "\n\n".join(combined_prompt_parts)

        # 3. 以单体文本发起请求
        async for chunk_data in self.stream_chat(full_combined_prompt, trace_id, **kwargs):
            yield chunk_data


# 全局单例
llm_client = LLMClient()
compression_llm_client = CompressionLLMClient()
