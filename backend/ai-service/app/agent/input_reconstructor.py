import asyncio

from app.agent.schemas.input_reconstruction import (
    DagRouteHint,
    InputReconstructionOutput,
    IntentCategory,
    PrimaryIntent,
    RagRetrievalRoute,
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
        from app.config.settings import global_config_container
        from app.types.constants import ModelSize
        config = global_config_container.get_model_config(ModelSize.MEDIUM)
        return config.get("model_id", "gpt-4o-mini")

    async def process(
        self,
        trace_id: str,
        user_input: str,
        prompt: str,
    ) -> InputReconstructionOutput:
        """
        执行输入重构与路由解析, 包含重试与降级兜底机制。

        效仿 MCP Intent Judge 的变量注入方式：接收由 prompt_manager.assemble_prompt()
        一次性渲染完成的完整 Prompt 字符串，不再由 Agent 内部手动拼接三槽位。
        为什么这样做：assemble_prompt() 使用 Jinja2 直接从 PG active 版本渲染变量，
        消除了 render_prompt() 三槽位拼接 + 硬编码枚举约束的双重不一致问题，
        确保 {{ PRIMARY_INTENTS }} 等模板变量能正确注入。
        """
        
        for attempt in range(self.max_retries + 1):
            try:
                logger.info(
                    f"[TraceID:{trace_id}] [NodeID:InputReconstructor] "
                    f"开始解析用户输入, attempt={attempt}"
                )
                
                # 利用大模型 Structured Outputs 特性强制返回 JSON
                # 与 MCP Intent Judge 一致：直接将完整 prompt 作为 system message 发送
                response = await self.llm_client.generate_structured(
                    model=self.model_name,
                    messages=[{"role": "system", "content": prompt}],
                    response_format=InputReconstructionOutput,
                    timeout=40.0 # 该 API 代理对 structured output 响应较慢，需要更长的超时
                )
                
                # 校验 trace_id 一致性
                response.trace_id = trace_id
                logger.info(
                    f"[TraceID:{trace_id}] [NodeID:InputReconstructor] "
                    f"解析成功, intent={response.intent_routing.primary_intent}"
                )
                return response
                
            except Exception as e:
                logger.warning(
                    f"[TraceID:{trace_id}] [NodeID:InputReconstructor] "
                    f"第 {attempt} 次解析失败, 异常类型: {type(e).__name__}, 原因: {e!s}"
                )
                if attempt == self.max_retries:
                    logger.error(
                        f"[TraceID:{trace_id}] [NodeID:InputReconstructor] "
                        f"达到最大重试次数, 触发降级策略. 最后一次错误类型: {type(e).__name__}, 原因: {e!s}"
                    )
                    return self._build_fallback_response(trace_id, user_input)
                logger.info(
                    f"[TraceID:{trace_id}] [NodeID:InputReconstructor] "
                    f"准备进行第 {attempt + 1} 次重试..."
                )
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
                "route_strategy": RagRetrievalRoute.HYBRID,
                "long_term_memory": {
                    "trigger": False,
                    "trigger_reason": "降级兜底，不触发检索",
                    "search_queries": [],
                    "temporal_focus": {"reference_time": None, "temporal_deviation": 0},
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
