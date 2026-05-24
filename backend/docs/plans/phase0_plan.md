# Phase 0: 工程规范与运行基线实施方案

## 1. 目标
严格遵循 `agent.md` 的约束，建立统一的开发规范、目录结构、代码质量检查工具和基础运行环境，确保后续开发在稳定、标准化的基座上进行。实现 100% 测试通过率和零 Linter 警告。

## 2. 目录结构初始化
根据系统架构设计，初始化以下核心物理目录：
- `/frontend`: 前端工程 (Electron + React + TypeScript)
- `/backend/runtime`: 后端控制面 (Go >= 1.22)
- `/backend/ai-service`: AI 智能服务 (Python >= 3.10)
- `/backend/shared`: 跨层共享契约 (Proto, Schemas)

## 3. 规范定义与契约

### 3.1 错误码与响应规范
定义全局统一的错误码枚举和标准 JSON 响应结构：
- **标准响应**: `{"code": 0, "msg": "success", "data": {}, "trace_id": "xxx"}`
- **错误码段**:
  - `0`: 成功
  - `1000-1999`: 系统级错误 (如配置加载失败、数据库连接失败)
  - `2000-2999`: 业务逻辑错误 (如状态机流转异常、权限拒绝)
  - `3000-3999`: 外部依赖错误 (如大模型 API 调用失败、工具执行失败)

### 3.2 日志与 TraceID 规范
- **格式**: 统一日志格式为结构化 JSON。
- **必填字段**: `timestamp`, `level`, `trace_id`, `task_id`, `node_id`, `module`, `message`。
- **链路追踪**: TraceID (`InteractionID`) 在请求入口（如前端发起或 Go 接收到外部事件）生成，通过 Go 的 `context.Context`、Python 的 `contextvars` 以及 HTTP/gRPC Header 贯穿全链路。

### 3.3 基础配置解析
- **静态配置**: 使用 `.env` 存储敏感环境变量（如本地数据库密码），使用 `config.yaml` 存储基础运行参数（如端口、日志级别）。
- **SSOT 原则**: Go Runtime 作为配置的唯一事实来源 (SSOT)，负责解析并向其他层提供配置。

### 3.4 健康检查协议
- **端点**: 各服务提供统一的 `/health` 接口（HTTP 或 gRPC Health Check）。
- **响应**: `{"status": "ok", "service": "<service_name>", "version": "<version>", "timestamp": "<iso8601>"}`。

## 4. 工具链与基线配置

### 4.1 Go Runtime (Backend)
- **依赖管理**: `go mod`
- **代码检查**: `golangci-lint` (配置严格模式，禁止魔法字符串，强制错误处理)
- **测试框架**: `go test`
- **格式化**: `gofumpt` / `goimports`

### 4.2 Python AI Service (Backend)
- **依赖管理**: `poetry` (推荐，便于锁定依赖) 或 `pip` + `requirements.txt`
- **代码检查**: `ruff` (替代 flake8/isort/black，极速 Linter & Formatter), `mypy` (严格类型检查)
- **测试框架**: `pytest`

### 4.3 Electron UI (Frontend)
- **依赖管理**: `pnpm` (推荐，严格依赖树)
- **代码检查**: `eslint` (配合 TypeScript 规则), `prettier`
- **测试框架**: `vitest` (速度快，兼容 Vite)
- **类型检查**: `tsc` (严格模式)

## 5. 实施步骤与测试验证

1. **目录与包初始化**: 创建物理目录，分别初始化 `go.mod`, `pyproject.toml`, `package.json`。
2. **规范代码化**: 在各语言中编写基础的常量定义文件（错误码、日志格式、状态枚举）。
3. **工具链配置**: 写入 `.golangci.yml`, `ruff.toml`, `.eslintrc.js` 等配置文件。
4. **基线代码编写**: 编写基础的日志 Logger 封装、配置加载器骨架和健康检查接口。
5. **测试用例编写**: 针对上述基线代码编写单元测试，确保配置能正确解析、日志格式符合预期、健康检查返回正确。
6. **自动化校验**: 运行所有 Linter 和测试，修复所有警告和报错，达到 100% 测试通过率。
7. **统一启动脚本**: 编写 `Makefile` 或类似脚本，提供一键安装依赖、运行检查和测试的命令。