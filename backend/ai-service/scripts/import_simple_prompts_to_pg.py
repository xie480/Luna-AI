"""
Luna AI MCP Prompt 入库脚本。

做什么：将 app/prompt/simple/mcp_intent_alignment、mcp_tool_calling、mcp_tool_screening
三个目录下的 system、memory、runtime 三槽位 Prompt 写入 PostgreSQL。
为什么这样做：MCP 相关 Prompt 需要进入 prompt_templates / prompt_versions 表，便于前端 Prompt 面板管理、版本发布与回滚。
输入输出：读取本地 .j2 模板文件，向 PostgreSQL 写入模板元数据与已发布版本；脚本无业务返回值。
边界条件：
    - 缺失任一槽位文件会直接抛错，避免只入库部分 Prompt 造成运行期行为不一致。
    - 已存在且内容一致的模板会跳过，保证重复运行幂等。
    - 已存在但内容不同的模板会创建新的 published 版本，并将旧 published 版本标记为 deprecated。
异常行为：数据库连接、文件读取、JSONB 写入失败时回滚事务并抛出明确异常。
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

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

# 三个需要入库的 MCP Prompt 分类。
TARGET_CATEGORIES: tuple[str, ...] = (
    "mcp_intent_alignment",
    "mcp_tool_calling",
    "mcp_tool_screening",
)

# Prompt 三槽位按固定顺序处理，便于日志排查与数据库记录一致。
TARGET_SLOTS: tuple[SlotPosition, ...] = (
    SlotPosition.SYSTEM,
    SlotPosition.MEMORY,
    SlotPosition.RUNTIME,
)

# 提取 Jinja 风格变量名，用于写入 prompt_versions.variables JSONB 字段，供前端管理面板展示。
VARIABLE_PATTERN = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")

# 版本状态集中定义，避免脚本中散落魔法字符串。
VERSION_STATUS_PUBLISHED = "published"
VERSION_STATUS_DEPRECATED = "deprecated"


@dataclass(frozen=True)
class PromptSeed:
    """单个 Prompt 槽位的入库描述"""
    name: str
    category: str
    slot_position: str
    file_path: Path
    content: str
    variables: list[str]


def extract_variables(content: str) -> list[str]:
    """从 Prompt 正文提取 Jinja 变量名"""
    variables: list[str] = []
    seen: set[str] = set()
    for match in VARIABLE_PATTERN.finditer(content):
        variable_name = match.group(1)
        if variable_name in seen:
            continue
        seen.add(variable_name)
        variables.append(variable_name)
    return variables


def build_prompt_seed(category: str, slot: SlotPosition) -> PromptSeed:
    """构建单个槽位的 PromptSeed"""
    file_path = SIMPLE_PROMPT_ROOT / category / f"{slot.value}.j2"
    if not file_path.exists():
        raise RuntimeError(f"Prompt 文件不存在 category={category} slot={slot.value} path={file_path}")

    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception as exc:
        raise RuntimeError(f"读取 Prompt 文件失败 category={category} slot={slot.value} path={file_path} error={exc}") from exc

    return PromptSeed(
        name=f"{category}_{slot.value}",
        category=category,
        slot_position=slot.value,
        file_path=file_path,
        content=content,
        variables=extract_variables(content),
    )


def build_all_prompt_seeds(categories: Sequence[str]) -> list[PromptSeed]:
    """构建全部待入库 PromptSeed"""
    seeds: list[PromptSeed] = []
    for category in categories:
        for slot in TARGET_SLOTS:
            seeds.append(build_prompt_seed(category, slot))
    return seeds


async def get_active_version(session: AsyncSession, template: PromptTemplate) -> PromptVersion | None:
    """获取模板当前激活版本"""
    if not template.active_version_id:
        return None
    result = await session.execute(select(PromptVersion).where(PromptVersion.id == template.active_version_id))
    return result.scalars().first()


async def archive_published_versions(session: AsyncSession, template_id: str) -> None:
    """归档同一模板下旧的已发布版本"""
    result = await session.execute(
        select(PromptVersion).where(
            PromptVersion.template_id == template_id,
            PromptVersion.status == VERSION_STATUS_PUBLISHED,
        )
    )
    for version in result.scalars().all():
        version.status = VERSION_STATUS_DEPRECATED
        session.add(version)


async def next_version_num(session: AsyncSession, template_id: str) -> int:
    """计算下一个版本号"""
    result = await session.execute(select(PromptVersion.version_num).where(PromptVersion.template_id == template_id))
    version_nums = [value for value in result.scalars().all() if value is not None]
    if not version_nums:
        return 1
    return max(version_nums) + 1


async def create_published_version(session: AsyncSession, template: PromptTemplate, seed: PromptSeed) -> PromptVersion:
    """为模板创建新的已发布版本"""
    await archive_published_versions(session, template.id)
    version = PromptVersion(
        id=generate_string_id(),
        template_id=template.id,
        version_num=await next_version_num(session, template.id),
        content=seed.content,
        variables=seed.variables,
        status=VERSION_STATUS_PUBLISHED,
    )
    session.add(version)
    await session.flush()

    template.active_version_id = version.id
    session.add(template)
    return version


async def upsert_prompt_seed(session: AsyncSession, seed: PromptSeed, dry_run: bool) -> str:
    """幂等写入单个 PromptSeed"""
    result = await session.execute(select(PromptTemplate).where(PromptTemplate.name == seed.name))
    template = result.scalars().first()

    if template is None:
        if dry_run:
            return "预演创建"
        template = PromptTemplate(
            id=generate_string_id(),
            name=seed.name,
            category=seed.category,
            slot_position=seed.slot_position,
            is_system=True,
        )
        session.add(template)
        await session.flush()
        version = await create_published_version(session, template, seed)
        logger.info(
            f"创建 Prompt 模板成功 template_id={template.id} version_id={version.id} "
            f"name={seed.name} category={seed.category} slot={seed.slot_position}"
        )
        return "已创建"

    metadata_changed = (
        template.category != seed.category
        or template.slot_position != seed.slot_position
        or template.is_system is not True
    )
    active_version = await get_active_version(session, template)
    content_changed = active_version is None or active_version.content != seed.content or active_version.variables != seed.variables

    if not metadata_changed and not content_changed:
        return "已存在且一致，跳过"

    if dry_run:
        if metadata_changed and content_changed:
            return "预演更新元数据并追加版本"
        if metadata_changed:
            return "预演更新元数据"
        return "预演追加版本"

    if metadata_changed:
        old_category = template.category
        old_slot = template.slot_position
        template.category = seed.category
        template.slot_position = seed.slot_position
        template.is_system = True
        session.add(template)
        logger.info(
            f"修正 Prompt 模板元数据 template_id={template.id} name={seed.name} "
            f"old_category={old_category} new_category={seed.category} old_slot={old_slot} new_slot={seed.slot_position}"
        )

    if content_changed:
        version = await create_published_version(session, template, seed)
        logger.info(
            f"追加 Prompt 已发布版本成功 template_id={template.id} version_id={version.id} "
            f"name={seed.name} version_num={version.version_num}"
        )
        return "已追加新版本"

    return "已更新元数据"


async def import_prompts(dry_run: bool) -> None:
    """执行 MCP Prompt 入库流程"""
    seeds = build_all_prompt_seeds(TARGET_CATEGORIES)
    logger.info(f"开始导入 MCP Prompt 到 PostgreSQL dry_run={dry_run} total={len(seeds)}")

    pg_client = PostgresClient(settings.postgres_conn_str)
    try:
        async with pg_client.session_factory() as session:
            try:
                for seed in seeds:
                    action = await upsert_prompt_seed(session, seed, dry_run)
                    logger.info(
                        f"Prompt 入库处理完成 action={action} name={seed.name} "
                        f"category={seed.category} slot={seed.slot_position} variables={seed.variables} path={seed.file_path}"
                    )

                if dry_run:
                    await session.rollback()
                    logger.info("MCP Prompt 入库预演完成，未提交数据库修改")
                else:
                    await session.commit()
                    logger.info("MCP Prompt 入库完成，数据库事务已提交")
            except Exception:
                await session.rollback()
                raise
    finally:
        await pg_client.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="将指定 MCP Prompt 三槽位模板导入 PostgreSQL")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只校验文件与数据库状态，不提交任何数据库修改",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    try:
        await import_prompts(dry_run=args.dry_run)
    except Exception as exc:
        logger.error(f"MCP Prompt 入库失败 error={exc}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
