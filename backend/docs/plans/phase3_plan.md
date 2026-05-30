# Phase 3：配置、Prompt 与密钥管理 架构设计与实施方案

## 1. 设计目标

本方案旨在为 Luna 项目构建一套安全、灵活、可追溯的配置与 Prompt 管理基础设施，彻底消除代码中的硬编码，实现系统的动态化。核心目标包括：

1.  **单一事实来源 (SSOT)**：确立 Go Runtime 为全局配置与 Prompt 资产的唯一权威存储与调度者，Python 层保持无状态。
2.  **敏感数据安全隔离**：实现 API Key 等敏感凭证的本地加密存储（AES-256-GCM + OS Keychain），防范明文泄露。
3.  **配置热更新**：支持用户在前端修改模型配置或系统参数后，后端（Go 与 Python）无缝热重载，无需重启应用。
4.  **Prompt 资产化与版本化**：将 Prompt 抽象为数据库中的模板与版本实体，支持细粒度的版本控制、回滚与 A/B 测试。
5.  **标准三槽位动态装配**：基于运行时上下文，在 Go 层动态组装 `system`, `memory`, `runtime` 三个标准 Prompt 槽位，交由 Python 层进行 Jinja2 渲染。

## 2. 目录结构规划

在现有三层架构基础上，扩展以下目录与文件结构：

### 2.1 Go Runtime (控制面)
```text
backend/runtime/internal/
├── config/
│   ├── config.go          # 基础静态配置加载 (已存在，需扩展)
│   ├── manager.go         # 动态配置管理器 (ConfigManager，负责热更新与内存快照)
│   ├── crypto.go          # AES-256-GCM 加解密与 OS Keychain 交互逻辑
│   └── event.go           # 配置变更事件总线 (EventBus)
├── prompt/
│   ├── manager.go         # Prompt 模板与版本管理器
│   ├── assembler.go       # 动态槽位装配逻辑 (Slot Assembly)
│   └── types.go           # Prompt 相关的领域结构体定义
├── repository/
│   ├── config_pg.go       # 动态配置的 PostgreSQL 存储实现
│   ├── prompt_pg.go       # Prompt 模板与版本的 PostgreSQL 存储实现
│   └── models.go          # 增加 SystemConfig, PromptTemplate, PromptVersion 模型
└── api/
    ├── config_handler.go  # 处理前端配置相关的 WS/HTTP 请求
    └── prompt_handler.go  # 处理前端 Prompt 相关的 WS/HTTP 请求
```

### 2.2 Python AI Service (智能层)
```text
backend/ai-service/app/
├── config/
│   ├── container.py       # 全局动态配置容器 (GlobalConfigContainer)
│   └── models.py          # 动态配置的 Pydantic 模型定义
├── api/
│   └── grpc_service.py    # 扩展 SyncConfig RPC 接口实现
└── agent/
    └── prompt_renderer.py # Jinja2 模板渲染器 (替代现有的硬编码 prompts.py)
```

### 2.3 Shared (跨层契约)
```text
backend/shared/proto/
└── communication.proto    # 增加 SyncConfig RPC，扩展 GenerateRequest 支持 PromptSlot
```

## 3. 核心类与接口设计规范

### 3.1 Go 层核心接口

*   **`ConfigManager` (配置管理器)**
    *   `GetConfig() *AppConfig`: 无锁读取当前配置的内存快照（基于 `atomic.Value`）。
    *   `UpdateConfig(updates map[string]interface{}) error`: 接收前端更新，识别敏感字段并加密，落盘至 PostgreSQL，更新内存快照，并通过 EventBus 广播 `ConfigChangedEvent`。
*   **`CryptoService` (加密服务)**
    *   `Encrypt(plaintext string) (string, error)`: 使用 Master Key 加密。
    *   `Decrypt(ciphertext string) (string, error)`: 使用 Master Key 解密。
*   **`PromptManager` (提示词管理器)**
    *   `Assemble(agentID string, contextVars map[string]string) ([]*pb.PromptSlot, error)`: 根据当前 Agent 状态，从 DB 提取激活的模板，组装为槽位数组。
    *   `PublishVersion(templateID string, versionID string) error`: 原子化切换模板的生效版本。
    *   `CreateTemplate(template *PromptTemplate) error`: 创建新的 Prompt 模板。
    *   `CreateVersion(templateID string, content string, variables []string) error`: 为指定模板创建新版本。
    *   `GetTemplates() ([]*PromptTemplate, error)`: 获取所有模板列表。
    *   `GetVersions(templateID string) ([]*PromptVersion, error)`: 获取指定模板的所有版本历史。
*   **`PromptHandler` (提示词 API 处理器)**
    *   提供供前端调用的 WebSocket/HTTP 接口，实现 Prompt 的查询、新增、修改（新增版本）与发布（热配置生效）。

### 3.2 Python 层核心类

*   **`GlobalConfigContainer`**: 维护 `LLMConfig` 等动态配置状态。提供异步的 `update_config` 方法，在接收到 Go 的 gRPC 推送时，更新配置并触发底层 LLM Client 的重新初始化。
*   **`PromptRenderer`**: 封装 Jinja2 环境（配置 `undefined=StrictUndefined`）。提供 `render_system_message(slots: List[PromptSlot], variables: Dict[str, str]) -> str` 方法，负责将 Go 传来的槽位与变量渲染为最终的字符串。

### 3.3 gRPC 协议扩展 (`communication.proto`)

