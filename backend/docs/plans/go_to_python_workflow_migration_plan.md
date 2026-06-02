# Go至Python工作流全面迁移实施方案

## 1. 迁移背景与整体重构目标

### 1.1 迁移背景
在 Luna 项目当前的架构设计中，Go 语言作为“唯一控制权威”负责全局 DAG 工作流的调度与状态机维护，而 Python 仅作为无状态的 AI 推理服务。然而，随着 AI Agent 业务复杂度的急剧提升，这种架构暴露出以下痛点：
1. **AI 生态割裂**：Python 拥有繁荣的 AI 原生工作流生态（如 LangGraph、AutoGen），当前架构无法直接复用这些成熟的图编排、检查点（Checkpoint）和多智能体（Multi-Agent）协作能力。
2. **状态机维护成本极高**：在 Go 中基于 Redis 手动实现复杂的 DAG 拓扑、局部重规划（DFS 遍历失效节点）、中断恢复等逻辑，工程复杂度极高且容易产生状态不一致的 Bug。
3. **动态路由能力受限**：AI 工作流往往需要基于 LLM 的输出进行高度动态的条件路由，静态的 DAG 结构难以满足这种“边执行边规划”的韧性需求。

### 1.2 整体重构目标
本次迁移的核心目标是**将工作流编排与状态控制逻辑全面下沉至 Python 层，彻底拥抱 LangGraph 生态**，具体包括：
1. **调度权转移**：废弃 Go 侧自研的 DAG 调度引擎与 Redis 状态机，由 Python 侧的 LangGraph 接管全局任务编排。
2. **Go 层退化**：Go 语言退化为高性能的 API 网关、WebSocket 代理、系统级资源管理器（如本地文件系统访问）以及前端与 Python 之间的通信桥梁。
3. **状态管理重构**：利用 LangGraph 原生的 `Checkpointer` 机制（基于 PostgreSQL）替代原有的 Redis 细粒度节点状态维护，实现更可靠的断点续传与时间旅行（Time Travel）调试能力。
4. **提升开发效能**：统一 AI 逻辑与编排逻辑的语言栈，大幅降低复杂 Agent 工作流的开发与维护成本。

---

## 2. 现有Go核心逻辑与Python结合LangGraph生态组件的详细映射架构设计

| 现有 Go 核心逻辑 (Current Go Architecture) | Python + LangGraph 目标架构 (Target Python Architecture) | 架构映射说明 |
| :--- | :--- | :--- |
| **DAG 调度器 (Scheduler & Worker Pool)** | **LangGraph `CompiledGraph`** | 原 Go 中的入度计算、Ready 队列调度，完全由 LangGraph 的节点（Nodes）和边（Edges）原生接管。LangGraph 的执行引擎自动处理拓扑排序与并发执行。 |
| **Redis 运行时状态机 (DAG State)** | **LangGraph `Checkpointer`** | 原本在 Redis 中手动维护的节点状态（PENDING, RUNNING, SUCCESS, FAILED），由 LangGraph 的内置状态（State）和持久化检查点自动管理。 |
| **局部重规划 (Local Replanning)** | **动态路由与 `Command` 机制** | 原本需要 Go DFS 找出失效节点再请求 Python 生成新图，现在直接在 LangGraph 中通过条件边（Conditional Edges）捕获异常，并路由至反思节点（Reflection Node）动态修正状态。 |
| **工具网关与权限拦截 (MCP Router & Gating)** | **`ToolNode` + `interrupt_before`** | 工具调用逻辑移至 Python。对于高危工具，利用 LangGraph 的 `interrupt_before` 机制挂起图执行，Go 侧捕获中断事件并向前端发起授权请求，授权后通过 `Command(resume=...)` 恢复执行。 |
| **记忆提交流程化 (Memory Write Commit)** | **状态归约 (Reducer) + 终态回调** | 记忆的暂存和最终提交，通过 LangGraph 的状态归约器（Reducer）收集，并在图的最终节点（End Node）统一执行 DB Commit，确保失败路径不污染记忆。 |
| **WebSocket 状态推送** | **`astream_events` 流式事件代理** | Go 侧不再主动生成状态机事件，而是作为透传代理，将 Python LangGraph 产生的标准流式事件（如 `on_chat_model_stream`, `on_tool_start`）转换为前端协议并推送。 |

---

## 3. 数据结构、状态管理机制及API接口的对齐与调整策略

### 3.1 数据结构对齐
*   **废弃旧表**：逐步废弃 PostgreSQL 中的 `workflow_plans`, `workflow_nodes`, `workflow_edges` 表。
*   **引入新表**：引入 LangGraph 官方支持的 `langgraph-checkpoint-postgres`，自动创建 `checkpoints`, `checkpoint_blobs`, `checkpoint_writes` 等表，用于存储图的执行快照。
*   **状态定义 (State Definition)**：在 Python 侧定义强类型的全局 `AgentState` (基于 `TypedDict` 或 `Pydantic`)，统一管理会话上下文。
    ```python
    from typing import TypedDict, Annotated, List
    from langgraph.graph.message import add_messages
    from langchain_core.messages import BaseMessage

    class AgentState(TypedDict):
        messages: Annotated[List[BaseMessage], add_messages]
        current_plan: str
        memory_staging: dict
        emotion_state: str
        # 其他全局状态...
    ```

