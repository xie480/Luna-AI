"""
Luna AI Prompt 类型定义

做什么：定义 Prompt 相关的枚举、常量和辅助函数。
为什么这样做：与 Go 版本的 types.go 保持一致。
"""

from enum import Enum
from typing import Dict


class SlotPosition(str, Enum):
    """定义 Prompt 槽位类型枚举"""
    SYSTEM = "system"
    MEMORY = "memory"
    RUNTIME = "runtime"


class PromptCategory(str, Enum):
    """定义 Prompt 业务分类枚举"""
    CHAT = "chat"
    SHORT_SUMMARY = "short_summary"
    LONG_SUMMARY = "long_summary"
    INPUT_RECONSTRUCTION = "input_reconstruction"
    USER_PROFILE_EXTRACT = "user_profile_extract"
    USER_PROFILE_SUMMARIZE = "user_profile_summarize"


# 占位符常量
PLACEHOLDER_SYSTEM = "{system}"
PLACEHOLDER_MEMORY = "{memory}"
PLACEHOLDER_RUNTIME = "{runtime}"

# 按注入顺序返回占位符列表
SLOT_PLACEHOLDERS = [PLACEHOLDER_SYSTEM, PLACEHOLDER_MEMORY, PLACEHOLDER_RUNTIME]

# 按注入顺序返回 SlotPosition 列表
SLOT_POSITIONS = [SlotPosition.SYSTEM, SlotPosition.MEMORY, SlotPosition.RUNTIME]


def render_template(template: str, variables: Dict[str, str]) -> str:
    """
    简单渲染 {{ KEY }} 占位符为对应变量的值
    """
    result = template
    for key, value in variables.items():
        # 替换带空格的格式 {{ KEY }}
        placeholder_with_space = f"{{{{ {key} }}}}"
        result = result.replace(placeholder_with_space, value)
        # 替换不带空格的格式 {{KEY}}
        placeholder_without_space = f"{{{{{key}}}}}"
        result = result.replace(placeholder_without_space, value)
    return result
