# 后端流式结构化输出解析与断句方案

## 1. 背景与痛点

当前系统在使用大模型（LLM）进行流式输出时，模型返回的是 JSON 字符串的碎片（Chunk）。由于 JSON 结构在流式传输过程中是不完整的，直接将这些碎片透传给前端会导致前端无法进行 `JSON.parse()` 解析，进而引发格式错乱、渲染闪烁以及无法及时提取 `emotion` 字段进行 Live2D 表情同步的问题。

## 2. 目标

在 **Python AI 服务层** 引入流式缓冲（Buffer）与状态机机制，负责“脏活累活”：
1. **提前提取情绪**：在流式输出早期精准捕获 `emotion` 字段，并立即下发，实现音画/神态的零延迟同步。
2. **语义断句**：对 `reply` 字段的内容进行缓冲，按标点符号（如逗号、句号等）进行语义断句，将完整的“小句”作为独立的 Chunk 下发。
3. **保持 Go 层纯粹**：Go 控制面仅负责调度和 WebSocket 透传，不参与复杂的字符串正则解析。

## 3. 核心设计

### 3.1 Prompt 强制顺序约束
为了确保 `emotion` 能够在 `reply` 之前被解析，必须在 System Prompt 中严格约束大模型的 JSON 输出顺序：
```json
{
  "thought": "内部思考过程...",
  "emotion": "Confused",
  "reply": "回复给用户的文本..."
}
```
*注：流式输出是按顺序到达的，保证 `emotion` 在前，可以让我们在文本生成前就触发前端的表情切换。*

### 3.2 Python 层流式解析状态机 (StreamParser)
在 `backend/ai-service/app/llm/` 下实现一个 `StreamParser` 类，维护一个内部 Buffer 和当前解析状态：

- **状态枚举**：`WAITING_THOUGHT`, `WAITING_EMOTION`, `WAITING_REPLY`, `FINISHED`
- **解析逻辑**：
  1. **收集**：将 LLM 返回的 token 追加到内部 Buffer。
  2. **情绪提取**：使用正则或字符串查找，一旦匹配到 `"emotion": "xxx"`，立即提取 `xxx`，并通过 gRPC 发送一个类型为 `emotion_update` 的独立事件。
  3. **标点断句**：当状态进入 `WAITING_REPLY` 时，维护一个 `reply_buffer`。
     - 定义断句标点集合：`['。', '！', '？', '……', '，', '\n']`。
     - 遍历 `reply_buffer`，一旦遇到上述标点，则将**标点及之前的内容**截断，作为一个完整的 `reply_chunk` 发送。
     - 剩余内容保留在 `reply_buffer` 中等待下一个 token。
  4. **收尾**：流结束时，清空并发送 `reply_buffer` 中剩余的所有文本。

### 3.3 gRPC 与 Go 层透传协议调整
Python 到 Go 的 gRPC 流式响应需要支持区分消息类型，Go 到前端的 WebSocket 消息同理。

**gRPC 消息结构示例 (伪代码):**
```protobuf
message ChatStreamResponse {
  string trace_id = 1;
  string type = 2; // "emotion_update" 或 "reply_chunk"
  string content = 3; // 情绪枚举值 或 句子文本
  bool is_finished = 4;
}
```

Go 层收到后，根据 `type` 组装对应的 WebSocket 消息（`WSMessage`）并直接广播给前端，不做额外处理。

## 4. 实施步骤

1. **Phase 1: 协议与 Prompt 更新**
   - 修改 `backend/shared/proto/communication.proto`，增加消息类型字段。
   - 修改 `backend/ai-service/app/agent/prompts.py` 或对应的 `.j2` 模板，强制 JSON 字段输出顺序。
2. **Phase 2: Python 解析器实现**
   - 编写 `StreamParser` 工具类，包含完整的单元测试（模拟 LLM 碎片输入，验证断句和情绪提取的正确性）。
   - 在 `grpc_service.py` 中集成 `StreamParser`。
3. **Phase 3: Go 层适配**
   - 更新 Go 层的 gRPC Client 接收逻辑。
   - 更新 WebSocket 网关的转发逻辑，确保 `emotion_update` 和 `reply_chunk` 能够正确路由到前端。