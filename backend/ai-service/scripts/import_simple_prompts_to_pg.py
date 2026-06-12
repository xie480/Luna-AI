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

# 需要入库的 MCP Prompt 分类。
TARGET_CATEGORIES: tuple[str, ...] = (
    # Phase 12（v3.0）：Skill 三阶段 Agent Prompt
    "mcp_skill_screening",
    "mcp_skill_loading",
    "mcp_skill_execution",
    # Phase 12（v3.0）：MCP 前置判断 Prompt
    "mcp_intent_judge",
    # Phase 12 新增：子 Agent Prompt
    "mcp_resource_extraction",
    "mcp_skill_fallback_extraction",
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
