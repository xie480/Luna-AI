import asyncio

from jinja2 import Template

from app.agent.schemas.input_reconstruction import (
    DagRouteHint,
    InputReconstructionOutput,
    IntentCategory,
    PrimaryIntent,
    RetrievalType,
)
from app.llm.client import LLMClient
from app.logger import get_logger

logger = get_logger(__name__)

class InputReconstructorAgent:
    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client
        # 强制使用 Mid Model 以保证低延迟
        self.model_name = "gpt-4o-mini" 
        self.max_retries = 2

    def _build_prompt(self, user_input: str, short_term_memory: str) -> str:
        """
        动态组装路由与情绪提取指南 Prompt，将枚举的有效值列表注入模板。
        """
        template_str = """
你是一个运行在 Luna AI 核心调度层前置的“输入重构与路由 Agent”。
你的核心职责是：接收用户的原始输入与短期会话上下文，消除输入中的指代歧义，精准识别用户意图，并为下游的 DAG 调度引擎生成结构化的路由与检索指令。
你必须严格按照预定义的 JSON Schema 输出，禁止包含任何额外的解释性文本。你的输出将直接决定系统后续的执行链路，请务必保持客观、严谨。

### 当前短期会话上下文 (Short-Term Memory)
-当前会话背景开始-
核心梗概：
{{CORE_SUMMARY}}
关键事实：
{{KEY_FACTS}} 
-当前会话背景结束-

-记忆片段开始-
{{MEMORY_SNIPPETS}}
-记忆片段结束-

### 用户原始输入
{{ user_input }}

### 消歧任务指南
1. 结合上述上下文，将用户输入中的代词（如“那个”、“他”、“上次”）替换为具体的实体。
2. 如果上下文中不存在该实体，请保留原样，并在 `unresolved_pronouns` 中记录原因，这将触发下游的长期记忆检索。
3. 确保 `disambiguated_text` 是一句语义完整、自然流畅的话。

### 检索路由解耦指南
你需要将检索意图严格拆分为三个独立维度，并分别评估是否触发：
1. **长期记忆 (Long-Term Memory)**：当需要回溯用户历史轨迹、个人偏好或补全未消歧实体时触发。
2. **外部知识 (External Knowledge)**：仅当用户明确要求查阅外部客观文档、系统手册或垂类知识库时触发。
3. **经验教训 (Experience Reflection)**：当用户表达负面情绪（如焦虑、后悔）、面临高危决策或主动要求复盘时触发，用于提取系统避坑指南。

### 情绪特征提取指南 (V-A 模型)
- **Valence (效价)**: -1.0 (极度负面/痛苦) 到 1.0 (极度正面/愉悦)。
- **Arousal (唤醒度)**: 0.0 (极度平静/困倦) 到 1.0 (极度激动/紧张)。
- 结合用户的输入语义，量化其情绪状态。

### ⚠️ 严格枚举约束与输出格式要求 ⚠️
你必须严格输出如下 JSON 结构。
【致命约束】：针对带有枚举约束的字段，你的输出值必须绝对限制在以下提供的有效值列表中，严禁自行编造！否则将导致系统严重崩溃！

* 允许的 primary_intent: [ {{ primary_intents | join(', ') }} ]
* 允许的 category: [ {{ categories | join(', ') }} ]
* 允许的 dag_route_hint: [ {{ dag_route_hints | join(', ') }} ]
* 允许的 required_retrieval_types: [ {{ retrieval_types | join(', ') }} ]

```json
{
  "trace_id": "必须与传入的 trace_id 保持一致",
  "original_input": "用户的原始输入文本",
  
  "reconstruction": {
    "disambiguated_text": "消歧后的完整文本。如果能在短期记忆中找到指代对象，会将其替换；如果找不到，会用 [未知实体] 等占位符标记。",
    "unresolved_pronouns": [
      {
        "original": "在当前短期会话上下文中无法找到明确指代目标的代词",
        "reason": "无法消歧的原因，例如：短期上下文缺失"
      }
    ]
  },

  "intent_routing": {
    "primary_intent": "必须从允许的 primary_intent 列表中选择",
    "category": "必须从允许的 category 列表中选择",
    "dag_route_hint": "必须从允许的 dag_route_hint 列表中选择",
    "required_retrieval_types": ["必须从允许的 required_retrieval_types 列表中选择"]
  },

  "retrieval_routing": {
    "long_term_memory": {
      "trigger": "布尔值，是否触发长期记忆检索",
      "trigger_reason": "触发检索的具体原因描述",
      "search_queries": ["提取并泛化出的多个搜索 Query，用于向量检索"],
      "temporal_focus": {
        "time_type": "时间指向类型，枚举值：PAST, FUTURE, CURRENT",
        "reference_time": "具体的参考时间戳，如果没有则为 null"
      },
      "entity_mentions": ["提取出的核心实体词"]
    },
    
    "external_knowledge": {
      "trigger": "布尔值，是否触发外部知识检索",
      "trigger_reason": "触发检索的具体原因描述",
      "search_queries": ["提取并泛化出的多个搜索 Query，用于向量检索"]
    },
    
    "experience_reflection": {
      "trigger": "布尔值，是否触发经验教训检索",
      "trigger_reason": "触发检索的具体原因描述",
      "search_queries": ["提取并泛化出的多个搜索 Query，用于向量检索"],
      "reflection_focus": "反思焦点，如 RISK_AVERSION, EFFICIENCY_OPTIMIZATION, COMMUNICATION_STYLE"
    }
  },

  "emotion_state": {
    "primary_emotion": "主导情绪标签，如 ANXIETY, JOY, ANGER",
    "intensity": "情绪的强烈程度，范围 0.0 到 1.0",
    "valence": "情绪效价（V-A 模型），范围 -1.0（极度负面）到 1.0（极度正面）",
    "arousal": "情绪唤醒度（V-A 模型），范围 0.0（极度平静）到 1.0（极度激动）",
    "emotion_trigger": "触发该情绪的具体原因或事件描述",
    "esm_transition_hint": "给 Go 层情绪状态机的跃迁暗示，如 REQUIRE_COMFORT"
  }
}
```
        """
        template = Template(template_str)
        
        # 动态注入枚举值列表
        return template.render(
            user_input=user_input,
            # TODO: 实际工程中需要从 short_term_memory 解析出 CORE_SUMMARY, KEY_FACTS, MEMORY_SNIPPETS
            CORE_SUMMARY="[暂无]",
            KEY_FACTS="[暂无]",
            MEMORY_SNIPPETS=short_term_memory if short_term_memory else "[暂无]",
            primary_intents=[e.value for e in PrimaryIntent],
            categories=[e.value for e in IntentCategory],
            dag_route_hints=[e.value for e in DagRouteHint],
            retrieval_types=[e.value for e in RetrievalType]
        )

    async def process(self, trace_id: str, user_input: str, short_term_memory: str) -> InputReconstructionOutput:
        """
        执行输入重构与路由解析，包含重试与降级兜底机制。
        """
        prompt = self._build_prompt(user_input, short_term_memory)
        
        for attempt in range(self.max_retries + 1):
            try:
                logger.info(f"[TraceID:{trace_id}] [NodeID:InputReconstructor] 开始解析用户输入, attempt={attempt}")
                
                # 利用大模型 Structured Outputs 特性强制返回 JSON
                response = await self.llm_client.generate_structured(
                    model=self.model_name,
                    messages=[{"role": "user", "content": prompt}],
                    response_format=InputReconstructionOutput,
                    timeout=5.0 # 严格的超时控制
                )
                
                # 校验 trace_id 一致性
                response.trace_id = trace_id 
                logger.info(f"[TraceID:{trace_id}] [NodeID:InputReconstructor] 解析成功, intent={response.intent_routing.primary_intent}")
                return response
                
            except Exception as e:
                logger.warning(f"[TraceID:{trace_id}] [NodeID:InputReconstructor] 解析失败: {e!s}")
                if attempt == self.max_retries:
                    logger.error(f"[TraceID:{trace_id}] [NodeID:InputReconstructor] 达到最大重试次数，触发降级策略")
                    return self._build_fallback_response(trace_id, user_input)
                await asyncio.sleep(0.5)

    def _build_fallback_response(self, trace_id: str, user_input: str) -> InputReconstructionOutput:
        """系统级兜底降级策略：当大模型解析彻底失败时，保证系统不崩溃，走最基础的闲聊链路"""
        # 构造一个默认的、安全的 InputReconstructionOutput 实例
        return InputReconstructionOutput(
            trace_id=trace_id,
            original_input=user_input,
            reconstruction={
                "disambiguated_text": user_input,
                "unresolved_pronouns": []
            },
            intent_routing={
                "primary_intent": PrimaryIntent.CHAT,
                "category": IntentCategory.CHAT,
                "dag_route_hint": DagRouteHint.FAST_CHAT,
                "required_retrieval_types": []
            },
            retrieval_routing={
                "long_term_memory": {
                    "trigger": False,
                    "trigger_reason": "降级兜底，不触发检索",
                    "search_queries": [],
                    "temporal_focus": {"time_type": "CURRENT", "reference_time": None},
                    "entity_mentions": []
                },
                "external_knowledge": {
                    "trigger": False,
                    "trigger_reason": "降级兜底，不触发检索",
                    "search_queries": []
                },
                "experience_reflection": {
                    "trigger": False,
                    "trigger_reason": "降级兜底，不触发检索",
                    "search_queries": [],
                    "reflection_focus": "NONE"
                }
            },
            emotion_state={
                "primary_emotion": "NEUTRAL",
                "intensity": 0.0,
                "valence": 0.0,
                "arousal": 0.0,
                "emotion_trigger": "降级兜底，无情绪",
                "esm_transition_hint": "NONE"
            }
        )
