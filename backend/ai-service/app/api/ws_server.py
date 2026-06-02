"""
⚠️ 已废弃：此文件中的 WebSocket 路由已完全移除。

WebSocket 已被 HTTP API + SSE 替代，具体迁移说明：
- 所有业务请求 → HTTP POST/GET（见 http_api.py）
- 实时事件推送 → SSE（见 sse.py）
- 记忆事件广播 → 通过 SSE 管理器推送

保留此文件仅用于引用旧的消息模型定义，新代码请勿引用。
所有新开发应使用 http_api.py 和 sse.py 中的接口。
"""

from pydantic import BaseModel
from typing import Any, List


class WSMessage(BaseModel):
    """【已废弃】原 WebSocket 消息结构，保留仅用于参考"""
    type: str
    trace_id: str
    payload: Any


class CMDUserInputPayload(BaseModel):
    """【已废弃】原聊天请求 Payload，保留仅用于参考"""
    sessionId: str
    message: str
    msgId: str
    history: List = []


class ChatStreamPayload(BaseModel):
    """【已废弃】原流式响应 Payload，保留仅用于参考"""
    type: str
    chunk: str
    is_finished: bool
    node_id: str
    error: str = ""
