"""
Luna AI 提示词模板模块（基础问答版）

做什么：通过 TemplateManager 从 templates/prompt/ 目录加载 .j2 模板文件。
        仅保留基础问答所需的 system 和 runtime 两个模板。
为什么这样做：遵循 agent.md 中禁止硬编码魔法字符串的规范，将提示词内容外置于 .j2 文件。
"""

from typing import Optional

from app.templates.template_manager import TemplateManager, get_template_manager

# ============================================================
# 模板名称常量
# ============================================================

# 系统层提示词模板（定义 Luna 的人格设定和行为约束）
TEMPLATE_SYSTEM: str = "system"
# 运行时上下文模板（注入当前用户输入和对话历史）
TEMPLATE_RUNTIME: str = "runtime"

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
# 运行时上下文提示词
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
    return _get_tm().render(
        TEMPLATE_RUNTIME,
        CURRENT_MESSAGE=current_message,
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
