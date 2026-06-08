## 1. 项目定位

**Luna 是什么：**
Luna 是一款本地优先、隐私安全的"陪伴式人格 + 长期记忆 + 主动行为"全栈 AI 桌面助理。其核心不仅是对话，而是建立自然语言理解 → 智能决策 → 工作流规划 → 工具执行 → 状态跟踪 → 长期记忆更新 → 主动交互 → 可恢复执行的完整闭环。

**Luna 不是什么：**

- **不是一个简单的 ChatBot 壳**：Luna 底层由强一致性的 DAG 任务状态机驱动。
- **不是一个云端 SaaS 平台**：Luna 强制本地优先，数据与敏感配置落盘本地。
- **不是一个纯 LLM 调用脚本**：系统采用 Python 统一控制面架构，严禁将复杂的任务调度、状态维持、工具权限审核散落在前端或其他不可控位置。

## 2. 面向人群

**产品的目标用户群：**
Luna 面向**普通个人本地使用，而不是企业使用**。

- 核心场景为个人电脑（Windows/macOS）桌面环境的长程陪伴与个人事务助理。
- 架构设计优先考虑个人设备的单机隔离性、本地存储的隐私性以及桌面端原生的交互体验，不涉及复杂的多租户（SaaS）、企业级 RBAC 权限或高并发集群部署场景。

*(注：参与本项目的开发人员、AI 代码代理在做技术选型时，必须以"单机桌面级运行效率与数据绝对控制权"为第一考量。)*

## 3. 使用的技术栈及其版本

> **假设：** 考虑到本地化桌面系统的兼容性与长期可维护性，以下为项目当前假定的核心技术栈及稳定版本基线。开发时需严格遵循此版本约束，禁止引入过于激进或已被废弃的依赖。

### 3.1 后端服务 (Python AI Service) - 统一控制与智能层

- **Python**: `>= 3.10` (强依赖 Type Hints 与现代 asyncio)。
- **API 框架**: `FastAPI 0.110+` (提供 HTTP 与 WebSocket/SSE 接口)。
- **持久化**: `PostgreSQL 15+` (个人本地默认主存储，用于配置、记忆、状态落盘)。
- **状态流转**: `Redis 7.0+` (本地运行，用于工作流状态同步、短期记忆与 Event Bus)。
- **AI 编排**: `LangGraph` (用于构建认知推理流与工作流调度)。
- **向量数据库**: `Qdrant 1.8+` (本地轻量化运行，用于长短期记忆检索)。
- **模型接口**: 严格遵循 OpenAI Compatible API 标准。
- **跨进程通信**: `WebSocket` / `SSE` / `HTTP` (与 Electron 通信)。

### 3.2 桌面端 (Electron UI) - 交互与渲染

- **Electron**: `30.x` 版本。
- **前端栈**: `React 18.x` + `TypeScript 5.x`。
- **状态管理**: `Zustand 4.x` (支持高频局部更新)。
- **多模态表现**: `Cubism WebGL SDK 4.x` (Live2D 渲染)，结合 Web Audio API 实现 TTS 同步。

## 4. 项目目录结构

系统实施**前后端物理与逻辑解耦**。

