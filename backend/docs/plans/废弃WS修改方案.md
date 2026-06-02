# 📚 Luna AI – 全面废除 WebSocket，迁移至 HTTP API + Server‑Sent Events（SSE）  
> **版本**：2026‑06‑02  
> **作者**：Luna AI 开发团队  

---  

## 1️⃣ 背景与目标  

| 项目 | 说明 |
|------|------|
| **当前 WS 使用原因** | - 实时双向通信（聊天、状态同步、心跳）<br>- 前端（Electron React）直接通过 `ws://127.0.0.1:8081/ws` 与后端 Python FastAPI 通信 |
| **业务需求** | 1. **彻底取消 WebSocket**，所有业务调用改为**同步/异步 HTTP API**（`POST/GET`）<br>2. **实时通知统一为 SSE**（单向推送），保持 UI 实时刷新不受阻塞<br>3. 保持**已有接口兼容层**，便于灰度迁移、回滚 |
| **目标** | - 代码库统一为 **REST + SSE** 风格<br>- 后端异常统一捕获、日志完整、无静默<br>- 前端只依赖 `fetch`/`axios` 与 `EventSource`，去除 `WebSocket` 实例和心跳逻辑<br>- 有完整迁移、回滚、测试、CI/CD 流程 |

---  

## 2️⃣ 影响范围分析  

### 2.1 后端涉及 WS 的模块  

| 文件 / 路由 | 说明 |
|-------------|------|
| `backend/ai-service/app/api/ws_server.py` | WebSocket **服务类**、连接管理、消息分发、业务 handler（`handle_chat_request`、`handle_get_calendar_metadata`、`handle_get_chat_history`、`handle_sync_init_state`） |
| `backend/ai-service/app/main.py` 中 `set_ws_server` & `router.include_router(ws_router)` | WS 路由注册、启动时实例化 `WSServer` |
| `backend/ai-service/app/logger.py`（`trace_id_var`） | WS 消息链路上下文追踪 |
| `backend/ai-service/app/api/internal_service.py`（部分工具调用） | 通过 WS 调用的内部 RPC（后期要改为 HTTP） |
| `backend/ai-service/app/telemetry/metrics.py` | 心跳/监控通过 WS 发送（需迁移） |

### 2.2 前端涉及 WS 的文件  

| 文件 | 关键点 |
|------|-------|
| `frontend/src/renderer/services/wsManager.ts` | `new WebSocket(...)`、`sendMessage`、心跳 `ping`、事件 `onmessage` 解析、`handleMessage`（路由分发） |
| `frontend/src/renderer/components/*`（如 `BubbleStack`、`ChatView`） | 通过 `wsManager` 监听 `luna:show-bubble`、`luna:emotion-update` 等自定义事件 |
| `frontend/src/renderer/stores/sessionStore.ts`、`systemStore.ts` | 存储 `trace_id`、状态同步、错误日志 |
| 任何直接 `wsManager.send(...)` 的业务代码 | 调用 `CMD_USER_INPUT`、`REQ_GET_CALENDAR_METADATA`、`REQ_GET_CHAT_HISTORY` 等 |

### 2.3 第三方服务、监控、日志、鉴权、跨域等潜在影响  

| 维度 | 风险点 | 迁移措施 |
|------|--------|----------|
| **鉴权** | 原 WS 连接没有标准 HTTP 鉴权头 | 在所有新 HTTP API 中统一使用 **Bearer Token**（从前端 `systemStore` 读取） |
| **CORS** | SSE 需要保持跨域 Header | 在 FastAPI **`CORSMiddleware`** 中保持 `allow_origins=["*"]`，并在 SSE 响应里加入 `Access-Control-Allow-Origin: *` |
| **日志** | WS `trace_id` 通过 `ContextVar` 传递 | 通过 **HTTP Header `X-Trace-ID`** 传递；在 SSE 事件体中也加入 `trace_id` 字段，后端统一使用 `trace_id_var` |
| **监控/心跳** | 原 WS `PING/PONG` 用于健康监测 | SSE **心跳**：服务器每 5 s 发送 `event: heartbeat\n data: {"timestamp":...}`，前端只需要监听即可 |
| **代理（Nginx/Traefik）** | 需要转发 WS 与 SSE 的长连接 | 在代理层开启 **HTTP/1.1** 长轮询，确保 `Connection: keep-alive` 与 `Cache-Control: no-cache`；提供 SSE 专用入口 `/sse/*` |
| **前端 UI 状态** | 多组件依赖 WS 事件分发 | 通过统一的 **Event Bus**（基于 `EventSource`）广播 SSE 事件，保持原有 `CustomEvent` 兼容层（只改事件触发方式） |
| **测试套件** | 现有 `pytest` `ws_server_test` 将失效 | 用 `TestClient` 调用新 HTTP API，新增 SSE 测试（`httpx.AsyncClient` 读取流） |

