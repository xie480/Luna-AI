import asyncio
import uvicorn
import grpc
from contextlib import asynccontextmanager
from fastapi import FastAPI

from app.api.health import router as health_router
from app.api import communication_pb2_grpc
from app.api.grpc_service import CommunicationServiceServicer
from app.config import settings
from app.logger import get_logger

logger = get_logger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用程序生命周期管理"""
    asyncio.create_task(serve_grpc())
    yield

app = FastAPI(title="Luna AI Service", lifespan=lifespan)

app.include_router(health_router)

async def serve_grpc():
    """启动 gRPC 服务"""
    server = grpc.aio.server()
    communication_pb2_grpc.add_CommunicationServiceServicer_to_server(
        CommunicationServiceServicer(), server
    )
    # 使用 0.0.0.0 绑定 IPv4 地址，确保 Windows 下 Go 客户端能正常连接
    listen_addr = f"0.0.0.0:{settings.grpc_port}"
    server.add_insecure_port(listen_addr)
    logger.info(f"gRPC 服务启动，监听地址: {listen_addr}")
    await server.start()
    await server.wait_for_termination()

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.ai_service_port,
        reload=True,
        log_level=settings.log_level.lower()
    )