```text
/LUNA V3
├── /frontend                          # 前端工程：Electron + React + TypeScript
│   ├── /docs                          # 前端相关系统设计文档、交互规范、渲染协议说明
│   │   ├── /plans                     # 前端具体实施方案、页面拆分、交互实现计划
│   │   └── /system                    # 前端架构设计方案
│   ├── /src                           # 前端源码
│   │   ├── /main                      # Electron 主进程：窗口、托盘、系统能力桥接
│   │   ├── /renderer                  # 渲染进程：UI、Live2D、状态展示、WS 监听
│   │   └── /shared                    # 前端共享类型、消息类型、UI 公共逻辑
│   └── (约束)                         # 纯展示与交互层。禁止直接访问本地 DB、Redis
│
├── /backend                           # 后端工程：Python AI 服务
│   ├── /docs                          # 后端系统架构设计文档、协议说明、状态机设计
│   │   ├── /plans                     # 后端具体实施方案、阶段拆分、接口实现计划
│   │   └── /system                    # 后端架构设计方案
│   ├── /ai-service                    # Python AI 智能服务与控制面
│   │   ├── /app/llm                   # 模型接入、流式输出、限流重试
│   │   ├── /app/rag                   # 检索、切片、Embedding、Rerank
│   │   ├── /app/agent                 # 认知推理流、结构化输出、意图解析、工作流调度
│   │   ├── /app/api                   # FastAPI 接口层 (HTTP/WS/SSE)
│   │   ├── /app/memory                # 记忆管理、落盘、检索
│   │   ├── /app/mcp                   # 工具路由、权限网关、Gating
│   │   ├── /app/state                 # 状态机管理 (WSM/ESM)
│   │   └── /app/config                # 统一配置管理与密钥管理
│   └── (约束)                         # Python 是唯一控制权威与智能提供者
│
└── agent.md                           # 项目级开发约束、协作规范、编码边界
```

## 5. 开发阶段