### 3.2 状态管理机制调整
*   **从“节点级状态”到“图级快照”**：不再关注单个节点是 PENDING 还是 RUNNING，而是关注整个图在某个时刻的 State 快照。
*   **并发与冲突控制**：利用 LangGraph Checkpointer 的并发控制机制，确保多 Agent 协作或并发工具调用时的数据一致性。

### 3.3 API 接口调整 (gRPC 重构)
*   **统一流式入口**：将原有的 `Chat`, `Replan`, `Summarize` 等零散 gRPC 接口，统一收拢为全双工的流式接口 `StreamGraphExecution`。
    ```protobuf
    // communication.proto
    message GraphExecutionRequest {
        string thread_id = 1; // 对应 LangGraph 的 thread_id
        string input_json = 2; // 用户输入或恢复执行的指令
        string command = 3; // START, RESUME, CANCEL
    }

    message GraphExecutionResponse {
        string event_type = 1; // on_chat_model_stream, on_tool_start, on_node_end 等
        string payload_json = 2; // 事件详情
    }

    service WorkflowService {
        rpc StreamGraphExecution(stream GraphExecutionRequest) returns (stream GraphExecutionResponse);
    }
    ```

---

## 4. Go第三方依赖在Python生态中的最佳替代方案

在将核心逻辑迁移至 Python 后，原 Go 层的部分基础设施依赖需要在 Python 生态中找到最佳替代品，以保证性能与稳定性：

| 领域 | 原 Go 依赖 | Python 生态最佳替代方案 | 替代理由与策略 |
| :--- | :--- | :--- | :--- |
| **数据库 ORM/Driver** | `pgx` / `gorm` | **`asyncpg` + `SQLAlchemy` (Async)** | `asyncpg` 是 Python 生态中最快的 PG 驱动，配合 SQLAlchemy 2.0 的异步特性，可满足高并发状态读写需求。 |
| **状态持久化** | 自研 Redis/PG 逻辑 | **`langgraph-checkpoint-postgres`** | LangGraph 官方维护的异步 PG 检查点库，完美契合图状态的保存与回溯。 |
| **缓存与消息总线** | `go-redis` | **`redis-py` (Asyncio 模式)** | 纯 Python 实现的 Redis 客户端，支持完整的异步 API，用于轻量级缓存和跨进程 Pub/Sub。 |
| **向量数据库** | `qdrant-go` | **`qdrant-client`** | Qdrant 官方 Python 客户端，与 LangChain/LlamaIndex 生态集成度极高，便于实现复杂的 RAG 检索逻辑。 |
| **大模型调用** | 自研统一调用层 | **`langchain-core` / `langchain-openai`** | 直接复用 LangChain 丰富的模型接入层，自带重试、限流、流式解析等完善机制。 |
| **RPC 通信** | `grpc-go` | **`grpcio` + `grpcio-tools` (AsyncIO)** | 保持 gRPC 协议不变，Python 侧使用异步 gRPC Server 承接 Go 网关的请求。 |

---

## 5. 分阶段具体执行步骤

本次迁移涉及底层架构的根本性变动，必须采用**分阶段、双轨并行、逐步替换**的策略，确保系统稳定性。

### Phase 1: 基础设施与环境准备 (Logic Decoupling & Env Setup)
1. **依赖引入**：在 `backend/ai-service/pyproject.toml` 中引入 `langgraph`, `langgraph-checkpoint-postgres`, `asyncpg` 等核心依赖。
2. **数据库初始化**：编写 Python 脚本，初始化 LangGraph 所需的 PostgreSQL Checkpoint 表结构。
3. **gRPC 协议升级**：修改 `communication.proto`，新增 `StreamGraphExecution` 双向流接口，并重新生成 Go 和 Python 的桩代码。
4. **Python 异步基座搭建**：确保 Python FastAPI/gRPC 服务全面采用 `asyncio` 模型，配置合理的连接池（DB/Redis）。

### Phase 2: 核心状态机与图结构重写 (Code Rewriting)
1. **定义 AgentState**：在 Python 侧明确定义全局状态结构 `AgentState`。
2. **构建基础 Graph**：使用 LangGraph 构建基础的对话与工具调用循环（ReAct 模式）。
    *   实现 `AgentNode`（调用 LLM 决定下一步）。
    *   实现 `ToolNode`（执行具体工具）。
    *   配置条件边（判断是继续调用工具还是结束）。
