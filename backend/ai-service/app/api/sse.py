"""
Luna AI SSE（Server-Sent Events）服务模块

做什么：提供 SSE 事件流路由，用于替代原 WebSocket 的实时推送功能。
        前端通过 EventSource 连接 /sse/notifications 接收实时事件。

事件类型：
    - CHAT_STREAM: 聊天流式输出块
    - EVT_MEMORY_SYNC: 记忆同步事件
    - ERROR: 错误通知
    - HEARTBEAT: 心跳（每 5 秒）

为什么这样做：废弃 WebSocket 后，实时推送统一使用 SSE 单向通道实现，
            业务请求使用普通的 HTTP POST/GET 完成。

边界条件：
    - 每个连接都有独立的异步生成器
    - 使用 asyncio.Queue 实现生产者-消费者模式
    - 心跳每 5 秒推送一次，保持连接活跃
异常行为：
    - 客户端断开时，生成器自动退出
    - 推送失败不阻塞其他客户端
"""

import asyncio
import json
import time
from typing import Any, Dict, Optional, AsyncGenerator

from fastapi import APIRouter, Depends, Header
from fastapi.responses import StreamingResponse

from app.logger import logger
from app.utils.snowflake import generate_string_id

router = APIRouter(prefix="/sse", tags=["sse"])


class SSEManager:
    """
    SSE 连接管理器。

    做什么：管理所有 SSE 客户端的连接和事件推送。
    为什么这样做：解耦事件生产者和消费者，HTTP API 通过 publish()
            向所有连接的客户端广播事件，无需关心连接细节。
    """

    def __init__(self):
        """初始化 SSE 管理器"""
        self._queues: set[asyncio.Queue] = set()
        self._lock = asyncio.Lock()

    async def register(self) -> asyncio.Queue:
        """
        注册一个新的 SSE 客户端队列。

        返回：一个 asyncio.Queue，用于接收推送给该客户端的事件。
        """
        queue: asyncio.Queue = asyncio.Queue()
        async with self._lock:
            self._queues.add(queue)
        return queue

    async def unregister(self, queue: asyncio.Queue) -> None:
        """
        注销一个 SSE 客户端队列。

        做什么：客户端断开连接时清理资源。
        """
        async with self._lock:
            self._queues.discard(queue)

    async def publish(self, event_data: Dict[str, Any]) -> None:
        """
        向所有连接的 SSE 客户端广播事件。

        输入：event_data 包含 type, trace_id, payload 字段的字典。
        异常：单个客户端队列满或不可用时，该客户端被自动移除，不影响其他客户端。
        """
        async with self._lock:
            queues = list(self._queues)

        for queue in queues:
            try:
                # 使用超时防止队列满时阻塞
                await asyncio.wait_for(queue.put(event_data), timeout=1.0)
            except asyncio.TimeoutError:
                # 队列满，移除该客户端（消费者可能已断开）
                async with self._lock:
                    self._queues.discard(queue)
            except Exception as e:
                logger.error(f"SSE 推送事件失败 error={e}")
                async with self._lock:
                    self._queues.discard(queue)


# 全局 SSE 管理器单例
sse_manager = SSEManager()


async def get_trace_id(x_trace_id: Optional[str] = Header(None)) -> str:
    """从请求头获取 trace_id，若不存在则自动生成"""
    return x_trace_id or generate_string_id()


async def event_generator(trace_id: str) -> AsyncGenerator[bytes, None]:
    """
    SSE 事件生成器。

    做什么：为每个 SSE 连接创建一个异步生成器，持续读取队列中的事件并推送。
    心跳：每 5 秒发送一次 HEARTBEAT 事件，保持连接活跃。

    输出格式（SSE 协议）：
        event: <event_type>\n
        data: <json_payload>\n\n
    """
    queue = await sse_manager.register()
    try:
        # 发送初始连接确认
        init_event = {
            "type": "CONNECTED",
            "trace_id": trace_id,
            "payload": {"status": "connected", "timestamp": int(time.time() * 1000)},
        }
        yield f"event: connected\ndata: {json.dumps(init_event)}\n\n".encode("utf-8")

        last_heartbeat = time.time()
        while True:
            try:
                # 等待事件，超时 5 秒用于发送心跳
                event_data = await asyncio.wait_for(queue.get(), timeout=5.0)
                event_type = event_data.get("type", "message")
                yield f"event: {event_type}\ndata: {json.dumps(event_data)}\n\n".encode("utf-8")
                last_heartbeat = time.time()
            except asyncio.TimeoutError:
                # 超时未收到事件，发送心跳
                now = time.time()
                if now - last_heartbeat >= 5.0:
                    heartbeat = {
                        "type": "HEARTBEAT",
                        "trace_id": trace_id,
                        "payload": {"timestamp": int(now * 1000)},
                    }
                    yield f"event: heartbeat\ndata: {json.dumps(heartbeat)}\n\n".encode("utf-8")
                    last_heartbeat = now
    except asyncio.CancelledError:
        logger.info(f"SSE 连接被取消 trace_id={trace_id}")
    except Exception as e:
        logger.error(f"SSE 生成器异常 trace_id={trace_id} error={e}")
    finally:
        await sse_manager.unregister(queue)
        logger.info(f"SSE 连接已关闭 trace_id={trace_id}")


@router.get("/notifications")
async def notifications(trace_id: str = Depends(get_trace_id)):
    """
    SSE 通知端点。

    前端使用 new EventSource('/sse/notifications') 建立连接。
    返回 Content-Type: text/event-stream 的流式响应。
    """
    return StreamingResponse(
        event_generator(trace_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
