"""
Luna AI gRPC 客户端模块

做什么：封装了与 Python AI 服务的 gRPC 通信。
为什么这样做：作为 Go Runtime 与 Python AI Service 之间的通信桥梁，确保消息的可靠透传。
输入输出：
    - AIClient: gRPC 客户端类
边界条件：
    - 自动从 context 提取 TraceID 注入 gRPC Metadata，并记录调用 Span
异常行为：
    - gRPC 连接失败时抛出异常
"""

import asyncio
import time
from datetime import datetime
from typing import AsyncGenerator, Optional

import grpc

from app.api import communication_pb2, communication_pb2_grpc
from app.logger import logger
from app.utils.snowflake import generate_string_id


class TelemetryUnaryClientInterceptor(grpc.aio.UnaryUnaryClientInterceptor):
    """
    gRPC 客户端拦截器
    自动从 context 提取 TraceID 注入 gRPC Metadata，并记录调用 Span。
    """
    async def intercept_unary_unary(self, continuation, client_call_details, request):
        # 在 Python 中，我们通常通过 contextvars 传递 trace_id
        # 这里为了简化，我们直接生成一个新的 trace_id，或者从 request 中提取（如果存在）
        trace_id = getattr(request, "trace_id", None) or generate_string_id()
        span_id = generate_string_id()

        metadata = client_call_details.metadata or []
        metadata.append(("x-trace-id", trace_id))
        metadata.append(("x-parent-span-id", span_id))

        new_details = grpc.aio.ClientCallDetails(
            client_call_details.method,
            client_call_details.timeout,
            metadata,
            client_call_details.credentials,
            client_call_details.wait_for_ready,
        )

        start_time = time.time()
        try:
            response = await continuation(new_details, request)
            status = "OK"
        except Exception as e:
            status = "ERROR"
            raise e
        finally:
            duration_ms = int((time.time() - start_time) * 1000)
            from app.telemetry.worker import get_worker
            worker = get_worker()
            if worker:
                worker.record_span_async({
                    "trace_id": trace_id,
                    "span_id": span_id,
                    "name": client_call_details.method,
                    "service": "python_ai_service",
                    "start_time": datetime.fromtimestamp(start_time),
                    "end_time": datetime.now(),
                    "duration_ms": duration_ms,
                    "status": status,
                    "attributes": "{}"
                })

        return response


class TelemetryStreamClientInterceptor(grpc.aio.UnaryStreamClientInterceptor):
    """gRPC 客户端流拦截器"""
    async def intercept_unary_stream(self, continuation, client_call_details, request):
        trace_id = getattr(request, "trace_id", None) or generate_string_id()
        span_id = generate_string_id()

        metadata = client_call_details.metadata or []
        metadata.append(("x-trace-id", trace_id))
        metadata.append(("x-parent-span-id", span_id))

        new_details = grpc.aio.ClientCallDetails(
            client_call_details.method,
            client_call_details.timeout,
            metadata,
            client_call_details.credentials,
            client_call_details.wait_for_ready,
        )

        start_time = time.time()
        
        # 获取原始的响应迭代器
        response_iterator = await continuation(new_details, request)
        
        # 定义一个包装生成器，用于追踪流的完整生命周期
        async def _wrap_iterator(iterator):
            status = "OK"
            try:
                async for response in iterator:
                    yield response
            except Exception as e:
                status = "ERROR"
                raise e
            finally:
                # 在流真正结束（或异常中断）时记录 Span
                duration_ms = int((time.time() - start_time) * 1000)
                from app.telemetry.worker import get_worker
                worker = get_worker()
                if worker:
                    worker.record_span_async({
                        "trace_id": trace_id,
                        "span_id": span_id,
                        "name": f"{client_call_details.method}_stream",
                        "service": "python_ai_service",
                        "start_time": datetime.fromtimestamp(start_time),
                        "end_time": datetime.now(),
                        "duration_ms": duration_ms,
                        "status": status,
                        "attributes": "{}"
                    })

        # 返回包装后的生成器
        return _wrap_iterator(response_iterator)


