from enum import Enum

from pydantic import BaseModel, Field


class PrimaryIntent(str, Enum):
    MODIFY_PLAN = "MODIFY_PLAN"             # 修改计划
    GREETING = "GREETING"                   # 日常问候
    QUERY_INFO = "QUERY_INFO"               # 信息查询
    EMOTION_VENTING = "EMOTION_VENTING"     # 情绪宣泄
    SYSTEM_COMMAND = "SYSTEM_COMMAND"       # 系统指令
    TOOL_INVOCATION = "TOOL_INVOCATION"     # 明确的工具调用

class IntentCategory(str, Enum):
    TASK_MANAGEMENT = "TASK_MANAGEMENT"     # 任务管理类
    CHAT = "CHAT"                           # 闲聊陪伴类
    KNOWLEDGE_QUERY = "KNOWLEDGE_QUERY"     # 知识问答类
    EMOTION_SUPPORT = "EMOTION_SUPPORT"     # 情感支持类

class DagRouteHint(str, Enum):
    MULTI_SOURCE_RETRIEVAL_WORKFLOW = "MULTI_SOURCE_RETRIEVAL_WORKFLOW" # 多源检索工作流
    FAST_CHAT = "FAST_CHAT"                                             # 快速闲聊通道
    AGENTIC_WORKFLOW = "AGENTIC_WORKFLOW"                               # 复杂Agent规划流
    GATING_APPROVAL = "GATING_APPROVAL"                                 # 强制人工审批流

class RetrievalType(str, Enum):
    LONG_TERM_MEMORY = "LONG_TERM_MEMORY"           # 长期记忆
    EXTERNAL_KNOWLEDGE = "EXTERNAL_KNOWLEDGE"       # 外部知识
    EXPERIENCE_REFLECTION = "EXPERIENCE_REFLECTION" # 经验教训

class UnresolvedPronoun(BaseModel):
    original: str = Field(..., description="原始代词")
    reason: str = Field(..., description="无法消歧的原因")

class Reconstruction(BaseModel):
    disambiguated_text: str = Field(..., description="消歧后的完整文本")
    unresolved_pronouns: list[UnresolvedPronoun] = Field(default_factory=list)

class IntentRouting(BaseModel):
    primary_intent: PrimaryIntent = Field(..., description="核心意图标识")
    category: IntentCategory = Field(..., description="意图大类")
    dag_route_hint: DagRouteHint = Field(..., description="DAG路由暗示")
    required_retrieval_types: list[RetrievalType] = Field(default_factory=list, description="需要触发的检索类型")

class TemporalFocus(BaseModel):
    reference_time: str | None = Field(None, description="参考时间戳")
    temporal_deviation: int = Field(0, description="允许前后偏差的天数")

class LongTermMemoryRouting(BaseModel):
    trigger: bool = Field(..., description="是否触发长期记忆检索")
    trigger_reason: str = Field(..., description="触发原因，例如需要回溯用户聊天历史或提取用户偏好")
    search_queries: list[str] = Field(default_factory=list, description="侧重于找回过去交流片段的Query")
    temporal_focus: TemporalFocus
    entity_mentions: list[str] = Field(default_factory=list, description="历史对话中提及的实体或昵称")

class ExternalKnowledgeRouting(BaseModel):
    trigger: bool = Field(..., description="是否触发外部知识检索")
    trigger_reason: str = Field(..., description="触发原因，例如用户查询客观事实、文档或操作手册")
    search_queries: list[str] = Field(default_factory=list, description="侧重于客观事实查询的Query")
    temporal_focus: TemporalFocus | None = Field(default=None, description="通常为空，除非明确要求特定时期的文档")
    entity_mentions: list[str] = Field(default_factory=list, description="客观名词、术语或API名称等")

class ExperienceReflectionRouting(BaseModel):
    trigger: bool = Field(..., description="是否触发经验教训检索")
    trigger_reason: str = Field(..., description="触发原因")
    search_queries: list[str] = Field(default_factory=list)
    reflection_focus: str = Field(..., description="反思焦点，如 RISK_AVERSION")

class RagRetrievalRoute(str, Enum):
    KEYWORD = "keyword"
    HYBRID = "hybrid"
    AGENTIC = "agentic"

class RetrievalRouting(BaseModel):
    route_strategy: RagRetrievalRoute = Field(default=RagRetrievalRoute.HYBRID, description="RAG路由策略")
    long_term_memory: LongTermMemoryRouting
    external_knowledge: ExternalKnowledgeRouting
    experience_reflection: ExperienceReflectionRouting

class EmotionState(BaseModel):
    primary_emotion: str = Field(..., description="主导情绪标签")
    intensity: float = Field(..., ge=0.0, le=1.0, description="情绪强度")
    valence: float = Field(..., ge=-1.0, le=1.0, description="情绪效价")
    arousal: float = Field(..., ge=0.0, le=1.0, description="情绪唤醒度")
    emotion_trigger: str = Field(..., description="触发情绪的原因")
    esm_transition_hint: str = Field(..., description="ESM状态机跃迁暗示，如 REQUIRE_COMFORT")

class InputReconstructionOutput(BaseModel):
    trace_id: str = Field(..., description="全链路追踪ID，必须与入参保持一致")
    original_input: str = Field(..., description="用户原始输入")
    reconstruction: Reconstruction
    intent_routing: IntentRouting
    retrieval_routing: RetrievalRouting
    emotion_state: EmotionState
