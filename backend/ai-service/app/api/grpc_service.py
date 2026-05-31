"""
Luna AI gRPC 通信服务实现

做什么：实现 gRPC 通信服务，处理 Ping 健康检查和 ChatStream 流式对话请求。
         流式对话支持多轮历史记录、TTFT 监控和全面的异常容错。
为什么这样做：作为 Go Runtime 与 Python AI Service 之间的通信桥梁，确保消息的可靠透传。
输入输出：
    - Ping(): 健康检查，返回 Pong 响应
    - ChatStream(): 流式对话，返回 AsyncGenerator[ChatStreamResponse]
边界条件：
    - ChatRequest.history 为空时表示首次对话
    - 客户端断开连接时立即停止流式输出
异常行为：
    - context.cancelled() 返回 True 时终止流
    - LLM 调用异常时返回结构化错误响应
"""

import time
from typing import AsyncGenerator

import grpc
import json
from app.api import communication_pb2
from app.api import communication_pb2_grpc
from app.logger import get_logger
from app.llm.client import llm_client, compression_llm_client
from app.llm.stream_parser import StreamParser
from app.constants import Role

logger = get_logger(__name__)


class CommunicationServiceServicer(
    communication_pb2_grpc.CommunicationServiceServicer
):
    """
    实现 gRPC 通信服务

    做什么：处理来自 Go Runtime 的 gRPC 请求，提供 Ping 和 ChatStream 服务。
    """

    def Ping(
        self,
        request: communication_pb2.PingRequest,
        context: grpc.ServicerContext,
    ) -> communication_pb2.PongResponse:
        """
        处理 Ping 请求并返回 Pong 响应

        做什么：接收 Ping 请求，记录日志后返回 Pong 响应。
        为什么这样做：用于 Go Runtime 和 Python AI Service 之间的健康检查。
        输入输出：
            - 输入：PingRequest {trace_id, timestamp}
            - 输出：PongResponse {trace_id, timestamp, source}
        边界条件：无。
        异常行为：无（纯同步操作，无需复杂错误处理）。
        """
        logger.info(
            f"[TraceID:{request.trace_id}] 收到 Ping 请求, "
            f"timestamp: {request.timestamp}"
        )

        response = communication_pb2.PongResponse(
            trace_id=request.trace_id,
            timestamp=int(time.time() * 1000),
            source="python-ai-service",
        )

        logger.info(
            f"[TraceID:{request.trace_id}] 返回 Pong 响应, "
            f"timestamp: {response.timestamp}, source: {response.source}"
        )
        return response

    async def ChatStream(
        self,
        request: communication_pb2.ChatRequest,
        context: grpc.ServicerContext,
    ) -> AsyncGenerator[communication_pb2.ChatStreamResponse, None]:
        """
        处理流式对话请求（支持多轮历史记录和系统提示词）

        做什么：接收 ChatRequest，提取 history 和 system_prompt，调用 LLM 客户端
               进行流式对话，将每个文本块封装为 ChatStreamResponse 返回。
        为什么这样做：作为对话入口，负责解析请求参数、监控 TTFT、处理客户端断开。
        输入输出：
            - 输入：ChatRequest {trace_id, message, history[], system_prompt}
            - 输出：AsyncGenerator[ChatStreamResponse, None]
        边界条件：
            - request.history 为空时表示无历史记录
            - 客户端断开时（context.cancelled() == True）终止流
        异常行为：
            - 解析 history 失败时使用空历史（兜底策略）
            - LLM 调用异常时返回错误响应
        """
        trace_id = request.trace_id
        message = request.message
        # 直接从 Go 端获取渲染好的完整 system_prompt
        system_prompt = request.system_prompt

        # 解析历史记录
        # proto 的 repeated ChatMessage 字段需要逐条解析
        history = []
        try:
            for hist_msg in request.history:
                history.append({
                    "role": hist_msg.role,
                    "content": hist_msg.content,
                })
        except Exception as e:
            # 解析失败时使用空历史（兜底策略）
            logger.warning(
                f"[TraceID:{trace_id}] 解析历史记录失败，使用空历史: {e}"
            )
            history = []

        history_count = len(history)
        logger.info(
            f"[TraceID:{trace_id}] 收到 ChatStream 请求, "
            f"message: {message[:100]}, "
            f"history_count: {history_count}, "
            f"system_prompt_length: {len(system_prompt)}"
        )

        # 记录 TTFT（首字延迟）起始时间
        start_time = time.monotonic()
        is_first_chunk = True

        # 初始化流式解析器，用于提取 emotion 和切分 reply 句子
        parser = StreamParser(trace_id)

        try:
            # 使用带上下文管理的流式接口
            async for chunk_data in llm_client.stream_chat_with_context(
                system_prompt=system_prompt,
                history=history,
                current_message=message,
                trace_id=trace_id,
            ):
                # 检查客户端是否已断开连接
                # 注意：grpc.aio.ServicerContext 使用 cancelled() 而非 is_active()
                if context.cancelled():
                    logger.warning(
                        f"[TraceID:{trace_id}] 客户端已断开连接，终止流式输出"
                    )
                    break

                # 计算 TTFT：首次收到非空 chunk 时记录延迟
                if is_first_chunk and chunk_data.get("chunk"):
                    ttft = (time.monotonic() - start_time) * 1000  # 转换为毫秒
                    logger.info(
                        f"[TraceID:{trace_id}] 首字延迟 (TTFT): {ttft:.0f}ms"
                    )
                    is_first_chunk = False

                raw_chunk = chunk_data.get("chunk", "")
                logger.debug(f"[TraceID:{trace_id}] 原始输出: {raw_chunk}")

                # 使用 StreamParser 解析原始 LLM 输出块，提取 emotion 和切分 reply
                msgs = parser.feed(chunk_data.get("chunk", ""))
                for msg_type, content in msgs:
                    # 构造 gRPC 响应，通过 type 字段区分消息类型
                    response = communication_pb2.ChatStreamResponse(
                        trace_id=trace_id,
                        chunk=content,
                        is_finished=False,
                        finish_reason="",
                        error="",
                    )
                    # 设置消息类型："emotion_update" 或 "reply_chunk"
                    response.type = msg_type
                    yield response
                    logger.info(
                        f"[TraceID:{trace_id}] 发送 ChatStreamResponse, "
                        f"type={msg_type}, chunk={content[:100]}"
                    )

                # 如果流结束，发送剩余缓冲并标记结束
                if chunk_data.get("is_finished", False):
                    flush_msgs = parser.flush()
                    if not flush_msgs:
                        # 没有剩余内容，直接发送空结束消息
                        response = communication_pb2.ChatStreamResponse(
                            trace_id=trace_id,
                            chunk="",
                            is_finished=True,
                            finish_reason=chunk_data.get("finish_reason") or "",
                            error=chunk_data.get("error") or "",
                        )
                        response.type = "reply_chunk"
                        yield response
                        logger.info(
                            f"[TraceID:{trace_id}] 发送结束 ChatStreamResponse"
                        )
                    else:
                        for f_type, f_content in flush_msgs:
                            response = communication_pb2.ChatStreamResponse(
                                trace_id=trace_id,
                                chunk=f_content,
                                is_finished=True,
                                finish_reason=chunk_data.get("finish_reason") or "",
                                error=chunk_data.get("error") or "",
                            )
                            response.type = f_type
                            yield response
                            logger.info(
                                f"[TraceID:{trace_id}] 发送结束 ChatStreamResponse, "
                                f"type={f_type}, chunk={f_content[:100]}"
                            )
                    break

        except Exception as e:
            # 确保所有异常都被捕获，不会导致 gRPC 流意外中断
            logger.error(
                f"[TraceID:{trace_id}] ChatStream 处理异常: "
                f"{type(e).__name__}: {e}"
            )
            try:
                response = communication_pb2.ChatStreamResponse(
                    trace_id=trace_id,
                    chunk="",
                    is_finished=True,
                    finish_reason="error",
                    error=f"AI 服务处理异常: {type(e).__name__}",
                )
                response.type = "reply_chunk"
                yield response
            except Exception:
                # 如果连发送错误响应都失败，忽略（流已关闭）
                logger.error(
                    f"[TraceID:{trace_id}] 发送错误响应失败，流可能已关闭"
                )

    async def SummarizeContext(
        self,
        request: communication_pb2.SummarizeContextRequest,
        context: grpc.ServicerContext,
    ) -> communication_pb2.SummarizeContextResponse:
        """
        处理后台摘要压缩请求

        做什么：接收 SummarizeContextRequest，直接使用 Go 端渲染好的完整 summarize_prompt，
                调用 LLM 生成摘要，解析 JSON 并校验非空后返回。
        为什么这样做：Go 端负责模板渲染，Python 端仅负责调用 LLM 并解析结果。
        输入输出：
            - 输入：SummarizeContextRequest {trace_id, summarize_prompt}
            - 输出：SummarizeContextResponse {trace_id, new_core_summary, new_key_facts}
        边界条件：
            - LLM 返回空字段时回退到当前值
            - JSON 解析失败时回退到当前值
        异常行为：
            - 任何异常都返回空摘要，确保系统稳定性
        """
        trace_id = request.trace_id
        logger.info(f"[TraceID:{trace_id}] 收到 SummarizeContext 请求")

        # 直接使用 Go 端渲染好的完整 summarize_prompt
        full_prompt = request.summarize_prompt

        messages = [{"role": Role.USER.value, "content": full_prompt}]

        max_retries = 3
        for attempt in range(max_retries):
            try:
                # 调用压缩模型，强制 JSON 输出格式
                result_text = await compression_llm_client.summarize(
                    messages=messages,
                    response_format={"type": "json_object"}
                )

                # 解析 JSON 并进行严格校验，处理 markdown 代码块包装以及数组形式的 key_facts
                try:
                    # 1. 移除可能的 markdown 代码块包装，例如 ```json {...}```
                    cleaned_text = result_text.strip()
                    # 使用正则提取最内层的 JSON 对象
                    import re
                    json_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", cleaned_text, re.DOTALL)
                    if json_match:
                        json_str = json_match.group(1)
                    else:
                        json_str = cleaned_text

                    # 2. 如果仍然包含多余的前缀/后缀，尝试定位首个 '{' 和最后一个 '}'
                    if not (json_str.startswith('{') and json_str.endswith('}')):
                        start_idx = json_str.find('{')
                        end_idx = json_str.rfind('}')
                        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                            json_str = json_str[start_idx:end_idx+1]
                    # 解析 JSON
                    result_json = json.loads(json_str)

                    # 提取 core_summary 并去除首尾空白
                    new_core_summary = str(result_json.get("core_summary", "")).strip()

                    # 提取 key_facts：可能是字符串或列表，统一转为字符串，每条以换行分隔
                    raw_key_facts = result_json.get("key_facts", "")
                    if isinstance(raw_key_facts, list):
                        new_key_facts = "\n".join([str(item).strip() for item in raw_key_facts if str(item).strip()])
                    else:
                        new_key_facts = str(raw_key_facts).strip()

                    # 校验非空：如果 LLM 返回 core_summary 或 key_facts 为空，则触发重试
                    if not new_core_summary or not new_key_facts:
                        logger.warning(
                            f"[TraceID:{trace_id}] 第 {attempt + 1} 次尝试：LLM 返回的 core_summary 或 key_facts 为空，准备重试"
                        )
                        if attempt < max_retries - 1:
                            continue
                        else:
                            logger.warning(f"[TraceID:{trace_id}] 达到最大重试次数，回退到空值")
                            new_core_summary = ""
                            new_key_facts = ""

                    logger.info(f"[TraceID:{trace_id}] 摘要压缩完成")
                    return communication_pb2.SummarizeContextResponse(
                        trace_id=trace_id,
                        new_core_summary=new_core_summary,
                        new_key_facts=new_key_facts,
                    )

                except json.JSONDecodeError:
                    logger.error(
                        f"[TraceID:{trace_id}] 第 {attempt + 1} 次尝试：压缩模型返回的不是有效的 JSON: "
                        f"{result_text[:200]}"
                    )
                    if attempt < max_retries - 1:
                        continue
                    else:
                        # JSON 解析失败时回退到空值
                        return communication_pb2.SummarizeContextResponse(
                            trace_id=trace_id,
                            new_core_summary="",
                            new_key_facts="",
                        )

            except Exception as e:
                logger.error(f"[TraceID:{trace_id}] 第 {attempt + 1} 次尝试：SummarizeContext 处理异常: {e}")
                if attempt < max_retries - 1:
                    continue
                else:
                    # 发生异常时返回空摘要，确保系统稳定性
                    return communication_pb2.SummarizeContextResponse(
                        trace_id=trace_id,
                        new_core_summary="",
                        new_key_facts="",
                    )


    async def SyncPresetConfig(
        self,
        request: communication_pb2.SyncPresetConfigRequest,
        context: grpc.ServicerContext,
    ) -> communication_pb2.SyncPresetConfigResponse:
        """
        处理 API 配置预设同步请求
        """
        logger.info(f"收到 SyncPresetConfig 请求, preset_id: {request.preset_id}, schema_version: {request.schema_version}")
        
        try:
            from app.config import global_config_container
            
            def proto_to_dict(model_config):
                return {
                    "base_url": model_config.base_url,
                    "api_key": model_config.api_key,
                    "model_id": model_config.model_id,
                    "max_tokens": model_config.max_tokens,
                    "temperature": model_config.temperature,
                }

            large_model = proto_to_dict(request.large_model)
            medium_model = proto_to_dict(request.medium_model)
            small_model = proto_to_dict(request.small_model)
            
            # 更新全局配置容器
            await global_config_container.update_preset_config(large_model, medium_model, small_model)
            
            return communication_pb2.SyncPresetConfigResponse(
                success=True,
                error_message=""
            )
        except Exception as e:
            logger.error(f"SyncPresetConfig 处理异常: {e}")
            return communication_pb2.SyncPresetConfigResponse(
                success=False,
                error_message=str(e)
            )
