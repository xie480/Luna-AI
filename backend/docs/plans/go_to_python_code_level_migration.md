# Go至Python底层逻辑100%无损复原迁移实操指南 (深度详细版)

本文档严格聚焦于将 `backend/runtime` 目录下的 Go 语言代码**原样、无损地**平移至 Python 生态。不引入任何新架构（如 LangGraph），不改变现有输入输出契约，确保前端与 AI 服务的交互感知为零变化。本指南提供了精确到代码块级别的转换示例。

---

## 第一部分：Go文件与目标Python模块的逐一映射关系

我们将采用 FastAPI 作为基础 Web 框架，完全复刻原 Go 目录结构。

| 原 Go 文件路径 (`backend/runtime/`) | 目标 Python 模块路径 (`backend/runtime_py/app/`) | 核心职责说明 |
| :--- | :--- | :--- |
| `cmd/main.go` | `main.py` | FastAPI 应用入口、生命周期管理（Lifespan）、依赖注入装配 |
| `internal/types/*.go` | `types/` (如 `constants.py`, `errors.py`) | 常量枚举、自定义异常类定义 |
| `internal/utils/snowflake/snowflake.go` | `utils/snowflake.py` | 雪花算法 ID 生成器 |
| `internal/config/config.go` | `config/settings.py` | 基于 Pydantic `BaseSettings` 的环境变量解析 |
| `internal/config/event.go` | `config/event_bus.py` | 进程内事件总线（EventBus） |
| `internal/infrastructure/postgres.go` | `infrastructure/postgres.py` | SQLAlchemy 异步引擎初始化 |
| `internal/infrastructure/redis.go` | `infrastructure/redis.py` | `redis.asyncio` 客户端初始化 |
| `internal/infrastructure/qdrant.go` | `infrastructure/qdrant.py` | `qdrant_client.AsyncQdrantClient` 初始化 |
| `internal/repository/*_pg.go` | `repository/*_pg.py` | PostgreSQL 数据访问层（CRUD） |
| `internal/repository/*_redis.go` | `repository/*_redis.py` | Redis 数据访问层 |
| `internal/prompt/manager.go` | `prompt/manager.py` | Jinja2 模板渲染与变量组装 |
| `internal/telemetry/worker.go` | `telemetry/worker.py` | 异步遥测数据落盘后台任务 |
| `internal/memory/manager.go` | `memory/manager.py` | 长期记忆流转与会话管理 |
| `internal/api/grpc_client.go` | `api/grpc_client.py` | `grpcio.aio` 异步 gRPC 客户端及拦截器 |
| `internal/api/ws_server.go` | `api/ws_server.py` | FastAPI WebSocket 路由及连接管理器 |
| `internal/api/*_handler.go` | `api/routers/*.py` | HTTP RESTful 接口路由 |

---

## 第二部分：核心机制的 Python 等价复刻方案 (附代码)

为了保证底层运行机制的绝对一致，必须对 Go 的语言特性进行精确的 Python 映射：

### 1. 并发控制与后台任务 (Goroutines -> Asyncio Tasks)
**Go 原逻辑 (`ws_server.go`)**:
```go
case types.WSMsgTypeCmdUserInput:
    // 异步处理聊天请求，避免阻塞读循环
    go s.handleChatRequest(ctx, conn, msg)
```

**Python 复刻方案**:
在 Python 中，直接 `await` 会阻塞 WebSocket 的读循环。必须使用 `asyncio.create_task`，并且为了防止 Task 被垃圾回收，需要将其保存在一个集合中。
```python
import asyncio

class WSServer:
    def __init__(self):
        self.background_tasks = set()

    async def handle_message(self, conn: WSConnection, msg: WSMessage):
        if msg.type == WSMsgType.CMD_USER_INPUT:
            task = asyncio.create_task(self.handle_chat_request(conn, msg))
            self.background_tasks.add(task)
            task.add_done_callback(self.background_tasks.discard)
```

### 2. 通道通信 (Channels -> Asyncio Queues)
**Go 原逻辑 (`telemetry/worker.go`)**:
```go
type Worker struct {
    spanChan chan *TraceSpan
}
func (w *Worker) RecordSpanAsync(span *TraceSpan) {
    select {
    case w.spanChan <- span:
    default: // 队列满则丢弃
    }
}
```

**Python 复刻方案**:
使用 `asyncio.Queue` 替代 `chan`。为了实现非阻塞的“队列满则丢弃”，使用 `queue.put_nowait()` 并捕获 `QueueFull` 异常。
```python
import asyncio

class TelemetryWorker:
    def __init__(self, max_size=10000):
        self.span_queue = asyncio.Queue(maxsize=max_size)

    def record_span_async(self, span: TraceSpan):
        try:
            self.span_queue.put_nowait(span)
        except asyncio.QueueFull:
            pass # 队列满则丢弃，与 Go 逻辑一致

    async def run(self):
        while True:
            span = await self.span_queue.get()
            # 执行批量入库逻辑...
            self.span_queue.task_done()
```

