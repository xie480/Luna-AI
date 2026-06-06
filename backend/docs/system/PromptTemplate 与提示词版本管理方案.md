# Luna PromptTemplate 与提示词版本管理方案

## 1. 章节目标

本文档定义 Luna 系统中系统提示词（System Prompt）的模板管理、版本控制和热更新机制。确保提示词能够灵活组装，支持版本回滚，且修改后无需重启系统即可生效。

## 2. 核心架构

Python ConfigManager 统一负责 Prompt 模板的存储、装配和版本管理。

### 2.1 模板存储

Prompt 模板存储于 PostgreSQL `prompt_templates` 表中，支持版本追踪：

```sql
CREATE TABLE prompt_templates (
    template_id VARCHAR(64) PRIMARY KEY,
    name VARCHAR(128) NOT NULL,          -- 模板名称，如 'system.persona'
    version INT NOT NULL DEFAULT 1,       -- 当前版本号
    content TEXT NOT NULL,                -- 模板内容（支持 {{slot}} 插槽）
    slots JSONB DEFAULT '[]',             -- 插槽定义
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 版本历史表 (Append-Only)
CREATE TABLE prompt_template_versions (
    version_id VARCHAR(64) PRIMARY KEY,
    template_id VARCHAR(64) NOT NULL,
    version INT NOT NULL,
    content TEXT NOT NULL,
    changed_by VARCHAR(64),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 2.2 插槽装配机制

模板支持 `{{slot_name}}` 插槽语法，Python 在运行时按需填充：

```python
class PromptTemplate:
    """Prompt 模板"""
    template_id: str
    content: str     # "你是 {{name}}，你的性格是 {{personality}}"
    slots: list[str] # ["name", "personality"]
```

```python
class PromptAssembler:
    """Prompt 装配器"""

    async def assemble(self, template_id: str, slot_values: dict) -> str:
        """根据模板 ID 和插槽值装配完整 Prompt"""
        template = await self._get_template(template_id)
        return template.content.format(**slot_values)
```

## 3. 热更新机制

1. Electron 前端修改 Prompt 模板内容。
2. WebSocket 发送更新请求至 Python Backend。
3. Python 将新版本写入 PostgreSQL（Append-Only）。
4. Python 更新内存缓存，下一次 LLM 调用立即生效。
5. 无需重启系统。

## 4. 版本回滚

Python 提供了 API 支持查询和历史版本切换：

```python
@app.get("/api/v1/prompts/{template_id}/versions")
async def list_versions(template_id: str):
    """列出指定模板的所有历史版本"""

@app.post("/api/v1/prompts/{template_id}/rollback")
async def rollback_version(template_id: str, version: int):
    """回滚到指定版本"""
```

## 5. 落地实施建议

1. **Phase 1**：实现 JSON/YAML 静态模板加载 + 基础插槽装配。
2. **Phase 2**：迁移至 PostgreSQL 存储，实现版本追踪。
3. **Phase 3**：实现热更新和前端版本管理界面。
