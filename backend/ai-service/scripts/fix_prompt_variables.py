"""
Luna AI 修复 PromptVersion 变量元数据脚本。

做什么：扫描 PostgreSQL 数据库中 `prompt_versions` 表的所有记录，
        使用正则从 `content` 中提取实际使用的 Jinja 风格变量（例如 {{ VAR_NAME }}），
        然后与 `variables` 字段（JSONB）进行对比。如果不一致，则更新 `variables` 字段。
为什么这样做：在开发过程中或者由于各种原因（例如在 UI 面板上修改了内容但未修改变量配置，
             或者入库脚本配置有误），可能导致实际内容里的变量与记录在案的变量元数据不一致。
             这可能导致渲染时遗漏参数或者 UI 提示不准确，因此需要此脚本对齐数据。
"""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# ai-service 根目录需要显式加入 sys.path
AI_SERVICE_ROOT = Path(__file__).resolve().parent.parent
if str(AI_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(AI_SERVICE_ROOT))

from app.config.settings import settings
from app.infrastructure.postgres import PostgresClient
from app.logger import logger
from app.repository.models import PromptVersion

# 提取 Jinja 风格变量名，如 {{ CORE_SUMMARY }}
VARIABLE_PATTERN = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


async def sync_variables_in_versions(session: AsyncSession) -> tuple[int, int]:
    """同步所有版本的变量。返回 (扫描总数, 更新数)。"""
    stmt = select(PromptVersion)
    result = await session.execute(stmt)
    versions = result.scalars().all()
    
    total_count = len(versions)
    updated_count = 0
    
    for version in versions:
        # 1. 从内容中提取变量并去重，同时保持稳定顺序（首次出现的顺序）
        extracted_vars_raw = VARIABLE_PATTERN.findall(version.content or "")
        extracted_vars = []
        seen = set()
        for v in extracted_vars_raw:
            if v not in seen:
                seen.add(v)
                extracted_vars.append(v)
        
        # 2. 读取数据库中当前的变量列表
        current_vars = version.variables or []
        if not isinstance(current_vars, list):
             current_vars = []
             
        # 3. 对比：只有在两者完全不一致（不考虑顺序的话用 set 对比，但最好保持完全一致）
        # 为了严谨，只要元素集合不同，或者有缺失，就用新提取的覆盖
        if set(extracted_vars) != set(current_vars):
            logger.info(
                f"发现不匹配 [ID: {version.id}, Template: {version.template_id}, Ver: {version.version_num}]\n"
                f"  当前记录: {current_vars}\n"
                f"  实际提取: {extracted_vars}"
            )
            version.variables = extracted_vars
            updated_count += 1
            
    if updated_count > 0:
        await session.commit()
        
    return total_count, updated_count


async def main() -> None:
    logger.info("开始核对 PromptVersion 中的 variables 数据...")
    pg_client = PostgresClient(settings.postgres_conn_str)

    async for session in pg_client.get_session():
        try:
            total, updated = await sync_variables_in_versions(session)
            logger.info(f"核对完成！共扫描 {total} 条记录，修复并更新了 {updated} 条记录。")
        except Exception as exc:
            logger.error(f"修复过程中发生异常: {exc}")
            await session.rollback()
            raise
        finally:
            await pg_client.close()

if __name__ == "__main__":
    asyncio.run(main())
