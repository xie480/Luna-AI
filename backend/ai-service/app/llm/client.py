import asyncio
from typing import AsyncGenerator, Dict, Any, Optional
from openai import AsyncOpenAI, APIError, RateLimitError, APIConnectionError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from pydantic import BaseModel, ValidationError

from app.config import settings
from app.logger import get_logger

logger = get_logger(__name__)


class StreamChunkModel(BaseModel):
    """
    流式输出数据结构校验模型
    
    做什么：使用 Pydantic 对流式输出的每个 Chunk 进行结构化校验。
    为什么这样做：确保输出数据结构的一致性和正确性，为后续复杂 Agent 铺垫，
                 同时满足 agent.md 中"强制要求 Python 侧通过 Pydantic 校验 JSON 结构化输出"的规范。
    输入输出：
        - chunk: 文本块内容
        - is_finished: 是否结束标志
        - finish_reason: 结束原因（如 stop, length, error 等）
        - error: 错误信息（可选）
    边界条件：finish_reason 和 error 可为 None。
    异常行为：如果数据不符合模型定义，Pydantic 会抛出 ValidationError。
    """
    chunk: str
    is_finished: bool
    finish_reason: Optional[str] = None
    error: Optional[str] = None

class LLMClient:
    """
    LLM 客户端封装，提供统一的流式对话接口和重试机制
    """
    def __init__(self) -> None:
        self.client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_api_base,
        )
        self.model_name = settings.model_name

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((RateLimitError, APIConnectionError)),
        reraise=True
    )
    async def _call_api_with_retry(self, messages: list[Dict[str, str]], **kwargs: Any) -> Any:
        """
        调用 OpenAI API，带有重试机制
        仅在遇到限流或连接错误时重试
        """
        return await self.client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            stream=True,
            **kwargs
        )

    async def stream_chat(
        self,
        messages: list[Dict[str, str]],
        trace_id: str,
        **kwargs: Any
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        流式对话接口
        
        做什么：调用 LLM API 并流式返回响应，使用 Pydantic 模型校验输出结构。
        为什么这样做：确保输出数据结构的一致性和正确性，满足 agent.md 规范要求。
        输入输出：
            - 输入：messages 消息列表、trace_id 追踪 ID、kwargs 其他 API 参数
            - 输出：AsyncGenerator，yield Dict 包含 chunk, is_finished, finish_reason, error 等信息
        边界条件：finish_reason 可为 None，error 可为 None。
        异常行为：
            - ValidationError：Pydantic 校验失败时记录错误日志并返回错误响应
            - APIError：LLM API 调用失败时返回错误响应
            - Exception：其他未知错误时返回错误响应
        
        Args:
            messages: 消息列表，格式为 [{"role": "user", "content": "hello"}]
            trace_id: 追踪 ID，用于日志
            **kwargs: 传递给 OpenAI API 的其他参数
            
        Yields:
            Dict 包含 chunk, is_finished, finish_reason, error 等信息
        """
        logger.info(f"[TraceID:{trace_id}] 开始调用 LLM API, model: {self.model_name}")
        
        try:
            response = await self._call_api_with_retry(messages, **kwargs)
            
            async for chunk in response:
                if chunk.choices and len(chunk.choices) > 0:
                    delta = chunk.choices[0].delta
                    finish_reason = chunk.choices[0].finish_reason
                    
                    content = delta.content if delta.content else ""
                    is_finished = finish_reason is not None
                    
                    # 使用 Pydantic 模型进行结构化校验
                    try:
                        chunk_model = StreamChunkModel(
                            chunk=content,
                            is_finished=is_finished,
                            finish_reason=finish_reason,
                            error=None
                        )
                        # 返回校验后的数据，使用 model_dump() 转换为 Dict
                        yield chunk_model.model_dump()
                    except ValidationError as ve:
                        logger.error(f"[TraceID:{trace_id}] Pydantic 校验失败: {str(ve)}")
                        # 校验失败时返回错误响应
                        error_model = StreamChunkModel(
                            chunk="",
                            is_finished=True,
                            finish_reason="error",
                            error=f"Validation Error: {str(ve)}"
                        )
                        yield error_model.model_dump()
                    
            logger.info(f"[TraceID:{trace_id}] LLM API 调用完成")
            
        except APIError as e:
            logger.error(f"[TraceID:{trace_id}] LLM API 调用失败: {str(e)}")
            # 使用 Pydantic 模型校验错误响应
            error_model = StreamChunkModel(
                chunk="",
                is_finished=True,
                finish_reason="error",
                error=f"API Error: {str(e)}"
            )
            yield error_model.model_dump()
        except Exception as e:
            logger.error(f"[TraceID:{trace_id}] LLM API 发生未知错误: {str(e)}")
            # 使用 Pydantic 模型校验错误响应
            error_model = StreamChunkModel(
                chunk="",
                is_finished=True,
                finish_reason="error",
                error=f"Unknown Error: {str(e)}"
            )
            yield error_model.model_dump()

# 全局单例
llm_client = LLMClient()
