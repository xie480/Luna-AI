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
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol

from app.logger import logger
from app.prompt.types import (
    PG_ONLY_PROMPT_CATEGORIES,
    PLACEHOLDER_MEMORY,
    PLACEHOLDER_RUNTIME,
    PLACEHOLDER_SYSTEM,
    PromptCategory,
)
from app.repository.models import PromptTemplate, PromptVersion
from app.repository.prompt_pg import PromptPGRepo
from app.utils.snowflake import generate_string_id


@dataclass(frozen=True)
class PromptPayload:
    """
    三槽位 Prompt 渲染载荷。

    做什么：承载从 PostgreSQL active 版本渲染后的 system、memory、runtime 三段内容。
    为什么这样做：RAG 证据评估等业务需要分别按 system message 注入三槽位，而不是拼接成单个字符串。
    输入输出：由 Manager.render_prompt 返回，调用方读取三个字符串字段。
    边界条件：某个槽位缺失时对应字段为空字符串。
    异常行为：该数据类不抛异常，加载失败由 Manager 或 CacheManager 抛出。
    """

    system: str = ""
    memory: str = ""
    runtime: str = ""


class PromptCache(Protocol):
    """定义 Prompt 缓存接口。"""

    async def get_or_load(self, category: PromptCategory) -> Any:
        """
        获取未渲染的三槽位 Prompt 缓存。

        做什么：供 Manager.render_prompt 从 PG/Redis 读取三槽位内容。
        为什么这样做：部分业务需要保留槽位边界，而不是只获取拼接后的完整 Prompt。
        输入输出：输入 PromptCategory，输出包含 system_content/memory_content/runtime_content 的对象。
        边界条件：PG-only 分类缺失时由具体实现抛错。
        异常行为：缓存或数据库异常向上抛出。
        """
        ...

    async def get_assembled_prompt(self, category: PromptCategory, variables: Dict[str, Any]) -> str:
        ...

    async def invalidate_cache(self, category: PromptCategory) -> None:
        ...


class Manager:
    """负责 Prompt 模板与版本的管理"""

    def __init__(self, repo: PromptPGRepo, cache_mgr: Optional[PromptCache] = None):
        self.repo = repo
        self.cache_mgr = cache_mgr

    async def assemble_prompt(self, category: PromptCategory, variables: Dict[str, Any]) -> str:
        """
        根据业务分类组装完整的 Prompt 字符串。

        做什么：从 PromptCache 加载 PostgreSQL active Prompt 版本，并渲染为完整文本。
        为什么这样做：业务 Prompt 组装必须通过 Python 控制面和 PG 版本管理，不允许业务代码直接读本地文件。
        输入输出：输入 PromptCategory 与变量字典，输出完整 Prompt 文本。
        边界条件：没有缓存管理器时返回最小兜底 Prompt；PG-only 分类缺失时由缓存层抛错后进入兜底。
        异常行为：缓存/数据库异常记录 warning，并返回最小兜底 Prompt 保持主链路可解释。
        """
        prompt_str = ""
        if self.cache_mgr:
            try:
                prompt_str = await self.cache_mgr.get_assembled_prompt(category, variables)
            except Exception as e:
                logger.warning(f"获取组装 Prompt 失败 category={category.value} error={e}")
                if category in PG_ONLY_PROMPT_CATEGORIES:
                    raise RuntimeError(f"PG-only Prompt 组装失败 category={category.value} error={e}") from e
                return self._build_minimal_prompt(variables)
        else:
            # 如果没有缓存管理器，普通聊天类 Prompt 返回兜底文本；PG-only 业务 Prompt 必须失败，避免绕过 PostgreSQL 版本管理。
            if category in PG_ONLY_PROMPT_CATEGORIES:
                raise RuntimeError(f"Prompt 缓存管理器不可用，无法从 PostgreSQL 组装 category={category.value}")
            return self._build_minimal_prompt(variables)

        # 清理剩余未被注入的占位符
        prompt_str = prompt_str.replace(PLACEHOLDER_SYSTEM, "")
        prompt_str = prompt_str.replace(PLACEHOLDER_MEMORY, "")
        prompt_str = prompt_str.replace(PLACEHOLDER_RUNTIME, "")

        # 去除多余空行（清理因占位符移除而产生的连续空行）
        prompt_str = self._clean_empty_lines(prompt_str)

        logger.info(f"组装 Prompt 成功 category={category.value} prompt_length={len(prompt_str)}")
        return prompt_str

    async def render_prompt(self, category: PromptCategory, variables: Dict[str, Any]) -> PromptPayload:
        """
        按三槽位分别渲染 Prompt。

        做什么：读取缓存中的三槽位原始模板，并分别替换变量后返回 PromptPayload。
        为什么这样做：Evidence Evaluator 需要把 system、memory、runtime 分别作为 message 注入模型。
        输入输出：输入 PromptCategory 和变量字典，输出 PromptPayload。
        边界条件：必须存在 cache_mgr；没有 cache_mgr 说明 PG Prompt 管理未初始化，直接抛错。
        异常行为：PG-only 分类缺失、数据库异常或模板加载失败会抛 RuntimeError 给业务层降级处理。
        """
        if not self.cache_mgr:
            raise RuntimeError("Prompt 缓存管理器不可用，无法按槽位渲染 Prompt")
        try:
            from app.prompt.types import render_template

            cached_prompt = await self.cache_mgr.get_or_load(category)
            payload = PromptPayload(
                system=render_template(cached_prompt.system_content, variables),
                memory=render_template(cached_prompt.memory_content, variables),
                runtime=render_template(cached_prompt.runtime_content, variables),
            )
            logger.info(
                f"按槽位渲染 Prompt 成功 category={category.value} "
                f"system_length={len(payload.system)} memory_length={len(payload.memory)} runtime_length={len(payload.runtime)}"
            )
            return payload
        except Exception as e:
            raise RuntimeError(f"按槽位渲染 Prompt 失败 category={category.value} error={e}") from e

    def _build_minimal_prompt(self, variables: Dict[str, Any]) -> str:
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

    async def delete_unused_version(self, template_id: str, version_id: str) -> None:
        """
        删除未在使用中的 Prompt 旧版本。

        做什么：物理删除指定模板下未被 active_version_id 引用、且不是 published 状态的版本。
        为什么这样做：历史版本会随着 Prompt 调整持续累积，允许用户清理未使用旧版本，同时保护当前生效版本不被误删。
        输入输出：输入模板 ID 与版本 ID；成功无返回值。
        边界条件：模板不存在、版本不存在、版本不属于模板、版本正在使用或仍处于 published 状态时拒绝删除。
        异常行为：校验失败抛出 ValueError，由 API 层转成明确错误响应；数据库删除失败向上抛出。
        """
        async def _tx_fn(tx_repo: PromptPGRepo) -> None:
            tmpl = await tx_repo.get_template(template_id)
            if not tmpl:
                raise ValueError(f"模板 {template_id} 不存在")

            version = await tx_repo.get_version(version_id)
            if not version:
                raise ValueError(f"版本 {version_id} 不存在")

            if version.template_id != template_id:
                raise ValueError(f"版本 {version_id} 不属于模板 {template_id}")

            if tmpl.active_version_id == version_id:
                raise ValueError("不能删除当前正在使用的 Prompt 版本")

            if version.status == "published":
                raise ValueError("不能删除仍处于 published 状态的 Prompt 版本")

            await tx_repo.delete_version(version_id)
            logger.info(f"删除未使用 Prompt 版本成功 template_id={template_id} version_id={version_id} status={version.status}")

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