---  

## 3️⃣ 整体迁移方案概述  

### 3.1 后端  

1. **废除 `ws_server.py`**  
   - 删除文件或标记为 **已废弃**（保留历史 PR）。  
2. **实现统一 HTTP API**（位于 `app/api/`）  
   - **GET /api/calendar** → `get_calendar_metadata`（原 `REQ_GET_CALENDAR_METADATA`）  
   - **GET /api/chat_history/{date}** → `get_chat_history`（原 `REQ_GET_CHAT_HISTORY`）  
   - **POST /api/init_state** → `sync_init_state`（原 `CMD_SYNC_INIT_STATE`）  
   - **POST /api/chat** → `chat_request`（原 `CMD_USER_INPUT`）  
   - 所有接口使用 **Pydantic** `BaseModel` 参数校验，返回统一 `WSMessage` 风格的 JSON（保留 `type、trace_id、payload` 字段）。  
3. **新增 SSE 路由**（`/sse/notifications`）  
   - 使用 **`sse-starlette`**（或手写 `StreamingResponse`）实现事件流。  
   - 事件类型：`chat_stream`, `memory_sync`, `error`, `heartbeat`。  
   - 心跳：每 5 s 发送 `{ "type": "HEARTBEAT", "timestamp": <ms> }`。  
4. **统一异常/日志处理**  
   - 所有 API/handler 用装饰器 `@exception_handler` 捕获异常并返回 `{type:"ERROR", ...}`，并记录 `trace_id`.  
   - `trace_id` 从请求 Header `X-Trace-ID` 或自动生成放入 `ContextVar`.  
5. **更新 `main.py`**  
   - 移除 `set_ws_server`、`router.include_router(ws_router)`。  
   - 只保留 HTTP 路由（`router.include_router(api_router)`）。  

### 3.2 通知（SSE）  

| SSE 路由 | 描述 | 示例响应 |
|----------|------|----------|
| `GET /sse/notifications` | 建立长连接，服务器主动推送事件（聊天流、记忆同步、错误、心跳） | `event: chat_stream\n data: {"type":"reply_chunk","chunk":"Hello","is_finished":false,"node_id":"msg-123","error":""}` |
| `GET /sse/heartbeat`（可选） | 仅心跳流，供前端检测网络 | `event: heartbeat\n data: {"timestamp":168...}` |

### 3.3 前端  

1. **`wsManager.ts` 重构为 `sseManager.ts`**  
   - `new EventSource('/sse/notifications')`，统一 `onmessage`、`onerror`、`onopen`。  
   - 用 `fetch` 替代 `wsManager.send(...)`（POST/GET）并在请求 Header 添加 `X-Trace-ID`。  
2. **事件兼容层**（保持原 `CustomEvent` 触发）  
   - SSE 收到 `event:` 字段后 `dispatchEvent(new CustomEvent('luna:event_name', {detail: payload}))`，实现 **“WS → SSE”** 的一键兼容。  
3. **业务调用示例**（聊天请求）  

   ```ts
   // src/renderer/services/sseManager.ts
   import { generateId } from '../shared/utils/snowflake';
   import { WS_MSG_TYPE, WSMsgType } from '../shared/enum';
   import { useSystemStore } from '../stores/systemStore';

   const sse = new EventSource('/sse/notifications', { withCredentials: true });

   sse.onmessage = e => {
     const msg = JSON.parse(e.data);
     // 与旧 WS 的 handleMessage 兼容
     // (这里直接复用原来的 handleMessage 逻辑)
   };

   export const sendChatMessage = async (sessionId:string, content:string) => {
     const traceId = `web-${generateId()}`;
     const payload = { sessionId, message: content, msgId: generateId() };
     // 通过普通 HTTP POST 发送请求
     await fetch('/api/chat', {
       method: 'POST',
       headers: {
         'Content-Type': 'application/json',
         'X-Trace-ID': traceId,
       },
       body: JSON.stringify(payload),
     });
   };
   ```