### 3. 状态管理与锁 (sync.Mutex -> asyncio.Lock)
**Go 原逻辑 (`ws_server.go`)**:
```go
type WSConnection struct {
    conn *websocket.Conn
    mu   sync.Mutex
}
func (c *WSConnection) WriteJSON(v interface{}) error {
    c.mu.Lock()
    defer c.mu.Unlock()
    return c.conn.WriteJSON(v)
}
```

**Python 复刻方案**:
FastAPI 的 `WebSocket.send_text` 不支持并发调用（如果两个 Task 同时向同一个 WS 发送数据会报错）。必须为每个连接绑定一个 `asyncio.Lock()`。
```python
from fastapi import WebSocket
import asyncio

class WSConnection:
    def __init__(self, websocket: WebSocket):
        self.ws = websocket
        self.lock = asyncio.Lock()
        
    async def write_json(self, data: dict):
        async with self.lock:
            await self.ws.send_json(data)
```

### 4. 上下文传递 (context.Context -> contextvars)
**Go 原逻辑**:
```go
traceID, _ := ctx.Value(logger.TraceIDKey).(string)
```

**Python 复刻方案**:
使用 `contextvars` 实现隐式上下文传递，避免修改所有函数的签名。
```python
import contextvars
import uuid

# 定义全局 ContextVar
trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="")

def get_trace_id() -> str:
    tid = trace_id_var.get()
    if not tid:
        tid = str(uuid.uuid4())
        trace_id_var.set(tid)
    return tid

# 在中间件或 WS 入口处设置
# trace_id_var.set(msg.trace_id)
```

---

## 第三部分：逐文件迁移与重写流程（按依赖层级）

迁移必须自底向上进行，确保每一层重写后都能独立通过单元测试。

### 阶段一：基础类型与工具层 (Layer 1)
1.  **`utils/snowflake.py`**: 
    *   **细节**: 必须严格复刻 Go 版本的时间戳纪元（Epoch）、机器码位数、序列号位移逻辑。Python 的位运算与 Go 一致，但需注意 Python 整数不会溢出，需手动取模（如 `& 0x7FFFFFFFFFFFFFFF`）以保证生成 64 位整数。
2.  **`types/constants.py`**: 
    *   **细节**: 将 Go 中的 `const` 转换为 Python 的 `enum.StrEnum`。例如 `WSMsgTypeCmdUserInput = "CMD_USER_INPUT"`。

### 阶段二：基础设施层 (Layer 2)
1.  **`config/settings.py`**: 
    *   **细节**: 使用 `pydantic-settings`。定义 `class Settings(BaseSettings):`，通过 `model_config = SettingsConfigDict(env_file=".env")` 加载。
2.  **`infrastructure/postgres.py`**: 
    *   **细节**: 使用 `SQLAlchemy 2.0` 的 `AsyncEngine`。
    ```python
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    engine = create_async_engine("postgresql+asyncpg://user:pass@localhost/luna")
    AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    ```

### 阶段三：数据访问层 (Layer 3)
1.  **`repository/models.py`**: 
    *   **细节**: 将 Go 的 GORM struct 转换为 SQLAlchemy ORM 模型。**关键**：字段名、类型、索引必须与现有数据库完全一致。
    ```python
    from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
    from datetime import datetime

    class Base(DeclarativeBase): pass

    class InteractionModel(Base):
        __tablename__ = "interactions"
        id: Mapped[str] = mapped_column(primary_key=True)
        session_id: Mapped[str] = mapped_column(index=True)
        user_content: Mapped[str]
        assistant_content: Mapped[str]
        created_at: Mapped[datetime]
    ```
2.  **`repository/chat_history_pg.py`**: 
    *   **细节**: 实现 `SaveInteraction`。
    ```python
    async def save_interaction(self, interaction: InteractionModel):
        async with self.session_factory() as session:
            session.add(interaction)
            await session.commit()
    ```

### 阶段四：核心业务逻辑层 (Layer 4)
1.  **`prompt/manager.py`**: 
    *   **细节**: 引入 `jinja2`。Go 的 `text/template` 和 Jinja2 语法有差异。Go 的 `{{ .USER_INPUT }}` 需要在 Python 中替换为 `{{ USER_INPUT }}`。必须编写脚本批量转换现有的 `.j2` 模板文件中的占位符语法。
2.  **`memory/manager.py`**: 
    *   **细节**: 逐行翻译 `RolloverSession` 等复杂逻辑。Go 中的 `time.Now().Format("20060102")` 对应 Python 的 `datetime.now().strftime("%Y%m%d")`。

