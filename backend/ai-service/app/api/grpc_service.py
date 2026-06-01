"""
Luna AI gRPC 通信服务实现

做什么：实现 gRPC 通信服务，处理 Ping、ChatStream、ShortSummarize、LongSummarize、
      Embedding 和 Rerank 请求。
        其中 Embedding 使用 SentenceTransformer 进行文本向量化，
        Rerank 使用 CrossEncoder 进行文档相关性重排打分。
为什么这样做：作为 Go Runtime 与 Python AI Service 之间的通信桥梁，确保消息的可靠透传。
输入输出：
    - Ping(): 健康检查，返回 Pong 响应
    - ChatStream(): 流式对话，返回 AsyncGenerator[ChatStreamResponse]
    - Embedding(): 文本向量化，返回 EmbeddingResponse
    - Rerank(): 文档重排打分，返回 RerankResponse
边界条件：
    - ChatRequest.history 为空时表示首次对话
    - Embedding 和 Rerank 模型在服务启动时加载，不可用时有明确降级策略
异常行为：
    - context.cancelled() 返回 True 时终止流
    - LLM 调用异常时返回结构化错误响应
"""

import json
import time
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Optional

import grpc

# 使用 TYPE_CHECKING 条件导入 sentence_transformers 的类型：
# - 类型检查时：可以看到完整的 SentenceTransformer / CrossEncoder 类型定义
# - 运行时：不会导入 sentence_transformers（重依赖，可能未安装）
# - 实际运行中，Embedding/Rerank 方法内部已有模型为 None 的守卫检查
if TYPE_CHECKING:
    from sentence_transformers import CrossEncoder, SentenceTransformer

from app.api import communication_pb2, communication_pb2_grpc
from app.constants import Role
from app.llm.client import compression_llm_client, llm_client
from app.llm.stream_parser import StreamParser
from app.logger import logger

# ============================================================
# 全局 Embedding 和 Rerank 模型实例
# 在服务启动时由 set_embedding_model() 和 set_rerank_model() 初始化
# 为什么是全局变量：SentenceTransformer 和 CrossEncoder 实例是线程安全的，
#   且模型加载开销较大（数百MB到数GB），必须在进程内复用。
# 为什么不在 __init__ 中加载：因为 CommunicationServiceServicer 由 gRPC 框架
#   在 add_CommunicationServiceServicer_to_server() 时创建，无法传递外部参数。
# ============================================================
_embedding_model: Optional["SentenceTransformer"] = None
_rerank_model: Optional["CrossEncoder"] = None


def set_embedding_model(model: "SentenceTransformer"):
    """
    设置全局 Embedding 模型实例

    做什么：在服务启动前注入已加载的 SentenceTransformer 实例。
    为什么这样做：避免 gRPC Servicer 无法接收构造函数参数的限制。
    输入：model - 已加载的 SentenceTransformer 实例
    边界条件：model 为 None 时后续 Embedding 调用将返回错误
    """
    global _embedding_model
    _embedding_model = model
    logger.info("全局 Embedding 模型已设置")


def set_rerank_model(model: "CrossEncoder"):
    """
    设置全局 Rerank 模型实例

    做什么：在服务启动前注入已加载的 CrossEncoder 实例。
    为什么这样做：避免 gRPC Servicer 无法接收构造函数参数的限制。
    输入：model - 已加载的 CrossEncoder 实例
    边界条件：model 为 None 时后续 Rerank 调用将返回错误
    """
    global _rerank_model
    _rerank_model = model
    logger.info("全局 Rerank 模型已设置")


