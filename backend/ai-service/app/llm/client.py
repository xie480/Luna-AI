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

from app.context.compression_audit import (
    create_compression_audit_payload,
    current_timestamp_ms,
    record_compression_audit_payload,
    record_compression_span,
)
from app.context.compression_types import CompressionActionEvent
from app.types.constants import (
    COMPRESSION_EVENT_COMPLETED,
    COMPRESSION_EVENT_FAILED,
    COMPRESSION_EVENT_INPUT_MEASURED,
    COMPRESSION_EVENT_TRIGGERED,
    COMPRESSION_STATUS_FAILED,
    COMPRESSION_STATUS_SUCCESS,
    CompressionScope,
    CompressionStage,
    CompressionTriggerReason,
    LLM_STRUCTURED_OUTPUT_UNSUPPORTED_PROVIDER_KEYWORDS,
    Role,
)
from app.llm.context_manager import (
    format_messages_for_api,
    measure_truncate_context,
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
        import httpx
        config = global_config_container.get_model_config(ModelSize.SMALL)
        api_key = config.get("api_key") or "dummy"
        base_url = config.get("base_url") or "https://api.openai.com/v1"
        
        http_client = httpx.AsyncClient(
            limits=httpx.Limits(keepalive_expiry=2.0, max_keepalive_connections=5)
        )
        
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            http_client=http_client,
            max_retries=0,
        )
        self.model_name = config.get("model_id") or "gpt-4o-mini"

    def _build_summarize_call_kwargs(self, messages: list[dict[str, str]], kwargs: dict[str, Any]) -> dict[str, Any]:
        """
        构建压缩模型调用参数。

        做什么：从动态配置读取小模型名称、max_tokens 与 temperature，并合并调用方传入的请求参数。
        为什么这样做：压缩模型调用入口需要共享同一套配置装配逻辑，避免重试版与单次版参数不一致。
        输入输出：输入消息列表和额外参数字典，输出可传给 OpenAI Chat Completions 的参数字典。
        边界条件：max_tokens 未配置或小于等于 0 时不下发，避免覆盖供应商默认策略。
        异常行为：配置读取失败时让异常向上暴露，由调用方记录当前业务上下文。
        """
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
        return call_kwargs

    async def summarize_once(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        """
        单次调用压缩模型并返回摘要文本。

        做什么：不使用 tenacity 额外重试，直接调用 OpenAI Compatible Chat Completions。
        为什么这样做：用户画像摘要有本地兜底路径，额外重试会放大连接超时并导致后台缓存重建超过总时限。
        输入输出：输入 Chat 消息与请求参数，输出模型返回文本，空响应转换为空字符串。
        边界条件：调用方可传 timeout 控制单次请求耗时；max_tokens 仍由小模型动态配置控制。
        异常行为：网络、限流、超时异常原样抛出，由业务层决定是否兜底或重试。
        """
        from app.llm.client import llm_client
        wait_time = await llm_client.acquire_call_slot()
        if wait_time > 0:
            logger.info(f"触发频率限制，等待 {wait_time:.2f} 秒后发起 LLM 调用 (Summarize)")
            import asyncio
            await asyncio.sleep(wait_time)

        call_kwargs = self._build_summarize_call_kwargs(messages, kwargs)
        response = await self.client.chat.completions.create(**call_kwargs)
        return response.choices[0].message.content or ""

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((RateLimitError, APIConnectionError)),
        reraise=True,
        before_sleep=before_sleep_log(logger, 20),
    )
    async def summarize(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        """
        带重试调用压缩模型并返回摘要文本。

        做什么：为会话压缩、RAG 查询改写等需要模型摘要质量的链路提供重试版入口。
        为什么这样做：这些链路缺少用户画像那样的确定性本地兜底，网络瞬断时需要有限重试提升成功率。
        输入输出：输入 Chat 消息与请求参数，输出模型返回文本，空响应转换为空字符串。
        边界条件：重试仅覆盖限流和连接异常；业务层仍应设置 timeout 防止无限等待。
        异常行为：重试耗尽后原样抛出异常，由上层记录 trace_id 和任务上下文。
        """
        return await self.summarize_once(messages, **kwargs)


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
        self._next_allowed_time: float = 0.0
        self.reload_config()

    async def _wait_for_slot(
        self,
        trace_id: str = "",
        session_id: str = "",
        message_id: str = "",
    ) -> None:
        """
        等待调用槽位（频率限制），并在等待期间向前端发送状态通知。

        做什么：根据配置的 llm_call_interval_seconds 检查是否需要等待，
                若需等待则通过 SSE 直接向前端发送等待状态通知，然后异步休眠。
                所有 LLM 调用入口（generate_structured / generate_structured_text /
                stream_chat）共享此方法，共用一个时间窗口。
        为什么这样做：确保一段时间内仅允许发起一次大模型请求。状态通知在此内部
                    完成，调用方无需注入回调或适配节点。
        输入输出：
            - 输入：trace_id 全链路追踪 ID、session_id 会话 ID、message_id 消息 ID
        边界条件：interval <= 0 时不等待，直接返回。
        """
        from app.config.settings import settings
        interval = settings.llm_call_interval_seconds
        if interval <= 0:
            # 重置 _next_allowed_time，防止之前设置的非零间隔值残留导致虚假频率限制
            self._next_allowed_time = 0.0
            return

        import time as _time
        now = _time.monotonic()

        if self._next_allowed_time > now:
            wait_time = self._next_allowed_time - now
            self._next_allowed_time += interval
            logger.info(
                f"[TraceID:{trace_id}] 触发频率限制，等待 {wait_time:.2f} 秒后发起 LLM 调用"
            )

            # 在等待期间，通过 SSE 向前端发布等待状态，告知用户当前处于阻塞阶段
            if session_id and message_id:
                try:
                    from app.api.chat_status_texts import get_chat_status_text
                    from app.api.sse import sse_manager
                    from app.types.constants import (
                        CHAT_STATUS_SCHEMA_VERSION,
                        WS_MSG_TYPE_EVT_CHAT_STATUS,
                        ChatStatusStage,
                        ChatStatusState,
                    )

                    sse_payload: dict[str, object] = {
                        "schema_version": CHAT_STATUS_SCHEMA_VERSION,
                        "session_id": session_id,
                        "message_id": message_id,
                        "stage": ChatStatusStage.LLM_RATE_LIMIT_WAIT.value,
                        "state": ChatStatusState.RUNNING.value,
                        "display_text": get_chat_status_text(ChatStatusStage.LLM_RATE_LIMIT_WAIT, ChatStatusState.RUNNING),
                        "is_visible": True,
                        "is_terminal": False,
                        "sequence": 1,
                        "timestamp_ms": int(_time.time() * 1000),
                        "error": "",
                    }
                    sse_event: dict[str, object] = {
                        "type": WS_MSG_TYPE_EVT_CHAT_STATUS,
                        "trace_id": trace_id,
                        "payload": sse_payload,
                    }
                    await sse_manager.publish(sse_event)
                except Exception as e:
                    logger.warning(
                        f"[TraceID:{trace_id}] 等待 LLM 调用期间发布状态失败: {e}"
                    )

            await asyncio.sleep(wait_time)
        else:
            self._next_allowed_time = now + interval

    async def acquire_call_slot(self) -> float:
        """
        获取 LLM 调用槽位，返回需要等待的秒数。

        做什么：检查频率限制，若距离上次调用不足间隔时间则返回剩余等待秒数，
                否则返回 0 并记录下次允许调用的时间点。
        为什么这样做：为 CompressionLLMClient 等外部调用方提供统一的频率限制检查，
                    由调用方自行决定是否等待，与内部 _wait_for_slot 的逻辑分离。
        输入输出：
            - 输出：需要等待的秒数（0 表示无需等待可直接发起调用）
        边界条件：interval <= 0 时不限制，返回 0。
        """
        from app.config.settings import settings
        interval = settings.llm_call_interval_seconds
        if interval <= 0:
            # 重置 _next_allowed_time，防止之前设置的非零间隔值残留导致虚假频率限制
            self._next_allowed_time = 0.0
            return 0.0

        import time as _time
        now = _time.monotonic()

        if self._next_allowed_time > now:
            wait_time = self._next_allowed_time - now
            self._next_allowed_time += interval
            return max(wait_time, 0.0)
        else:
            self._next_allowed_time = now + interval
            return 0.0

    def reload_config(self) -> None:
        """
        重新加载配置并重新初始化客户端
        """
        logger.info("LLM Client 正在重新加载配置...")
        from app.config.settings import global_config_container
        from app.types.constants import ModelSize
        import httpx
        # 默认使用中模型进行日常对话
        config = global_config_container.get_model_config(ModelSize.MEDIUM)
        api_key = config.get("api_key") or "dummy"
        base_url = config.get("base_url") or "https://api.openai.com/v1"
        
        http_client = httpx.AsyncClient(
            limits=httpx.Limits(keepalive_expiry=2.0, max_keepalive_connections=5)
        )
        
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            http_client=http_client,
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
        
        # 从 kwargs 中提取链路标识用于频率限制等待状态通知
        await self._wait_for_slot(
            trace_id=str(kwargs.get("trace_id", "")),
            session_id=str(kwargs.get("session_id", "")),
            message_id=str(kwargs.get("message_id", "")),
        )

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
        await self._wait_for_slot(
            trace_id=str(kwargs.get("trace_id", "")),
            session_id=str(kwargs.get("session_id", "")),
            message_id=str(kwargs.get("message_id", "")),
        )

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
        session_id: str = "",
        message_id: str = "",
        **kwargs: Any
    ) -> AsyncGenerator[dict[str, Any], None]:
        logger.info(f"[TraceID:{trace_id}] 开始调用 LLM API, model: {self.model_name}, prompt: {prompt}")
        buffer = LLMStreamBuffer()

        await self._wait_for_slot(
            trace_id=trace_id,
            session_id=session_id,
            message_id=message_id,
        )

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
            # NOTE: When exception message formatting fails, safely fallback to type name
            try:
                error_msg = f"{type(e).__name__}: {e}"
            except Exception:
                error_msg = f"{type(e).__name__}"
            
            logger.error(
                f"[TraceID:{trace_id}] LLM API 发生未知错误: {error_msg}"
            )
            
            # 安全获取错误名称，避免 Pydantic 校验异常
            try:
                error_name = str(type(e).__name__)
            except Exception:
                error_name = "UnknownError"

            # 尝试发送缓冲的剩余内容
            remaining = buffer.flush()
            if remaining:
                try:
                    chunk_model = StreamChunkModel(
                        chunk=remaining,
                        is_finished=True,
                        finish_reason="error",
                        error=f"未知错误: {error_name}",
                    )
                    yield chunk_model.model_dump()
                except ValidationError as validation_error:
                    logger.error(f"[TraceID:{trace_id}] 异常兜底块校验失败: {validation_error}")
            else:
                try:
                    error_model = StreamChunkModel(
                        chunk="",
                        is_finished=True,
                        finish_reason="error",
                        error=f"AI 服务发生未知错误（{error_name}），请稍后重试",
                    )
                    yield error_model.model_dump()
                except ValidationError as validation_error:
                    logger.error(f"[TraceID:{trace_id}] 最终错误块校验失败: {validation_error}")
                    # 如果连带 error string 构造模型也失败了，最安全的退路是返回一个写死常量的模型
                    fallback_model = StreamChunkModel(
                        chunk="",
                        is_finished=True,
                        finish_reason="error",
                        error="AI 服务发生系统内部错误，请稍后重试",
                    )
                    yield fallback_model.model_dump()

    async def stream_chat_with_context(
        self,
        system_prompt: str,
        history: list[dict[str, str]],
        current_message: str,
        trace_id: str,
        disambiguated_text: str = "",
        session_id: str = "",
        message_id: str = "",
        **kwargs: Any
    ) -> AsyncGenerator[dict[str, Any], None]:
        """
        带上下文管理的流式对话接口。

        做什么：在发起流式对话前执行消息级上下文裁剪，并在发生实际裁剪时记录压缩审计与 Span。
        为什么这样做：消息级裁剪是最终 Prompt 保护链路的一部分，必须纳入统一压缩审计口径。
        输入输出：输入系统提示词、历史消息、当前消息和链路标识，输出流式 chunk 生成器。
        边界条件：裁剪测量失败时降级为原始消息，不阻断主对话链路。
        异常行为：审计写入失败由 telemetry helper 降级处理，流式主链路继续执行。
        """
        session_id_from_kwargs = str(kwargs.pop("session_id", session_id)) if session_id or kwargs.get("session_id") else session_id
        message_id_from_kwargs = str(kwargs.pop("message_id", message_id)) if message_id or kwargs.get("message_id") else message_id

        def _serialize_messages(messages: list[dict[str, str]]) -> str:
            parts: list[str] = []
            for msg in messages:
                role = msg.get("role", "")
                content = msg.get("content", "")
                parts.append(f"[{role}]\n{content}")
            return "\n\n".join(parts)

        # 1. 尝试进行 Token 截断 (复用现有逻辑获取截断后的列表)
        try:
            from app.config.settings import global_config_container, settings
            from app.types.constants import ModelSize
            config = global_config_container.get_model_config(ModelSize.MEDIUM)
            # 优先使用动态配置中的 max_context_tokens，若为 0 或负数则回退到 settings 的静态默认值
            # 为什么这样做：前端 API 配置预设默认值为 0，导致 max_input_tokens 计算为负数，
            # 每次请求都触发消息级裁剪且永远失败（参考压缩审计日志 COMPRESSION_FAILED）
            dynamic_max = config.get("max_context_tokens", 0)
            max_context_tokens = dynamic_max if dynamic_max > 0 else settings.max_context_tokens

            trim_started_at = current_timestamp_ms()
            trim_metrics = measure_truncate_context(
                system_prompt=system_prompt,
                history=history,
                current_message=current_message,
                max_context_tokens=max_context_tokens,
                model_name=self.model_name,
            )
            truncated_messages = format_messages_for_api(
                system_prompt=system_prompt,
                history=history,
                current_message=current_message,
                max_context_tokens=max_context_tokens,
                model_name=self.model_name,
            )
            if trim_metrics.removed_history_count > 0 or trim_metrics.is_over_limit_after_trim:
                before_text = _serialize_messages(history)
                after_text = _serialize_messages(truncated_messages[1:-1])
                failure_reason = "消息级裁剪后仍超出上下文限制" if trim_metrics.is_over_limit_after_trim else ""
                events = [
                    CompressionActionEvent(
                        event_type=COMPRESSION_EVENT_TRIGGERED,
                        timestamp_ms=trim_started_at,
                        detail="最终 Prompt 输入超过上限，触发消息级裁剪",
                        payload={"removed_history_count": trim_metrics.removed_history_count},
                    ),
                    CompressionActionEvent(
                        event_type=COMPRESSION_EVENT_INPUT_MEASURED,
                        timestamp_ms=current_timestamp_ms(),
                        detail="已测量消息级裁剪前后 Token",
                        payload={
                            "before_tokens": trim_metrics.before_tokens,
                            "after_tokens": trim_metrics.after_tokens,
                            "removed_history_count": trim_metrics.removed_history_count,
                        },
                    ),
                    CompressionActionEvent(
                        event_type=COMPRESSION_EVENT_COMPLETED if not trim_metrics.is_over_limit_after_trim else COMPRESSION_EVENT_FAILED,
                        timestamp_ms=current_timestamp_ms(),
                        detail="消息级裁剪完成" if not trim_metrics.is_over_limit_after_trim else "消息级裁剪后仍超出限制",
                        payload={"removed_history_count": trim_metrics.removed_history_count},
                    ),
                ]
                payload = create_compression_audit_payload(
                    trace_id=trace_id,
                    session_id=session_id_from_kwargs,
                    message_id=message_id_from_kwargs,
                    stage=CompressionStage.MESSAGE_TRIM,
                    scope=CompressionScope.SESSION_HISTORY,
                    trigger_reason=CompressionTriggerReason.FINAL_PROMPT_TOKEN_OVER_LIMIT,
                    source_keys=["history"],
                    before_text=before_text,
                    after_text=after_text,
                    raw_tokens=trim_metrics.before_tokens,
                    after_trim_tokens=trim_metrics.after_tokens,
                    final_tokens=trim_metrics.after_tokens,
                    is_success=not trim_metrics.is_over_limit_after_trim,
                    failure_reason=failure_reason,
                    events=events,
                    timestamp_ms=trim_started_at,
                )
                duration_ms = max(1, current_timestamp_ms() - trim_started_at)
                record_compression_audit_payload(
                    payload,
                    status=COMPRESSION_STATUS_SUCCESS if payload.is_success else COMPRESSION_STATUS_FAILED,
                )
                record_compression_span(
                    payload,
                    duration_ms=duration_ms,
                    status=COMPRESSION_STATUS_SUCCESS if payload.is_success else COMPRESSION_STATUS_FAILED,
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
        async for chunk_data in self.stream_chat(
            full_combined_prompt,
            trace_id,
            final_message,
            session_id=session_id_from_kwargs,
            message_id=message_id_from_kwargs,
            **kwargs
        ):
            yield chunk_data

    @retry(
        wait=wait_exponential(multiplier=1, min=1, max=30),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type((RateLimitError, APIConnectionError)),
        before_sleep=lambda retry_state: logger.warning(
            f"LLM 非流式 API 重试 {retry_state.attempt_number}/3 次，"
            f"等待 {retry_state.next_action.sleep:.1f}s 后重试，"
            f"异常类型: {type(retry_state.outcome.exception()).__name__}"
        ) if retry_state.outcome and retry_state.outcome.failed else None,
    )
    async def _call_api_sync_with_retry(
        self, messages: list[dict[str, str]], trace_id: str, **kwargs: Any
    ) -> Any:
        """
        非流式 Chat Completions API 调用（带 tenacity 重试）。

        做什么：对非流式 LLM API 调用提供与流式调用一致的重试策略。
        为什么这样做：非流式请求同样可能遭遇 RateLimitError 或网络瞬时故障，
                     必须复用统一的 3 次指数退避重试机制。
        输入输出：输入 messages 列表和 API 参数，输出 ChatCompletion 响应对象。
        边界条件：重试 3 次耗尽后 tenacity 会将最终异常上抛给调用方。
        异常行为：RateLimitError / APIConnectionError 由 tenacity 自动重试；
                 其他异常不做重试直接上抛。
        """
        # 清理不应透传给 OpenAI API 的内部参数
        kwargs.pop("trace_id", None)
        kwargs.pop("session_id", None)
        kwargs.pop("message_id", None)
        logger.info(
            f"[TraceID:{trace_id}] 发起非流式 API 请求, "
            f"model: {self.model_name}, 消息数: {len(messages)}"
        )
        return await self.client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            stream=False,
            timeout=120.0,
            **kwargs,
        )

    async def chat_sync(
        self,
        system_prompt: str,
        history: list[dict[str, str]],
        current_message: str,
        trace_id: str,
        disambiguated_text: str = "",
        session_id: str = "",
        message_id: str = "",
        **kwargs: Any
    ) -> str:
        """
        非流式对话接口——一次性获取 LLM 完整回复文本。

        做什么：组装消息上下文（含 Token 裁剪），通过非流式 API 调用获取完整回复文本。
                不做 JSON Schema 结构化约束，依赖 Prompt 内嵌的 JSON 格式指令。
        为什么这样做：统一非流式响应模式下，后端等待完整回复后执行同步 TTS 合成，
                     再将文本、音频、情绪等打包为单次 JSON 响应下发。
        输入输出：
            - 输入：system_prompt 系统提示词、history 上下文历史、
                    current_message 当前用户消息、trace_id 全链路追踪 ID、
                    session_id 会话 ID、message_id 消息 ID
            - 输出：LLM 完整回复文本（str，原始全文不做任何加工）
        边界条件：
            - 上下文裁剪失败时降级为原始消息，不阻断主对话链路
            - 裁剪后的 messages 直接作为 Chat Completions API 的 messages 参数
        异常行为：
            - RateLimitError / APIConnectionError：tenacity 自动重试 3 次，耗尽后上抛
            - APIError / 其他异常：记录日志后上抛，由调用方（MainChatLlmNode）捕获并处理降级
        """
        # 1. 消息级 Token 裁剪（复用 stream_chat_with_context 的裁剪逻辑）
        try:
            from app.config.settings import global_config_container, settings
            from app.types.constants import ModelSize
            from app.llm.context_manager import (
                measure_truncate_context, format_messages_for_api,
            )
            from app.context.compression_audit import (
                create_compression_audit_payload,
                record_compression_audit_payload,
                record_compression_span,
                current_timestamp_ms,
            )
            from app.context.compression_types import CompressionActionEvent
            from app.types.constants import (
                CompressionStage,
                CompressionTriggerReason,
                CompressionScope,
                COMPRESSION_EVENT_TRIGGERED,
                COMPRESSION_EVENT_INPUT_MEASURED,
                COMPRESSION_EVENT_COMPLETED,
                COMPRESSION_EVENT_FAILED,
                COMPRESSION_STATUS_SUCCESS,
                COMPRESSION_STATUS_FAILED,
            )

            config = global_config_container.get_model_config(ModelSize.MEDIUM)
            dynamic_max = config.get("max_context_tokens", 0)
            max_context_tokens = dynamic_max if dynamic_max > 0 else settings.max_context_tokens

            trim_started_at = current_timestamp_ms()
            trim_metrics = measure_truncate_context(
                system_prompt=system_prompt,
                history=history,
                current_message=current_message,
                max_context_tokens=max_context_tokens,
                model_name=self.model_name,
            )
            truncated_messages = format_messages_for_api(
                system_prompt=system_prompt,
                history=history,
                current_message=current_message,
                max_context_tokens=max_context_tokens,
                model_name=self.model_name,
            )

            # 记录压缩审计（仅在发生实际裁剪时）
            if trim_metrics.removed_history_count > 0 or trim_metrics.is_over_limit_after_trim:
                def _serialize_messages(messages: list[dict[str, str]]) -> str:
                    parts: list[str] = []
                    for msg in messages:
                        role = msg.get("role", "")
                        content = msg.get("content", "")
                        parts.append(f"[{role}]\n{content}")
                    return "\n\n".join(parts)

                before_text = _serialize_messages(history)
                after_text = _serialize_messages(truncated_messages[1:-1])
                failure_reason = "消息级裁剪后仍超出上下文限制" if trim_metrics.is_over_limit_after_trim else ""
                events = [
                    CompressionActionEvent(
                        event_type=COMPRESSION_EVENT_TRIGGERED,
                        timestamp_ms=trim_started_at,
                        detail="最终 Prompt 输入超过上限，触发消息级裁剪（非流式路径）",
                        payload={"removed_history_count": trim_metrics.removed_history_count},
                    ),
                    CompressionActionEvent(
                        event_type=COMPRESSION_EVENT_INPUT_MEASURED,
                        timestamp_ms=current_timestamp_ms(),
                        detail="已测量消息级裁剪前后 Token",
                        payload={
                            "before_tokens": trim_metrics.before_tokens,
                            "after_tokens": trim_metrics.after_tokens,
                            "removed_history_count": trim_metrics.removed_history_count,
                        },
                    ),
                    CompressionActionEvent(
                        event_type=COMPRESSION_EVENT_COMPLETED if not trim_metrics.is_over_limit_after_trim else COMPRESSION_EVENT_FAILED,
                        timestamp_ms=current_timestamp_ms(),
                        detail="消息级裁剪完成（非流式路径）" if not trim_metrics.is_over_limit_after_trim else "消息级裁剪后仍超出限制（非流式路径）",
                        payload={"removed_history_count": trim_metrics.removed_history_count},
                    ),
                ]
                payload = create_compression_audit_payload(
                    trace_id=trace_id,
                    session_id=session_id,
                    message_id=message_id,
                    stage=CompressionStage.MESSAGE_TRIM,
                    scope=CompressionScope.SESSION_HISTORY,
                    trigger_reason=CompressionTriggerReason.FINAL_PROMPT_TOKEN_OVER_LIMIT,
                    source_keys=["history"],
                    before_text=before_text,
                    after_text=after_text,
                    raw_tokens=trim_metrics.before_tokens,
                    after_trim_tokens=trim_metrics.after_tokens,
                    final_tokens=trim_metrics.after_tokens,
                    is_success=not trim_metrics.is_over_limit_after_trim,
                    failure_reason=failure_reason,
                    events=events,
                    timestamp_ms=trim_started_at,
                )
                duration_ms = max(1, current_timestamp_ms() - trim_started_at)
                record_compression_audit_payload(
                    payload,
                    status=COMPRESSION_STATUS_SUCCESS if payload.is_success else COMPRESSION_STATUS_FAILED,
                )
                record_compression_span(
                    payload,
                    duration_ms=duration_ms,
                    status=COMPRESSION_STATUS_SUCCESS if payload.is_success else COMPRESSION_STATUS_FAILED,
                )
        except Exception as e:
            logger.error(f"[TraceID:{trace_id}] 非流式对话上下文裁剪失败，使用原始消息: {e}")
            truncated_messages = [
                {"role": Role.SYSTEM.value, "content": system_prompt},
                *history,
                {"role": Role.USER.value, "content": current_message},
            ]

        # 2. 应用消歧文本替换最后一条用户消息
        final_message = disambiguated_text if disambiguated_text else current_message
        for i in range(len(truncated_messages) - 1, -1, -1):
            if truncated_messages[i].get("role") == Role.USER.value:
                truncated_messages[i] = {"role": Role.USER.value, "content": final_message}
                break

        # 3. 频率控制
        await self._wait_for_slot(
            trace_id=trace_id,
            session_id=session_id,
            message_id=message_id,
        )

        # 4. 非流式 API 调用（带 tenacity 重试）
        logger.info(
            f"[TraceID:{trace_id}] 开始非流式 LLM 调用, "
            f"model: {self.model_name}, 消息数: {len(truncated_messages)}"
        )
        try:
            response = await self._call_api_sync_with_retry(
                messages=truncated_messages,
                trace_id=trace_id,
                session_id=session_id,
                message_id=message_id,
                **kwargs,
            )
            content = response.choices[0].message.content or ""
            logger.info(
                f"[TraceID:{trace_id}] 非流式 LLM 调用完成, "
                f"回复长度: {len(content)} 字符"
            )
            return content
        except (RateLimitError, APIConnectionError) as e:
            logger.error(
                f"[TraceID:{trace_id}] 非流式 LLM API 重试耗尽后仍失败: "
                f"{type(e).__name__}: {e}"
            )
            raise
        except APIError as e:
            logger.error(
                f"[TraceID:{trace_id}] 非流式 LLM API 返回错误: "
                f"status_code={e.status_code}, message={e.message}"
            )
            raise
        except Exception as e:
            logger.error(
                f"[TraceID:{trace_id}] 非流式 LLM API 发生未知错误: "
                f"{type(e).__name__}: {e}"
            )
            raise


# 全局单例
llm_client = LLMClient()
compression_llm_client = CompressionLLMClient()
