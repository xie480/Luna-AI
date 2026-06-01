"""
Luna AI gRPC 通信服务实现

做什么：实现 gRPC 通信服务，处理 Ping 健康检查和 ChatStream 流式对话请求。
         流式对话支持多轮历史记录、TTFT 监控和全面的异常容错。
为什么这样做：作为 Go Runtime 与 Python AI Service 之间的通信桥梁，确保消息的可靠透传。
输入输出：
    - Ping(): 健康检查，返回 Pong 响应
    - ChatStream(): 流式对话，返回 AsyncGenerator[ChatStreamResponse]
    - CompressHistory(): 历史记录压缩，返回 CompressHistoryResponse
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
from app.logger import logger
from app.llm.client import llm_client, compression_llm_client
from app.llm.stream_parser import StreamParser
from app.constants import Role


class CommunicationServiceServicer(
    communication_pb2_grpc.CommunicationServiceServicer
):
    """
    实现 gRPC 通信服务

    做什么：处理来自 Go Runtime 的 gRPC 请求，提供 Ping、ChatStream、CompressHistory 等服务。
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
                if context.cancelled():
                    logger.warning(
                        f"[TraceID:{trace_id}] 客户端已断开连接，终止流式输出"
                    )
                    break

                # 计算 TTFT：首次收到非空 chunk 时记录延迟
                if is_first_chunk and chunk_data.get("chunk"):
                    ttft = (time.monotonic() - start_time) * 1000
                    logger.info(
                        f"[TraceID:{trace_id}] 首字延迟 (TTFT): {ttft:.0f}ms"
                    )
                    is_first_chunk = False

                raw_chunk = chunk_data.get("chunk", "")
                logger.debug(f"[TraceID:{trace_id}] 原始输出: {raw_chunk}")

                # 使用 StreamParser 解析原始 LLM 输出块
                msgs = parser.feed(chunk_data.get("chunk", ""))
                for msg_type, content in msgs:
                    response = communication_pb2.ChatStreamResponse(
                        trace_id=trace_id,
                        chunk=content,
                        is_finished=False,
                        finish_reason="",
                        error="",
                    )
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

        full_prompt = request.summarize_prompt
        messages = [{"role": Role.USER.value, "content": full_prompt}]

        max_retries = 3
        for attempt in range(max_retries):
            try:
                result_text = await compression_llm_client.summarize(
                    messages=messages,
                    response_format={"type": "json_object"}
                )

                try:
                    cleaned_text = result_text.strip()
                    import re
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
                    return communication_pb2.SummarizeContextResponse(
                        trace_id=trace_id,
                        new_core_summary="",
                        new_key_facts="",
                    )

    async def CompressHistory(
        self,
        request: communication_pb2.CompressHistoryRequest,
        context: grpc.ServicerContext,
    ) -> communication_pb2.CompressHistoryResponse:
        """
        处理历史记录压缩请求

        做什么：接收 CompressHistoryRequest，对历史会话进行深度压缩与摘要提取。
        为什么这样做：将完整的历史会话（含摘要和历史对话）压缩为结构化摘要，用于长期记忆持久化。
        输入输出：
            - 输入：CompressHistoryRequest {session_id, session_context}
            - 输出：CompressHistoryResponse {summary}
        边界条件：
            - session_context 为空时返回空摘要
            - LLM 返回空内容时返回空摘要
        异常行为：
            - LLM 调用异常时返回空摘要，不抛出异常（保障 Go 端稳定性）
            - 重试策略：最多 3 次，指数退避
        """
        trace_id = request.session_id
        logger.info(f"[SessionID:{trace_id}] 收到 CompressHistory 请求")

        session_context = request.session_context.strip()
        if not session_context:
            logger.warning(f"[SessionID:{trace_id}] 会话上下文为空，跳过压缩")
            return communication_pb2.CompressHistoryResponse(summary="")

        # 构造压缩提示词：要求 LLM 对历史对话进行深度压缩
        prompt = (
            "你是一个高效的对话摘要引擎。请对以下历史会话进行深度压缩与摘要提取。\n\n"
            "要求：\n"
            "1. 提取用户的核心关注点、偏好和关键决策\n"
            "2. 记录 Luna 提供的重要信息和建议\n"
            "3. 以简洁的段落形式组织，保留关键细节\n"
            "4. 摘要长度控制在 500 字以内\n"
            "5. 用第三人称叙述\n\n"
            f"需要压缩的历史会话：\n{session_context}\n\n"
            "请直接输出压缩后的摘要文本，不要包含任何前缀或后缀说明。"
        )

        messages = [{"role": Role.USER.value, "content": prompt}]

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
                        f"[SessionID:{trace_id}] 第 {attempt + 1} 次尝试：LLM 返回空摘要，准备重试"
                    )
                    if attempt < max_retries - 1:
                        continue
                    else:
                        logger.warning(f"[SessionID:{trace_id}] 达到最大重试次数，返回空摘要")
                        summary = ""

                logger.info(
                    f"[SessionID:{trace_id}] 历史压缩完成",
                )
                return communication_pb2.CompressHistoryResponse(summary=summary)

            except Exception as e:
                logger.error(
                    f"[SessionID:{trace_id}] 第 {attempt + 1} 次尝试：CompressHistory 处理异常: {e}"
                )
                if attempt < max_retries - 1:
                    continue
                else:
                    return communication_pb2.CompressHistoryResponse(summary="")

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