class CommunicationServiceServicer(
    communication_pb2_grpc.CommunicationServiceServicer
):
    """
    实现 gRPC 通信服务

    做什么：处理来自 Go Runtime 的 gRPC 请求，提供 Ping、ChatStream、LongSummarize 等服务。
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
        # 获取重构后的无歧义文本
        disambiguated_text = request.disambiguated_text

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
                disambiguated_text=disambiguated_text,
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

    async def ShortSummarize(
        self,
        request: communication_pb2.ShortSummarizeRequest,
        context: grpc.ServicerContext,
    ) -> communication_pb2.ShortSummarizeResponse:
        """
        处理后台短期摘要压缩请求

        做什么：接收 ShortSummarizeRequest，直接使用 Go 端渲染好的完整 summarize_prompt，
                调用 LLM 生成摘要，解析 JSON 并校验非空后返回。
        为什么这样做：Go 端负责模板渲染，Python 端仅负责调用 LLM 并解析结果。
        输入输出：
            - 输入：ShortSummarizeRequest {trace_id, summarize_prompt}
            - 输出：ShortSummarizeResponse {trace_id, new_core_summary, new_key_facts}
        边界条件：
            - LLM 返回空字段时回退到当前值
            - JSON 解析失败时回退到当前值
        异常行为：
            - 任何异常都返回空摘要，确保系统稳定性
        """
        trace_id = request.trace_id
        logger.info(f"[TraceID:{trace_id}] 收到 ShortSummarize 请求")

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
                    return communication_pb2.ShortSummarizeResponse(
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
                        return communication_pb2.ShortSummarizeResponse(
                            trace_id=trace_id,
                            new_core_summary="",
                            new_key_facts="",
                        )

            except Exception as e:
                logger.error(f"[TraceID:{trace_id}] 第 {attempt + 1} 次尝试：ShortSummarize 处理异常: {e}")
                if attempt < max_retries - 1:
                    continue
                else:
                    return communication_pb2.ShortSummarizeResponse(
                        trace_id=trace_id,
                        new_core_summary="",
                        new_key_facts="",
                    )

    async def LongSummarize(
        self,
        request: communication_pb2.LongSummarizeRequest,
        context: grpc.ServicerContext,
    ) -> communication_pb2.LongSummarizeResponse:
        """
        处理长期历史记录压缩请求

        做什么：接收 LongSummarizeRequest，直接使用 Go 端渲染好的完整 summarize_prompt，
                调用 LLM 生成长期记忆摘要。
        为什么这样做：将完整的历史会话压缩为结构化摘要，用于长期记忆持久化。Go 端负责模板渲染。
        输入输出：
            - 输入：LongSummarizeRequest {session_id, summarize_prompt}
            - 输出：LongSummarizeResponse {summary}
        边界条件：
            - summarize_prompt 为空时返回空摘要
            - LLM 返回空内容时返回空摘要
        异常行为：
            - LLM 调用异常时返回空摘要，不抛出异常（保障 Go 端稳定性）
            - 重试策略：最多 3 次，指数退避
        """
        trace_id = request.session_id
        logger.info(f"[SessionID:{trace_id}] 收到 LongSummarize 请求")

        summarize_prompt = request.summarize_prompt.strip()
        if not summarize_prompt:
            logger.warning(f"[SessionID:{trace_id}] 长期记忆压缩提示词为空，跳过压缩")
            return communication_pb2.LongSummarizeResponse(summary="")

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
                return communication_pb2.LongSummarizeResponse(summary=summary)

            except Exception as e:
                logger.error(
                    f"[SessionID:{trace_id}] 第 {attempt + 1} 次尝试：LongSummarize 处理异常: {e}"
                )
                if attempt < max_retries - 1:
                    continue
                else:
                    return communication_pb2.LongSummarizeResponse(summary="")

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

    async def Embedding(
        self,
        request: communication_pb2.EmbeddingRequest,
        context: grpc.ServicerContext,
    ) -> communication_pb2.EmbeddingResponse:
        """
        处理文本向量化请求

        做什么：接收文本，使用 SentenceTransformer 模型将其编码为稠密向量，
                返回 JSON 序列化的 float64 数组。
        为什么这样做：将自然语言文本转换为语义向量，用于 Qdrant 向量检索和语义相似度计算。
        输入输出：
            - 输入：EmbeddingRequest {text}
            - 输出：EmbeddingResponse {vector_json, success, error_message}
        边界条件：
            - text 为空时返回 success=false
            - Embedding 模型未加载时返回 success=false
        异常行为：
            - 向量化过程中的任何异常均被捕获，返回 success=false + 错误信息
        """
        text = (request.text or "").strip()
        if not text:
            return communication_pb2.EmbeddingResponse(
                vector_json="[]",
                success=False,
                error_message="text is blank"
            )

        if _embedding_model is None:
            logger.error("Embedding 模型未加载，无法处理向量化请求")
            return communication_pb2.EmbeddingResponse(
                vector_json="[]",
                success=False,
                error_message="Embedding model not loaded"
            )

        try:
            # 使用 SentenceTransformer 编码文本
            vec = _embedding_model.encode(text).tolist()
            vector_json = json.dumps(vec, ensure_ascii=False)
            logger.info(f"Embedding 向量化完成, text_length={len(text)}, vector_dim={len(vec)}")
            return communication_pb2.EmbeddingResponse(
                vector_json=vector_json,
                success=True,
                error_message=""
            )
        except Exception as e:
            logger.exception("Embedding 向量化失败")
            return communication_pb2.EmbeddingResponse(
                vector_json="[]",
                success=False,
                error_message=str(e)
            )

    async def InputReconstruction(
        self,
        request: communication_pb2.InputReconstructionRequest,
        context: grpc.ServicerContext,
    ) -> communication_pb2.InputReconstructionResponse:
        """
        处理用户输入重构与路由解析请求
        """
        trace_id = request.trace_id
        logger.info(f"[TraceID:{trace_id}] 收到 InputReconstruction 请求")

        try:
            from app.agent.input_reconstructor import InputReconstructorAgent
            from app.llm.client import llm_client
            
            agent = InputReconstructorAgent(llm_client)
            result = await agent.process(
                trace_id=trace_id,
                user_input=request.user_input,
                system_prompt=request.system_prompt,
                memory_prompt=request.memory_prompt,
                runtime_prompt=request.runtime_prompt
            )
            
            return communication_pb2.InputReconstructionResponse(
                trace_id=trace_id,
                json_output=result.model_dump_json(),
                success=True,
                error_message=""
            )
        except Exception as e:
            logger.exception(f"[TraceID:{trace_id}] InputReconstruction 处理异常")
            return communication_pb2.InputReconstructionResponse(
                trace_id=trace_id,
                json_output="",
                success=False,
                error_message=str(e)
            )

    async def Rerank(
        self,
        request: communication_pb2.RerankRequest,
        context: grpc.ServicerContext,
    ) -> communication_pb2.RerankResponse:
        """
        处理文档重排打分请求

        做什么：接收查询文本和候选文档列表，使用 CrossEncoder 模型计算每对 (query, doc)
                的相关性分数。
        为什么这样做：在 Qdrant 向量检索（粗排）之后，通过 CrossEncoder 精排提升召回质量。
        输入输出：
            - 输入：RerankRequest {query, documents[]}
            - 输出：RerankResponse {scores[], success, error_message}
        边界条件：
            - query 为空时返回 success=false
            - documents 为空时返回空 scores + success=true
            - Rerank 模型未加载时返回 success=false
        异常行为：
            - predict 过程中的任何异常均被捕获，返回 success=false + 错误信息
        """
        query = (request.query or "").strip()
        docs = list(request.documents)

        if not query:
            return communication_pb2.RerankResponse(
                scores=[],
                success=False,
                error_message="query is blank"
            )

        if not docs:
            return communication_pb2.RerankResponse(
                scores=[],
                success=True,
                error_message=""
            )

        if _rerank_model is None:
            logger.error("Rerank 模型未加载，无法处理重排请求")
            return communication_pb2.RerankResponse(
                scores=[],
                success=False,
                error_message="Rerank model not loaded"
            )

        try:
            # 构造 (query, doc) 对并预测分数
            pairs = [[query, d] for d in docs]
            scores = _rerank_model.predict(pairs).tolist()
            logger.info(f"Rerank 重排完成, query_length={len(query)}, doc_count={len(docs)}")
            return communication_pb2.RerankResponse(
                scores=scores,
                success=True,
                error_message=""
            )
        except Exception as e:
            logger.exception("Rerank 重排失败")
            return communication_pb2.RerankResponse(
                scores=[],
                success=False,
                error_message=str(e)
            )
