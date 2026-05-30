# Phase 3：配置、Prompt 与密钥管理 前端架构与实施方案

## 1. 设计目标与业务背景

基于 `agent.md` 的三层解耦架构与 `phase3_plan.md` 的后端设计，前端（Electron + React）在 Phase 3 中的核心定位是**配置与 Prompt 资产的可视化管理及交互触发端**。

前端架构设计的核心目标包括：

1.  **遵循 SSOT 原则**：前端不持久化任何配置或 Prompt 数据，所有状态均通过 WebSocket/HTTP 从 Go Runtime 获取，并监听 Go 的广播事件进行状态同步。
2.  **安全交互体验**：提供安全的 API Key 输入面板（密码框掩码、脱敏展示），确保敏感信息在前端内存中生命周期最短，且绝不落盘。
3.  **Prompt 资产可视化**：构建直观的 Prompt 模板与版本管理界面，支持 `[业务场景]_[槽位]` 规范的展示，提供版本 Diff 对比与一键发布（热配置）功能。
4.  **实时调试能力**：提供开发者视角的调试面板，支持模拟上下文变量，预览 Jinja2 渲染后的完整 Prompt 字符串。

## 2. 前端技术栈规划

*   **框架**：React 18.x + TypeScript 5.x
*   **状态管理**：Zustand 4.x (用于全局配置状态与 UI 临时状态)
*   **路由**：React Router v6 (用于设置面板内的多视图切换)
*   **通信**：WebSocket (基于现有的 `wsManager.ts`，用于接收配置变更广播) + Fetch/Axios (用于 CRUD 操作)
*   **UI 组件库**：(假设项目已有基础组件库，如 Radix UI 或自定义组件)
*   **代码编辑器**：Monaco Editor 或 CodeMirror (用于 Prompt 模板的高亮编辑与 Diff 展示)

## 3. 目录与文件结构设计

在 `frontend/src/renderer/` 目录下扩展以下结构：

```text
frontend/src/renderer/
├── components/
│   ├── Settings/                  # 设置面板根组件
│   │   ├── SettingsModal.tsx      # 设置弹窗容器
│   │   ├── GeneralConfig/         # 全局配置与密钥管理模块
│   │   │   ├── ApiKeyInput.tsx    # 安全的 API Key 输入组件
│   │   │   └── ModelSelector.tsx  # 模型切换组件
│   │   ├── PromptManager/         # Prompt 资产管理模块
│   │   │   ├── TemplateList.tsx   # 模板列表 (按业务场景分组)
│   │   │   ├── VersionHistory.tsx # 版本历史与状态展示
│   │   │   ├── PromptEditor.tsx   # 基于 Monaco 的代码编辑器
│   │   │   └── DiffViewer.tsx     # 版本差异对比组件
│   │   └── DebugPanel/            # 调试与预览模块
│   │       └── PromptPreview.tsx  # 模拟上下文渲染预览
├── services/
│   ├── configService.ts           # 封装配置相关的 HTTP API 请求
│   └── promptService.ts           # 封装 Prompt 相关的 HTTP API 请求
├── stores/
│   ├── configStore.ts             # Zustand: 全局配置状态 (监听 WS 同步)
│   └── promptStore.ts             # Zustand: Prompt 管理界面的 UI 状态
└── types/
    ├── config.ts                  # 配置相关的数据模型接口
    └── prompt.ts                  # Prompt 相关的数据模型接口
```

## 4. 核心状态管理方案 (Zustand)

### 4.1 `configStore.ts` (全局配置状态)

负责维护从 Go 获取的最新配置快照，并监听 WebSocket 的 `config.changed` 事件实现热更新。

```typescript
import { create } from 'zustand';
import { wsManager } from '../services/wsManager';
import { AppConfig } from '../types/config';

interface ConfigState {
  config: AppConfig | null;
  isLoading: boolean;
  error: string | null;
  fetchConfig: () => Promise<void>;
  updateConfig: (updates: Partial<AppConfig>) => Promise<void>;
}

export const useConfigStore = create<ConfigState>((set) => {
  // 监听 Go 后端的配置变更广播
  wsManager.on('config.changed', (newConfig: AppConfig) => {
    set({ config: newConfig });
  });

  return {
    config: null,
    isLoading: false,
    error: null,
    fetchConfig: async () => {
      set({ isLoading: true });
      try {
        // 调用 HTTP API 获取脱敏后的配置
        const res = await fetch('/api/v1/config');
        const data = await res.json();
        set({ config: data, isLoading: false });
      } catch (err) {
        set({ error: 'Failed to load config', isLoading: false });
      }
    },
    updateConfig: async (updates) => {
      // 发送更新请求，Go 端处理加密与落盘后会广播 config.changed
      await fetch('/api/v1/config', {
        method: 'PUT',
        body: JSON.stringify(updates),
      });
    },
  };
});
```

## 5. 核心业务模块组件拆分与实现

### 5.1 系统全局配置与加密密钥安全输入面板 (`GeneralConfig`)

