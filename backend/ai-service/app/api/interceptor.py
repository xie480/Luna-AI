import grpc
from app.logger import trace_id_var, logger

class TelemetryInterceptor(grpc.aio.ServerInterceptor):
    """gRPC 服务端拦截器：提取 Go 侧注入的 TraceID 并绑定到 Loguru 上下文。"""

    async def intercept_service(self, continuation, handler_call_details):
        metadata = dict(handler_call_details.invocation_metadata)
        trace_id = metadata.get("x-trace-id", "UNKNOWN")
        parent_span_id = metadata.get("x-parent-span-id", "")

        # 设置 contextvars，使同一协程内任意位置都能获取 TraceID
        token = trace_id_var.set(trace_id)

        try:
            # 绑定 loguru 上下文，后续所有日志自动携带 trace_id 字段
            with logger.contextualize(trace_id=trace_id, parent_span_id=parent_span_id):
                logger.info(f"收到 gRPC 请求: {handler_call_details.method}")
                return await continuation(handler_call_details)
        except Exception as e:
            logger.error(f"gRPC 处理异常: {str(e)}")
            raise
        finally:
            trace_id_var.reset(token)