class AIClient:
    """封装了与 Python AI 服务的 gRPC 通信"""

    def __init__(self, address: str):
        """创建一个新的 AIClient 实例"""
        self.address = address
        self.channel = grpc.aio.insecure_channel(
            address,
            interceptors=[
                TelemetryUnaryClientInterceptor(),
                TelemetryStreamClientInterceptor(),
            ]
        )
        self.client = communication_pb2_grpc.CommunicationServiceStub(self.channel)
        logger.info(f"成功连接到 AI 服务 address={address}")

    async def close(self) -> None:
        """关闭 gRPC 连接"""
        if self.channel:
            await self.channel.close()

    async def ping(self, trace_id: str) -> communication_pb2.PongResponse:
        """发送 Ping 请求到 AI 服务"""
        req = communication_pb2.PingRequest(
            trace_id=trace_id,
            timestamp=int(time.time() * 1000)
        )
        logger.info(f"发送 Ping 请求到 AI 服务 trace_id={trace_id} timestamp={req.timestamp}")

        try:
            resp = await self.client.Ping(req, timeout=5.0)
            logger.info(f"收到 AI 服务的 Pong 响应 trace_id={trace_id} timestamp={resp.timestamp} source={resp.source}")
            return resp
        except grpc.aio.AioRpcError as e:
            logger.error(f"Ping 请求失败 trace_id={trace_id} error={e}")
            raise RuntimeError(f"ping failed: {e}")

    async def chat_stream(self, req: communication_pb2.ChatRequest) -> AsyncGenerator[communication_pb2.ChatStreamResponse, None]:
        """发送流式对话请求到 AI 服务"""
        logger.info(f"发送 ChatStream 请求到 AI 服务 trace_id={req.trace_id}")

        try:
            async for resp in self.client.ChatStream(req):
                yield resp
        except grpc.aio.AioRpcError as e:
            logger.error(f"ChatStream 请求失败 trace_id={req.trace_id} error={e}")
            raise RuntimeError(f"chat stream failed: {e}")

    async def short_summarize(self, req: communication_pb2.ShortSummarizeRequest) -> communication_pb2.ShortSummarizeResponse:
        """发送短期摘要压缩请求到 AI 服务"""
        logger.info(f"发送 ShortSummarize 请求到 AI 服务 trace_id={req.trace_id}")

        try:
            resp = await self.client.ShortSummarize(req, timeout=30.0)
            return resp
        except grpc.aio.AioRpcError as e:
            logger.error(f"ShortSummarize 请求失败 trace_id={req.trace_id} error={e}")
            raise RuntimeError(f"short summarize failed: {e}")

    async def long_summarize(self, req: communication_pb2.LongSummarizeRequest) -> communication_pb2.LongSummarizeResponse:
        """发送长期历史记录压缩请求到 AI 服务"""
        logger.info(f"发送 LongSummarize 请求到 AI 服务 session_id={req.session_id}")

        try:
            resp = await self.client.LongSummarize(req, timeout=60.0)
            logger.info(f"收到 LongSummarize 响应 session_id={req.session_id} summary_length={len(resp.summary)}")
            return resp
        except grpc.aio.AioRpcError as e:
            logger.error(f"LongSummarize 请求失败 session_id={req.session_id} error={e}")
            raise RuntimeError(f"long summarize failed: {e}")

    async def embedding(self, req: communication_pb2.EmbeddingRequest) -> communication_pb2.EmbeddingResponse:
        """发送文本向量化请求到 AI 服务"""
        logger.info(f"发送 Embedding 请求到 AI 服务 text_length={len(req.text)}")

        try:
            resp = await self.client.Embedding(req, timeout=30.0)
            logger.info(f"收到 Embedding 响应 success={resp.success} error_message={resp.error_message}")
            return resp
        except grpc.aio.AioRpcError as e:
            logger.error(f"Embedding 请求失败 error={e}")
            raise RuntimeError(f"embedding 请求失败: {e}")

    async def input_reconstruction(self, req: communication_pb2.InputReconstructionRequest) -> communication_pb2.InputReconstructionResponse:
        """发送用户输入重构与路由解析请求到 AI 服务"""
        logger.info(f"发送 InputReconstruction 请求到 AI 服务 trace_id={req.trace_id}")

        try:
            resp = await self.client.InputReconstruction(req, timeout=30.0)
            return resp
        except grpc.aio.AioRpcError as e:
            logger.error(f"InputReconstruction 请求失败 trace_id={req.trace_id} error={e}")
            raise RuntimeError(f"input reconstruction failed: {e}")

    async def rerank(self, req: communication_pb2.RerankRequest) -> communication_pb2.RerankResponse:
        """发送文档重排打分请求到 AI 服务"""
        logger.info(f"发送 Rerank 请求到 AI 服务 query_length={len(req.query)} doc_count={len(req.documents)}")

        try:
            resp = await self.client.Rerank(req, timeout=60.0)
            logger.info(f"收到 Rerank 响应 success={resp.success} score_count={len(resp.scores)}")
            return resp
        except grpc.aio.AioRpcError as e:
            logger.error(f"Rerank 请求失败 error={e}")
            raise RuntimeError(f"rerank 请求失败: {e}")

    async def sync_preset_config(self, req: communication_pb2.SyncPresetConfigRequest) -> communication_pb2.SyncPresetConfigResponse:
        """发送预设配置同步请求到 AI 服务"""
        logger.info(f"发送 SyncPresetConfig 请求到 AI 服务 preset_id={req.preset_id}")

        try:
            resp = await self.client.SyncPresetConfig(req, timeout=5.0)
            return resp
        except grpc.aio.AioRpcError as e:
            logger.error(f"SyncPresetConfig 请求失败 preset_id={req.preset_id} error={e}")
            raise RuntimeError(f"sync preset config failed: {e}")