**设计逻辑**：
*   API Key 必须以密码框形式输入，展示时仅显示掩码（如 `sk-****1234`）。
*   前端不保存明文 Key，提交后立即清除组件内部的明文状态。

**关键组件示例 (`ApiKeyInput.tsx`)**：

```tsx
import React, { useState } from 'react';
import { useConfigStore } from '../../stores/configStore';

export const ApiKeyInput: React.FC = () => {
  const { config, updateConfig } = useConfigStore();
  const [isEditing, setIsEditing] = useState(false);
  const [inputValue, setInputValue] = useState('');

  // 假设 config 中包含脱敏后的 key
  const displayKey = config?.llm?.openai?.api_key || 'Not Set';

  const handleSave = async () => {
    if (inputValue) {
      await updateConfig({ 'llm.openai.api_key': inputValue });
      setInputValue('');
      setIsEditing(false);
    }
  };

  return (
    <div className="api-key-input">
      <label>OpenAI API Key</label>
      {isEditing ? (
        <>
          <input
            type="password"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            placeholder="sk-..."
          />
          <button onClick={handleSave}>Save</button>
          <button onClick={() => setIsEditing(false)}>Cancel</button>
        </>
      ) : (
        <>
          <span>{displayKey}</span>
          <button onClick={() => setIsEditing(true)}>Edit</button>
        </>
      )}
    </div>
  );
};
```

### 5.2 Prompt 模板与多版本管理可视化界面 (`PromptManager`)

**设计逻辑**：
*   **列表视图**：按业务场景（如 `chat`, `summarize`）分组展示模板，清晰标明三个标准槽位（`system`, `memory`, `runtime`）。
*   **版本历史**：选中模板后，展示其版本时间线，高亮当前 `Published` 版本。
*   **编辑器**：提供代码编辑器编写 Jinja2 模板，支持保存为 `Draft` 或直接 `Publish`。

**数据模型定义 (`types/prompt.ts`)**：

```typescript
export interface PromptTemplate {
  id: string;
  name: string; // e.g., "chat_system"
  category: string; // e.g., "chat"
  slot_position: 'system' | 'memory' | 'runtime';
  is_system: boolean;
  active_version_id: string;
}

export interface PromptVersion {
  id: string;
  template_id: string;
  version_num: number;
  content: string;
  variables: string[];
  status: 'draft' | 'published' | 'archived';
  created_at: string;
}
```

**关键组件示例 (`PromptEditor.tsx` 伪代码)**：

```tsx
import React, { useState } from 'react';
import Editor from '@monaco-editor/react'; // 假设使用 Monaco
import { promptService } from '../../services/promptService';

interface Props {
  templateId: string;
  initialContent: string;
  onSaved: () => void;
}

export const PromptEditor: React.FC<Props> = ({ templateId, initialContent, onSaved }) => {
  const [content, setContent] = useState(initialContent);

  const handleCreateVersion = async () => {
    // 提取 Jinja2 变量 (简单正则示例)
    const variables = Array.from(content.matchAll(/\{\{(.*?)\}\}/g)).map(m => m[1].trim());
    
    await promptService.createVersion(templateId, content, variables);
    onSaved();
  };

  return (
    <div className="prompt-editor">
      <Editor
        height="400px"
        defaultLanguage="jinja2"
        value={content}
        onChange={(val) => setContent(val || '')}
      />
      <button onClick={handleCreateVersion}>Save as New Version</button>
    </div>
  );
};
```

### 5.3 实时上下文与槽位渲染调试视图 (`DebugPanel`)

**设计逻辑**：
*   允许开发者手动输入模拟的上下文变量（如 `user_name`, `current_time`）。
*   调用 Go 提供的 Dry Run 接口，获取 Python 渲染后的完整 Prompt 字符串。
*   展示最终组装的 `system`, `memory`, `runtime` 槽位内容，便于排查“大模型精神分裂”或变量缺失问题。

**数据服务层实现 (`services/promptService.ts`)**：

```typescript
export const promptService = {
  // ... 其他 CRUD 方法
  
  // 触发 Dry Run 预览
  previewPrompt: async (agentId: string, contextVars: Record<string, string>) => {
    const response = await fetch('/api/v1/prompts/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ agent_id: agentId, context_variables: contextVars }),
    });
    return response.json(); // 返回渲染后的完整字符串
  }
};
```

## 6. 实施步骤建议

1.  **基础框架搭建**：在 `components/Settings` 下建立路由结构，引入 Zustand store。
2.  **配置面板开发**：优先实现 `GeneralConfig`，打通与 Go 的 HTTP 获取和 WebSocket 热更新链路，验证 API Key 的安全输入与脱敏展示。
3.  **Prompt 管理器开发**：实现 `PromptManager` 的列表与版本历史视图，集成 Monaco Editor。
4.  **调试面板开发**：实现 `DebugPanel`，联调 Go 的 Dry Run 接口，完成渲染预览功能。