"""
Luna AI MCP Prompt 全量入库脚本。

做什么：遍历 app/prompt/simple 目录下的所有子目录（分类），将 system、memory、runtime
        三槽位 Prompt 写入 PostgreSQL 的 prompt_templates / prompt_versions 表。
为什么这样做：批量将本地模板文件更新/导入到 PG 数据库，使新增加的变量（如 CURRENT_TIME）生效。
"""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# ai-service 根目录需要显式加入 sys.path，保证无论从仓库根目录还是 ai-service 目录运行脚本，均可导入 app 包。
AI_SERVICE_ROOT = Path(__file__).resolve().parent.parent
if str(AI_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(AI_SERVICE_ROOT))

from app.config.settings import settings
from app.infrastructure.postgres import PostgresClient
from app.logger import logger
from app.prompt.types import SlotPosition
from app.repository.models import PromptTemplate, PromptVersion
from app.utils.snowflake import generate_string_id

# simple Prompt 根目录固定在 app/prompt/simple
SIMPLE_PROMPT_ROOT = AI_SERVICE_ROOT / "app" / "prompt" / "simple"

# 提取 Jinja 风格变量名正则。
VARIABLE_PATTERN = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*(?:\|[^}]*)?\}\}")

# 版本状态常量。
VERSION_STATUS_PUBLISHED = "published"
VERSION_STATUS_DEPRECATED = "deprecated"


async def main() -> None:
    """主入口：连接数据库，导入所有分类的三槽位。"""
    logger.info(f"开始扫描并导入 {SIMPLE_PROMPT_ROOT} 下的 Prompt 模板到 PostgreSQL...")

    if not SIMPLE_PROMPT_ROOT.exists():
        logger.error(f"Prompt 根目录不存在: {SIMPLE_PROMPT_ROOT}")
        return

    pg_client = PostgresClient(settings.postgres_conn_str)
    # 记录本次有内容变更的分类，用于后续失效 Redis 缓存
    changed_categories: set[str] = set()
    # 记录本次处理过的所有分类（含内容未变更的），用于确保 Redis 缓存一致性
    processed_categories: set[str] = set()

    async for session in pg_client.get_session():
        try:
            for category_path in SIMPLE_PROMPT_ROOT.iterdir():
                if not category_path.is_dir():
                    continue
                
                category = category_path.name
                
                for slot in [SlotPosition.SYSTEM, SlotPosition.MEMORY, SlotPosition.RUNTIME]:
                    name = f"{category}_{slot.value}"
                    file_path = category_path / f"{slot.value}.j2"
                    
                    if not file_path.exists():
                        continue
                        
                    content = file_path.read_text(encoding="utf-8").strip()
                    
                    # 提取变量并去重
                    effective_vars = list(set(VARIABLE_PATTERN.findall(content)))

                    # 查找已有模板
                    stmt = select(PromptTemplate).where(
                        PromptTemplate.category == category,
                        PromptTemplate.slot_position == slot.value,
                    )
                    result = await session.execute(stmt)
                    existing_template: PromptTemplate | None = result.scalar_one_or_none()

                    if existing_template is None:
                        # 创建新模板
                        tmpl = PromptTemplate(
                            id=generate_string_id(),
                            name=name,
                            category=category,
                            slot_position=slot.value,
                            is_system=True,
                        )
                        session.add(tmpl)
                        await session.flush()

                        version = PromptVersion(
                            id=generate_string_id(),
                            template_id=tmpl.id,
                            version_num=1,
                            content=content,
                            variables=effective_vars,
                            status=VERSION_STATUS_PUBLISHED,
                        )
                        session.add(version)
                        await session.flush()
                        tmpl.active_version_id = version.id
                        changed_categories.add(category)

                        logger.info(
                            f"创建新模板与版本: category={category} slot={slot.value} "
                            f"template_id={tmpl.id} version_id={version.id}"
                        )
                    else:
                        # 查找当前活跃版本
                        active_version: PromptVersion | None = None
                        if existing_template.active_version_id:
                            stmt_ver = select(PromptVersion).where(
                                PromptVersion.id == existing_template.active_version_id
                            )
                            result_ver = await session.execute(stmt_ver)
                            active_version = result_ver.scalar_one_or_none()

                        if active_version and active_version.content == content:
                            logger.info(
                                f"模板内容一致，跳过: category={category} slot={slot.value} "
                                f"template_id={existing_template.id}"
                            )
                            processed_categories.add(category)
                            continue

                        # 废弃旧版本
                        if active_version:
                            active_version.status = VERSION_STATUS_DEPRECATED
                            logger.info(
                                f"废弃旧版本: template_id={existing_template.id} "
                                f"version_id={active_version.id}"
                            )

                        # 找最大版本号
                        stmt_max = select(PromptVersion).where(
                            PromptVersion.template_id == existing_template.id
                        ).order_by(PromptVersion.version_num.desc()).limit(1)
                        result_max = await session.execute(stmt_max)
                        max_ver = result_max.scalar_one_or_none()
                        next_ver_num = (max_ver.version_num + 1) if max_ver else 1

                        new_version = PromptVersion(
                            id=generate_string_id(),
                            template_id=existing_template.id,
                            version_num=next_ver_num,
                            content=content,
                            variables=effective_vars,
                            status=VERSION_STATUS_PUBLISHED,
                        )
                        session.add(new_version)
                        await session.flush()
                        existing_template.active_version_id = new_version.id
                        changed_categories.add(category)

                        logger.info(
                            f"创建新版本: category={category} slot={slot.value} "
                            f"version_num={next_ver_num} version_id={new_version.id}"
                        )

            await session.commit()
            logger.info("所有 Prompt 同步到数据库完成。")

            # ================================================================
            # 失效 Redis 缓存：对所有处理过的分类强制清除 Redis 缓存，
            # 确保 CacheManager 下次 get_or_load 从 PG 重新加载最新版本。
            # 为什么这样做：chat 等分类不在 PG_ONLY_PROMPT_CATEGORIES 中，
            # CacheManager 会优先从 Redis 读取缓存（TTL 1 小时）。
            # 即使 PG 与本地文件内容一致，Redis 中也可能存有更早版本的缓存。
            # 强制清除所有分类的缓存，避免旧模板（如不含 TTS_LANGUAGE 条件分支的 runtime.j2）持续被命中。
            # ================================================================
            all_categories = changed_categories | processed_categories
            if all_categories:
                await _invalidate_redis_caches(all_categories)

        except Exception as exc:
            logger.error(f"导入过程中发生异常: {exc}")
            await session.rollback()
            raise
        finally:
            await pg_client.close()


