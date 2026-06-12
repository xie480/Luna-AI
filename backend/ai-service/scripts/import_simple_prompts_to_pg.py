"""
Luna AI MCP Prompt 入库脚本 — 仅导入 skill_execution_summary 分类。

做什么：将 app/prompt/simple/skill_execution_summary 目录下的 system、memory、runtime
        三槽位 Prompt 写入 PostgreSQL 的 prompt_templates / prompt_versions 表。
为什么这样做：skill_execution_summary 是 v3.1 新增的 Prompt 分类，需要单独入库一次。
输入输出：读取本地 .j2 模板文件，向 PostgreSQL 写入模板元数据与已发布版本；脚本无业务返回值。
边界条件：
    - 缺失任一槽位文件会直接抛错，避免只入库部分 Prompt 造成运行期行为不一致。
    - 已存在且内容一致的模板会跳过，保证重复运行幂等。
    - 已存在但内容不同的模板会创建新的 published 版本，并将旧 published 版本标记为 deprecated。
异常行为：数据库连接、文件读取、JSONB 写入失败时回滚事务并抛出明确异常。
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

# simple Prompt 根目录固定在 app/prompt/simple，禁止从运行目录拼接，避免 Windows / PowerShell 下路径漂移。
SIMPLE_PROMPT_ROOT = AI_SERVICE_ROOT / "app" / "prompt" / "simple"

# 需要入库的分类 — 仅 skill_execution_summary。
CATEGORY = "skill_execution_summary"
CATEGORY_DIR = SIMPLE_PROMPT_ROOT / CATEGORY

# Prompt 三槽位按固定顺序处理。
SLOTS_TO_PROCESS: list[dict[str, str | list[str]]] = [
    {"slot": SlotPosition.SYSTEM, "vars": [], "name": f"{CATEGORY}_system"},
    {"slot": SlotPosition.MEMORY, "vars": ["ALL_ROUND_EXECUTION_RESULTS"], "name": f"{CATEGORY}_memory"},
    {"slot": SlotPosition.RUNTIME, "vars": [], "name": f"{CATEGORY}_runtime"},
]

# 提取 Jinja 风格变量名正则。
VARIABLE_PATTERN = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")

# 版本状态常量。
VERSION_STATUS_PUBLISHED = "published"
VERSION_STATUS_DEPRECATED = "deprecated"


async def main() -> None:
    """主入口：连接数据库，导入 skill_execution_summary 三槽位。"""
    logger.info(f"开始导入 {CATEGORY} Prompt 模板到 PostgreSQL...")

    if not CATEGORY_DIR.exists():
        logger.error(f"分类目录不存在: {CATEGORY_DIR}")
        return

    pg_client = PostgresClient(settings.postgres_conn_str)

    async for session in pg_client.get_session():
        try:
            for slot_info in SLOTS_TO_PROCESS:
                slot: SlotPosition = slot_info["slot"]  # type: ignore
                declared_vars: list[str] = slot_info["vars"]  # type: ignore
                name: str = slot_info["name"]  # type: ignore

                # 读取 .j2 文件
                file_path = CATEGORY_DIR / f"{slot.value}.j2"
                if not file_path.exists():
                    raise FileNotFoundError(
                        f"分类 '{CATEGORY}' 缺少 {slot.value}.j2 槽位文件，"
                        f"期望路径: {file_path}"
                    )
                content = file_path.read_text(encoding="utf-8").strip()

                # 提取变量（优先使用声明的变量列表，若为空则从文件提取）
                effective_vars = declared_vars if declared_vars else VARIABLE_PATTERN.findall(content)

                # 查找已有模板
                stmt = select(PromptTemplate).where(
                    PromptTemplate.category == CATEGORY,
                    PromptTemplate.slot_position == slot.value,
                )
                result = await session.execute(stmt)
                existing_template: PromptTemplate | None = result.scalar_one_or_none()

                if existing_template is None:
                    # 创建新模板
                    tmpl = PromptTemplate(
                        id=generate_string_id(),
                        name=name,
                        category=CATEGORY,
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
                        f"创建新模板与版本: category={CATEGORY} slot={slot.value} "
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
                            f"模板内容一致，跳过: category={CATEGORY} slot={slot.value} "
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
                        f"创建新版本: category={CATEGORY} slot={slot.value} "
                        f"version_num={next_ver_num} version_id={new_version.id}"
                    )

            await session.commit()
            logger.info(f"{CATEGORY} Prompt 导入完成。")

        except Exception as exc:
            logger.error(f"导入过程中发生异常: {exc}")
            await session.rollback()
            raise
        finally:
            await pg_client.close()


if __name__ == "__main__":
    asyncio.run(main())
