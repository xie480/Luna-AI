"""
Luna AI 提示词模板模块（基础问答版）

做什么：通过 TemplateManager 从 templates/prompt/ 目录加载 .j2 模板文件。
        仅保留基础问答所需的 system 和 runtime 两个模板。
为什么这样做：遵循 agent.md 中禁止硬编码魔法字符串的规范，将提示词内容外置于 .j2 文件。
"""

from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from app.templates.template_manager import TemplateManager, get_template_manager

# ============================================================
# 模板名称常量
# ============================================================

# 系统层提示词模板（定义 Luna 的人格设定和行为约束）
TEMPLATE_SYSTEM: str = "system"
# 运行时上下文模板（注入当前用户输入和对话历史）
TEMPLATE_RUNTIME: str = "runtime"
# 记忆上下文模板
TEMPLATE_MEMORY: str = "memory"
# 摘要压缩模板
TEMPLATE_SUMMARIZE: str = "summarize"

# ============================================================
# TemplateManager 实例
# ============================================================

_tm: Optional[TemplateManager] = None


def _get_tm() -> TemplateManager:
    """获取 TemplateManager 单例实例"""
    global _tm
    if _tm is None:
        _tm = get_template_manager()
    return _tm


# ============================================================
# 系统层提示词
# ============================================================

def get_system_prompt() -> str:
    """
    获取核心系统提示词

    作用：从 system.j2 模板加载 Luna 的人格设定和行为约束。
    返回：完整的系统提示词字符串；模板加载失败时返回空字符串。
    """
    return _get_tm().render(TEMPLATE_SYSTEM)


# ============================================================
# 记忆上下文提示词
# ============================================================

def render_memory_prompt(
    core_summary: str = "",
    key_facts: str = "",
    memory_snippets: str = "",
) -> str:
    """
    渲染记忆上下文提示词

    作用：将核心摘要、关键事实和记忆片段注入 memory.j2 模板。

    参数：
        core_summary: 核心摘要
        key_facts: 关键事实
        memory_snippets: 记忆片段

    返回：渲染后的记忆提示词字符串。
    """
    return _get_tm().render(
        TEMPLATE_MEMORY,
        CORE_SUMMARY=core_summary or "无",
        KEY_FACTS=key_facts or "无",
        MEMORY_SNIPPETS=memory_snippets or "无",
    )

# ============================================================
# 运行时提示词
# ============================================================
def render_runtime_prompt(
    current_message: str,
) -> str:
    """
    渲染运行时上下文提示词

    作用：将当前用户输入注入 runtime.j2 模板，生成包含思维链要求和输出格式约束的完整提示词。

    参数：
        current_message: 当前用户输入的文本

    返回：渲染后的运行时提示词字符串。
    """
    # 1. 获取当前东八区时间
    tz = ZoneInfo("Asia/Shanghai")
    current_time = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S %A")

    # 2. 渲染运行时上下文
    return _get_tm().render(
        TEMPLATE_RUNTIME,
        CURRENT_MESSAGE=current_message,
        CURRENT_TIME=current_time,
    )


# ============================================================
# 摘要压缩提示词
# ============================================================

def render_summarize_prompt(
    current_core_summary: str,
    current_key_facts: str,
    messages_text: str,
) -> str:
    """
    渲染摘要压缩提示词

    作用：将当前摘要和新对话记录注入 summarize.j2 模板。
    """
    return _get_tm().render(
        TEMPLATE_SUMMARIZE,
        CURRENT_CORE_SUMMARY=current_core_summary,
        CURRENT_KEY_FACTS=current_key_facts,
        MESSAGES_TEXT=messages_text,
    )


# ============================================================
# 辅助函数
# ============================================================

def list_available_templates() -> list[str]:
    """返回所有可用模板名称列表"""
    return _get_tm().list_templates()


def invalidate_template_cache(name: Optional[str] = None) -> None:
    """清除模板缓存"""
    _get_tm().invalidate_cache(name)