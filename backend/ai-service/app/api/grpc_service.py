import time
import grpc
from typing import AsyncGenerator
from app.api import communication_pb2
from app.api import communication_pb2_grpc
from app.logger import get_logger
from app.llm.client import llm_client

logger = get_logger(__name__)

class CommunicationServiceServicer(communication_pb2_grpc.CommunicationServiceServicer):
    """
    实现 gRPC 通信服务
    """
    def Ping(self, request: communication_pb2.PingRequest, context: grpc.ServicerContext) -> communication_pb2.PongResponse:
        """
        处理 Ping 请求并返回 Pong 响应
        """
        logger.info(f"[TraceID:{request.trace_id}] 收到 Ping 请求, timestamp: {request.timestamp}")
        
        response = communication_pb2.PongResponse(
            trace_id=request.trace_id,
            timestamp=int(time.time() * 1000),
            source="python-ai-service"
        )
        
        logger.info(f"[TraceID:{request.trace_id}] 返回 Pong 响应, timestamp: {response.timestamp}")
        return response

    async def ChatStream(
        self,
        request: communication_pb2.ChatRequest,
        context: grpc.ServicerContext
    ) -> AsyncGenerator[communication_pb2.ChatStreamResponse, None]:
        """
        处理流式对话请求
        """
        trace_id = request.trace_id
        message = request.message
        
        logger.info(f"[TraceID:{trace_id}] 收到 ChatStream 请求, message: {message[:50]}...")
        
        # 构造简单的消息列表，后续可扩展为包含历史记录
        messages = [{"role": "user", "content": message}]
        
        try:
            async for chunk_data in llm_client.stream_chat(messages, trace_id):
                # 检查客户端是否已断开连接
                if context.is_active() is False:
                    logger.warning(f"[TraceID:{trace_id}] 客户端已断开连接，终止流式输出")
                    break
                    
                response = communication_pb2.ChatStreamResponse(
                    trace_id=trace_id,
                    chunk=chunk_data["chunk"],
                    is_finished=chunk_data["is_finished"],
                    finish_reason=chunk_data["finish_reason"] or "",
                    error=chunk_data["error"] or ""
                )
                yield response
                
        except Exception as e:
            logger.error(f"[TraceID:{trace_id}] ChatStream 处理异常: {str(e)}")
            yield communication_pb2.ChatStreamResponse(
                trace_id=trace_id,
                chunk="",
                is_finished=True,
                finish_reason="error",
                error=str(e)
            )