| 所属卷              | 阶段                             | 目标                                 | 行动内容 (已优化)                                                                                                                                                                                                                                                             | 退出标准                                                                                 | 备注 / 注意                                                 | 状态                              | 涉及文档 |
|:---------------- |:------------------------------ |:---------------------------------- |:---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |:------------------------------------------------------------------------------------ |:------------------------------------------------------- |:------------------------------- |:----------------------------- |
| **卷一：工程底座与前后端打通** | **Phase 0：工程规范与运行基线**          | 先把项目能"按统一规则开发、调试、追踪"建立起来。          | • 统一仓库结构与模块边界，确立 Python Backend 为全局配置与状态的唯一事实来源 (SSOT)。<br>• 定义基础静态环境配置 (`.env` / `config.yaml`) 解析方式。<br>• 约定日志格式与贯穿全链路的 TraceID 下发规范。<br>• 约定错误码规范、结构化 JSON 响应约束及状态枚举。<br>• 明确前后端严格调用边界。<br>• 建立本地开发启动方式与多层健康检查协议。                       | • 前后端团队按照同一套规范开发，不需要口头约定接口格式<br>• 任何请求都能携带 trace_id 并在日志中查到完整链路<br>• 项目可以一键启动本地最小开发环境 | **为什么先做这个**：后面所有阶段都会依赖协议、日志、配置、错误码。如果不先统一，后续每加能力必生兼容问题。 | 已完成                             | [`backend/docs/system/配置与环境管理方案.md`](backend/docs/system/配置与环境管理方案.md)<br>[`backend/docs/system/日志、监控与审计方案.md`](backend/docs/system/日志、监控与审计方案.md)<br>[`frontend/docs/system/桌面端交互与前端架构方案.md`](frontend/docs/system/桌面端交互与前端架构方案.md) |
|                  | **Phase 1：前后端通信骨架打通**           | 跑通 Electron → Python 的最小通信链路。 | • Electron 启动并建立到 Python 的 WebSocket/SSE 单向数据流连接。<br>• 定义最小消息协议：Ping / Pong / Error / Health。<br>• 本地 Redis、PostgreSQL 完成基础可用部署（暂不涉及复杂业务建表）。<br>• 前后端都能健康检查联调，确保连通性。                                                         | • 前端发一个 Ping<br>• Python 回 PONG<br>• 前端 UI 能显示 PONG            | **注意**：这一步只验证链路，不做任何智能、不做任何状态机、不做任何记忆。                  | 已完成                             | [`backend/docs/system/数据存储与同步方案.md`](backend/docs/system/数据存储与同步方案.md)<br>[`backend/docs/system/日志、监控与审计方案.md`](backend/docs/system/日志、监控与审计方案.md)<br>[`frontend/docs/system/桌面端交互与前端架构方案.md`](frontend/docs/system/桌面端交互与前端架构方案.md) |
|                  | **Phase 2：基础流式问答能力**           | 先把"能像聊天产品一样说话"做出来。                 | • Python 接入统一大模型调用层（OpenAI Compatible API），屏蔽底层厂商差异。<br>• 支持本地 vLLM/Ollama 与云端 API 切换，内置基础重试机制。<br>• Python 负责流式代理、消息转发及 TTFT（首字延迟）核心指标记录。<br>• Electron 依据 Python 下发的 `CurrentNodeId` 负责气泡流式渲染。<br>• 统一流式消息结构与结束标记，强制要求 Python 侧通过 Pydantic 校验 JSON 结构化输出。<br>• 设计结构化核心系统提示词，明确 Luna 角色定位、任务目标、回复风格和行为约束。<br>• 实现多轮对话上下文历史记录管理与 Token 边界截断策略。<br>• 实现流式输出缓冲平滑机制（合并小 Token 为语义完整的短句后输出）。<br>• 实现网络异常及中断的分层捕获与容错处理。 | • 可以稳定进行普通 LLM 对话<br>• 支持流式输出<br>• 支持多轮对话上下文感知<br>• 支持 Token 边界截断<br>• 流式输出平滑，前端无逐字闪烁<br>• 网络中断有友好降级提示<br>• 不接工具、不接记忆、不接 RAG                                  | **为什么重要**：验证的是"AI 输入输出管道"是否稳定，而不是智能是否足够复杂。              | 已完成（增强）                             | [`backend/docs/system/大模型接入与统一调用层设计.md`](backend/docs/system/大模型接入与统一调用层设计.md)<br>[`frontend/docs/system/桌面端交互与前端架构方案.md`](frontend/docs/system/桌面端交互与前端架构方案.md)<br>[`backend/docs/plans/phase2_plan.md`](backend/docs/plans/phase2_plan.md) |
|                  | **Phase 3：配置、Prompt 与密钥管理**    | 消除硬编码，让系统具备可配置能力。                  | • 引入 OS Keychain 存储主密钥，结合 AES-256-GCM 在 PostgreSQL 中加密存储 API Key。<br>• PostgreSQL 存储 Prompt 模板与模型动态配置，实现 Append-Only 历史版本记录快照。<br>• Python 维护 ConfigManager，通过内部 Event Bus 分发配置变更事件。<br>• Python 层实现热重载配置，实现动静分离。<br>• 先实现 JSON/YAML MVP 版本的 Prompt 插槽装配，再向数据库迁移。 | • 前端修改系统 Prompt 后下一次对话立即生效<br>• 无需重启整个系统<br>• 敏感信息不落明文                               | **注意**：Prompt 版本必须可回滚，不能只保留"当前值"。                       | 已完成                             | [`backend/docs/system/配置与环境管理方案.md`](backend/docs/system/配置与环境管理方案.md)<br>[`backend/docs/system/PromptTemplate 与提示词版本管理方案.md`](backend/docs/system/PromptTemplate%20与提示词版本管理方案.md)<br>[`backend/docs/system/权限与安全方案.md`](backend/docs/system/权限与安全方案.md) |
|                  | **Phase 4：最小可观测性与审计链路**        | 让系统从一开始就能被追踪。                      | • TraceID (`InteractionID`) 贯穿前后端全链路。<br>• 记录请求入站、模型调用（含 TTFT 与耗时预估）、工具调用、状态变化。<br>• PostgreSQL 引入 `audit_logs` 表，结合 WAL 机制记录防篡改的关键审计事件。<br>• Python 侧输出日志强制对敏感信息进行 Regex 脱敏（替换为 `[REDACTED]`）。<br>• 在 Electron 提供基础调试面板，支持按 TraceID 查询链路。                                  | • 任意请求都能查到完整生命周期<br>• 能定位失败源头（前端/Python/模型）<br>• 后续排障不需要猜                         | **为什么放这里**：可观测性拖到最后会让后续加能力变成黑盒，必须提前。                    | 已完成                             | [`backend/docs/system/日志、监控与审计方案.md`](backend/docs/system/日志、监控与审计方案.md)<br>[`backend/docs/system/权限与安全方案.md`](backend/docs/system/权限与安全方案.md)<br>[`frontend/docs/system/桌面端交互与前端架构方案.md`](frontend/docs/system/桌面端交互与前端架构方案.md) |
| **卷二：记忆与知识底座**   | **Phase 5：短期会话记忆与上下文窗口管理**     | 先让系统记住"当前会话正在发生什么"。                | • Redis 维护短期上下文窗口，隔离日常闲聊与任务执行日志。<br>• 记录最近消息、临时状态、当前任务上下文。<br>• 定义上下文过长时的裁剪策略，防止 Token 溢出导致注意力丢失。<br>• 支持会话恢复时的最小上下文重建，基于 Python 引擎的最新会话拉取请求。                                                                                                                              | • 对话中系统能正确引用前文<br>• 重启后会话短期上下文可按策略恢复<br>• 上下文不会无限膨胀                                  | **注意**：短期记忆不等于长期记忆，不要混用。                                | 已完成                             | [`backend/docs/system/多层记忆系统设计.md`](backend/docs/system/多层记忆系统设计.md)<br>[`backend/docs/system/数据存储与同步方案.md`](backend/docs/system/数据存储与同步方案.md) |
|                  | **Phase 6：长期记忆写入与恢复**          | 让系统真正"记得住"。                        | • Python (`AnalyzeMemory`) 负责记忆提取、冲突对比、结构化更新指令生成。<br>• Python 负责 Memory Write Commit 的事务落盘，执行软删除或追加到 PostgreSQL。<br>• 实现关系型 PostgreSQL 与向量库 Qdrant 的同步写入，Python 提供降级重试防脑裂。<br>• 定义记忆写入的用户授权确认条件（Gating）、去重策略与版本回溯能力。                                                                   | • 告知偏好后，重启系统仍能识别并记住<br>• 记忆写入可追溯、可撤销、可更新                                             | **关键原则**：长期记忆不能由模型"想写就写"，必须经过 Python 的提交控制。                 | 已完成                             | [`backend/docs/system/多层记忆系统设计.md`](backend/docs/system/多层记忆系统设计.md)<br>[`backend/docs/system/数据存储与同步方案.md`](backend/docs/system/数据存储与同步方案.md)<br>[`backend/docs/system/用户画像与偏好建模方案.md`](backend/docs/system/用户画像与偏好建模方案.md) |
|                  | **Phase 7：RAG 知识检索增强**         | 让系统能基于外部知识回答问题。                    | • 部署本地 Qdrant，打通文档切片、Embedding、检索流程。<br>• 实现动态 RAG 路由机制：按需划分为 Search、Modular 与 Agentic 检索。<br>• Python 工作流中维护 RAG 子图（Sub-DAG）状态机。<br>• Python 负责实际检索与融合，合并各源的 Evidence 及置信度并注入 Prompt。                                                                                | • 导入文档后可回答具体问题<br>• 答案能引用检索结果<br>• 低相关结果不会污染最终回答                                     | **注意**：RAG 是"证据注入"，不是"记忆替代"。                            | 已完成                             | [`backend/docs/system/知识库检索增强生成方案.md`](backend/docs/system/知识库检索增强生成方案.md)<br>[`backend/docs/system/多层记忆系统设计.md`](backend/docs/system/多层记忆系统设计.md) |
|                  | **Phase 8：上下文治理与摘要压缩**         | 解决长对话、长任务导致的上下文污染。                 | • Python 侧串联 Multi-Agent 上下文治理流水线（提取、过滤、融合、压缩）。<br>• Python 负责状态机推进，保存中间态，推送"治理进度"提示给前端。<br>• 将"最近意图"与"历史资料"分层保存，消除 GIGO 效应。<br>• 对超长聊天做冗余裁剪，单独记录中间 Prompt 载荷和 Token 压缩率审计。                                                                                                | • 冗余长记录输入也能抓住最新意图<br>• 旧信息不会压倒新信息<br>• 压缩过程可回放、可审计                                   | **顺序原因**：先有记忆与 RAG，才知道该保留和压缩什么。                         | 未完成                             | [`backend/docs/system/多智能体协作与角色分工方案.md`](backend/docs/system/多智能体协作与角色分工方案.md)<br>[`backend/docs/system/多层记忆系统设计.md`](backend/docs/system/多层记忆系统设计.md) |
| **卷三：工作流与状态控制**  | **Phase 9：DAG 工作流内核**          | 让系统具备多步规划与可执行能力。                   | • Python 实现执行容器：Plan、Phase、Node。<br>• 基于 Redis 维护 DAG 拓扑及入度状态，Worker Pool 调度 Pending 节点。<br>• 打通 Python 局部重规划接口，节点失败时由 Python DFS 计算受影响子图并由 LLM 修剪。<br>• 异步通过 Event Bus 将状态机流转 Write-Behind 持久化。                                                                             | • Python 返回 3 个顺序节点 JSON<br>• Python 能按依赖顺序执行<br>• 节点状态成功流转                              | **注意**：先不追求复杂容错，先把"能跑起来"做对。                             | 未完成                             | [`backend/docs/system/DAG 编排方案.md`](backend/docs/system/DAG%20编排方案.md)<br>[`backend/docs/system/数据存储与同步方案.md`](backend/docs/system/数据存储与同步方案.md) |
|                  | **Phase 10：任务状态机与中断恢复**        | 让任务不仅能跑，还能停、能恢复、能回滚。               | • Python 建立完备的任务状态机，映射 DAG 节点流转的可能状态。<br>• 支持任务级别的超时控制、手动取消与自动补偿策略。<br>• 将 Plan 运行时快照定期异步持久化到 PostgreSQL。<br>• 恢复时加载序列化上下文，实现从断点节点的无缝拉起。                                                                                                                                       | • 任务中断后可恢复<br>• 超时能正确终止<br>• 不出现"半死不活"状态                                             | **独立成段**：DAG 解决"怎么排"，状态机解决"怎么活"。                        | 未完成                             | [`backend/docs/system/DAG 编排方案.md`](backend/docs/system/DAG%20编排方案.md)<br>[`backend/docs/system/工作状态机与情绪状态机方案.md`](backend/docs/system/工作状态机与情绪状态机方案.md) |
|                  | **Phase 11：工作与情绪状态双轨治理**       | 让系统懂"继续、暂停还是安抚"。                   | • 实现调度引擎中 WSM（工作状态）与 ESM（情绪状态）物理与逻辑双解耦。<br>• Python 触发情感事件，捕捉状态跃迁（如怒气）。<br>• 高危情绪下，Python 冻结当前工具执行上下文，拒绝暴露高危 Tool。<br>• 情绪安抚结束后，支持从 Snapshot 恢复原有工作流。                                                                                                          | • AI 跑长任务时用户叫停能立即冻结<br>• 进入安抚态，不硬跑                                                   | **注意**：情绪状态是主动行为的安全闸门，不是装饰。                             | 未完成                             | [`backend/docs/system/工作状态机与情绪状态机方案.md`](backend/docs/system/工作状态机与情绪状态机方案.md)<br>[`backend/docs/system/DAG 编排方案.md`](backend/docs/system/DAG%20编排方案.md) |
| **卷四：工具与治理**     | **Phase 12：MCP 工具协议与基础接入**     | 打通标准化工具调用。                         | • Python 实现独立工具路由与执行网关，作为副作用操作唯一入口。<br>• 定义标准化 MCP 工具注册、模式校验与三阶段路由协议。<br>• 接入 L0 级低危工具（时间、天气、读取）。<br>• 工具执行结果序列化回传给 Python 工作流引擎并投递至下游节点。                                                                                                                                      | • AI 自主调用低危工具并回答<br>• 工具调用有完整记录<br>• 不绕过 Python 控制面                                      | **注意**：工具不能由模型直调，必须过 Python Gateway。                        | 未完成                             | [`backend/docs/system/工具协议与 MCP 能力接入方案.md`](backend/docs/system/工具协议与%20MCP%20能力接入方案.md)<br>[`backend/docs/system/权限与安全方案.md`](backend/docs/system/权限与安全方案.md) |
|                  | **Phase 13：权限治理与前端 Gating**    | 让高危工具必须经过用户确认。                     | • 对工具按 RiskLevel 进行强管控标记（L0 到 L3 级）。<br>• 执行到 L2 高危操作时，Python 拦截并挂起 DAG，进入审批态。<br>• 通过 WebSocket/SSE 向 Electron 推送请求，弹出 Gating 确认窗口。<br>• 用户拒绝即终止，同意则 Python 恢复执行，全程写防抵赖日志。                                                                                                        | • 敏感/高危操作均能正确拦截弹窗<br>• 拒绝不误执行<br>• 审计链路准确记录                                          | **为什么放这里**：有主动执行能力前必须先有管控，否则是风险放大器。                     | 未完成                             | [`backend/docs/system/权限与安全方案.md`](backend/docs/system/权限与安全方案.md)<br>[`backend/docs/system/工具协议与 MCP 能力接入方案.md`](backend/docs/system/工具协议与%20MCP%20能力接入方案.md)<br>[`frontend/docs/system/桌面端交互与前端架构方案.md`](frontend/docs/system/桌面端交互与前端架构方案.md) |
|                  | **Phase 14：审计回放、DevTools 与调试** | 让每一步可解释、可回放、可排障。                   | • 前端 UI 提供基于 TraceID 的完整链路回放。<br>• 展示节点输入输出耗时，及被重规划修剪掉的失效子图。<br>• 开发 Context Visualizer 直观呈现 Prompt 载荷和 Chunk 过滤。<br>• 集成 PostgreSQL 审计回看，展示参数与 Gating 记录。                                                                                                                 | • 任务结束后能在 UI 回看全流程<br>• 快速定位卡点<br>• 支持后续问题复盘                                         | **说明**：不是锦上添花，是系统持续迭代的底层刚需。                             | 未完成                             | [`backend/docs/system/日志、监控与审计方案.md`](backend/docs/system/日志、监控与审计方案.md)<br>[`backend/docs/system/权限与安全方案.md`](backend/docs/system/权限与安全方案.md)<br>[`frontend/docs/system/桌面端交互与前端架构方案.md`](frontend/docs/system/桌面端交互与前端架构方案.md) |
| **卷五：协作、主动与表现**  | **Phase 15：多 Agent 协作与上下文共享**  | 具备角色分工与冲突控制能力。                     | • 前端支持多 Agent 任务区的多实例渲染与高亮。<br>• Python 管控长短期上下文在多 Agent 间的隔离与暴露边界。<br>• Python 作为权威控制台监测多 Agent 争抢全局资源（如音频）冲突。<br>• 资源冲突时向前端发 `EVT_NODE_AUTH_REQUIRED` 让用户仲裁。                                                                                                                 | • 多 Agent 协作完成复杂任务<br>• 不互相污染上下文<br>• 冲突有明确仲裁                                        | **注意**：重点是治理上下文与职责边界。                                   | 未完成                             | [`backend/docs/system/多智能体协作与角色分工方案.md`](backend/docs/system/多智能体协作与角色分工方案.md)<br>[`backend/docs/system/多层记忆系统设计.md`](backend/docs/system/多层记忆系统设计.md) |
|                  | **Phase 16：主动感知与后台任务**         | 突破"一问一答"，能在后台主动做事。                 | • 监测 OS 空闲状态或剪贴板变化并上报。<br>• Python 实现基于 Redis Token Bucket 的速率限制与静默期检测。<br>• Python 提供评估规划，输出是否打扰的决定及解释。<br>• 涉高危工具的主动计划，Python 直接拦截转为前端无声待办卡片。                                                                                                                                | • 空闲后能自动总结/提醒<br>• 主动行为不打扰用户<br>• 支持用户限制主动模式                                         | **关键点**：主动行为必须受治理，防变"打扰"。                               | 未完成                             | [`backend/docs/system/主动感知与自主行动机制.md`](backend/docs/system/主动感知与自主行动机制.md)<br>[`backend/docs/system/工具协议与 MCP 能力接入方案.md`](backend/docs/system/工具协议与%20MCP%20能力接入方案.md)<br>[`backend/docs/system/工作状态机与情绪状态机方案.md`](backend/docs/system/工作状态机与情绪状态机方案.md) |
|                  | **Phase 17：Live2D、TTS 与多模态表现** | 让系统具备陪伴感和表达力。                      | • 前端初始化 PIXI 引擎与 Live2D，建立防白屏兜底策略。<br>• Python 解析音文本流，下发嘴型计算同步指令。<br>• Python 定时下发指令维持待机视线追踪等轻微活动。<br>• 支持情绪骤变响应，强制打断轻巧动作并在 200ms 内淡入表情动作。                                                                                                                                     | • 输出时角色张嘴说话<br>• 情绪语义触发对应动作<br>• 视觉与状态机一致                                            | **为什么放最后**：体验层增强，不影响正确性但提升完整感。                          | 未完成                             | [`frontend/docs/system/Live2D 角色渲染与多模态表现方案.md`](frontend/docs/system/Live2D%20角色渲染与多模态表现方案.md)<br>[`frontend/docs/system/桌面端交互与前端架构方案.md`](frontend/docs/system/桌面端交互与前端架构方案.md)<br>[`backend/docs/system/工作状态机与情绪状态机方案.md`](backend/docs/system/工作状态机与情绪状态机方案.md) |

