"""
Luna AI 事件总线模块

做什么：提供简单的进程内发布订阅机制。
为什么这样做：解耦组件，例如配置变更时通知其他模块重新加载。
输入输出：
    - EventBus: 事件总线类
    - Event: 事件结构
    - EventType: 事件类型枚举
边界条件：
    - 异步执行处理器，避免阻塞发布者
异常行为：
    - 处理器执行异常不影响其他处理器
"""

import asyncio
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Coroutine


class EventType(str, Enum):
    """定义事件类型"""
    CONFIG_CHANGED = "ConfigChanged"
    RAG_DOCUMENT_DEPRECATED = "RagDocumentDeprecated"


@dataclass
class RagDocumentDeprecatedEvent:
    doc_id: str
    
    @property
    def type(self) -> EventType:
         return EventType.RAG_DOCUMENT_DEPRECATED


class Event:
    """定义事件结构"""
    def __init__(self, type_: EventType, data: Any = None):
        self.type = type_
        self.data = data


# 事件处理器函数签名，支持同步和异步函数
EventHandler = Callable[[Any], Coroutine[Any, Any, None] | None]


class EventBus:
    """提供简单的发布订阅机制"""
    def __init__(self):
        self._handlers: dict[EventType, list[EventHandler]] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """订阅指定类型的事件"""
        async with self._lock:
            if event_type not in self._handlers:
                self._handlers[event_type] = []
            self._handlers[event_type].append(handler)

    async def publish(self, event: Event) -> None:
        """发布事件"""
        async with self._lock:
            handlers = self._handlers.get(event.type, []).copy()

        for handler in handlers:
            # 异步执行处理器，避免阻塞发布者
            if asyncio.iscoroutinefunction(handler):
                asyncio.create_task(handler(event))
            else:
                # 如果是同步函数，在默认的 executor 中运行以避免阻塞事件循环
                loop = asyncio.get_running_loop()
                loop.run_in_executor(None, handler, event)

# 全局事件总线单例
event_bus = EventBus()
