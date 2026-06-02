"""
Luna AI Prompt 管理器模块

做什么：负责 Prompt 模板与版本的管理。
为什么这样做：与 Go 版本的 manager.go 保持一致，提供组装 Prompt、管理模板和版本的功能。
输入输出：
    - Manager: Prompt 管理器类
边界条件：
    - 组装 Prompt 时，即使 db 和 redis 都不可用也返回一个基本提示文本
    - 清理连续多余的空行
异常行为：
    - 数据库操作失败时抛出异常
"""

import json
from typing import Dict, List, Optional, Protocol

from app.logger import logger
from app.prompt.types import (
    PLACEHOLDER_MEMORY,
    PLACEHOLDER_RUNTIME,
    PLACEHOLDER_SYSTEM,
    PromptCategory,
)
from app.repository.models import PromptTemplate, PromptVersion
from app.repository.prompt_pg import PromptPGRepo
from app.utils.snowflake import generate_string_id


class PromptCache(Protocol):
    """定义 Prompt 缓存接口"""
    async def get_assembled_prompt(self, category: PromptCategory, variables: Dict[str, str]) -> str:
        ...

    async def invalidate_cache(self, category: PromptCategory) -> None:
        ...


class Manager:
    """负责 Prompt 模板与版本的管理"""

    def __init__(self, repo: PromptPGRepo, cache_mgr: Optional[PromptCache] = None):
        self.repo = repo
        self.cache_mgr = cache_mgr

    async def assemble_prompt(self, category: PromptCategory, variables: Dict[str, str]) -> str:
        """
        根据业务分类组装完整的 Prompt 字符串
        """
        prompt_str = ""
        if self.cache_mgr:
            try:
                prompt_str = await self.cache_mgr.get_assembled_prompt(category, variables)
            except Exception as e:
                logger.warning(f"获取组装 Prompt 失败 category={category.value} error={e}")
                return self._build_minimal_prompt(variables)
        else:
            # 如果没有缓存管理器，直接返回兜底文本
            return self._build_minimal_prompt(variables)

        # 清理剩余未被注入的占位符
        prompt_str = prompt_str.replace(PLACEHOLDER_SYSTEM, "")
        prompt_str = prompt_str.replace(PLACEHOLDER_MEMORY, "")
        prompt_str = prompt_str.replace(PLACEHOLDER_RUNTIME, "")

        # 去除多余空行（清理因占位符移除而产生的连续空行）
        prompt_str = self._clean_empty_lines(prompt_str)

        logger.info(f"组装 Prompt 成功 category={category.value} prompt_length={len(prompt_str)}")
        return prompt_str

    def _build_minimal_prompt(self, variables: Dict[str, str]) -> str:
        """构建最基本的安全兜底提示文本"""
        parts = [
            "你是一个 AI 助手。\n\n",
            "当前时间：",
            variables.get("CURRENT_TIME", ""),
            "\n\n用户输入：",
            variables.get("CURRENT_MESSAGE", "")
        ]
        return "".join(parts)

    def _clean_empty_lines(self, input_str: str) -> str:
        """清理连续多余的空行（3行以上压缩为2行）"""
        while "\n\n\n" in input_str:
            input_str = input_str.replace("\n\n\n", "\n\n")
        return input_str.strip()

    async def list_templates(self) -> List[PromptTemplate]:
        """获取所有模板列表"""
        return await self.repo.list_templates()

    async def get_versions(self, template_id: str) -> List[PromptVersion]:
        """获取指定模板的所有版本"""
        return await self.repo.get_versions_by_template(template_id)

    async def create_template(self, name: str, category: str, slot_position: str, is_system: bool) -> PromptTemplate:
        """创建新的 Prompt 模板"""
        tmpl = PromptTemplate(
            id=generate_string_id(),
            name=name,
            category=category,
            slot_position=slot_position,
            is_system=is_system,
        )

        await self.repo.create_template(tmpl)
        logger.info(f"创建 Prompt 模板成功 template_id={tmpl.id} name={name}")
        return tmpl

    async def create_version(self, template_id: str, content: str, variables: str) -> PromptVersion:
        """为指定模板创建新版本"""
        # 获取当前最大版本号
        versions = await self.repo.get_versions_by_template(template_id)
        
        next_version_num = 1
        if versions:
            next_version_num = versions[0].version_num + 1

        # 确保 variables 是有效的 JSON 数组字符串
        if not variables:
            variables = "[]"
        elif not variables.startswith("["):
            # 如果前端传过来的是逗号分隔的字符串，转换为 JSON 数组
            vars_list = [v.strip() for v in variables.split(",")]
            variables = json.dumps(vars_list)

        version = PromptVersion(
            id=generate_string_id(),
            template_id=template_id,
            version_num=next_version_num,
            content=content,
            variables=json.loads(variables), # SQLAlchemy JSONB expects Python object
            status="draft",
        )

        await self.repo.create_version(version)
        logger.info(f"创建 Prompt 版本成功 version_id={version.id} template_id={template_id}")
        return version

    async def publish_version(self, template_id: str, version_id: str) -> None:
        """
        发布版本（将其设为模板的 active_version_id）
        发布成功后自动使对应的 Redis 缓存失效
        """
        async def _tx_fn(tx_repo: PromptPGRepo) -> None:
            tmpl = await tx_repo.get_template(template_id)
            if not tmpl:
                raise ValueError(f"模板 {template_id} 不存在")

            # 验证版本是否存在
            version = await tx_repo.get_version(version_id)
            if not version:
                raise ValueError(f"版本 {version_id} 不存在")

            if version.template_id != template_id:
                raise ValueError(f"版本 {version_id} 不属于模板 {template_id}")

            # 将之前处于 published 状态的版本更新为 deprecated
            versions = await tx_repo.get_versions_by_template(template_id)
            for v in versions:
                if v.status == "published" and v.id != version_id:
                    v.status = "deprecated"
                    await tx_repo.update_version(v)

            # 更新当前版本状态为 published
            version.status = "published"
            await tx_repo.update_version(version)

            # 更新模板的 active_version_id
            tmpl.active_version_id = version_id
            await tx_repo.update_template(tmpl)

            logger.info(f"发布 Prompt 版本成功 template_id={template_id} version_id={version_id}")

            # 版本发布后自动使缓存失效
            if self.cache_mgr:
                try:
                    await self.cache_mgr.invalidate_cache(PromptCategory(tmpl.category))
                except Exception as cache_err:
                    logger.warning(f"清除 Prompt 缓存失败 category={tmpl.category} error={cache_err}")

        await self.repo.run_in_transaction(_tx_fn)

    async def rollback_version(self, template_id: str, target_version_id: str) -> None:
        """
        回滚版本
        物理删除当前处于 published 状态的最新版本，并将目标回滚版本的状态从 deprecated 恢复为 published
        """
        async def _tx_fn(tx_repo: PromptPGRepo) -> None:
            tmpl = await tx_repo.get_template(template_id)
            if not tmpl:
                raise ValueError(f"模板 {template_id} 不存在")

            # 验证目标回滚版本是否存在
            target_version = await tx_repo.get_version(target_version_id)
            if not target_version:
                raise ValueError(f"版本 {target_version_id} 不存在")

            if target_version.template_id != template_id:
                raise ValueError(f"版本 {target_version_id} 不属于模板 {template_id}")

            if target_version.status != "deprecated":
                raise ValueError(f"只能回滚到已废弃(deprecated)的版本，当前状态: {target_version.status}")

            # 查找当前处于 published 状态的版本
            current_published_version = None
            versions = await tx_repo.get_versions_by_template(template_id)
            for v in versions:
                if v.status == "published":
                    current_published_version = v
                    break

            if not current_published_version:
                raise ValueError("未找到当前已发布的版本")

            # 物理删除当前已发布的版本
            await tx_repo.delete_version(current_published_version.id)

            # 将目标回滚版本状态更新为 published
            target_version.status = "published"
            await tx_repo.update_version(target_version)

            # 更新模板的 active_version_id
            tmpl.active_version_id = target_version_id
            await tx_repo.update_template(tmpl)

            logger.info(f"回滚 Prompt 版本成功 template_id={template_id} target_version_id={target_version_id} deleted_version_id={current_published_version.id}")

            # 版本回滚后自动使缓存失效
            if self.cache_mgr:
                try:
                    await self.cache_mgr.invalidate_cache(PromptCategory(tmpl.category))
                except Exception as cache_err:
                    logger.warning(f"清除 Prompt 缓存失败 category={tmpl.category} error={cache_err}")

        await self.repo.run_in_transaction(_tx_fn)
