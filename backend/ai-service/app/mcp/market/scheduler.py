"""
MCP 市场定时采集调度器。

做什么：由 app.main.py 在启动时创建，以后台 asyncio 任务的形式定期执行：
        1. 调用 DiscoveryEngine.run_discovery() 采集原始数据
        2. 调用 MarketNormalizer 去重标准化
        3. 将标准化后的条目 upsert 到 mcp_marketplace 表
        4. 写 mcp_marketplace_discovery_log 审计日志
        默认每 24 小时执行一次，首次启动后等待 60 秒再执行（给依赖就绪时间）。
为什么这样做：采集逻辑本已存在但未被调用，需要一个调度器将其接入运行生命周期。
边界条件：
    - PG 不可用时跳过本轮采集，不阻塞调度循环。
    - 单次采集失败只记日志不阻断后续定时触发。
"""

import asyncio
from datetime import datetime, timezone
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.logger import logger
from app.infrastructure.postgres import PostgresClient
from app.utils.snowflake import generate_string_id
from app.mcp.market.discovery import DiscoveryEngine
from app.mcp.market.normalizer import MarketNormalizer
from app.mcp.market.types import NormalizedItem
from app.repository.models import MCPMarketplace, MCPMarketplaceDiscoveryLog


class MarketDiscoveryScheduler:
    """MCP 市场定时采集调度器。

    做什么：后台定时任务，每隔 DISCOVERY_INTERVAL_SECONDS 秒触发一次完整采集流程。
    为什么这样做：MCP 市场数据需要保持新鲜度，定期从各数据源拉取最新 Server 列表。
    边界条件：
        - pg_client 为 None 时不启动采集。
        - 采集/持久化失败仅日志记录，不崩溃。
    """

    # 采集周期：24 小时（生产环境建议值）
    DISCOVERY_INTERVAL_SECONDS: int = 24 * 60 * 60

    def __init__(self, pg_client: PostgresClient | None) -> None:
        """初始化调度器。

        参数：
            pg_client: PostgreSQL 客户端实例，用于写入采集结果。
                       为 None 时调度器仅打印警告，不执行采集任务。
        """
        self._pg_client = pg_client
        self._task: asyncio.Task | None = None
        self._engine = DiscoveryEngine()
        self._normalizer = MarketNormalizer()

    async def start(self) -> None:
        """启动后台采集循环。

        做什么：创建 asyncio 任务执行 _run_loop。
                首次触发前等待 60 秒，确保依赖（PG、网络）已就绪。
        为什么这样做：启动时立即执行可能因基础设施未完全就绪而失败。
        """
        if self._task is not None:
            logger.warning("MCP 市场采集调度器已在运行，跳过重复启动")
            return

        if self._pg_client is None:
            logger.warning("MCP 市场采集调度器未启动：PG 客户端不可用")
            return

        self._task = asyncio.create_task(self._run_loop())
        logger.info("MCP 市场采集调度器已启动，首次采集将在 60 秒后执行")

    async def stop(self) -> None:
        """停止后台采集循环。"""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
            logger.info("MCP 市场采集调度器已停止")

    async def trigger_once(self) -> None:
        """手动触发一次立即采集（供 API 或调试使用）。

        做什么：忽略调度周期，立即执行一轮完整的采集→标准化→持久化流程。
        边界条件：PG 不可用时静默跳过。
        """
        if self._pg_client is None:
            logger.warning("手动采集跳过：PG 客户端不可用")
            return
        await self._execute_discovery()

    async def _run_loop(self) -> None:
        """后台采集主循环。

        做什么：无限循环，每次执行完一轮采集后等待 DISCOVERY_INTERVAL_SECONDS 秒。
        为什么这样做：使用固定间隔而非 Cron 表达式，简化实现且对桌面本地场景足够。
        """
        try:
            # 首次启动等待 60 秒，让基础设施完全就绪
            await asyncio.sleep(60)

            while True:
                logger.info("MCP 市场定时采集任务开始执行")
                try:
                    await self._execute_discovery()
                    logger.info("MCP 市场定时采集任务执行完成")
                except Exception as e:
                    logger.error(f"MCP 市场定时采集任务异常: {e}")

                logger.info(f"MCP 市场采集调度器等待 {self.DISCOVERY_INTERVAL_SECONDS} 秒后下次执行")
                await asyncio.sleep(self.DISCOVERY_INTERVAL_SECONDS)

        except asyncio.CancelledError:
            logger.info("MCP 市场采集调度器循环被取消")
            raise

    async def _execute_discovery(self) -> None:
        """执行一轮完整的采集→标准化→持久化流程。

        流程：
            1. DiscoveryEngine.run_discovery() 采集所有来源的原始数据。
            2. MarketNormalizer.normalize() 去重并标准化字段。
            3. 将标准化后的条目逐条 upsert 到 mcp_marketplace 表。
            4. 记录审计日志到 mcp_marketplace_discovery_log 表。
        """
        # Step 1: 采集原始数据
        raw_items = await self._engine.run_discovery()
        if not raw_items:
            logger.info("本轮采集未获取到任何 MCP Server 数据")
            return

        logger.info(f"原始采集结果: {len(raw_items)} 条")

        # 日志：打印前3条原始数据的 name/description/repository_url，确认采集层数据完整
        raw_sample = raw_items[:3]
        for i, r_item in enumerate(raw_sample):
            logger.info(
                f"原始数据[{i}]: "
                f"name={r_item.name} "
                f"desc_len={len(r_item.description)} "
                f"repo_url={r_item.repository_url} "
                f"endpoint_url={r_item.endpoint_url} "
                f"author={r_item.author} "
                f"license={r_item.license} "
                f"tags={r_item.tags} "
                f"raw_data keys={list(r_item.raw_data.keys()) if r_item.raw_data else 'empty'}"
            )

        # Step 2: 标准化与去重
        normalized_items = await self._normalizer.normalize(raw_items)
        if not normalized_items:
            logger.info("标准化后无有效条目，跳过持久化")
            return

        logger.info(f"标准化去重后: {len(normalized_items)} 条")

        # 日志：打印前3条标准化后的数据，确认字段映射正确
        norm_sample = normalized_items[:3]
        for i, n_item in enumerate(norm_sample):
            logger.info(
                f"标准化数据[{i}]: "
                f"name={n_item.name} "
                f"display_name={n_item.display_name} "
                f"desc_len={len(n_item.description)} "
                f"repo_url={n_item.repository_url} "
                f"endpoint_url={n_item.endpoint_url} "
                f"author={n_item.author} "
                f"license={n_item.license} "
                f"tags={n_item.tags} "
                f"category={n_item.category}"
            )

        # Step 3: 持久化到 PostgreSQL
        async with self._pg_client.session_factory() as session:
            inserted_count = 0
            updated_count = 0

            for item in normalized_items:
                try:
                    is_new = await self._upsert_marketplace(session, item)
                    if is_new:
                        inserted_count += 1
                    else:
                        updated_count += 1
                except Exception as e:
                    logger.error(f"持久化 MCP Server 失败 name={item.name} error={e}")

            # Step 4: 记录审计日志
            await self._log_discovery(session, "full_discovery", len(normalized_items), inserted_count, updated_count)
            await session.commit()

        logger.info(
            f"MCP 市场持久化完成: 新增 {inserted_count} 条, 更新 {updated_count} 条, "
            f"共处理 {len(normalized_items)} 条"
        )

    async def _upsert_marketplace(self, session: AsyncSession, item: NormalizedItem) -> bool:
        """将标准化条目 upsert 到 mcp_marketplace 表。

        策略：
            - 先按 repository_url 精确匹配查询已有记录。
            - 如果不存在，再按 name + author 组合查询。
            - 存在则更新（upcert），不存在则插入（insert）。
        返回：
            True 表示新增，False 表示更新。
        """
        # 查询已存在的记录
        existing = None

        if item.repository_url:
            result = await session.execute(
                select(MCPMarketplace).where(MCPMarketplace.repository_url == item.repository_url).limit(1)
            )
            existing = result.scalar_one_or_none()

        if existing is None and item.name and item.author:
            result = await session.execute(
                select(MCPMarketplace).where(
                    MCPMarketplace.name == item.name,
                    MCPMarketplace.author == item.author,
                ).limit(1)
            )
            existing = result.scalar_one_or_none()

        if existing is None and item.endpoint_url:
            result = await session.execute(
                select(MCPMarketplace).where(MCPMarketplace.endpoint_url == item.endpoint_url).limit(1)
            )
            existing = result.scalar_one_or_none()

        now = datetime.now(timezone.utc)

        # 注意：官方 Registry 仅返回 Server 目录信息，不包含工具能力（tools/list）、
        # 健康详情（health_detail）和安全标记（security_flags）。
        # 这些字段需要通过连接每个 Server 的 remotes URL 动态获取
        # （MCP Protocol tools/list 等 RPC 调用），采集阶段不填充。
        # 参见：https://modelcontextprotocol.io/registry/about

        if existing:
            # 更新已有记录（保留 install_count 等动态字段不被覆盖）
            existing.display_name = item.display_name
            existing.description = item.description or existing.description
            existing.author = item.author or existing.author
            existing.repository_url = item.repository_url or existing.repository_url
            existing.homepage_url = item.homepage_url or existing.homepage_url
            existing.endpoint_url = item.endpoint_url or existing.endpoint_url
            existing.license = item.license or existing.license
            existing.category = item.category if item.category != "uncategorized" else existing.category
            existing.tags = item.tags if item.tags else existing.tags
            existing.original_data = item.original_data if item.original_data else existing.original_data
            existing.updated_at = now
            return False
        else:
            # 插入新记录
            new_item = MCPMarketplace(
                id=generate_string_id(),
                name=item.name,
                display_name=item.display_name,
                description=item.description,
                author=item.author,
                repository_url=item.repository_url,
                homepage_url=item.homepage_url,
                endpoint_url=item.endpoint_url,
                license=item.license,
                category=item.category,
                tags=item.tags,
                source=item.source,
                original_data=item.original_data,
                created_at=now,
                updated_at=now,
            )
            session.add(new_item)
            return True

    async def _log_discovery(
        self,
        session: AsyncSession,
        action: str,
        total_items: int,
        inserted_count: int,
        updated_count: int,
    ) -> None:
        """记录采集审计日志到 mcp_marketplace_discovery_log 表。

        参数：
            session: 数据库会话
            action: 操作类型（如 full_discovery）
            total_items: 本次采集标准化后总条目数
            inserted_count: 新增条目数
            updated_count: 更新条目数
        """
        log_entry = MCPMarketplaceDiscoveryLog(
            id=generate_string_id(),
            source="discovery_scheduler",
            action=action,
            item_name=f"total={total_items}_inserted={inserted_count}_updated={updated_count}",
            item_url="",
            status="success",
            detail=f"采集完成: 共 {total_items} 条, 新增 {inserted_count} 条, 更新 {updated_count} 条",
        )
        session.add(log_entry)