```protobuf
// 1. 增加配置同步服务
message SyncConfigRequest {
    string version_id = 1;
    string llm_config_json = 2; // 包含明文 API Key 的 JSON
}

message SyncConfigResponse {
    bool success = 1;
    string error_message = 2;
}

// 在 AIService 中增加 RPC
// rpc SyncConfig(SyncConfigRequest) returns (SyncConfigResponse);

// 2. 扩展 GenerateAction 请求
message PromptSlot {
    string slot_name = 1;
    string template_content = 2;
    bool is_required = 3;
}

// 修改 GenerateRequest，移除硬编码的 prompt 字段，改为动态槽位
message GenerateRequest {
    string session_id = 1;
    string agent_id = 2;
    repeated PromptSlot system_slots = 3; 
    map<string, string> context_variables = 4;
    string user_input = 5;
    // ... 其他字段
}
```

## 4. 配置与敏感密钥的安全隔离与加载机制

1.  **动静分离**：
    *   静态环境配置（如服务端口、DB 连接串）保留在 `.env` 或 `config.yaml` 中，需重启生效。
    *   动态用户配置（如 API Key、默认模型）存储于 PostgreSQL 的 `system_config` 表中。
2.  **OS-Native 加密体系**：
    *   Go 启动时，通过 `zalando/go-keyring` 等库向操作系统 Keychain（macOS Keychain / Windows Credential Manager）请求 Master Key。若不存在则生成随机 AES-256 密钥并存入。
    *   对于 `system_config` 中标记为 `is_encrypted=true` 的字段，写入 DB 前必须使用 Master Key 进行 AES-GCM 加密。
3.  **热更新闭环**：
    *   前端发起配置修改 -> Go `ConfigManager` 加密落盘 -> 更新 Go 内存 `atomic.Value` -> 触发 EventBus -> Go 通过 gRPC `SyncConfig` 将**解密后的明文配置**推送给 Python -> Python 热重载 LLM Client。
    *   **安全红线**：明文 API Key 仅在 Go 内存和 Python 内存中短暂存在，严禁打印至任何日志文件。

## 5. Prompt 管理的模块化设计思路

1.  **双实体数据库模型**：
    *   `prompt_templates`: 存储元数据（`id`, `name`, `category`, `slot_position`, `is_system`, `active_version_id`）。
    *   `prompt_versions`: 存储具体内容（`id`, `template_id`, `version_num`, `content`, `variables`, `status`）。
2.  **标准三槽位与统一命名规范**：
    *   所有 Prompt 模板必须遵循 `[具体业务场景]_[槽位名称]` 的统一命名格式。
    *   槽位严格划分为三个：`system` (核心设定/规则), `memory` (长短期记忆), `runtime` (即时状态/临时指令)。
    *   例如：普通对话场景对应 `chat_system`, `chat_memory`, `chat_runtime`；总结场景对应 `summarize_system`, `summarize_memory`, `summarize_runtime`。
3.  **运行时动态装配 (Go 层)**：
    *   在每次触发 LLM 节点前，Go 的 `PromptManager` 根据当前业务场景（如 `chat` 或 `summarize`）查询对应的三个标准槽位模板。
    *   提取对应的 `active_version_id` 内容，组装成 `[]PromptSlot` 数组。
    *   收集上下文变量（如 `{{current_time}}`, `{{user_name}}`, `{{memory_summary}}`）构建 `context_variables` 字典。
4.  **无状态渲染 (Python 层)**：
    *   Python 接收到 `PromptSlot` 数组和变量字典后，使用 Jinja2 逐个渲染槽位。
    *   **容错策略**：若 `is_required=true` 的槽位渲染失败（如变量缺失），抛出异常中断流程；若 `is_required=false`，则静默跳过该槽位，保证核心对话能力不中断。
5.  **分类治理**：
    *   `is_system=true` 的模板（如 JSON 输出格式约束、核心安全规则）禁止前端删除，仅允许新增版本。
    *   内容型模板（如 Persona 设定）允许自由编辑与热插拔。

## 6. 实施步骤与退出标准

### Phase 3.1: 数据库模型与加密基建
*   **行动**：在 Go 层定义 `SystemConfig`, `PromptTemplate`, `PromptVersion` 的 GORM 模型并自动迁移。实现 `CryptoService` 接入 OS Keychain。
*   **退出标准**：能成功向 DB 写入加密配置，并能正确解密读取。

### Phase 3.2: 配置热更新链路打通
*   **行动**：实现 Go `ConfigManager` 与 EventBus。扩展 gRPC `SyncConfig` 接口。Python 层实现 `GlobalConfigContainer` 接收推送并重载 LLM Client。
*   **退出标准**：通过 API 修改 API Key 后，下一次对话立即使用新 Key 生效，无需重启服务。

### Phase 3.3: Prompt 资产化与动态装配
*   **行动**：实现 Go `PromptManager` 的装配逻辑与 CRUD 接口。在 `prompt_handler.go` 中暴露供前端查询、修改 Prompt 的 API。修改 `communication.proto` 引入 `PromptSlot`。Python 层引入 Jinja2 渲染器，彻底移除 `prompts.py` 中的硬编码字符串。重构现有的 Prompt 模板，严格按照 `[业务场景]_[槽位]` (如 `chat_system`, `summarize_memory`) 的规范进行拆分和重命名。
*   **退出标准**：系统能基于数据库中的标准三槽位 Prompt 模板正常进行对话；前端可通过 API 查询和修改 Prompt；修改数据库中的 Prompt 内容并发布后，下一次对话立即体现新设定（热配置）。

### Phase 3.4: 异常兜底与审计
*   **行动**：在 Go 层实现 DB 读取失败时的 Hardcode Fallback Prompt。完善配置变更与 Prompt 渲染失败的日志记录（注意脱敏）。
*   **退出标准**：即使清空 PostgreSQL 数据库，系统仍能使用内存兜底 Prompt 进行基础回复，不发生 Panic。