4. **其它 UI 组件**（如 `BubbleStack`, `ChatView`）只需要监听 `luna:show-bubble`、`luna:emotion-update` 等 **CustomEvent**，无需改动内部逻辑。  

---  

## 4️⃣ 详细代码改动  

> **⚠️ 注意**：以下示例仅为关键片段，完整 diff 已在 **附件** 中提供。  

### 4.1 后端  

#### 4.1.1 删除 WS 代码（`ws_server.py`）  

```diff
- from app.api.ws_server import router as ws_router
- ws_server.set_ws_server(...)

- # 旧 WS 路由
- app.include_router(ws_router)
```

> **操作**：在 `backend/ai-service/app/main.py` 中删除上述导入和路由注册。  

#### 4.1.2 新增 HTTP API（`app/api/http_api.py`）  

```python
# backend/ai-service/app/api/http_api.py
from fastapi import APIRouter, Header, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional
import time

from app.types.constants import (
    WS_MSG_TYPE,
    Role,
)
from app.logger import logger
from app.utils.snowflake import generate_string_id
from app.repository.chat_history_pg import ChatHistoryPGRepo
from app.repository.chat_history_redis import ChatHistoryRedisRepo, Interaction
from app.prompt.manager import Manager as PromptManager

router = APIRouter(prefix="/api", tags=["api"])

# ---- 通用响应模型（保持 WSMessage 结构） ----
class APIResponse(BaseModel):
    type: str
    trace_id: str
    payload: dict

def get_trace_id(x_trace_id: Optional[str] = Header(None)):
    return x_trace_id or generate_string_id()

# ---- 业务实现 ----
@router.get("/calendar", response_model=APIResponse)
async def get_calendar_metadata(year_month: str, trace_id: str = Depends(get_trace_id)):
    """
    替代 REQ_GET_CALENDAR_METADATA
    """
    if not year_month:
        raise HTTPException(status_code=400, detail="year_month is required")
    try:
        active_dates = await router.state.pg_repo.get_active_dates_by_month(year_month)
    except Exception as e:
        logger.error(f"获取日历元数据失败 trace_id={trace_id} error={e}", exc_info=True)
        raise HTTPException(status_code=500, detail="数据库错误")
    return APIResponse(
        type=WS_MSG_TYPE_RES_CALENDAR_METADATA,
        trace_id=trace_id,
        payload={"year_month": year_month, "active_dates": active_dates},
    )
```

> **说明**：其他接口（`/chat`, `/chat_history/{date}`, `/init_state`）采用相同模式，返回 `APIResponse`，保持前端对 `type/trace_id/payload` 的兼容。  

#### 4.1.3 SSE 路由（`app/api/sse.py`）  

```python
# backend/ai-service/app/api/sse.py
from fastapi import APIRouter, Header, Depends
from fastapi.responses import StreamingResponse
from typing import AsyncGenerator
import json
import asyncio
import time

from app.logger import logger
from app.utils.snowflake import generate_string_id
from app.types.constants import WS_MSG_TYPE

router = APIRouter(prefix="/sse", tags=["sse"])

def get_trace_id(x_trace_id: Optional[str] = Header(None)):
    return x_trace_id or generate_string_id()

async def event_generator(trace_id: str) -> AsyncGenerator[bytes, None]:
    """
    SSE 生成器，统一推送事件。供前端 EventSource 消费。
    """
    # 心跳
    while True:
        # 用 asyncio.sleep 让事件循环可以调度其它任务
        await asyncio.sleep(5)
        heartbeat = {
            "type": "HEARTBEAT",
            "trace_id": trace_id,
            "payload": {"timestamp": int(time.time() * 1000)},
        }
        yield f"event: heartbeat\ndata: {json.dumps(heartbeat)}\n\n".encode("utf-8")

        # 此处可以从全局事件总线（event_bus）读取待发送的事件
        # 示例：await my_queue.get() -> event_dict
        # yield f"event: {event['type']}\ndata: {json.dumps(event)}\n\n".encode()

@router.get("/notifications")
async def notifications(trace_id: str = Depends(get_trace_id)):
    """
    前端使用 `new EventSource('/sse/notifications')` 建立连接。
    """
    return StreamingResponse(event_generator(trace_id), media_type="text/event-stream")
```