async def _invalidate_redis_caches(changed_categories: set[str]) -> None:
    """
    失效 Redis 中已变更分类的 Prompt 缓存。

    做什么：遍历 changed_categories 中的所有分类，清除对应的 Redis 缓存键。
    为什么这样做：CacheManager 对非 PG_ONLY_PROMPT_CATEGORIES 的分类使用 Redis
                 作为一级缓存。PG 内容更新后必须同步清除 Redis 缓存，否则旧模板
                 会持续被命中。
    输入：changed_categories 需要失效的 PromptCategory 值集合。
    边界条件：Redis 不可用时静默降级，只记录警告。
    """
    from app.infrastructure.redis import RedisClient
    from app.prompt.types import PromptCategory, PG_ONLY_PROMPT_CATEGORIES

    # Prompt 缓存的 Redis key 前缀，与 app.prompt.cache.CACHE_KEY_PREFIX 保持一致
    CACHE_KEY_PREFIX = "luna:prompt:"

    try:
        redis_client = RedisClient(
            addr=settings.redis_addr,
            password=settings.redis_password,
            db=settings.redis_db,
        )
        raw_client = redis_client.get_client()
        for cat_value in changed_categories:
            # PG_ONLY 分类不使用 Redis 缓存，跳过
            try:
                cat_enum = PromptCategory(cat_value)
                if cat_enum in PG_ONLY_PROMPT_CATEGORIES:
                    continue
            except ValueError:
                pass

            cache_key = f"{CACHE_KEY_PREFIX}{cat_value}"
            await raw_client.delete(cache_key)
            logger.info(f"已失效 Redis Prompt 缓存: category={cat_value} cache_key={cache_key}")

        await redis_client.close()
        logger.info(f"Redis 缓存失效完成，共处理 {len(changed_categories)} 个分类")
    except Exception as e:
        logger.warning(f"Redis 缓存失效失败（非致命错误，下次 get_or_load 将从 PG 重新加载）: {e}")


if __name__ == "__main__":
    asyncio.run(main())
