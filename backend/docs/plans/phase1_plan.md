# Phase 1: 三层通信骨架打通架构设计方案

## 1. 目标
跑通 Electron (前端) → Go (控制面) → Python (AI 服务) 的最小通信链路，验证三层架构的连通性。本阶段**不涉及**任何智能逻辑、状态机流转或记忆存储，仅聚焦于基础通信协议的建立与验证。

## 2. 职责边界

### 2.1 Electron 前端 (UI 层)
- **职责**: 负责建立与 Go 控制面的 WebSocket 连接，发送基础指令，并渲染接收到的响应。
- **约束**: 绝对禁止直连 Python AI 服务或本地数据库。所有通信必须通过 Go WebSocket 网关。

### 2.2 Go 控制面 (Runtime 层)
- **职责**: 作为全局通信枢纽。
  - 提供 WebSocket 服务供前端连接。
  - 提供 gRPC/HTTP 客户端调用 Python AI 服务。
  - 负责消息的路由与透传。
- **约束**: Go 是唯一控制权威，负责维护连接状态和请求上下文 (TraceID)。

### 2.3 Python AI 服务 (智能层)
- **职责**: 提供 gRPC/HTTP 服务端，接收来自 Go 的请求，执行无状态的简单逻辑（如 Ping/Pong 响应）并返回结果。
- **约束**: 保持无状态，不持有全局调度权，仅响应 Go 的调用。

## 3. 上下游数据流转链路

### 3.1 Ping/Pong 链路 (核心验证场景)
1. **前端发起**: Electron 客户端通过 WebSocket 向 Go 发送 `Ping` 消息，消息体包含生成的 `trace_id`。
2. **Go 接收与转发**: Go WebSocket 网关接收到消息，解析出 `trace_id`，将其注入到 gRPC/HTTP 请求上下文中，向 Python 服务发起 `Ping` RPC 调用。
3. **Python 处理与响应**: Python 服务接收到请求，提取 `trace_id` 记录日志，并返回 `Pong` 响应。
4. **Go 接收与推送**: Go 接收到 Python 的响应，将其封装为 WebSocket 消息，推送回 Electron 客户端。
5. **前端渲染**: Electron 客户端接收到 `Pong` 消息，在 UI 上展示。

### 3.2 健康检查链路
- **前端**: 定期向 Go 发送 WebSocket 心跳 (Ping) 维持连接。
- **Go**: 提供 HTTP `/health` 接口供外部监控，同时内部定期检查与 Python 服务的 gRPC/HTTP 连接状态。
- **Python**: 提供 HTTP `/health` 或 gRPC Health Check 接口供 Go 检查。

## 4. 核心接口定义规范

### 4.1 WebSocket 消息规范 (Electron <-> Go)
所有 WebSocket 消息必须遵循统一的 JSON Schema。

**基础消息结构**:
```json
{
  "type": "string",      // 消息类型，如 "PING", "PONG", "ERROR"
  "trace_id": "string",  // 贯穿全链路的唯一标识
  "payload": "object"    // 消息体，根据 type 变化
}
```

**Ping 消息**:
```json
{
  "type": "PING",
  "trace_id": "req-12345",
  "payload": {
    "timestamp": 1678886400000
  }
}
```

**Pong 消息**:
```json
{
  "type": "PONG",
  "trace_id": "req-12345",
  "payload": {
    "timestamp": 1678886400100,
    "source": "python-ai-service"
  }
}
```

**Error 消息**:
```json
{
  "type": "ERROR",
  "trace_id": "req-12345",
  "payload": {
    "code": 3001,
    "message": "Python service unavailable"
  }
}
```

### 4.2 gRPC 接口规范 (Go <-> Python)
定义 `shared/proto/communication.proto`。

```protobuf
syntax = "proto3";

package communication;
option go_package = "luna/shared/proto/communication";

message PingRequest {
  string trace_id = 1;
  int64 timestamp = 2;
}

message PongResponse {
  string trace_id = 1;
  int64 timestamp = 2;
  string source = 3;
}

service CommunicationService {
  rpc Ping(PingRequest) returns (PongResponse);
}
```

## 5. 底层通信异常处理机制

### 5.1 WebSocket 异常 (Electron <-> Go)
- **连接断开**: 前端需实现指数退避的自动重连机制。Go 端需清理断开连接的会话资源。
- **消息解析失败**: Go 端若收到格式不合法的 JSON，需返回 `ERROR` 消息（包含错误码和原因），并记录日志，不中断连接。

### 5.2 RPC 异常 (Go <-> Python)
- **调用超时**: Go 调用 Python 必须设置 Context 超时时间（如 5 秒）。超时后，Go 需向前端返回 `ERROR` 消息。
- **服务不可用**: 若 Python 服务宕机，Go 的 gRPC 客户端需实现重试机制（如重试 3 次）。若最终失败，向前端返回 `ERROR` 消息。
- **错误透传**: Python 端发生的内部错误，需封装为标准的 gRPC 错误码返回给 Go，Go 再将其转换为 WebSocket `ERROR` 消息推送给前端。

## 6. 基础设施部署
- **Redis**: 本地启动 Redis 7.0+ 实例，验证连接可用性（暂不建表）。
- **PostgreSQL**: 本地启动 PostgreSQL 15+ 实例，验证连接可用性（暂不建表）。
- **配置**: 在 `.env` 中配置 Redis 和 PostgreSQL 的连接字符串，由 Go Runtime 统一解析并验证连接。

## 7. 退出标准检查清单
- [x] 定义并提交 `shared/proto/communication.proto`。
- [x] 定义并提交 WebSocket 消息 JSON Schema。
- [x] Go Runtime 实现 WebSocket 服务端和 gRPC 客户端。
- [x] Python AI Service 实现 gRPC 服务端。
- [x] Electron 前端实现 WebSocket 客户端和简单的 Ping/Pong UI。
- [x] 成功演示：前端点击 Ping -> Go 转发 -> Python 响应 -> Go 推送 -> 前端显示 Pong。
- [x] 所有请求日志中包含完整的 `trace_id`。
- [x] 本地 Redis、PostgreSQL 完成基础可用部署及连接验证。
- [x] 三层都能健康检查联调，确保前后端与智能层的连通性。
