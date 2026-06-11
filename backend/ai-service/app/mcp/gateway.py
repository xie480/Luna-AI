"""
MCP 统一访问网关。

做什么：作为所有远程 MCP 调用的统一入口，负责鉴权注入、请求代理、
        响应转发、日志记录和限流控制。本地 MCP 调用不经过此网关。
为什么这样做：远程 MCP 存在鉴权、可用性、延迟等不确定因素，
            需要统一管控层来保证安全性和可观测性。
"""

import time
import httpx
from typing import Any
from pydantic import BaseModel

from app.logger import logger
from app.mcp.types import MCPToolResult
from app.utils.snowflake import generate_string_id


class CircuitBreakerConfig(BaseModel):
    failure_threshold: float = 0.5
    recovery_timeout: int = 60
    min_request_count: int = 5


class CircuitBreaker:
    def __init__(self, config: CircuitBreakerConfig):
        self.config = config
        self.failures = 0
        self.total = 0
        self.is_open = False
        self.last_failure_time = 0.0

    def allow_request(self) -> bool:
        if self.is_open:
            if time.monotonic() - self.last_failure_time > self.config.recovery_timeout:
                self.is_open = False
                self.failures = 0
                self.total = 0
                return True
            return False
        return True

    def record_success(self) -> None:
        self.total += 1

    def record_failure(self) -> None:
        self.total += 1
        self.failures += 1
        self.last_failure_time = time.monotonic()
        if self.total >= self.config.min_request_count:
            if (self.failures / self.total) >= self.config.failure_threshold:
                self.is_open = True
                logger.warning(f"熔断器触发，失败率超过阈值: {self.failures}/{self.total}")


class MCPRemoteGateway:
    """MCP 远程调用网关。"""

    def __init__(self) -> None:
        self._circuit_breakers: dict[str, CircuitBreaker] = {}
        self._default_breaker_config = CircuitBreakerConfig()
        
    def _get_circuit_breaker(self, endpoint_url: str) -> CircuitBreaker:
        if endpoint_url not in self._circuit_breakers:
            self._circuit_breakers[endpoint_url] = CircuitBreaker(self._default_breaker_config)
        return self._circuit_breakers[endpoint_url]
        
    def _build_auth_headers(self, auth_config: dict[str, Any] | None) -> dict[str, str]:
        if not auth_config:
            return {}
            
        auth_type = auth_config.get("type", "none")
        if auth_type == "bearer":
            return {"Authorization": f"Bearer {auth_config.get('token', '')}"}
        elif auth_type == "api_key":
            key_name = auth_config.get("key_name", "X-API-Key")
            return {key_name: auth_config.get("api_key", "")}
        return {}

    def _parse_response(self, response: httpx.Response) -> MCPToolResult:
        try:
            data = response.json()
            if "error" in data:
                return MCPToolResult(
                    success=False,
                    output_text="",
                    error_message=str(data["error"]),
                    execution_id=generate_string_id()
                )
            
            result_data = data.get("result", {})
            output = str(result_data.get("output", ""))
            is_error = result_data.get("isError", False)
            
            return MCPToolResult(
                success=not is_error,
                output_text=output[:4096] + ("[truncated]" if len(output) > 4096 else ""),
                error_message=output if is_error else "",
                execution_id=generate_string_id()
            )
        except Exception as e:
            return MCPToolResult(
                success=False,
                output_text="",
                error_message=f"解析响应失败: {e}",
                execution_id=generate_string_id()
            )

    def _record_latency(self, endpoint_url: str, tool_name: str, latency: int) -> None:
        """记录调用延迟。"""
        # 使用统一可观测性体系（这里简单通过 logger 审计记录）
        logger.info(f"[Gateway] 远程 MCP 调用 tool={tool_name} latency={latency}ms endpoint={endpoint_url}")

    async def execute_remote_tool(
        self,
        endpoint_url: str,
        tool_name: str,
        parameters: dict[str, Any],
        auth_config: dict[str, Any] | None = None,
        trace_id: str = "",
        timeout: float = 30.0,
    ) -> MCPToolResult:
        """执行远程 MCP 工具调用。"""
        breaker = self._get_circuit_breaker(endpoint_url)
        if not breaker.allow_request():
            return MCPToolResult(
                success=False,
                output_text="",
                error_message=f"远程 MCP '{tool_name}' 熔断器开启中，稍后自动恢复",
                execution_id=generate_string_id()
            )

        headers = self._build_auth_headers(auth_config)
        headers["Content-Type"] = "application/json"
        
        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    endpoint_url,
                    json={
                        "jsonrpc": "2.0",
                        "method": "tools/call",
                        "params": {
                            "name": tool_name,
                            "arguments": parameters,
                        },
                        "id": generate_string_id(),
                    },
                    headers=headers,
                )
                response.raise_for_status()
                result = self._parse_response(response)
                breaker.record_success()
                
                # 补充字段
                result.latency_ms = int((time.monotonic() - start) * 1000)
                result.risk_level = "remote_proxy" # 或传入实际 risk_level
                return result
                
        except Exception as exc:
            breaker.record_failure()
            return MCPToolResult(
                success=False,
                output_text="",
                error_message=f"远程 MCP 调用失败: {exc!s}",
                execution_id=generate_string_id(),
                latency_ms=int((time.monotonic() - start) * 1000),
                risk_level="remote_proxy"
            )
        finally:
            elapsed = max(0, int((time.monotonic() - start) * 1000))
            self._record_latency(endpoint_url, tool_name, elapsed)

_gateway_instance = None

def get_gateway() -> MCPRemoteGateway:
    global _gateway_instance
    if _gateway_instance is None:
        _gateway_instance = MCPRemoteGateway()
    return _gateway_instance