### 阶段五：API 与网络层 (Layer 5)
1.  **`api/grpc_client.py`**: 
    *   **细节**: 复刻 `TelemetryUnaryClientInterceptor`。在 Python 中需实现 `grpc.aio.UnaryUnaryClientInterceptor`。
    ```python
    import grpc
    from grpc.aio import UnaryUnaryClientInterceptor, ClientCallDetails

    class TelemetryInterceptor(UnaryUnaryClientInterceptor):
        async def intercept_unary_unary(self, continuation, client_call_details, request):
            trace_id = get_trace_id()
            metadata = client_call_details.metadata or []
            metadata.append(("x-trace-id", trace_id))
            new_details = ClientCallDetails(
                client_call_details.method, client_call_details.timeout, metadata, client_call_details.credentials
            )
            # 记录开始时间
            response = await continuation(new_details, request)
            # 记录结束时间并推入 Telemetry Queue
            return response
    ```
2.  **`api/ws_server.py`**: 
    *   **细节**: 复刻 `handleChatRequest`。这是最核心的逻辑。
    ```python
    async def handle_chat_request(self, conn: WSConnection, msg: WSMessage):
        # 1. 解析 Payload
        payload = CMDUserInputPayload.model_validate(msg.payload)
        
        # 2. 调用 Input Reconstruction (gRPC)
        recon_resp = await self.ai_client.input_reconstruction(...)
        
        # 3. 组装 Prompt
        system_prompt = await self.prompt_mgr.assemble(...)
        
        # 4. 调用 ChatStream (gRPC)
        stream = self.ai_client.chat_stream(...)
        full_content = ""
        try:
            async for resp in stream:
                full_content += resp.chunk
                # 5. 推送给前端
                await conn.write_json({"type": "CHAT_STREAM", "payload": {"chunk": resp.chunk}})
        except grpc.aio.AioRpcError as e:
            # 处理流中断
            pass
            
        # 6. 异步落盘 DB/Redis
        asyncio.create_task(self.save_to_db(payload.session_id, full_content))
    ```

### 阶段六：入口装配 (Layer 6)
1.  **`main.py`**: 
    *   **细节**: 使用 FastAPI 的 `@asynccontextmanager` 实现 `lifespan`。
    ```python
    from fastapi import FastAPI
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup: 初始化 DB, Redis, gRPC Client
        await init_db()
        telemetry_task = asyncio.create_task(telemetry_worker.run())
        yield
        # Shutdown: 优雅关闭
        telemetry_task.cancel()
        await close_db()

    app = FastAPI(lifespan=lifespan)
    app.include_router(ws_router)
    ```

---

## 第四部分：语言特性差异导致的功能畸变前置规避策略

在 100% 复刻过程中，以下差异极易导致隐蔽 Bug，必须前置规避：

### 1. JSON 序列化中的零值处理 (Zero Values vs None)
*   **风险**：Go 的 `omitempty` 在字段为零值（如 `""`, `0`, `false`）时会忽略该字段。Python 的 `json.dumps` 默认保留所有字段，除非显式剔除。
*   **规避**：在 Python 侧定义 Pydantic 模型时，使用 `model_dump(exclude_none=True, exclude_defaults=True)`，并仔细核对前端是否依赖某些空字符串字段。

### 2. 时间戳精度差异
*   **风险**：Go 的 `time.Now().UnixMilli()` 返回 `int64`。Python 的 `time.time()` 返回浮点数秒。
*   **规避**：在 Python 中严格封装时间获取函数：`int(time.time() * 1000)`，确保写入数据库和返回给前端的时间戳类型与精度与 Go 绝对一致。

### 3. gRPC 流式读取的异常捕获
*   **风险**：Go 中通过 `err == io.EOF` 判断流结束。Python 的 `grpc.aio` 流式读取使用 `async for response in stream:`，异常会以 `grpc.aio.AioRpcError` 抛出。
*   **规避**：
    ```python
    try:
        async for resp in stream:
            # 处理 chunk
    except grpc.aio.AioRpcError as e:
        if e.code() == grpc.StatusCode.CANCELLED:
            pass # 正常取消
        else:
            # 记录错误并发送 error chunk
    ```

### 4. 字符串 Builder 性能与格式
*   **风险**：Go 中大量使用 `strings.Builder` 拼接 Prompt（如 `memorySnippetsBuilder`）。Python 中直接使用 `+=` 性能较差。
*   **规避**：在 Python 中使用列表收集字符串，最后使用 `"".join(snippets_list)`，确保换行符 `\n` 的位置与 Go 代码中的 `fmt.Sprintf` 产出完全一致，否则会影响 LLM 的理解。

### 5. 协程上下文丢失 (Late Binding)
*   **风险**：Go 中 `go func() { ... }()` 会自动捕获闭包变量。Python 的 `asyncio.create_task` 如果在循环中创建，可能会捕获到循环变量的最终值。
*   **规避**：在 Python 中启动后台任务时，必须通过函数参数显式传递变量：
    ```python
    # 错误：可能捕获错误的 msg_id
    asyncio.create_task(save_to_db(msg_id)) 
    
    # 正确：显式绑定
    async def _save(m_id): await save_to_db(m_id)
    asyncio.create_task(_save(msg_id))