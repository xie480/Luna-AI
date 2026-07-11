import asyncio
import httpx
from typing import Dict, Optional, Any
from mcp.client.sse import sse_client
from mcp.client.session import ClientSession
import httpx
from mcp.client.streamable_http import streamable_http_client
from contextlib import AsyncExitStack

from app.logger import logger
from app.mcp.server_manager import MCPServerManager

class McpConnectionManager:
    """
    MCP Server 连接管理器。

    做什么：维护与外部 MCP Server 的长连接 (ClientSession)，复用底层连接以优化性能。
    为什么这样做：官方 MCP SDK 基于 SSE + HTTP 建立全双工通信通道，初始化开销较大，
               必须在进程级维护活跃的 Session。
    """
    _instance = None

    def __init__(self):
        # 字典结构: server_id -> {"session": ClientSession, "transport": SSEClientTransport, "exit_stack": AsyncExitStack}
        self._connections: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    @classmethod
    def get_instance(cls) -> "McpConnectionManager":
        if cls._instance is None:
            cls._instance = McpConnectionManager()
        return cls._instance

    async def get_or_create_session(self, server_id: str) -> Optional[ClientSession]:
        """
        获取或创建指定 server 的 MCP Session。
        """
        async with self._lock:
            if server_id in self._connections:
                return self._connections[server_id]["session"]

            # 需要创建新连接
            manager = MCPServerManager.get_instance()
            config = manager.get_server_config(server_id)
            if not config:
                logger.error(f"Cannot create connection: config not found for server {server_id}")
                return None

            if config.transport_type != "sse":
                logger.error(f"Unsupported transport type '{config.transport_type}' for server {server_id}. Only 'sse' is supported.")
                return None

            endpoint_url = config.endpoint_url
            if not endpoint_url:
                logger.error(f"Cannot create connection: endpoint_url is empty for server {server_id}")
                return None

            # 准备鉴权 Header
            headers = {}
            token = manager.resolve_auth_token(server_id)
            if token:
                if config.auth.type == "bearer":
                    headers["Authorization"] = f"Bearer {token}"
                elif config.auth.type == "api_key":
                    # 注意: 这里假设 API Key 放在 x-api-key header 中，不同服务可能有差异
                    headers["x-api-key"] = token
                elif config.auth.type == "service_token":
                    headers["Authorization"] = f"Bearer {token}" # fallback or specific handling

            logger.info(f"Connecting to MCP server {server_id} at {endpoint_url} via SSE...")
            
            try:
                exit_stack = AsyncExitStack()
                
                # We always use the standard sse_client instead of streamable_http_client
                # streamable_http_client has issues with certain servers where it hangs during initialize()
                # standard sse_client works fine with both standard and smithery servers
                read_stream, write_stream = await exit_stack.enter_async_context(
                    sse_client(
                        url=endpoint_url,
                        headers=headers,
                        timeout=config.timeout_seconds
                    )
                )
                
                # IMPORTANT: Initialize session using specific initialization timeout to prevent hanging forever
                # Some servers might accept connection but never respond to initialize()
                session = ClientSession(read_stream, write_stream)
                await exit_stack.enter_async_context(session)

                # Initialize MCP protocol with explicit timeout
                init_timeout = max(config.timeout_seconds, 15.0)  # Use config timeout or min 15s
                try:
                    await asyncio.wait_for(session.initialize(), timeout=init_timeout)
                except asyncio.TimeoutError:
                    raise Exception(f"MCP Session initialize() timed out after {init_timeout} seconds")

                self._connections[server_id] = {
                    "session": session,
                    "exit_stack": exit_stack
                }
                
                logger.info(f"Successfully connected to MCP server {server_id}")
                return session

            except Exception as e:
                logger.error(f"Failed to connect to MCP server {server_id}: {e}", exc_info=True)
                # Ensure cleanup on failure
                try:
                    if 'exit_stack' in locals():
                        await exit_stack.aclose()
                except Exception as ce:
                    logger.error(f"Failed to cleanup after connection error for {server_id}: {ce}")
                return None

    async def close_session(self, server_id: str):
        """关闭指定 server 的连接"""
        async with self._lock:
            if server_id in self._connections:
                logger.info(f"Closing connection for MCP server {server_id}")
                conn = self._connections.pop(server_id)
                try:
                    await conn["exit_stack"].aclose()
                except Exception as e:
                    logger.error(f"Error closing connection for {server_id}: {e}")

    async def close_all(self):
        """关闭所有连接"""
        # 取出所有 server_ids 避免遍历时修改字典
        server_ids = list(self._connections.keys())
        for sid in server_ids:
            await self.close_session(sid)