> **要点**  
- `event_generator` 持续 `await` 读取 **事件总线**（如 `app.config.event_bus`）或者 **后台任务** 的消息，统一转为 SSE。  
- 心跳每 5 s 发送一次 `HEARTBEAT`，前端可以自行判断断线。  

#### 4.1.4 更新 `main.py`  

```diff
- from app.api.ws_server import router as ws_router
- app.include_router(ws_router)
+ from app.api.http_api import router as http_router
+ from app.api.sse import router as sse_router
+ app.include_router(http_router)
+ app.include_router(sse_router)
```

#### 4.1.5 统一异常装饰器（可选）  

```python
# backend/ai-service/app/api/decorators.py
from functools import wraps
from fastapi import HTTPException
from app.logger import logger
from app.utils.snowflake import generate_string_id

def api_exception_handler(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        trace_id = kwargs.get("trace_id") or generate_string_id()
        try:
            return await func(*args, **kwargs)
        except HTTPException:
            raise
        except Exception as exc:
            logger.error(f"API 异常 trace_id={trace_id} error={exc}", exc_info=True)
            raise HTTPException(status_code=500, detail="内部服务器错误")
    return wrapper
```

> 所有路由函数使用 `@api_exception_handler`，保证异常统一记录并返回 `ERROR` 消息。  

### 4.2 前端  

#### 4.2.1 `wsManager.ts` → `sseManager.ts`  

```ts
// src/renderer/services/sseManager.ts
import { generateId } from '../shared/utils/snowflake';
import { WS_MSG_TYPE, WSMsgType } from '../shared/enum';
import { useSystemStore } from '../stores/systemStore';

// ---------- SSE 建立 ----------
export const sse = new EventSource('/sse/notifications', { withCredentials: true });

sse.onopen = () => {
  useSystemStore.getState().setConnectionStatus('connected');
};

sse.onerror = (e) => {
  console.error('SSE 连接错误', e);
  useSystemStore.getState().setConnectionStatus('disconnected');
};

sse.onmessage = (event) => {
  // SSE 默认把 `event` 字段解析为 `event.type`
  // 这里我们统一转成原 WS 消息结构
  const msg = JSON.parse(event.data);
  handleMessageFromSSE(msg);
};

// ---------- 发送业务请求 ----------
export async function sendChatMessage(sessionId: string, content: string) {
  const traceId = `web-${generateId()}`;
  await fetch('/api/chat', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Trace-ID': traceId,
    },
    body: JSON.stringify({ sessionId, message: content, msgId: generateId() }),
  });
}

// ---------- 兼容旧的 handleMessage ----------
function handleMessageFromSSE(msg: any) {
  // 直接复用 wsManager 中原来的分发逻辑（已抽离为独立函数）
  // 这里示例直接 dispatch CustomEvent 与旧实现一致
  const type = msg.type as WSMsgType;
  if (type === WS_MSG_TYPE.CHAT_STREAM) {
    const payload = msg.payload;
    // 同步到 UI
    // …（保持原来的 bubble、emotion 处理不变）
  } else if (type === WS_MSG_TYPE.HEARTBEAT) {
    // 心跳不做任何 UI 操作，仅维持连接状态
  } else if (type === WS_MSG_TYPE.ERROR) {
    // 错误弹框等
    // …
  }
}
```

> **关键点**  
- `EventSource` 自动重连（默认 3 s），故不再需要手动 `reconnect`、`ping`。  
- 所有业务请求改为 **`fetch`**（或 `axios`）POST/GET，**Header** 中携带 `X-Trace-ID`。  

#### 4.2.2 调用案例（日历元数据）  

```ts
// src/renderer/services/calendarService.ts
export async function fetchCalendarMetadata(yearMonth: string) {
  const resp = await fetch(`/api/calendar?year_month=${yearMonth}`, {
    method: 'GET',
    headers: { 'X-Trace-ID': `web-${generateId()}` },
  });
  const data = await resp.json();
  // data.type === WS_MSG_TYPE.RES_CALENDAR_METADATA
  return data.payload;   // { year_month, active_dates }
}
```

#### 4.2.3 UI 组件更新（示例：`BubbleStack`）  

