"""
Luna AI 内部服务模块

做什么：提供原本通过 gRPC 暴露的内部服务调用，如 ShortSummarize, LongSummarize 等。
为什么这样做：移除 gRPC 后，这些功能直接作为普通的 Python 异步函数调用。
"""

import json
import re
from typing import Any, Dict, Tuple

from app.llm.client import compression_llm_client
from app.logger import logger
from app.types.constants import Role


class InternalService:
    """提供内部服务调用"""

    async def short_summarize(self, trace_id: str, summarize_prompt: str) -> Tuple[str, str]:
        """
        处理后台短期摘要压缩请求
        返回: (new_core_summary, new_key_facts)
        """
        logger.info(f"[TraceID:{trace_id}] 收到 ShortSummarize 请求")

        messages = [{"role": Role.USER.value, "content": summarize_prompt}]

        max_retries = 3
        for attempt in range(max_retries):
            try:
                result_text = await compression_llm_client.summarize(
                    messages=messages,
                    response_format={"type": "json_object"}
                )

                try:
                    cleaned_text = result_text.strip()
                    json_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", cleaned_text, re.DOTALL)
                    if json_match:
                        json_str = json_match.group(1)
                    else:
                        json_str = cleaned_text

                    if not (json_str.startswith('{') and json_str.endswith('}')):
                        start_idx = json_str.find('{')
                        end_idx = json_str.rfind('}')
                        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                            json_str = json_str[start_idx:end_idx+1]

                    result_json = json.loads(json_str)
                    new_core_summary = str(result_json.get("core_summary", "")).strip()

                    raw_key_facts = result_json.get("key_facts", "")
                    if isinstance(raw_key_facts, list):
                        new_key_facts = "\n".join([str(item).strip() for item in raw_key_facts if str(item).strip()])
                    else:
                        new_key_facts = str(raw_key_facts).strip()

                    if not new_core_summary or not new_key_facts:
                        logger.warning(
                            f"[TraceID:{trace_id}] 第 {attempt + 1} 次尝试：LLM 返回的 core_summary 或 key_facts 为空，准备重试"
                        )
                        if attempt < max_retries - 1:
                            continue
                        else:
                            logger.warning(f"[TraceID:{trace_id}] 达到最大重试次数，回退到空值")
                            return "", ""

                    logger.info(f"[TraceID:{trace_id}] 摘要压缩完成")
                    return new_core_summary, new_key_facts

                except json.JSONDecodeError:
                    logger.error(
                        f"[TraceID:{trace_id}] 第 {attempt + 1} 次尝试：压缩模型返回的不是有效的 JSON: "
                        f"{result_text[:200]}"
                    )
                    if attempt < max_retries - 1:
                        continue
                    else:
                        return "", ""

            except Exception as e:
                logger.error(f"[TraceID:{trace_id}] 第 {attempt + 1} 次尝试：ShortSummarize 处理异常: {e}")
                if attempt < max_retries - 1:
                    continue
                else:
                    return "", ""
                    
        return "", ""

    async def long_summarize(self, session_id: str, summarize_prompt: str) -> str:
        """
        处理长期历史记录压缩请求
        返回: summary
        """
        logger.info(f"[SessionID:{session_id}] 收到 LongSummarize 请求")

        summarize_prompt = summarize_prompt.strip()
        if not summarize_prompt:
            logger.warning(f"[SessionID:{session_id}] 长期记忆压缩提示词为空，跳过压缩")
            return ""

        messages = [{"role": Role.USER.value, "content": summarize_prompt}]

        max_retries = 3
        for attempt in range(max_retries):
            try:
                # 调用压缩模型
                result_text = await compression_llm_client.summarize(
                    messages=messages,
                    response_format={"type": "text"}
                )

                summary = result_text.strip()
                if not summary:
                    logger.warning(
                        f"[SessionID:{session_id}] 第 {attempt + 1} 次尝试：LLM 返回空摘要，准备重试"
                    )
                    if attempt < max_retries - 1:
                        continue
                    else:
                        logger.warning(f"[SessionID:{session_id}] 达到最大重试次数，返回空摘要")
                        summary = ""

                logger.info(f"[SessionID:{session_id}] 历史压缩完成")
                return summary

            except Exception as e:
                logger.error(
                    f"[SessionID:{session_id}] 第 {attempt + 1} 次尝试：LongSummarize 处理异常: {e}"
                )
                if attempt < max_retries - 1:
                    continue
                else:
                    return ""
                    
        return ""

internal_service = InternalService()
