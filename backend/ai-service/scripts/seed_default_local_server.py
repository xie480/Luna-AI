"""
Luna AI 本地默认 MCP 服务器种子脚本。

做什么：向 mcp_server_registrations 表写入一个默认的本地 MCP 服务器记录。
        默认服务器是 filesystem 服务器，提供文件系统读写工具能力。
为什么这样做：用户首次使用时，系统需要至少一个本地服务器来展示 MCP 能力，
             减少初始配置负担。
输入输出：向 PostgreSQL 写入一条 MCPServerRegistration 记录；无业务返回值。
边界条件：
    - 已存在同名服务器时跳过（幂等）。
    - 数据库连接失败时抛出明确异常。
异常行为：数据库写入失败时回滚事务并抛出异常。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import select

# ai-service 根目录需要显式加入 sys.path
AI_SERVICE_ROOT = Path(__file__).resolve().parent.parent
if str(AI_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(AI_SERVICE_ROOT))

from app.config.settings import settings
from app.infrastructure.postgres import PostgresClient
from app.logger import logger
from app.repository.models import MCPServerRegistration
from app.utils.snowflake import generate_string_id

# ============================================================================
# 默认服务器配置
# ============================================================================

# 默认的 filesystem 本地 MCP 服务器配置。
# 使用 @modelcontextprotocol/server-filesystem 包，通过 npx 启动。
# 限制文件操作范围到用户的家目录下的 LunaAI_Workspace 目录。
DEFAULT_SERVER_CONFIG: dict[str, Any] = {
    "name": "defaultsystem-local",
    "command": "npx",
    "args": [
        "-y",
        "@modelcontextprotocol/server-filesystem",
        "F:/YilenaCode/Luna-AI",
    ],
    "env": {},
    "description": "本地文件系统 MCP 服务器",
    "enabled": True,
}


async def seed_default_local_server() -> bool:
    """
    写入默认的本地 MCP 服务器到数据库。

    做什么：
        1. 连接 PostgreSQL。
        2. 检查是否已存在名为 DEFAULT_SERVER_CONFIG["name"] 的服务器。
        3. 若已存在则跳过（幂等）。
        4. 若不存在则插入一条 MCPServerRegistration 记录。
    返回:
        bool: True 表示插入成功或已存在无需操作，False 表示操作失败。
    """
    pg_client: PostgresClient | None = None
    try:
        pg_client = PostgresClient(settings.postgres_conn_str)

        async with pg_client.session_factory() as session:
            # Step 1: 检查是否已存在
            name = DEFAULT_SERVER_CONFIG["name"]
            result = await session.execute(
                select(MCPServerRegistration).where(
                    MCPServerRegistration.name == name,
                ).limit(1)
            )
            existing = result.scalar_one_or_none()

            if existing:
                logger.info(
                    f"默认本地服务器 '{name}' 已存在 (id={existing.id})，跳过写入"
                )
                return True

            # Step 2: 插入新记录
            server_id = generate_string_id()
            new_server = MCPServerRegistration(
                id=server_id,
                name=name,
                command=DEFAULT_SERVER_CONFIG["command"],
                args=DEFAULT_SERVER_CONFIG["args"],
                env=DEFAULT_SERVER_CONFIG["env"],
                description=DEFAULT_SERVER_CONFIG["description"],
                enabled=DEFAULT_SERVER_CONFIG["enabled"],
                tool_count=0,
                endpoint_url="",
                health_status="unknown",
                metadata_={},
            )
            session.add(new_server)
            await session.commit()

            logger.info(
                f"默认本地服务器 '{name}' 写入成功 (id={server_id})"
            )
            return True

    except Exception as e:
        logger.error(f"写入默认本地服务器失败: {e}")
        return False
    finally:
        if pg_client is not None:
            await pg_client.close()


async def main() -> None:
    """
    主入口。

    做什么：调用 seed_default_local_server 并打印执行结果。
    为什么这样做：脚本可以直接从命令行独立运行。
    """
    logger.info("开始写入默认本地 MCP 服务器...")
    success = await seed_default_local_server()
    if success:
        logger.info("默认本地 MCP 服务器写入完成")
        print("✅ 默认本地 MCP 服务器写入完成")
    else:
        logger.error("默认本地 MCP 服务器写入失败")
        print("❌ 默认本地 MCP 服务器写入失败")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