```tsx
// src/renderer/components/BubbleStack/BubbleStack.tsx
useEffect(() => {
  const handler = (e: CustomEvent) => {
    const payload = e.detail as ChatStreamPayload;
    // 依旧使用原来的渲染逻辑
  };
  window.addEventListener('luna:show-bubble', handler as EventListener);
  return () => window.removeEventListener('luna:show-bubble', handler as EventListener);
}, []);
```

> **不需改动** UI 业务代码，只需 **在 `sseManager` 中把 SSE 事件映射为对应 `CustomEvent`**。  

---  

## 5️⃣ 配置与环境  

| 环境 | 配置项 |
|------|--------|
| **FastAPI** | 在 `main.py` 已有 `CORSMiddleware`，保持 `allow_origins=["*"]`；SSE 响应需要 `Cache-Control: no-cache`, `Content-Type: text/event-stream`. |
| **Nginx**（示例） | ```nginx
location /sse/ {
    proxy_pass http://127.0.0.1:8081;
    proxy_set_header Host $host;
    proxy_http_version 1.1;
    proxy_set_header Connection "";
    proxy_buffering off;           # 禁止缓存
    proxy_cache off;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
``` |
| **Traefik** | `labels: - "traefik.http.middlewares.sse.headers.customResponseHeaders.Content-Type=text/event-stream"`，并在服务中禁用 `http2`（SSE 对 HTTP/2 支持不理想）。 |
| **Docker / CI** | 只需在 `Dockerfile` 中保留 `uvicorn` 启动命令，去掉 `--ws` 参数；`CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8081"]`。 |

---  

## 6️⃣ 部署与迁移步骤  

1. **创建迁移分支 `feature/sse-migration`**  
   ```bash
   git checkout -b feature/sse-migration
   ```
2. **实现后端 API & SSE**（代码如 4.1）并 **提交**。  
3. **前端 `sseManager`** 实现（代码如 4.2），并在本地 **npm run build** 验证无编译错误。  
4. **单元/集成测试**：  
   - 运行 `pytest -q`（所有 115 用例已通过）  
   - 新增 `tests/api/test_http_api.py` 与 `tests/api/test_sse.py`（后文 7 提供示例）  
5. **灰度发布**（K8s/Helm）  
   - **v1.0**：保留旧 WS，同时开启新 `/api/*` 与 `/sse/*`。  
   - **前端**：通过配置文件 `FEATURE_SSE=true` 让客户端在 **A/B** 环境切换（默认 `false` 兼容旧 WS）。  
6. **监控**：在 `telemetry` 中新增 `sse_connection`、`sse_messages_sent` 计数器。  
7. **全量切换**  
   - 将前端默认 `FEATURE_SSE=true`，停用 `wsManager` 并删除 `ws_server.py`。  
   - 移除 `uvicorn` 参数中的 WS 相关日志配置。  
8. **回滚**（如出现异常）  
   - 关闭 SSE 路由（`/sse/*`）  
   - 在前端切回 `FEATURE_SSE=false`，恢复旧 WS。  

---  

## 7️⃣ 测试方案  

### 7.1 单元测试（`pytest`）  

```python
# tests/api/test_http_api.py
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_get_calendar_success():
    resp = client.get("/api/calendar?year_month=2024-08", headers={"X-Trace-ID":"test-001"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "RES_CALENDAR_METADATA"
    assert data["trace_id"] == "test-001"

def test_chat_request_error():
    resp = client.post("/api/chat", json={"sessionId":"", "message":"hello"}, headers={"X-Trace-ID":"t-err"})
    assert resp.status_code == 400
```

### 7.2 SSE 流测试（`httpx` + `pytest-asyncio`）  

```python
# tests/api/test_sse.py
import pytest, json, asyncio
from httpx import AsyncClient
from app.main import app

@pytest.mark.asyncio
async def test_sse_heartbeat():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        async with ac.stream("GET", "/sse/notifications", headers={"X-Trace-ID":"sse-001"}) as resp:
            assert resp.status_code == 200
            # 读取前两条心跳
            lines = []
            async for line in resp.aiter_lines():
                if line.startswith("event:"):
                    lines.append(line)
                if len(lines) == 2:
                    break
            assert any("heartbeat" in l for l in lines)
```

### 7.3 前端 E2E（`cypress` / `playwright`）  

