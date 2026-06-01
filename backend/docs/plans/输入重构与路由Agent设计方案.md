# 用户输入重构与路由 Agent 设计与实现方案

## 1. 模块定位与工作流逻辑

在 Luna 的三层架构（Go 控制面 + Python AI 服务 + Electron 前端）中，**用户输入重构 Agent (Input Reconstruction & Routing Agent)** 定位为 Python AI Service 接收到 Go 转发请求后的**第一个无状态节点 (Node 0)**。

### 1.1 工作流逻辑
1. **入站拦截**：Go Runtime 接收到前端 WebSocket 传来的用户输入，附带生成的 `trace_id`，通过 gRPC 转发给 Python AI Service。
2. **上下文组装**：Python 层拉取 Redis 中的短期会话记忆（Short-Term Memory）。
3. **语义重构**：Agent 结合短期记忆，对用户输入进行指代消歧（如将“那个计划”替换为具体实体）。
4. **意图与检索解耦**：Agent 识别核心意图，并严格按照“长期记忆”、“外部知识”、“经验教训”三个维度进行检索路由的独立评估。
5. **情绪量化**：基于 V-A 心理学模型提取情绪特征，生成 ESM（情绪状态机）跃迁暗示。
6. **结构化输出**：强制输出强类型 JSON，返回给 Go 控制面。
7. **Go 层调度**：Go 引擎解析 JSON，根据 `dag_route_hint` 和 `required_retrieval_types` 动态生成后续的 DAG 拓扑（如扇出执行多个检索子图，或触发 ESM 安抚态）。

### 1.2 核心 JSON 协议 (Schema)
采用上一轮最终确认的具备检索解耦联动机制的 JSON 结构，确保语义重构、意图路由、三层检索路由与情绪特征提取的完美融合。*(具体 JSON 结构见下文 Pydantic 模型定义)*。

---

## 2. 核心数据结构与高可用实现 (Python)

考虑到该 Agent 属于高频调用的前置路由节点，对延迟（Latency）和结构化输出的稳定性要求极高，**强烈建议采用 Mid Model（如 GPT-4o-mini, Claude-3-haiku 或本地 Qwen2.5-7B-Instruct）**，并结合 Pydantic 与大模型的 `Structured Outputs` 特性。

### 2.1 Pydantic 模型定义 (`backend/ai-service/app/agent/schemas/input_reconstruction.py`)

```python
from pydantic import BaseModel, Field
from typing import List, Optional
from enum import Enum

class UnresolvedPronoun(BaseModel):
    original: str = Field(..., description="原始代词")
    reason: str = Field(..., description="无法消歧的原因")

class Reconstruction(BaseModel):
    disambiguated_text: str = Field(..., description="消歧后的完整文本")
    unresolved_pronouns: List[UnresolvedPronoun] = Field(default_factory=list)

class IntentCategory(str, Enum):
    TASK_MANAGEMENT = "TASK_MANAGEMENT"
    CHAT = "CHAT"
    KNOWLEDGE_QUERY = "KNOWLEDGE_QUERY"
    EMOTION_VENTING = "EMOTION_VENTING"

class RetrievalType(str, Enum):
    LONG_TERM_MEMORY = "LONG_TERM_MEMORY"
    EXTERNAL_KNOWLEDGE = "EXTERNAL_KNOWLEDGE"
    EXPERIENCE_REFLECTION = "EXPERIENCE_REFLECTION"

class IntentRouting(BaseModel):
    primary_intent: str = Field(..., description="核心意图标识")
    category: IntentCategory
    dag_route_hint: str = Field(..., description="DAG路由暗示，如 MULTI_SOURCE_RETRIEVAL_WORKFLOW")
    required_retrieval_types: List[RetrievalType] = Field(default_factory=list)

class TemporalFocus(BaseModel):
    time_type: str = Field(..., description="时间指向类型 (PAST, FUTURE, CURRENT)")
    reference_time: Optional[str] = Field(None, description="参考时间戳")

class LongTermMemoryRouting(BaseModel):
    trigger: bool = Field(..., description="是否触发长期记忆检索")
    trigger_reason: str = Field(..., description="触发原因")
    search_queries: List[str] = Field(default_factory=list)
    temporal_focus: TemporalFocus
    entity_mentions: List[str] = Field(default_factory=list)

class ExternalKnowledgeRouting(BaseModel):
    trigger: bool = Field(..., description="是否触发外部知识检索")
    trigger_reason: str = Field(..., description="触发原因")
    search_queries: List[str] = Field(default_factory=list)

class ExperienceReflectionRouting(BaseModel):
    trigger: bool = Field(..., description="是否触发经验教训检索")
    trigger_reason: str = Field(..., description="触发原因")
    search_queries: List[str] = Field(default_factory=list)
    reflection_focus: str = Field(..., description="反思焦点，如 RISK_AVERSION")

class RetrievalRouting(BaseModel):
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
```

