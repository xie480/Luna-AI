import asyncio

from app.agent.schemas.input_reconstruction import (
    DagRouteHint,
    InputReconstructionOutput,
    IntentCategory,
    PrimaryIntent,
)
from app.llm.client import LLMClient
from app.logger import logger

class InputReconstructorAgent:
    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client
        self.max_retries = 2
        
    @property
    def model_name(self) -> str:
        """动态获取 Mid Model 的名称"""
        from app.config import global_config_container
        config = global_config_container.get_model_config("medium")
        return config.get("model_id", "gpt-4o-mini")

    def _build_prompt(self, system_prompt: str, memory_prompt: str, runtime_prompt: str) -> str:
        """
        动态组装路由与情绪提取指南 Prompt, 将枚举的有效值列表注入模板。
        """
        # Go 层已经将变量渲染好, 这里只需要将三个槽位拼接起来
        return f"{system_prompt}\n\n{memory_prompt}\n\n{runtime_prompt}"

    async def process(
        self,
        trace_id: str,
        user_input: str,
        system_prompt: str,
        memory_prompt: str,
        runtime_prompt: str
    ) -> InputReconstructionOutput:
        """
        执行输入重构与路由解析, 包含重试与降级兜底机制。
        """
        prompt = self._build_prompt(system_prompt, memory_prompt, runtime_prompt)
        
        for attempt in range(self.max_retries + 1):
            try:
                logger.info(
                    f"[TraceID:{trace_id}] [NodeID:InputReconstructor] "
                    f"开始解析用户输入, attempt={attempt}"
                )
                
                # 利用大模型 Structured Outputs 特性强制返回 JSON
                response = await self.llm_client.generate_structured(
                    model=self.model_name,
                    messages=[{"role": "user", "content": prompt}],
                    response_format=InputReconstructionOutput,
                    timeout=15.0 # 放宽超时控制，因为结构化输出可能较慢
                )
                
                # 校验 trace_id 一致性
                response.trace_id = trace_id
                logger.info(
                    f"[TraceID:{trace_id}] [NodeID:InputReconstructor] "
                    f"解析成功, intent={response.intent_routing.primary_intent}"
                )
                return response
                
            except Exception as e:
                logger.warning(f"[TraceID:{trace_id}] [NodeID:InputReconstructor] 解析失败: {e!s}")
                if attempt == self.max_retries:
                    logger.error(
                        f"[TraceID:{trace_id}] [NodeID:InputReconstructor] "
                        "达到最大重试次数, 触发降级策略"
                    )
                    return self._build_fallback_response(trace_id, user_input)
                await asyncio.sleep(0.5)

    def _build_fallback_response(self, trace_id: str, user_input: str) -> InputReconstructionOutput:
        """系统级兜底降级策略: 当大模型解析彻底失败时, 保证系统不崩溃, 走最基础的闲聊链路"""
        # 构造一个默认的、安全的 InputReconstructionOutput 实例
        return InputReconstructionOutput(
            trace_id=trace_id,
            original_input=user_input,
            reconstruction={
                "disambiguated_text": user_input,
                "unresolved_pronouns": []
            },
            intent_routing={
                "primary_intent": PrimaryIntent.GREETING,
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
