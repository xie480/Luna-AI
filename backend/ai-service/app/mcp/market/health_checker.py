"""
MCP 运行验证引擎。

做什么：定期对已收录的远程 MCP Endpoint 进行健康检查，探测协议支持
        情况、响应延迟和是否需要认证。
为什么这样做：远程 MCP 最大的问题是失效，大量公开 MCP 服务存在认证和
            配置问题需要持续监控。
"""

import time
import httpx
from app.logger import logger


class HealthChecker:
    """MCP 运行验证引擎。"""

    @staticmethod
    async def check_endpoint(endpoint_url: str, timeout: float = 5.0) -> dict:
        """
        检查远程 Endpoint 的健康状态。
        """
        start = time.monotonic()
        health_status = "unknown"
        latency_ms = 0
        protocol = "unknown"
        auth_required = False
        
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                # 尝试 GET /health 或 OPTIONS
                resp = None
                try:
                    resp = await client.options(endpoint_url)
                except Exception:
                    pass
                
                if not resp or resp.status_code >= 500:
                    try:
                        resp = await client.get(endpoint_url)
                    except Exception:
                        pass
                
                if resp and resp.status_code < 500:
                    health_status = "online"
                    
                    # 探测是否需要认证
                    if resp.status_code in (401, 403):
                        auth_required = True
                        
                    # 探测协议
                    content_type = resp.headers.get("Content-Type", "").lower()
                    if "text/event-stream" in content_type:
                        protocol = "sse"
                    else:
                        protocol = "http"
                else:
                    health_status = "offline"
                    
        except Exception as e:
            logger.debug(f"健康检查失败 {endpoint_url}: {e}")
            health_status = "offline"
            
        latency_ms = int((time.monotonic() - start) * 1000)
        
        return {
            "health_status": health_status,
            "latency_ms": latency_ms,
            "protocol": protocol,
            "auth_required": auth_required
        }

    @staticmethod
    def get_next_degraded_status(current_status: str) -> str:
        """
        根据当前状态计算下一个降级状态。
        online -> degraded -> offline
        """
        if current_status == "online":
            return "degraded"
        return "offline"
