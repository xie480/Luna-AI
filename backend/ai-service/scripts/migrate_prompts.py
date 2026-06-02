"""
Luna AI 提示词迁移脚本

做什么：将旧版的提示词迁移到新的数据库结构中。
为什么这样做：作为运维工具，用于初始化或升级数据库中的提示词模板。
"""

import asyncio
import json
import os
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import settings
from app.infrastructure.postgres import PostgresClient
from app.logger import logger
from app.prompt.types import SlotPosition
from app.repository.models import PromptTemplate, PromptVersion
from app.utils.snowflake import generate_string_id

# 提示词文件目录
PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "runtime" / "internal" / "prompt" / "simple"


class MigrateGroup:
    def __init__(self, name: str, category: str, slot: str, vars: list[str], purpose: str):
        self.name = name
        self.category = category
        self.slot = slot
        self.vars = vars
        self.purpose = purpose


async def main():
    logger.info("开始迁移提示词...")

    # 初始化 PostgreSQL 连接
    pg_client = PostgresClient(settings.postgres_conn_str)

    # Input Reconstruction 模板拆分为三条 slot 记录，category 为 input_reconstruction
    input_reconstruction_groups = [
        MigrateGroup(
            name="input_reconstruction_system",
            category="input_reconstruction",
            slot=SlotPosition.SYSTEM.value,
            vars=[],
            purpose="输入重构场景 - 系统设定",
        ),
        MigrateGroup(
            name="input_reconstruction_memory",
            category="input_reconstruction",
            slot=SlotPosition.MEMORY.value,
            vars=["CORE_SUMMARY", "KEY_FACTS", "MEMORY_SNIPPETS"],
            purpose="输入重构场景 - 记忆上下文",
        ),
        MigrateGroup(
            name="input_reconstruction_runtime",
            category="input_reconstruction",
            slot=SlotPosition.RUNTIME.value,
            vars=["USER_INPUT", "PRIMARY_INTENTS", "CATEGORIES", "DAG_ROUTE_HINTS", "RETRIEVAL_TYPES"],
            purpose="输入重构场景 - 运行时上下文",
        ),
    ]

    async for session in pg_client.get_session():
        try:
            # 先删除旧的 input_reconstruction 模板数据
            # 1. 查找要删除的模板 ID
            from sqlalchemy import select
            stmt = select(PromptTemplate.id).where(PromptTemplate.category == 'input_reconstruction')
            result = await session.execute(stmt)
            template_ids = result.scalars().all()

            if template_ids:
                # 2. 删除对应的版本
                await session.execute(delete(PromptVersion).where(PromptVersion.template_id.in_(template_ids)))
                # 3. 删除模板
                await session.execute(delete(PromptTemplate).where(PromptTemplate.id.in_(template_ids)))
                await session.commit()

            # 插入三条新的 input_reconstruction slot 模板
            for sg in input_reconstruction_groups:
                vars_json = json.dumps(sg.vars)

                # 从 simple 目录读取
                file_path = PROMPTS_DIR / "input_reconstruction" / f"{sg.slot}.j2"
                if not file_path.exists():
                    logger.error(f"读取提示词文件失败: {file_path} 不存在")
                    continue

                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()

                tmpl_id = generate_string_id()
                tmpl = PromptTemplate(
                    id=tmpl_id,
                    name=sg.name,
                    category=sg.category,
                    slot_position=sg.slot,
                    is_system=True,
                )
                session.add(tmpl)
                await session.flush() # 获取 ID

                # Create version
                version_id = generate_string_id()
                version = PromptVersion(
                    id=version_id,
                    template_id=tmpl.id,
                    version_num=1,
                    content=content,
                    variables=json.loads(vars_json),
                    status="published",
                )
                session.add(version)
                await session.flush()

                # Update active version
                tmpl.active_version_id = version.id
                await session.commit()

                logger.info(f"已迁移 {sg.name} (category={sg.category}, slot={sg.slot})")

        except Exception as e:
            logger.error(f"迁移失败: {e}")
            await session.rollback()
        finally:
            await pg_client.close()

    logger.info("迁移完成。")


if __name__ == "__main__":
    asyncio.run(main())
