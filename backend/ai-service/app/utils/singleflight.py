"""
Luna AI SingleFlight 模块

做什么：提供类似 Go 语言 golang.org/x/sync/singleflight 的机制。
为什么这样做：防止缓存击穿。当多个协程同时请求同一个 Key 时，只有第一个协程去执行实际的加载逻辑，
             其他协程只需等待同一个 Future 的结果。
"""

import asyncio
from typing import Any, Callable, Coroutine, Dict


class SingleFlight:
    """
    SingleFlight 机制实现
    """
    def __init__(self):
        self._futures: Dict[str, asyncio.Future] = {}
        self._lock = asyncio.Lock()

    async def do(self, key: str, coro_func: Callable[[], Coroutine[Any, Any, Any]]) -> Any:
        """
        执行 coro_func，但对于相同的 key，同一时刻只会执行一次。
        其他并发请求会等待第一次执行的结果。
        """
        async with self._lock:
            if key in self._futures:
                # 已经有请求在处理了，直接等待它的结果
                fut = self._futures[key]
                is_first = False
            else:
                # 我是第一个请求，创建一个 Future 让别人等
                fut = asyncio.Future()
                self._futures[key] = fut
                is_first = True

        if not is_first:
            return await fut

        try:
            # 执行实际的耗时操作
            result = await coro_func()
            fut.set_result(result)
            return result
        except Exception as e:
            fut.set_exception(e)
            raise e
        finally:
            # 清理现场
            async with self._lock:
                self._futures.pop(key, None)
