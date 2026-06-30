"""工具执行工作池。

做什么：通过 asyncio.Semaphore 控制全局最大并发数。
为什么这样做：防止并行执行导致资源耗尽（连接池、文件句柄、API 限流）。
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.logger import logger


class ToolWorkerPool:
    """工具执行工作池。

    分层限流：
        1. 全局 Semaphore：控制整个 Agent Loop 的最大并发工具调用数
        2. State 级 Semaphore：控制单个 State 内的最大并发
        3. 工具级限流：特定工具（如 web_search）的独立限流
    """

    def __init__(
        self,
        global_max_concurrency: int = 20,
        state_max_concurrency: int = 10,
        tool_specific_limits: dict[str, int] | None = None,
    ):
        """初始化工作池。

        参数:
            global_max_concurrency: 全局最大并发工具调用数，默认 20。
            state_max_concurrency: 单 State 内最大并发数，默认 10。
            tool_specific_limits: 工具级限流配置，如 {"web_search": 2}。
        """
        self._global_semaphore = asyncio.Semaphore(global_max_concurrency)
        self._state_semaphore = asyncio.Semaphore(state_max_concurrency)
        self._tool_limiters: dict[str, asyncio.Semaphore] = {}
        if tool_specific_limits:
            for tool_name, limit in tool_specific_limits.items():
                self._tool_limiters[tool_name] = asyncio.Semaphore(limit)

    async def acquire(self, tool_name: str = "") -> None:
        """获取执行许可。

        做什么：
        1. 先获取全局 Semaphore
        2. 再获取 State 级 Semaphore
        3. 如果工具有限流器，再获取工具级 Semaphore

        参数:
            tool_name: 工具名称，用于工具级限流。空字符串时跳过工具级限流。
        """
        await self._global_semaphore.acquire()
        await self._state_semaphore.acquire()

        if tool_name and tool_name in self._tool_limiters:
            await self._tool_limiters[tool_name].acquire()

        logger.debug(
            f"ToolWorkerPool: 获取许可成功 tool={tool_name}, "
            f"global_available={self._global_semaphore._value + 1}, "  # type: ignore[attr-defined]
            f"state_available={self._state_semaphore._value + 1}"  # type: ignore[attr-defined]
        )

    async def release(self, tool_name: str = "") -> None:
        """释放执行许可。

        参数:
            tool_name: 工具名称，用于释放工具级限流器。
        """
        if tool_name and tool_name in self._tool_limiters:
            self._tool_limiters[tool_name].release()

        self._state_semaphore.release()
        self._global_semaphore.release()

    @property
    def global_available(self) -> int:
        """获取全局可用许可数（仅调试用）。"""
        return self._global_semaphore._value  # type: ignore[attr-defined]

    @property
    def state_available(self) -> int:
        """获取 State 级可用许可数（仅调试用）。"""
        return self._state_semaphore._value  # type: ignore[attr-defined]
