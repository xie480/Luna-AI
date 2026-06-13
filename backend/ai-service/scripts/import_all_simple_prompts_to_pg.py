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

                        logger.info(
                            f"创建新版本: category={category} slot={slot.value} "
                            f"version_num={next_ver_num} version_id={new_version.id}"
                        )

            await session.commit()
            logger.info("所有 Prompt 同步到数据库完成。")

        except Exception as exc:
            logger.error(f"导入过程中发生异常: {exc}")
            await session.rollback()
            raise
        finally:
            await pg_client.close()


if __name__ == "__main__":
    asyncio.run(main())
