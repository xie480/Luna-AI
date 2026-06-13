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
    
    # --- Phase 12 新增：多轮策略与评价 ---
    MCP_SKILL_MEMORY = "mcp_skill_memory"
    MCP_EVALUATION = "mcp_evaluation"


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
    except Exception:
        return str(value)


def render_template(template: str, variables: Dict[str, Any]) -> str:
    """
    渲染 Prompt 模板。

    做什么：使用 Jinja2 渲染模板，支持复杂的逻辑如 {% for %} 和 {% if %}。
    为什么这样做：MCP 技能调用等需要处理列表迭代和条件分支，简单的正则替换已无法满足需求。
    输入输出：输入模板字符串和变量字典，输出渲染后的字符串。
    边界条件：未定义的变量会被安全地渲染为空字符串；复杂对象按 JSON 输出。
    """
    from jinja2 import Environment, Undefined
    import json

    def finalize_value(value: Any) -> Any:
        if value is None or isinstance(value, Undefined):
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, (dict, list)):
            try:
                return json.dumps(value, ensure_ascii=False)
            except Exception:
                return str(value)
        return str(value)

    env = Environment(finalize=finalize_value)
    try:
        tmpl = env.from_string(template)
        return tmpl.render(**variables)
    except Exception as e:
        from app.logger import logger
        logger.error(f"Jinja2 渲染 Prompt 失败: {e}")
        # 如果 Jinja2 渲染失败（例如语法错误），回退到返回原始模板文本
        return template