## 6. 编码注意事项

### 6.1 工程纪律与编码红线（强制）

1. **禁止硬编码魔法字符串**
   所有事件名、状态码、动作指令、错误码、工具名必须定义为统一常量。
2. **所有枚举与常量集中管理**
   * Python：`constants.py` 或 `types/`
   * TypeScript：`enum.ts`
   * 跨层状态统一通过 Schema 同步。
3. **禁止占位实现伪造成功**
   禁止提交 `pass`、空实现、假成功返回；未实现功能必须抛 `NotImplementedError` 或返回明确错误码。
4. **禁止假设输入合法**
   所有输入必须做判空、类型校验、Schema 校验、长度限制、枚举检查。
5. **必须使用中文详细注释（强制）**
   每个类、方法、接口、关键逻辑块、状态流转、并发控制、异常处理都必须写中文注释，说明：
   * 做什么
   * 为什么这样做
   * 输入输出
   * 边界条件
   * 异常行为
6. **注释必须与代码同步更新**
   修改逻辑、协议、状态流转、错误码时必须同步更新注释，过期注释视为缺陷。
7. **所有异步逻辑必须声明生命周期**
   必须明确：
   * 谁创建
   * 谁取消
   * 谁回收
   * 超时策略
   * 重试次数
   * 降级方案
