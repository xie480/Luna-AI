# API 配置预设与多模型路由设计方案

## 1. 背景与目标

当前系统依赖 `.env` 文件和单一的 `system_config` 表来管理 LLM 配置，存在以下问题：
1. 无法快速切换不同的 API 供应商或配置组合。
2. 仅支持单一模型，无法根据任务复杂度（如日常对话、复杂推理、后台摘要压缩）路由到不同规格（大、中、小）的模型，导致成本和性能无法兼顾。
3. 违反了 `agent.md` 中“彻底废弃任何基于 .env 文件的底层配置方式”的规范。

**目标：**
1. 引入“API 配置预设 (API Config Preset)”概念，允许用户保存多套配置并快速切换。
2. 每个预设内聚大 (Large)、中 (Medium)、小 (Small) 三种规格的模型配置。
3. 彻底移除 `.env` 中的 LLM 配置，所有配置通过 Go 控制面持久化并经由 gRPC 推送至 Python AI 服务。
4. 前端提供高度可用的配置界面，模型 ID 必须通过接口动态获取。

## 2. 数据库表结构设计

在 PostgreSQL 中新增 `api_config_presets` 表。

### 2.1 `api_config_presets` 表

| 字段名 | 类型 | 约束 | 说明 |
| :--- | :--- | :--- | :--- |
| `id` | `VARCHAR(64)` | PRIMARY KEY | 预设 ID，使用 Snowflake 算法生成 |
| `name` | `VARCHAR(255)` | NOT NULL, UNIQUE | 预设名称（用户自定义） |
| `is_active` | `BOOLEAN` | NOT NULL, DEFAULT false | 是否为当前激活的预设（全局唯一） |
| `large_model_config` | `JSONB` | NOT NULL | 大模型配置（加密存储 API Key） |
| `medium_model_config` | `JSONB` | NOT NULL | 中模型配置（加密存储 API Key） |
| `small_model_config` | `JSONB` | NOT NULL | 小模型配置（加密存储 API Key） |
| `created_at` | `TIMESTAMP` | DEFAULT CURRENT_TIMESTAMP | 创建时间 |
| `updated_at` | `TIMESTAMP` | DEFAULT CURRENT_TIMESTAMP | 更新时间 |

### 2.2 模型配置 JSON 结构 (`ModelConfig`)

```json
{
  "base_url": "https://api.openai.com/v1",
  "api_key": "sk-...", // 数据库中存储加密后的密文
  "model_id": "gpt-4o",
  "max_tokens": 8192, // 0 或 null 表示无上限
  "temperature": 0.7
}
```

## 3. 接口契约设计

### 3.1 前后端 HTTP 接口 (Go -> Electron)

所有接口前缀：`/api/v1/config/presets`

#### 3.1.1 获取所有预设列表
- **GET** `/`
- **Response:**
  ```json
  {
    "code": 0,
    "msg": "success",
    "data": [
      {
        "id": "1234567890",
        "name": "OpenAI 默认",
        "is_active": true,
        "large_model_config": { ... }, // API Key 脱敏为 "********" 或 boolean
        "medium_model_config": { ... },
        "small_model_config": { ... }
      }
    ]
  }
  ```

#### 3.1.2 创建/更新预设
- **POST** `/`
- **Request:**
  ```json
  {
    "id": "1234567890", // 可选，无则创建，有则更新
    "name": "OpenAI 默认",
    "large_model_config": { "base_url": "...", "api_key": "...", "model_id": "...", "max_tokens": 8192, "temperature": 0.7 },
    "medium_model_config": { ... },
    "small_model_config": { ... }
  }
  ```
- **Response:** 成功返回预设 ID。

#### 3.1.3 激活预设
- **POST** `/{id}/activate`
- **Response:** 成功状态。激活后，Go 会自动通过 gRPC 将配置推送给 Python。

#### 3.1.4 删除预设
- **DELETE** `/{id}`
- **Response:** 成功状态。禁止删除当前激活的预设。

#### 3.1.5 动态获取模型列表
- **POST** `/api/v1/models/fetch`
- **说明：** 前端传入 Base URL 和 API Key，Go 代理请求目标 API 的 `/v1/models` 接口，返回可用模型列表。
- **Request:**
  ```json
  {
    "base_url": "https://api.openai.com/v1",
    "api_key": "sk-..."
  }
  ```
- **Response:**
  ```json
  {
    "code": 0,
    "msg": "success",
    "data": [
      { "id": "gpt-4o", "name": "gpt-4o" },
      { "id": "gpt-3.5-turbo", "name": "gpt-3.5-turbo" }
    ]
  }
  ```

### 3.2 gRPC 通信协议 (Go -> Python)

更新 `backend/shared/proto/communication.proto`。

```protobuf
// 模型配置结构
message ModelConfig {
  string base_url = 1;
  string api_key = 2; // 明文，仅在内存中流转
  string model_id = 3;
  int32 max_tokens = 4; // 0 表示无上限
  float temperature = 5;
}

// 预设配置同步请求
message SyncPresetConfigRequest {
  string schema_version = 1; // 必须包含版本号，例如 "v1.0"
  string preset_id = 2;
  ModelConfig large_model = 3;
  ModelConfig medium_model = 4;
  ModelConfig small_model = 5;
}

// 预设配置同步响应
message SyncPresetConfigResponse {
  bool success = 1;
  string error_message = 2;
}

service CommunicationService {
  // ... 现有方法 ...
  
  // 同步预设配置
  rpc SyncPresetConfig(SyncPresetConfigRequest) returns (SyncPresetConfigResponse);
}
```

## 4. Python 服务改造

1. **移除 `.env` 依赖**：清理 `app/config.py` 中关于 `openai_api_base`、`openai_api_key`、`model_name` 等硬编码配置。
2. **GlobalConfigContainer 改造**：接收 `SyncPresetConfigRequest`，将大、中、小模型配置分别存储在内存中。
3. **模型路由 (Model Router)**：
   - 在 `app/llm/client.py` 中实现路由逻辑。
   - 根据任务类型选择模型：
     - 复杂推理、Agent 规划 -> `large_model`
     - 日常对话、普通问答 -> `medium_model`
     - 后台摘要压缩、简单分类 -> `small_model`

## 5. 前端 UI 改造

1. **废弃旧组件**：移除 `ApiKeyInput.tsx` 和 `ModelSelector.tsx`。
2. **新建 `ApiConfigPanel.tsx`**：
   - **顶部预设管理区**：下拉列表（选择历史预设）、新增按钮（清空表单）、保存按钮（弹窗输入名称）。
   - **模型配置区块**：三个平行的卡片（大模型、中模型、小模型）。
   - **动态模型选择**：每个区块内的“模型 ID”字段为下拉框，当 Base URL 和 API Key 失去焦点或点击“刷新”时，调用 `/api/v1/models/fetch` 获取列表。
3. **状态管理**：新建 `apiConfigStore.ts` 管理预设列表和当前表单状态。