3. **工具迁移**：将原 Go 侧的低危工具（如时间、天气、基础检索）使用 `@tool` 装饰器迁移至 Python 侧。

### Phase 3: 权限管控与中断恢复机制接入 (Gating & Interrupts)
1. **高危工具拦截**：在 LangGraph 中配置 `interrupt_before=["sensitive_tools_node"]`。
2. **Go 侧代理改造**：Go 侧的 gRPC Client 捕获到 Python 抛出的 `__interrupt__` 事件后，将其转换为 WebSocket 消息 `EVT_NODE_AUTH_REQUIRED` 推送给 Electron 前端。
3. **恢复执行链路**：前端用户点击“同意”后，Go 侧通过 gRPC 发送带有 `Command(resume=True)` 的请求，唤醒 Python 侧的 LangGraph 继续执行。

### Phase 4: 记忆系统与复杂 AI 组件接入 (AI Component Integration)
1. **RAG 节点化**：将原有的文档切片、Embedding、检索逻辑封装为 LangGraph 的 `RetrieveNode`。
2. **记忆提交流程**：在 LangGraph 的最终节点（或通过状态 Reducer），实现对 Staging Memory 的真实 DB Commit。
3. **多智能体协作**：利用 LangGraph 的多图嵌套（Subgraphs）或多 Agent 路由机制，重构原有的复杂任务拆解逻辑。

### Phase 5: Go 层退化与测试验收 (Testing & Acceptance)
1. **剥离 Go 侧旧逻辑**：通过特性开关（Feature Flag）关闭 Go 侧的旧版 DAG 引擎和 Redis 状态机。
2. **端到端流式测试**：验证 Electron -> Go (WS) -> Python (LangGraph) -> Go (WS) -> Electron 的全链路流式输出（打字机效果）是否平滑无闪烁。
3. **断点恢复测试**：模拟进程崩溃或强行中断，验证重启后能否通过 `thread_id` 从 PostgreSQL Checkpoint 完美恢复执行现场。

---

## 6. 核心技术难点预判及相应的回滚保障机制

### 6.1 核心技术难点预判

| 难点领域 | 潜在风险 | 应对策略 |
| :--- | :--- | :--- |
| **流式事件解析与延迟** | LangGraph 内部事件极其丰富（Token 级、Node 级、Graph 级），若 Go 侧代理处理不当，会导致前端渲染卡顿或乱序。 | 使用 LangGraph 的 `astream_events(version="v2")` API，在 Python 侧进行事件过滤与聚合，仅将必要的 UI 渲染事件（如 `on_chat_model_stream`, `on_custom_event`）通过 gRPC Stream 推送给 Go。 |
| **本地系统级工具调用** | Python 运行在受限环境中，可能无法直接执行某些需要 OS 级权限的本地操作（如修改系统配置），而这些原本由 Go 负责。 | **反向 RPC 机制**：对于必须由 Go 执行的系统级工具，Python 侧的 Tool 实现为“向 Go 发起 gRPC 请求”，Go 执行完毕后将结果返回给 Python 的 LangGraph 节点。 |
| **并发性能瓶颈** | Python 的 GIL 和异步模型在处理海量并发工作流时，吞吐量可能不及 Go。 | 1. 确保所有 I/O 密集型操作（DB, API）绝对异步化。<br>2. 依赖 PostgreSQL Checkpointer 的行级锁机制，支持未来横向扩展多个 Python Worker 进程。 |

### 6.2 回滚保障机制 (Rollback Strategy)

为了防止迁移过程中出现不可逆的系统崩溃，必须建立完善的回滚机制：

1. **双轨运行架构 (Dual-Track Architecture)**：
    *   在代码层面保留原有的 Go DAG 引擎逻辑。
    *   在 Go 的配置文件（`config.yaml`）中引入全局开关：`workflow.engine: "langgraph" | "legacy_go"`。
    *   API 路由层根据开关决定是将请求交给 Go 内部的 Scheduler，还是通过 gRPC 转发给 Python。
2. **数据物理隔离**：
    *   LangGraph 的状态数据严格写入独立的 `langgraph_*` 系列表中。
    *   绝不修改或复用原有的 `workflow_plans`, `workflow_nodes` 表，确保旧引擎随时可以接管旧数据。
3. **一键降级预案**：
    *   若在生产/测试环境中发现 Python 侧出现严重的内存泄漏或死锁，运维人员只需修改 `config.yaml` 并重启 Go 服务，系统即可瞬间切回旧版 Go 引擎。
    *   *注：切回旧引擎时，正在 LangGraph 中执行的进行中任务（In-flight tasks）将会失败，但系统整体可用性得以保全。*
4. **灰度迁移策略**：
    *   初期仅将“闲聊”和“简单问答”路由至 LangGraph。
    *   待稳定性验证通过后，再逐步将“复杂文档调研”、“多步工具调用”等重度任务迁移至新架构。