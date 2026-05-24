import time
import grpc
from app.api import communication_pb2
from app.api import communication_pb2_grpc
from app.logger import get_logger

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
