import asyncio
from typing import AsyncGenerator, Dict, Any, Optional
from openai import AsyncOpenAI, APIError, RateLimitError, APIConnectionError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.config import settings
from app.logger import get_logger

logger = get_logger(__name__)

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
                    
                    yield {
                        "chunk": content,
                        "is_finished": is_finished,
                        "finish_reason": finish_reason,
                        "error": None
                    }
                    
            logger.info(f"[TraceID:{trace_id}] LLM API 调用完成")
            
        except APIError as e:
            logger.error(f"[TraceID:{trace_id}] LLM API 调用失败: {str(e)}")
            yield {
                "chunk": "",
                "is_finished": True,
                "finish_reason": "error",
                "error": f"API Error: {str(e)}"
            }
        except Exception as e:
            logger.error(f"[TraceID:{trace_id}] LLM API 发生未知错误: {str(e)}")
            yield {
                "chunk": "",
                "is_finished": True,
                "finish_reason": "error",
                "error": f"Unknown Error: {str(e)}"
            }

# 全局单例
llm_client = LLMClient()
