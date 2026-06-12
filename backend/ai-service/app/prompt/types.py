"""
Luna AI Prompt 类型定义

做什么：定义 Prompt 相关的枚举、常量和辅助函数。
为什么这样做：与 Go 版本的 types.go 保持一致。
"""

import json
from enum import Enum
from typing import Any, Dict


class SlotPosition(str, Enum):
    """定义 Prompt 槽位类型枚举"""
    SYSTEM = "system"
    MEMORY = "memory"
    RUNTIME = "runtime"


class PromptCategory(str, Enum):
    """
    定义 Prompt 业务分类枚举。

    做什么：集中声明所有可由 PromptManager 组装的业务 Prompt 分类。
    为什么这样做：业务代码只能通过枚举引用分类，避免散落魔法字符串导致 PG 查询分类不一致。
    输入输出：枚举值会直接映射 prompt_templates.category 字段。
    边界条件：新增分类必须同步入库脚本和业务调用方。
    异常行为：使用不存在的分类会在枚举构造阶段抛出 ValueError。
    """

    CHAT = "chat"
    SHORT_SUMMARY = "short_summary"
    LONG_SUMMARY = "long_summary"
    INPUT_RECONSTRUCTION = "input_reconstruction"
    EVIDENCE_EVALUATOR = "evidence_evaluator"
    USER_PROFILE_EXTRACT = "user_profile_extract"
    USER_PROFILE_SUMMARIZE = "user_profile_summarize"

    # --- Phase 12 新增：MCP 三 Agent Prompt 分类 ---
    # 做什么：为 MCP 工具链中的三个 Agent 分别提供独立的 Prompt 模板分类。
    #         Agent 1（初筛）、Agent 2（参数提取）、Agent 3（意图对齐）
    #         各有独立的 system/memory/runtime 三槽位模板。
    # 为什么这样做：三 Agent 的 Prompt 模板内容差异较大（Agent 1 不含 Schema，
    #             Agent 2 含完整 Schema，Agent 3 聚焦结果校准），
    #             分开存储便于独立迭代和版本管理。
    MCP_TOOL_SCREENING = "mcp_tool_screening"
    MCP_TOOL_CALLING = "mcp_tool_calling"
    MCP_INTENT_ALIGNMENT = "mcp_intent_alignment"

    # --- Phase 12（v3.0）新增：Skill 三阶段 Prompt 分类 ---
    # 做什么：为 Skill 三阶段 Agent 分别提供独立的 Prompt 模板分类。
    #         Agent 1（初筛）、Agent 2（加载）、Agent 3（执行·含退回）。
    # 为什么这样做：Skill 阶段的 Prompt 与原有 Tool 阶段的 Prompt 内容差异较大，
    #             分开存储便于独立迭代和版本管理。
    MCP_SKILL_SCREENING = "mcp_skill_screening"
    MCP_SKILL_LOADING = "mcp_skill_loading"
    MCP_SKILL_EXECUTION = "mcp_skill_execution"

    # --- Phase 12 新增：资源提取子 Agent Prompt 分类 ---
    MCP_RESOURCE_EXTRACTION = "mcp_resource_extraction"
    MCP_SKILL_FALLBACK_EXTRACTION = "mcp_skill_fallback_extraction"

    # --- Phase 12（v3.0）新增：MCP 前置判断 Prompt 分类 ---
    MCP_INTENT_JUDGE = "mcp_intent_judge"


# 这些分类必须从 PostgreSQL 读取，禁止运行期回退到 app/prompt/simple 本地文件。
# 做什么：约束已纳入 Prompt 管理面板的业务 Prompt 只以 PG 版本为准。
# 为什么这样做：用户画像与证据评估 Prompt 需要支持数据库版本管理、发布和回滚，不能继续绕过 PG。
PG_ONLY_PROMPT_CATEGORIES = {
    PromptCategory.EVIDENCE_EVALUATOR,
    PromptCategory.USER_PROFILE_EXTRACT,
    PromptCategory.USER_PROFILE_SUMMARIZE,
}

# 占位符常量
PLACEHOLDER_SYSTEM = "{system}"
PLACEHOLDER_MEMORY = "{memory}"
PLACEHOLDER_RUNTIME = "{runtime}"

# 按注入顺序返回占位符列表
SLOT_PLACEHOLDERS = [PLACEHOLDER_SYSTEM, PLACEHOLDER_MEMORY, PLACEHOLDER_RUNTIME]

# 按注入顺序返回 SlotPosition 列表
SLOT_POSITIONS = [SlotPosition.SYSTEM, SlotPosition.MEMORY, SlotPosition.RUNTIME]


def _normalize_variable_value(value: Any) -> str:
    """
    将 Prompt 变量值标准化为可替换字符串。

    做什么：把 str / list / dict / None 等运行时变量统一转换为字符串。
    为什么这样做：RAG 证据评估 Prompt 会传入列表和字典，如果直接 replace 会触发类型异常。
    输入输出：输入任意变量值，输出可注入 Prompt 的字符串。
    边界条件：None 渲染为空字符串；复杂对象优先按 JSON 输出，便于模型理解结构。
    异常行为：JSON 序列化失败时降级为 str(value)，保证 Prompt 组装不中断。
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except TypeError:
        return str(value)


def render_template(template: str, variables: Dict[str, Any]) -> str:
    """
    简单渲染 {{ KEY }} 占位符为对应变量的值。

    做什么：支持 {{ KEY }} 与 {{KEY}} 两种占位符格式。
    为什么这样做：现有 simple Prompt 文件两种写法并存，统一在 Python 控制面完成渲染。
    输入输出：输入模板正文和变量字典，输出渲染后的 Prompt 字符串。
    边界条件：不存在的变量不会被替换；非字符串变量会转为 JSON 或字符串。
    异常行为：本函数不主动抛业务异常。
    """
    result = template
    for key, value in variables.items():
        normalized_value = _normalize_variable_value(value)
        # 替换带空格的格式 {{ KEY }}
        placeholder_with_space = f"{{{{ {key} }}}}"
        result = result.replace(placeholder_with_space, normalized_value)
        # 替换不带空格的格式 {{KEY}}
        placeholder_without_space = f"{{{{{key}}}}}"
        result = result.replace(placeholder_without_space, normalized_value)
    return result