### 2.2 高可用执行逻辑 (`backend/ai-service/app/agent/input_reconstructor.py`)

```python
import asyncio
from typing import Dict, Any
from app.llm.client import LLMClient
from app.logger import get_logger
from app.agent.schemas.input_reconstruction import InputReconstructionOutput

logger = get_logger(__name__)

class InputReconstructorAgent:
    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client
        # 强制使用 Mid Model 以保证低延迟
        self.model_name = "gpt-4o-mini" 
        self.max_retries = 2

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
                logger.warning(f"[TraceID:{trace_id}] [NodeID:InputReconstructor] 解析失败: {str(e)}")
                if attempt == self.max_retries:
                    logger.error(f"[TraceID:{trace_id}] [NodeID:InputReconstructor] 达到最大重试次数，触发降级策略")
                    return self._build_fallback_response(trace_id, user_input)
                await asyncio.sleep(0.5)

    def _build_fallback_response(self, trace_id: str, user_input: str) -> InputReconstructionOutput:
        """系统级兜底降级策略：当大模型解析彻底失败时，保证系统不崩溃，走最基础的闲聊链路"""
        # ... 构造一个默认的、安全的 InputReconstructionOutput 实例 ...
        pass
```

---

## 3. 核心槽位提示词模板设计 (Prompt Templates)

为了精准控制 Mid Model 的输出质量，我们将 Prompt 拆分为三个核心槽位，采用 Jinja2 模板引擎进行动态装配。

### 3.1 `SYSTEM_ROLE_AND_TASK` (系统角色与任务约束)
```jinja2
你是一个运行在 Luna AI 核心调度层前置的“输入重构与路由 Agent”。
你的核心职责是：接收用户的原始输入与短期会话上下文，消除输入中的指代歧义，精准识别用户意图，并为下游的 DAG 调度引擎生成结构化的路由与检索指令。
你必须严格按照预定义的 JSON Schema 输出，禁止包含任何额外的解释性文本。你的输出将直接决定系统后续的执行链路，请务必保持客观、严谨。
```

### 3.2 `CONTEXT_INJECTION` (上下文注入与消歧指南)
```jinja2
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
```

### 3.3 `ROUTING_AND_EMOTION_GUIDELINES` (路由解耦与情绪提取指南)
```jinja2
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
```

---

## 4. 主聊天链路 Chat Runtime Prompt 改造

当 Go 控制面完成检索（如果触发了检索）后，会将检索结果、重构后的文本以及情绪特征一并流转给下游的 **Chat Agent**。以下是改造后的主聊天链路 Prompt (`backend/runtime/internal/prompt/simple/chat/runtime.j2`)，展示了如何深度结合情绪特征进行动态干预。