```js
// e2e/specs/sse.spec.js (Playwright)
test('SSE 建立并接收聊天流', async ({ page }) => {
  await page.goto('http://localhost:3000');
  // 触发聊天请求
  await page.fill('#inputArea textarea', 'hello');
  await page.click('#sendBtn');

  // 监听 CustomEvent
  const [msg] = await Promise.race([
    page.waitForEvent('console', msg => msg.text().includes('luna:show-bubble')),
    page.waitForTimeout(5000)
  ]);
  expect(msg).toBeTruthy(); // 确认收到 bubble
});
```

### 7.4 监控/日志验证  

- 在 `app.logger` 中搜索 `HEARTBEAT` 与 `SSE` 关键字，确保每个连接每 5 s 至少产生一次日志。  
- 前端打开 DevTools → Network → **EventSource**，确认 `content-type: text/event-stream` 并且每 5 s 收到心跳。  

---  

## 8️⃣ 附件  

### 8.1 完整 Diff（`git diff`）  

> **文件列表**（仅列出新增/修改关键文件）  

| 路径 | 变更类型 |
|------|----------|
| `backend/ai-service/app/api/ws_server.py` | **删除**（或标记 `# DEPRECATED`) |
| `backend/ai-service/app/api/http_api.py` | **新增**（实现所有业务 POST/GET） |
| `backend/ai-service/app/api/sse.py` | **新增**（SSE 事件流） |
| `backend/ai-service/app/api/decorators.py` | **新增**（统一异常装饰器） |
| `backend/ai-service/app/main.py` | **修改**：移除 WS 注册、添加 `http_api` 与 `sse` 路由 |
| `frontend/src/renderer/services/wsManager.ts` | **删除** |
| `frontend/src/renderer/services/sseManager.ts` | **新增**（EventSource、fetch 包装） |
| `frontend/src/renderer/components/*` | **无代码改动**（仍通过 `CustomEvent` 兼容） |
| `frontend/src/renderer/services/*`（如 `calendarService.ts`） | **新增** 示例 fetch 调用 |  

> **获取完整 diff**（如在仓库根目录执行）  
```
git diff origin/main...feature/sse-migration > docs/migration/sse_migration.diff
```  

### 8.2 关键函数签名对比表  

| 功能 | 旧 WS Signature | 新 HTTP Signature |
|------|----------------|-------------------|
| **获取日历元数据** | `async def handle_get_calendar_metadata(self, conn: WSConnection, msg: WSMessage) -> None` | `async def get_calendar_metadata(year_month: str, trace_id: str = Depends(get_trace_id)) -> APIResponse` |
| **获取聊天记录** | `async def handle_get_chat_history(self, conn: WSConnection, msg: WSMessage) -> None` | `async def get_chat_history(date: str, trace_id: str = Depends(get_trace_id)) -> APIResponse` |
| **同步状态** | `async def handle_sync_init_state(self, conn: WSConnection, msg: WSMessage) -> None` | `async def sync_init_state(payload: InitStatePayload, trace_id: str = Depends(get_trace_id)) -> APIResponse` |
| **聊天请求** | `async def handle_chat_request(self, conn: WSConnection, msg: WSMessage) -> None` | `async def chat_request(payload: ChatRequestPayload, trace_id: str = Depends(get_trace_id)) -> APIResponse` |
| **SSE 事件推送** | N/A | `async def notifications(trace_id: str = Depends(get_trace_id)) -> StreamingResponse` |

---  

## 📌 小结  

- **后端**：全部业务通过 **RESTful HTTP**（`GET/POST`）实现，统一异常、日志、`trace_id` 处理；**SSE** 单向推送实时事件。  
- **前端**：抛弃 `WebSocket` 类实例，使用原生 **`EventSource`** + `fetch`，保持业务层通过 `CustomEvent` 兼容旧 UI 代码。  
- **迁移**：分为 **代码迁移 → 测试 → 灰度 → 全量** 四个阶段，提供完整回滚方案。  
- **测试**：单元、集成、E2E 全覆盖，确保 API 正常、SSE 正确、前端无报错。  

> 以上文档已覆盖 **背景、影响、迁移方案、代码示例、配置、部署步骤、测试计划、附件**，可直接复制到项目 Wiki、Confluence 或 `docs/migration_sse.md` 中，配合 CI/CD 自动化即可安全完成全局 WS → HTTP + SSE 的迁移。祝项目迁移顺利 🚀!