8. **所有跨层通信必须版本化**
   必须包含 `schema_version`，禁止静默破坏兼容性。
9. **所有状态迁移必须显式记录**
   必须记录：
   `from -> to`、触发原因、trace_id、task_id。
10. **所有异常必须可恢复或可解释**
    必须明确：
    * 是否可重试
    * 是否可回滚
    * 是否需人工确认
11. **禁止跨层职责污染**
    * Electron 禁止调度 / Memory Commit / Tool Execution
    * Python 负责全局调度、状态维持、工具权限审核与智能推理
12. **所有关键链路必须可审计**
    日志必须带：
    `trace_id`、`task_id`、`node_id`、`latency_ms`、`retry_count`
13. **所有提交必须满足可恢复原则**
    崩溃后必须支持：
    * 状态恢复
    * 任务续跑
    * SQL / Redis 状态重建
14. **接口契约优先于临时联调**
    禁止先写代码后补协议；必须先定义 Schema。
15. **禁止提交调试残留**
    包括：
    * `console.log`
    * `print`
    * 临时 mock
    * 测试账号 / 密钥
    * 本地路径硬编码
16. **复杂逻辑必须先写设计再编码**
    涉及 DAG、状态机、工具调用、记忆写入、多 Agent 协作时，必须先补设计文档再实现。
