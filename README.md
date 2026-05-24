# Luna AI

Luna 是一款本地优先、隐私安全的“陪伴式人格 + 长期记忆 + 主动行为”全栈 AI 桌面助理。其核心不仅是对话，而是建立自然语言理解 → 智能决策 → 工作流规划 → 工具执行 → 状态跟踪 → 长期记忆更新 → 主动交互 → 可恢复执行的完整闭环。

## 项目架构

系统严格实施**三层物理与逻辑解耦**：

1. **前端工程 (Electron + React + TypeScript)**：纯展示与交互层。
2. **后端控制面 (Golang Runtime)**：唯一调度权威，负责工作流、状态机、工具路由和持久化。
3. **AI 智能层 (Python AI Service)**：无状态智能计算，负责大模型接入、RAG、认知推理。

## 目录结构

- `/frontend`: 前端工程
- `/backend/runtime`: Go 控制面
- `/backend/ai-service`: Python AI 智能服务
- `/backend/shared`: 跨后端层共享契约 (Proto, Schemas)
- `agent.md`: 项目级开发约束、协作规范、编码边界

## 开发规范

请严格遵守 `agent.md` 中定义的开发规范与编码红线。
