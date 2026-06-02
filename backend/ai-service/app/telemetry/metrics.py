"""
Luna AI 实时监控指标收集器

做什么：实现一个环形缓冲区，并通过后台任务定时收集系统 CPU、内存、协程数量等指标。
为什么这样做：为前端的实时监控仪表盘提供数据支持。
"""

import asyncio
import threading
import time
from collections import deque
from datetime import datetime
from typing import Any, Dict, List, Optional

import psutil

from app.logger import logger


class MetricPoint:
    """监控数据点"""
    def __init__(
        self,
        timestamp: datetime,
        system_cpu_usage: float,
        system_memory_usage: float,
        go_goroutines_count: int,  # 在 Python 中对应 asyncio tasks 数量
        llm_token_consumption: int,
        tool_call_failure_rate: float,
    ):
        self.timestamp = timestamp
        self.system_cpu_usage = system_cpu_usage
        self.system_memory_usage = system_memory_usage
        self.go_goroutines_count = go_goroutines_count
        self.llm_token_consumption = llm_token_consumption
        self.tool_call_failure_rate = tool_call_failure_rate

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "system_cpu_usage": self.system_cpu_usage,
            "system_memory_usage": self.system_memory_usage,
            "go_goroutines_count": self.go_goroutines_count,
            "llm_token_consumption": self.llm_token_consumption,
            "tool_call_failure_rate": self.tool_call_failure_rate,
        }


class RingBuffer:
    """环形缓冲区，用于存储最近的监控指标"""
    def __init__(self, capacity: int):
        self.capacity = capacity
        self.data: deque[MetricPoint] = deque(maxlen=capacity)
        self._lock = threading.Lock()

    def push(self, point: MetricPoint) -> None:
        """添加一个新的数据点"""
        with self._lock:
            self.data.append(point)

    def get_recent(self, n: int) -> List[Dict[str, Any]]:
        """获取最近的 n 个数据点，按时间正序排列"""
        with self._lock:
            # deque 已经保证了顺序，我们只需要取最后 n 个
            items = list(self.data)[-n:] if n > 0 else []
            return [item.to_dict() for item in items]


# 全局单例
_global_metrics_buffer: Optional[RingBuffer] = None
_collector_task: Optional[asyncio.Task] = None
_running = False


def init_metrics() -> None:
    """初始化全局监控指标缓冲区"""
    global _global_metrics_buffer
    # 存储最近 24 小时（按分钟聚合，共 1440 个数据点）
    _global_metrics_buffer = RingBuffer(1440)


def get_metrics_buffer() -> Optional[RingBuffer]:
    """获取全局监控指标缓冲区"""
    return _global_metrics_buffer


async def start_metrics_collector() -> None:
    """启动监控指标收集器"""
    global _collector_task, _running
    if _running:
        return
        
    _running = True
    _collector_task = asyncio.create_task(_collect_loop())
    logger.info("Metrics collector started")


async def stop_metrics_collector() -> None:
    """停止监控指标收集器"""
    global _running, _collector_task
    if not _running:
        return
        
    _running = False
    if _collector_task:
        _collector_task.cancel()
        try:
            await _collector_task
        except asyncio.CancelledError:
            pass
    logger.info("Metrics collector stopped")


async def _collect_loop() -> None:
    """收集循环"""
    buffer = get_metrics_buffer()
    if not buffer:
        return

    # 首次调用 cpu_percent 需要间隔
    psutil.cpu_percent()
    
    while _running:
        try:
            await asyncio.sleep(3.0)
            
            # 收集真实系统指标
            cpu_usage = psutil.cpu_percent()
            mem = psutil.virtual_memory()
            mem_usage_mb = mem.used / (1024 * 1024)
            
            # 获取当前事件循环中的任务数
            try:
                loop = asyncio.get_running_loop()
                tasks_count = len(asyncio.all_tasks(loop))
            except RuntimeError:
                tasks_count = 0
                
            # 模拟一些业务指标（实际应用中应从业务模块获取）
            # 这里为了演示，生成一些随机波动的数据
            import random
            
            point = MetricPoint(
                timestamp=datetime.now(),
                system_cpu_usage=cpu_usage,
                system_memory_usage=mem_usage_mb,
                go_goroutines_count=tasks_count,
                llm_token_consumption=random.randint(0, 500),
                tool_call_failure_rate=random.uniform(0, 0.05),
            )
            
            buffer.push(point)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Metrics collection error: {e}")