17. **日志语言规范**
    * 所有日志必须使用 `logger`（Python logging），禁止使用 `print` 或 `console.log`。
    * 所有日志 msg 必须使用简体中文，禁止使用英文。
18. **参考系统设计文档**
    编码时请参考 `backend/docs/system` 和 `frontend/docs/system`。
19. **不要强调兼容性和扩展性**
    以可读性为最优先，不要过度强调代码的兼容性和扩展性。
20. **所有业务和实体的 ID 生成必须统一使用雪花算法（Snowflake），禁止使用 UUID（强制）**
    *   所有涉及主键、唯一标识生成的场景（包括但不限于：消息 ID、会话 ID、任务 ID、节点 ID、记忆 ID、工具调用日志 ID、Trace ID 等），必须使用项目提供的统一雪花算法生成器。
    *   **Python 层**：使用 `app/utils/snowflake.py` 的 `generate_id()`（返回 `int`）或 `generate_string_id()`（返回 `str`）。
    *   **TypeScript 层**：使用 `frontend/src/shared/utils/snowflake.ts` 的 `generateId()`（返回 `string`）。
    *   禁止直接使用 `crypto.randomUUID()`、`uuid.uuid4()`、`Date.now()` 拼接字符串等方式生成 ID。
    *   所有数据库中 ID 字段类型使用 `VARCHAR(64)` 或 `BIGINT`，禁止使用 `UUID` 类型。

