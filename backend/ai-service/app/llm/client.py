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
import json
from collections.abc import AsyncGenerator
from typing import Any

from openai import APIConnectionError, APIError, AsyncOpenAI, BadRequestError, RateLimitError
from pydantic import BaseModel, ValidationError
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.types.constants import (
    LLM_STRUCTURED_OUTPUT_UNSUPPORTED_PROVIDER_KEYWORDS,
    Role,
)
from app.llm.context_manager import (
    format_messages_for_api,
    should_flush_buffer,
)
from app.logger import logger

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
    finish_reason: str | None = None
    error: str | None = None


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
        self._buffer: list[str] = []

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
        self.client = None
        self.model_name = ""
        self.reload_config()

    def reload_config(self) -> None:
        """
        重新加载配置并重新初始化客户端
        """
        from app.config.settings import global_config_container
        from app.types.constants import ModelSize
        config = global_config_container.get_model_config(ModelSize.SMALL)
        api_key = config.get("api_key") or "dummy"
        base_url = config.get("base_url") or "https://api.openai.com/v1"
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
        )
        self.model_name = config.get("model_id") or "gpt-4o-mini"

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((RateLimitError, APIConnectionError)),
        reraise=True,
        before_sleep=before_sleep_log(logger, 20),
    )
    async def summarize(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        from app.config.settings import global_config_container
        from app.types.constants import ModelSize
        config = global_config_container.get_model_config(ModelSize.SMALL)
        model_name = config.get("model_id") or self.model_name
        logger.info(f"正在调用压缩模型 API: {model_name}")
        max_tokens = config.get("max_tokens")
        temperature = config.get("temperature", 0.7)

        call_kwargs = {
            "model": model_name,
            "messages": messages,
            "stream": False,
            "temperature": temperature,
            **kwargs
        }
        if max_tokens and max_tokens > 0:
            call_kwargs["max_tokens"] = max_tokens

        response = await self.client.chat.completions.create(**call_kwargs)
        return response.choices[0].message.content or ""


class LLMClient:
    """
    LLM 客户端封装，提供统一的流式对话接口、重试机制和上下文管理

    做什么：封装 AsyncOpenAI 客户端，集成上下文截断、流式输出缓冲和异常容错。
    为什么这样做：作为 LLM 调用的唯一入口，确保所有调用经过统一的校验、重试和审计流程。
    """

    def __init__(self) -> None:
        """初始化 AsyncOpenAI 客户端"""
        self.client = None
        self.model_name = ""
        self.base_url = ""
        self.reload_config()

    def reload_config(self) -> None:
        """
        重新加载配置并重新初始化客户端
        """
        logger.info("LLM Client 正在重新加载配置...")
        from app.config.settings import global_config_container
        from app.types.constants import ModelSize
        # 默认使用中模型进行日常对话
        config = global_config_container.get_model_config(ModelSize.MEDIUM)
        api_key = config.get("api_key") or "dummy"
        base_url = config.get("base_url") or "https://api.openai.com/v1"
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
        )
        self.model_name = config.get("model_id") or "gpt-3.5-turbo"
        self.base_url = base_url

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
        current_message: str,
        **kwargs: Any
    ) -> Any:
        logger.info("正在调用 LLM API（带重试机制）")
        # 内部统一封装为单体 user 消息
        messages = [{
                        "role": Role.SYSTEM.value,
                        "content": prompt
                    },
                    {
                        "role": Role.USER.value,
                        "content": current_message
                    }
                ]
        
        from app.config.settings import global_config_container
        from app.types.constants import ModelSize
        config = global_config_container.get_model_config(ModelSize.LARGE)
        max_tokens = config.get("max_tokens")
        temperature = config.get("temperature", 0.7)

        call_kwargs = {
            "model": self.model_name,
            "messages": messages,
            "stream": True,
            "temperature": temperature,
            "timeout": 60.0,  # API 调用超时 60 秒
            **kwargs
        }
        if max_tokens and max_tokens > 0:
            call_kwargs["max_tokens"] = max_tokens

        return await self.client.chat.completions.create(**call_kwargs)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((RateLimitError, APIConnectionError, asyncio.TimeoutError)),
        reraise=True,
        before_sleep=before_sleep_log(logger, 20),
    )
    async def generate_structured(
        self,
        model: str,
        messages: list[dict[str, str]],
        response_format: type[BaseModel],
        timeout: float = 15.0,
        **kwargs: Any
    ) -> BaseModel:
        """
        调用大模型并强制返回结构化 JSON 数据

        做什么：发送请求并指定 response_format 约束，强制 LLM 返回符合 Pydantic Schema 的 JSON。
                若模型不支持原生 structured output（如 DeepSeek），自动降级为普通对话后解析 JSON。
        为什么这样做：确保智能层输出的数据结构符合预期的 Pydantic 模型定义，在进入业务流程前完成校验。
        输入输出：
            - 输入：model 模型名称、messages 消息列表、response_format Pydantic 模型类、timeout 超时秒数
            - 输出：经过 Pydantic 校验后的模型实例
        边界条件：
            - 某些 API 网关/代理不支持 OpenAI 原生的 json_schema 约束，回退返回 markdown 包裹的 JSON
            - 空内容会触发 ValueError
        异常行为：
            - 网络错误/限流由 tenacity 自动重试
            - 模型不支持 structured output（400 BadRequest）时自动降级重试
            - JSON 解析失败抛出 ValidationError
        """
        logger.info(f"正在调用 LLM API (Structured Outputs), model: {model}")
        
        from app.config.settings import global_config_container
        from app.types.constants import ModelSize
        config = global_config_container.get_model_config(ModelSize.MEDIUM)
        temperature = config.get("temperature", 0.7)

        call_kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "timeout": timeout,
            **kwargs
        }

        if self._should_use_native_structured_output(model):
            # === 第一阶段：仅在供应商明确支持时尝试原生 structured output ===
            # DeepSeek 当前会直接拒绝 json_schema 类型的 response_format；提前绕开可避免
            # 产生 400 Bad Request 噪声，并减少 InputReconstructor 的无效重试。
            structured_kwargs = dict(call_kwargs)
            structured_kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": response_format.__name__,
                    "schema": response_format.model_json_schema(),
                    "strict": True
                }
            }

            try:
                response = await self.client.chat.completions.create(**structured_kwargs)
                content = response.choices[0].message.content
            except BadRequestError as e:
                # 模型不支持 structured output 时降级为普通对话，避免结构化 Agent 直接中断。
                logger.warning(
                    f"[StructuredOutput] 模型 {model} 不支持原生结构化输出，"
                    f"已切换为 Prompt Schema 约束降级调用，错误原因: {e!s}"
                )
                content = await self._fallback_structured_call(call_kwargs, response_format)
            except Exception as e:
                # 其他错误也尝试降级，保证输入重构链路有机会获得可解析 JSON。
                logger.warning(
                    f"[StructuredOutput] 原生结构化输出调用失败，"
                    f"已切换为 Prompt Schema 约束降级调用，异常类型: {type(e).__name__}, 原因: {e!s}"
                )
                content = await self._fallback_structured_call(call_kwargs, response_format)
        else:
            content = await self._fallback_structured_call(call_kwargs, response_format)
        
        if not content:
            raise ValueError("LLM 返回了空内容")
        
        # 清理可能存在的 markdown 代码块包裹
        cleaned = content.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]  # 去掉 ```json
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]  # 去掉 ```
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]  # 去掉结尾的 ```
        cleaned = cleaned.strip()
        
        if cleaned != content:
            logger.info(
                f"[StructuredOutput] LLM 返回的内容包含 markdown 代码块包裹，已自动清理。"
                f"原始内容前 50 字符: {content[:50]!r}"
            )
            
        return response_format.model_validate_json(cleaned)

    def _should_use_native_structured_output(self, model: str) -> bool:
        """
        判断当前模型接入是否允许使用 OpenAI 原生结构化输出参数。

        做什么：根据模型名称与当前 base_url 识别已知不支持 json_schema response_format
                的供应商，并在调用前切换到 Prompt Schema 降级模式。
        为什么这样做：DeepSeek 兼容接口当前会返回“response_format type unavailable”
                的 400 错误；预判能力可以避免请求层报错噪声和 Agent 层重复重试。
        输入输出：
            - 输入：model 为本次调用使用的模型名称
            - 输出：True 表示允许发送 response_format，False 表示必须走降级调用
        边界条件：model 或 base_url 为空时不命中禁用关键字，默认按 OpenAI 兼容能力尝试。
        异常行为：本方法不抛异常，只负责保守能力判断。
        """
        capability_probe_text = f"{model} {self.base_url}".lower()
        for provider_keyword in LLM_STRUCTURED_OUTPUT_UNSUPPORTED_PROVIDER_KEYWORDS:
            if provider_keyword in capability_probe_text:
                logger.info(
                    f"[StructuredOutput] 检测到模型接入 {provider_keyword} 暂不支持原生结构化输出，"
                    f"model={model}，将直接使用 Prompt Schema 降级模式"
                )
                return False
        return True

    async def _fallback_structured_call(
        self,
        call_kwargs: dict[str, Any],
        response_format: type[BaseModel],
    ) -> str:
        """
        structured output 降级调用：使用普通对话并注入 JSON Schema 到 system prompt，
        要求 LLM 返回符合 Schema 的纯 JSON。

        做什么：当模型不支持 response_format 参数时，将 JSON Schema 注入到 system prompt
                末尾，引导模型自行生成符合结构的 JSON 输出。
        返回：清理后的 JSON 字符串（可能包含 markdown 代码块包裹，由调用方清理）。
        """
        fallback_messages = list(call_kwargs["messages"])
        schema_json = response_format.model_json_schema()

        # 在 system prompt 末尾追加 JSON Schema 约束说明
        schema_prompt = (
            "\n\n你必须以 JSON 格式回复，严格遵循以下 JSON Schema 定义：\n"
            f"{json.dumps(schema_json, ensure_ascii=False, indent=2)}\n\n"
            "请确保输出的 JSON 完全符合上述 Schema，不要包含任何额外说明文字。"
        )

        for i, msg in enumerate(fallback_messages):
            if msg.get("role") == "system":
                fallback_messages[i] = {
                    "role": "system",
                    "content": msg["content"] + schema_prompt
                }
                break
        else:
            # 没有 system message，添加一个
            fallback_messages.insert(0, {
                "role": "system",
                "content": schema_prompt
            })

        fallback_kwargs = dict(call_kwargs)
        fallback_kwargs["messages"] = fallback_messages
        # 移除可能残留的 response_format 相关 key
        fallback_kwargs.pop("response_format", None)

        logger.info("[StructuredOutput] 执行降级调用：注入 JSON Schema 到 system prompt")
        response = await self.client.chat.completions.create(**fallback_kwargs)
        return response.choices[0].message.content or ""

    async def generate_structured_text(
        self,
        model: str,
        messages: list[dict[str, str]],
        timeout: float = 30.0,
        **kwargs: Any,
    ) -> str:
        """
        调用大模型并返回非流式文本。

        做什么：为后台摘要类任务提供统一的非流式文本调用入口。
        为什么这样做：用户画像压缩摘要需要普通文本输出，不适合复用流式聊天接口。
        输入输出：输入模型名和 messages，输出模型文本。
        边界条件：空内容返回空字符串，由调用方判定是否失败。
        异常行为：网络错误由 OpenAI 客户端抛出，调用方负责记录。
        """
        response = await self.client.chat.completions.create(
            model=model,
            messages=messages,
            stream=False,
            timeout=timeout,
            **kwargs,
        )
        return response.choices[0].message.content or ""

    async def stream_chat(
        self,
        prompt: str,
        trace_id: str,
        current_message: str,
        **kwargs: Any
    ) -> AsyncGenerator[dict[str, Any], None]:
        logger.info(f"[TraceID:{trace_id}] 开始调用 LLM API, model: {self.model_name}, prompt: {prompt}")
        buffer = LLMStreamBuffer()

        try:
            response = await self._call_api_with_retry(prompt, current_message, **kwargs)

            import time as _time
            _last_chunk_time = _time.monotonic()
            STREAM_TIMEOUT = 120.0  # 120秒内若无新 chunk 则判定流式超时

            async for chunk in response:
                # 检查流式超时：距离上次收到 chunk 超过 STREAM_TIMEOUT 秒
                now = _time.monotonic()
                if now - _last_chunk_time > STREAM_TIMEOUT:
                    logger.error(f"[TraceID:{trace_id}] LLM 流式输出超时（{STREAM_TIMEOUT}s 无新 chunk）")
                    error_model = StreamChunkModel(
                        chunk="",
                        is_finished=True,
                        finish_reason="timeout",
                        error="AI 回复超时，请稍后重试",
                    )
                    yield error_model.model_dump()
                    break

                # 收到有效 chunk，重置超时计数器
                _last_chunk_time = now

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
                except ValidationError as validation_error:
                    logger.error(f"[TraceID:{trace_id}] 取消兜底块校验失败: {validation_error}")
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
                except ValidationError as validation_error:
                    logger.error(f"[TraceID:{trace_id}] 异常兜底块校验失败: {validation_error}")
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
        history: list[dict[str, str]],
        current_message: str,
        trace_id: str,
        disambiguated_text: str = "",
        **kwargs: Any
    ) -> AsyncGenerator[dict[str, Any], None]:
        """
        带上下文管理的流式对话接口
        """
        # 1. 尝试进行 Token 截断 (复用现有逻辑获取截断后的列表)
        try:
            from app.config.settings import global_config_container
            from app.types.constants import ModelSize
            config = global_config_container.get_model_config(ModelSize.MEDIUM)
            max_context_tokens = config.get("max_context_tokens", 128000)
            
            truncated_messages = format_messages_for_api(
                system_prompt=system_prompt,
                history=history,
                current_message=current_message,
                max_context_tokens=max_context_tokens,
                model_name=self.model_name,
            )
        except Exception as e:
            logger.error(f"[TraceID:{trace_id}] 上下文截断失败，使用原始消息: {e}")
            truncated_messages = [
                {"role": Role.SYSTEM.value, "content": system_prompt},
                *history,
                {"role": Role.USER.value, "content": current_message},
            ]

        # 2. 将截断后的结构化消息合并为单体完整提示词文本
        combined_prompt_parts = []
        for msg in truncated_messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == Role.SYSTEM.value:
                combined_prompt_parts.append(content)

        full_combined_prompt = "\n\n".join(combined_prompt_parts)

        # 3. 替换 LLM 请求中的当前用户消息为重构后的无歧义文本
        final_message = disambiguated_text if disambiguated_text else current_message

        # 4. 以单体文本发起请求
        async for chunk_data in self.stream_chat(full_combined_prompt, trace_id, final_message, **kwargs):
            yield chunk_data


# 全局单例
llm_client = LLMClient()
compression_llm_client = CompressionLLMClient()