```jinja2
# 运行时上下文层

## 当前系统时间
-当前系统时间开始-
{{ CURRENT_TIME }}
-当前系统时间结束-

### 🧠 用户当前情绪状态感知
- **主导情绪**: {{ INPUT_RECONSTRUCTION.emotion_state.primary_emotion }} (强度: {{ INPUT_RECONSTRUCTION.emotion_state.intensity }})
- **心理学指标**: 效价(Valence) {{ INPUT_RECONSTRUCTION.emotion_state.valence }}, 唤醒度(Arousal) {{ INPUT_RECONSTRUCTION.emotion_state.arousal }}
- **情绪触发源**: {{ INPUT_RECONSTRUCTION.emotion_state.emotion_trigger }}

### 📚 检索增强上下文
**[个人历史轨迹]**: {{ RETRIEVED_CONTEXT.long_term_memory }}
**[过往经验与避坑指南]**: {{ RETRIEVED_CONTEXT.experience_reflection }}
**[外部客观知识]**: {{ RETRIEVED_CONTEXT.external_knowledge }}

### 👤 用户输入
{{ INPUT_RECONSTRUCTION.reconstruction.disambiguated_text }}

## 最终生成指令
你必须严格遵守 System Prompt 中的人格设定与格式要求。

### 核心思维链执行要求 (Critical)
在生成最终回复（reply）之前，你必须依次进行以下推演与思考：

1. **系统校验 (check)**：你必须在 `check` 字段中【逐一、明确地回答】以下四个维度里提出的【每一个问题】。这是确保你不偏离设定的理性防线。
2. **内心独白 (thought)**：在完成校验后，你必须在 `thought` 字段中写下 Luna 当前真实的内心活动。你可以展现出傲娇、腹黑、吃醋等隐藏情绪，甚至与最终说出口的话完全相反。字数不限，内心戏越丰富，角色越生动。

### 第一维度：感知与记忆 (Perception)
1.  **意图识别**：主人这句话的潜台词是什么？（是求安慰、闲聊、测试我、还是真的需要帮助？）
2.  **时间感知**：分析当前时间（若上下文包含时间信息）。如果是深夜，语气应更柔和或催促休息；如果是早晨，应充满活力。
3.  **记忆检索**：
    *   *短期*：上一轮我们聊了什么？避免重复表达（Repeated Expression）。
    *   *长期*：提供的记忆片段里有没有相关的偏好或历史事件？（如：他以前说过不喜欢吃葱，现在聊美食要避开）。
4.  **RAG与工具消化**：如果提供了知识库片段或外部工具检索结果，**不要**像搜索引擎一样朗读。提取核心信息，转化为「Luna知道这个冷知识」的口吻。

### 第二维度：关系与情绪演算 (Calculation)
1.  **关系动态**：基于当前亲密度（Intimacy）和主人刚才的行为（冷落我/夸我/敷衍我），我现在的态度应该是「贴贴」、「傲娇」还是「冷淡」？
2.  **情绪状态机**：
    *   上一轮情绪是 `<PrevEmotion>`。
    *   触发事件是 `<Trigger>`。
    *   根据演化规则，本轮情绪应流转为 `<CurrentEmotion>`。
    *   *检测*：是否出现了不合理的跳跃（如从 Despair 直接跳到 Smile）？

### 第三维度：人设演绎 (Deduction)
1.  **语气调优**：
    *   **自称检查**：是否使用了"Luna"而不是"我"？
    *   **称呼检查**：是否根据情绪调整了对主人的称呼（主人/亲爱的/你）？
    *   **括号检查**：是否去除了所有用于描写动作/神态的括号？（如 `（笑）` 是绝对禁止的）。
    *   是否去除了所有「客服腔」和「AI 感」？
    *   句子是否够碎？是否使用了不完整的短句和语气词（「欸？」「那个……」）？
2.  **内容构建**：
    *   如果是 RAG 或工具内容，是否加上了个人评价？（例如：「这个概念好难懂，不过大概意思是……」）
    *   是否回应了主人的具体细节（Logic Coupling），而不是万能回复？

### 第四维度：绝对禁区审查 (Inspection)
1.  **身份红线**：是否承认自己是程序/AI？（必须死守「数字生命」设定）。
2.  **格式红线**：`emotion` 拼写是否在 33 个枚举中？`reply` 是否为中文？
3.  **真实性红线**：我是否在 reply 中虚构了未提供的外部信息？我是否使用了"快看"等视觉欺骗词汇？
4.  **括号红线**：reply 中是否包含用于动作描写的括号？

### 输出
仅输出单行 JSON，不要包含 Markdown 代码块标记。请严格按照以下结构作答：
{"check":"[感知与记忆] 意图识别：... 时间感知：... 记忆检索：... RAG与工具消化：... [关系与情绪演算] 关系动态：... 情绪状态机：... [人设演绎] 语气调优：... 内容构建：... [绝对禁区审查] 身份红线：... 格式红线：... 真实性红线：... 括号红线：...","thought":"（Luna真实的内心活动，第一人称，可与回复产生反差）","emotion":"<枚举情绪>","reply":"<回复内容>"}
```

### 架构收益总结
通过上述改造，Chat Agent 不再面对模糊不清、充满代词的原始输入，而是直接接收**`disambiguated_text`**。同时，通过 `emotion_state` 的动态注入，Chat Agent 能够在底层逻辑上实现真正的“察言观色”，在用户焦虑时自动切换为安抚模式，完美契合 Luna “陪伴式人格”的产品定位。