### 6.2 职责与边界约束

1. **调度逻辑绝对收口**：禁止把任务状态、调度逻辑散落在前端 React 组件中。Python 是唯一的 Single Source of Truth。前端看到的状态只是 Python 通过 WebSocket/SSE 推送的镜像。
2. **禁止越级调用**：前端绝不允许直接访问大模型 API。一切交互必须经由 Python API 网关流转。
3. **接口契约至上**：禁止在没有 JSON Schema 定义的情况下直接修改接口参数进行"临时联调"。

### 6.3 健壮性与异步处理

1. **异步控制流**：Python 中的所有 Worker 和任务流必须绑定 `asyncio` 的超时控制，保证超时、用户中断时能立刻回收资源。必须配置 `timeout` 和连接池限制。
2. **AI 输出兜底**：所有 Python 对大模型的调用必须附带结构化约束 (JSON Schema)。若解析失败，必须有重试或降级策略，绝不能将崩溃异常直接抛出引发系统瘫痪。
3. **可恢复机制**：所有执行的任务节点需将状态写入 Redis/PostgreSQL。如果系统强行断电，再次启动时 Python 必须能从快照（Snapshot）中恢复 DAG。

### 6.4 安全与治理

1. **隐私边界**：坚守本地优先。所有用户的配置、长期记忆、密钥必须保存在本地 PostgreSQL（推荐 OS Keychain 加密），严禁打印敏感凭证到日志中。
2. **主动行为边界**：AI 主动发起的任何操作，若涉及修改/删除文件、网络请求等高风险动作，Python 必须强行挂起任务（`PENDING_USER_APPROVAL`），并要求前端展示授权卡片，未获用户授权绝不允许放行。
3. **长期记忆一致性**：任务执行中产生的"事实记忆"和"用户偏好"更新，必须暂存于 Staging 区，只有当工作流最终标记为 `SUCCESS` 时才能提交到数据库，防止错误路径污染记忆。

### 6.5 可观测性与调试

1. **全链路追踪**：所有日志必须强绑定关键标识符，打印格式需包含 `[TraceID:xxx] [TaskID:xxx] [NodeID:xxx]`。
2. **错误处理**：Python 中禁止使用 `pass` 吞掉错误。所有上抛的 Exception 必须包含当前操作上下文。
3. **调试建议**：建议开发者在 Python 层开启详细的 Event Log，通过前端的 Debug Console 直观查看状态机跃迁，定位问题时优先排查 Redis 中的 DAG 树结构是否符合预期。

### 6.6 文件编码规范

1. **强制 UTF-8 编码**：所有源代码文件、配置文件、文档（包括 Markdown）必须使用 UTF-8 编码保存，禁止使用 GBK 或其他编码格式，以防止跨平台或跨语言解析时出现乱码。
