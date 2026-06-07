# 用户画像页面与交互 - 前端实施文档

## 1. 背景与目标

本功能在 Electron 渲染端新增“用户画像”入口和“Luna眼中的你”页面，让用户查看、手动新增、编辑、删除 Luna 当前保存的用户画像。前端仅负责交互展示和调用后端 API，不直接访问 PostgreSQL、Redis 或模型服务，符合 [`agent.md`](../../../agent.md) 的前后端职责边界。

后端实施方案见 [`backend/docs/plans/user_profile_plan.md`](../../../backend/docs/plans/user_profile_plan.md)。

## 2. 设计原则

1. 页面用于阅读画像，不使用普通表格作为主展示形态。
2. 按类别分组展示，优先使用卡片、分区、标签组等更适合“画像”阅读的形式。
3. 所有数据从 Python API 获取，前端不持久化画像真源。
4. 手动新增、编辑、删除后必须刷新后端数据，并展示缓存状态。
5. 错误、加载、空状态必须有明确 UI。
6. 不引入大型新架构，复用现有 Modal、Sidebar、Zustand、Service 风格。

## 3. 现有结构复用点

| 现有文件 | 用法 |
| --- | --- |
| [`frontend/src/renderer/components/Sidebar/Sidebar.tsx`](../../src/renderer/components/Sidebar/Sidebar.tsx) | 新增左侧菜单项“用户画像” |
| [`frontend/src/renderer/components/Modal/Modal.tsx`](../../src/renderer/components/Modal/Modal.tsx) | 新增 Modal 面板渲染分支 |
| [`frontend/src/renderer/stores/systemStore.ts`](../../src/renderer/stores/systemStore.ts) | 扩展 `ModalPanelType` |
| [`frontend/src/renderer/services/memoryService.ts`](../../src/renderer/services/memoryService.ts) | 参考服务层写法，但新建独立 userProfileService |
| [`frontend/src/renderer/services/ragService.ts`](../../src/renderer/services/ragService.ts) | 参考 TraceID 注入和标准响应解析方式 |
| [`frontend/src/shared/utils/snowflake.ts`](../../src/shared/utils/snowflake.ts) | 生成前端 TraceID 与幂等键 |
| [`frontend/src/shared/enum.ts`](../../src/shared/enum.ts) | 新增用户画像类别、状态、schema_version 常量 |

## 4. 新增文件建议

```text
frontend/src/renderer/types/userProfile.ts
frontend/src/renderer/services/userProfileService.ts
frontend/src/renderer/stores/userProfileStore.ts
frontend/src/renderer/components/UserProfile/UserProfilePanel.tsx
frontend/src/renderer/components/UserProfile/UserProfilePanel.css
frontend/src/renderer/components/UserProfile/ProfileCategorySection.tsx
frontend/src/renderer/components/UserProfile/ProfileCard.tsx
frontend/src/renderer/components/UserProfile/ProfileEditor.tsx
frontend/src/renderer/components/UserProfile/ProfileCacheStatus.tsx
```

## 5. 类型设计

在 [`frontend/src/renderer/types/userProfile.ts`](../../src/renderer/types/userProfile.ts) 新增以下类型。

```ts
export type UserProfileCategory =
  | 'appearance'
  | 'personality'
  | 'likes'
  | 'dislikes'
  | 'fears'
  | 'expectations'
  | 'habits'
  | 'custom';

export type UserProfileSourceType = 'manual' | 'model_extracted';
export type UserProfileStatus = 'active' | 'superseded' | 'deleted' | 'rejected';
export type UserProfileCacheStatus = 'valid' | 'dirty' | 'missing' | 'rebuilding' | 'failed';

export interface UserProfileItem {
  id: string;
  schema_version: 'user_profile.v1';
  category: UserProfileCategory;
  category_label: string;
  custom_category_name: string | null;
  content: string;
  source_type: UserProfileSourceType;
  confidence: number;
  status: UserProfileStatus;
  source_excerpt?: string;
  created_at: string | null;
  updated_at: string | null;
  last_confirmed_at: string | null;
}

export interface UserProfileListResponse {
  schema_version: 'user_profile.v1';
  items: UserProfileItem[];
  grouped: Record<string, UserProfileItem[]>;
  total: number;
  cache_status: UserProfileCacheStatus;
}

export interface UserProfileMutationPayload {
  schema_version: 'user_profile.v1';
  category: UserProfileCategory;
  custom_category_name?: string | null;
  content: string;
  idempotency_key?: string;
}

export interface UserProfileCacheStatusResponse {
  schema_version: 'user_profile.cache.v1';
  status: UserProfileCacheStatus;
  updated_at: string | null;
  source_item_count: number;
  summary_length: number;
  last_error: string;
}
```

在 [`frontend/src/shared/enum.ts`](../../src/shared/enum.ts) 增加常量映射：

```ts
export const USER_PROFILE_CATEGORY = {
  APPEARANCE: 'appearance',
  PERSONALITY: 'personality',
  LIKES: 'likes',
  DISLIKES: 'dislikes',
  FEARS: 'fears',
  EXPECTATIONS: 'expectations',
  HABITS: 'habits',
  CUSTOM: 'custom',
} as const;

export const USER_PROFILE_SCHEMA_VERSION = 'user_profile.v1';
```

## 6. 服务层设计

新增 [`frontend/src/renderer/services/userProfileService.ts`](../../src/renderer/services/userProfileService.ts)。服务层负责：

1. 统一 API 根路径 `/api/v1/user-profile`。
2. 为每个请求附加 `X-Trace-ID`。
3. POST 手动新增时生成 `Idempotency-Key`。
4. 解析标准响应结构，业务错误抛出中文 Error。
5. 不在组件内拼接 URL 和响应结构。

API 方法：

| 方法 | HTTP | 用途 |
| --- | --- | --- |
| `listItems(category?)` | GET `/items` | 获取全部或指定类别画像 |
| `listCategoryItems(category)` | GET `/categories/{category}/items` | 局部刷新类别 |
| `createItem(payload)` | POST `/items` | 手动新增画像 |
| `updateItem(itemId, payload)` | PUT `/items/{item_id}` | 编辑画像 |
| `deleteItem(itemId)` | DELETE `/items/{item_id}` | 删除画像 |
| `getCacheStatus()` | GET `/cache/status` | 查询压缩缓存状态 |
| `rebuildCache()` | POST `/cache/rebuild` | 手动触发缓存重建 |

错误处理规则：

1. HTTP 非 2xx：优先读取后端 `msg`，否则显示 `用户画像请求失败：HTTP 状态码`。
2. 响应缺失 `code/msg/data/trace_id`：显示 `用户画像响应结构异常`。
3. 业务 `code !== 0`：显示后端 `msg`。
4. 网络超时：显示 `用户画像服务暂时不可用，请稍后刷新`。

## 7. Zustand Store 设计

新增 [`frontend/src/renderer/stores/userProfileStore.ts`](../../src/renderer/stores/userProfileStore.ts)。状态字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `items` | `UserProfileItem[]` | 当前 active 画像列表 |
| `groupedItems` | `Record<string, UserProfileItem[]>` | 按类别分组后的列表 |
| `selectedCategory` | `UserProfileCategory | 'all'` | 当前筛选类别 |
| `cacheStatus` | `UserProfileCacheStatusResponse | null` | Redis 压缩缓存状态 |
| `isLoading` | `boolean` | 首屏加载 |
| `isRefreshing` | `boolean` | 手动刷新 |
| `isSaving` | `boolean` | 新增或编辑提交中 |
| `isDeleting` | `boolean` | 删除中 |
| `isRebuildingCache` | `boolean` | 缓存重建中 |
| `error` | `string | null` | 页面级错误 |
| `lastLoadedAt` | `number | null` | 最近成功刷新时间 |

Actions：

| Action | 说明 |
| --- | --- |
| `fetchItems()` | 拉取全部画像和缓存状态 |
| `fetchByCategory(category)` | 拉取指定类别 |
| `createProfile(payload)` | 新增手动画像，成功后刷新 |
| `updateProfile(itemId, payload)` | 编辑画像，成功后刷新 |
| `deleteProfile(itemId)` | 删除画像，成功后刷新 |
| `refreshCacheStatus()` | 查询缓存状态 |
| `rebuildCache()` | 触发缓存重建，随后轮询状态 |
| `clearError()` | 清理页面错误 |

Store 不需要持久化到 localStorage，避免隐私数据在前端额外落盘。

## 8. 侧栏与 Modal 改造

### 8.1 Sidebar 菜单

在 [`frontend/src/renderer/components/Sidebar/Sidebar.tsx`](../../src/renderer/components/Sidebar/Sidebar.tsx) 的 `MENU_ITEMS` 中新增：

```ts
{
  id: 'userProfile',
  label: '用户画像',
  icon: <UserProfileIcon />,
}
```

建议放在“记忆”和“Prompt 管理”之间，因为它属于关系域记忆，但是独立管理页。

### 8.2 SystemStore 类型

在 [`frontend/src/renderer/stores/systemStore.ts`](../../src/renderer/stores/systemStore.ts) 扩展：

```ts
export type ModalPanelType = 'dag' | 'memory' | 'userProfile' | 'prompts' | 'knowledge' | 'settings' | 'logs' | 'clothing';
```

### 8.3 Modal 渲染

在 [`frontend/src/renderer/components/Modal/Modal.tsx`](../../src/renderer/components/Modal/Modal.tsx) 增加标题与渲染分支：

| panel | title |
| --- | --- |
| `userProfile` | `Luna眼中的你` |

默认尺寸建议：宽 860，高 680。小屏下保持可滚动。

## 9. 页面布局

页面标题固定为：`Luna眼中的你`。

推荐布局：

```text
┌──────────────────────────────────────────────┐
│ Luna眼中的你                                  │
│ Luna 会把稳定、明确、与你本人相关的信息放在这里 │
├──────────────────────────────────────────────┤
│ 缓存状态条  已同步 / 待更新 / 重建中 / 失败      │
├──────────────────────────────────────────────┤
│ 新增画像输入区                                │
│ 类别选择  自定义类别  内容输入  保存按钮         │
├──────────────────────────────────────────────┤
│ 类别筛选标签                                  │
│ 全部 外貌 性格 喜欢 厌恶 害怕 期待 癖好 自定义   │
├──────────────────────────────────────────────┤
│ 分组卡片区                                    │
│ [喜欢的东西]                                  │
│   卡片：用户喜欢无糖咖啡                       │
│ [厌恶的东西]                                  │
│   卡片：用户不喜欢香菜                         │
└──────────────────────────────────────────────┘
```

### 9.1 顶部说明区

说明文本建议：

> 这里是 Luna 当前保存的、用于理解你的稳定画像。你可以手动补充、修改或删除。Luna 不会把玩笑、反讽或角色扮演内容当成稳定画像。

### 9.2 缓存状态条

状态展示：

| status | 文案 | UI |
| --- | --- | --- |
| valid | 已同步到聊天提示词 | 绿色点 |
| dirty | 有更新待压缩 | 黄色点，显示“重建”按钮 |
| missing | 暂无压缩缓存 | 灰色点，显示“生成”按钮 |
| rebuilding | 正在整理画像 | 蓝色转圈 |
| failed | 整理失败 | 红色点，显示失败原因和重试按钮 |

### 9.3 手动录入区

字段：

1. 类别选择：下拉框，包含标准类别和自定义。
2. 自定义类别输入：仅当类别为 `custom` 时显示。
3. 内容输入：多行输入框，限制 4 到 200 字。
4. 保存按钮：提交中禁用。
5. 辅助提示：`请填写稳定、明确、与你本人相关的信息，例如：我平时只喝无糖咖啡。`

前端校验：

1. 内容为空或少于 4 字，禁止提交。
2. 内容超过 200 字，禁止提交并提示。
3. `custom` 未填写自定义类别，禁止提交。
4. 禁止重复点击提交；使用 `isSaving` 锁。

### 9.4 分类展示方案

不使用普通表格。采用分组卡片：

- 每个类别一个 `ProfileCategorySection`。
- 类别标题显示中文名、数量、更新时间。
- 每条画像一个 `ProfileCard`。
- 画像卡片展示：正文、来源标签、置信度、最近确认时间、编辑和删除按钮。

来源标签：

| source_type | 文案 |
| --- | --- |
| manual | 你手动告诉 Luna |
| model_extracted | Luna 从对话中整理 |

置信度展示：

1. 手动画像显示 `已确认`。
2. 模型提取画像显示 `置信度 92%`。
3. 低于 0.75 的条目后端通常不入库；如果未来展示待确认条目，需用弱化样式。

### 9.5 编辑交互

点击卡片“编辑”：

1. 打开内联编辑或复用 `ProfileEditor` 弹层。
2. 默认填入原类别和内容。
3. 提交成功后刷新列表和缓存状态。
4. 取消时不修改本地状态。

### 9.6 删除交互

点击“删除”：

1. 弹出确认提示：`删除后 Luna 将不再在聊天中参考这条画像。`
2. 用户确认后调用删除 API。
3. 删除中禁用该卡片操作。
4. 成功后从 UI 移除，并刷新缓存状态。

### 9.7 刷新交互

页面右上角提供刷新按钮：

1. 调用 `fetchItems()` 与 `refreshCacheStatus()`。
2. 刷新中保留旧数据，显示轻量 loading。
3. 失败时保留旧数据并显示错误条。

## 10. 状态与边界情况

### 10.1 首屏加载

`UserProfilePanel` mount 时调用 `fetchItems()`。首次加载显示骨架屏，不显示空状态。

### 10.2 空状态

当 total 为 0 时展示：

标题：`Luna还没有形成稳定画像`

说明：`你可以手动告诉 Luna 一些稳定偏好，或者在长期对话整理后由 Luna 谨慎提取。`

按钮：`添加第一条画像`。

### 10.3 加载态

1. 首屏：骨架卡片。
2. 刷新：右上角按钮转圈。
3. 保存：保存按钮显示 `保存中...`。
4. 删除：卡片半透明，按钮禁用。
5. 缓存重建：状态条显示转圈。

### 10.4 失败提示

失败分级：

1. 页面级失败：首屏拉取失败，展示重试按钮。
2. 操作级失败：新增、编辑、删除失败，使用页面内错误条或现有全局提示。
3. 缓存失败：状态条显示失败原因，不影响画像列表。

错误文案必须中文，避免直接暴露堆栈。

### 10.5 隐私边界

1. 不把画像写入 localStorage。
2. 不在 `console.log` 打印画像内容。
3. 错误上报不得包含完整画像正文，可只包含 item_id 和 trace_id。
4. 前端不展示被软删除和 superseded 的历史版本，除非未来做审计页。

## 11. API 对接细节

### 11.1 获取列表

请求：

```http
GET /api/v1/user-profile/items
X-Trace-ID: web-xxx
```

前端处理：

1. `data.grouped` 存入 `groupedItems`。
2. `data.items` 存入 `items`。
3. `data.cache_status` 仅作为简要状态，随后可调用 `getCacheStatus()` 获取详细状态。

### 11.2 新增手动画像

请求：

```http
POST /api/v1/user-profile/items
X-Trace-ID: web-xxx
Idempotency-Key: web-yyy
Content-Type: application/json
```

Body：

```json
{
  "schema_version": "user_profile.v1",
  "category": "likes",
  "custom_category_name": null,
  "content": "用户喜欢无糖咖啡",
  "idempotency_key": "web-yyy"
}
```

成功后：

1. 清空输入框。
2. 刷新列表。
3. 刷新缓存状态。
4. 提示 `已添加到 Luna 的画像中`。

### 11.3 编辑画像

请求：

```http
PUT /api/v1/user-profile/items/{item_id}
```

成功后关闭编辑器并刷新。

### 11.4 删除画像

请求：

```http
DELETE /api/v1/user-profile/items/{item_id}
```

成功后从当前列表移除；如果刷新失败，仍以服务端响应为准，触发一次完整刷新。

### 11.5 缓存重建

请求：

```http
POST /api/v1/user-profile/cache/rebuild
```

成功返回 task_id 后，前端进入 `isRebuildingCache=true`，每 2 秒调用 `getCacheStatus()`，直到 status 不再是 `rebuilding` 或达到最大轮询次数。

## 12. 组件职责

### 12.1 `UserProfilePanel`

页面容器，负责加载 Store、布局、错误条和整体状态。

### 12.2 `ProfileCacheStatus`

展示缓存状态和重建按钮，不直接操作列表数据。

Props：

```ts
interface ProfileCacheStatusProps {
  status: UserProfileCacheStatusResponse | null;
  isRebuilding: boolean;
  onRebuild: () => void;
  onRefresh: () => void;
}
```

### 12.3 `ProfileEditor`

新增和编辑复用组件。

Props：

```ts
interface ProfileEditorProps {
  mode: 'create' | 'edit';
  initialValue?: UserProfileItem;
  isSaving: boolean;
  onSubmit: (payload: UserProfileMutationPayload) => Promise<void>;
  onCancel?: () => void;
}
```

### 12.4 `ProfileCategorySection`

按类别展示分区，负责折叠、数量和空分区弱提示。

### 12.5 `ProfileCard`

展示单条画像和操作按钮。卡片不直接调用 service，只通过 props 回调触发 Store action。

## 13. 样式方案

新增 [`frontend/src/renderer/components/UserProfile/UserProfilePanel.css`](../../src/renderer/components/UserProfile/UserProfilePanel.css)。建议沿用现有暗色玻璃风格：

1. 页面背景透明，适配 Modal。
2. 卡片使用半透明背景和细边框。
3. 类别区块使用柔和渐变标题条。
4. 来源和置信度使用 pill 标签。
5. 删除按钮使用低饱和红色，仅 hover 时增强。
6. 空状态使用居中插画式文案，不需要引入图片资源。

## 14. 权限与安全处理

1. 前端不传 `user_id`，由后端决定当前用户。
2. 所有修改操作必须等待后端确认后更新最终状态。
3. 不在组件内保存后端返回的历史来源原文到 localStorage。
4. 操作失败不得静默吞掉，需要显示中文错误。
5. 画像内容输入只做文本处理，不渲染 HTML，防止注入。

## 15. 测试方案

### 15.1 单元测试

| 测试项 | 重点 |
| --- | --- |
| 类型常量 | 类别映射完整，schema_version 正确 |
| service 响应解析 | 成功、HTTP 错误、业务错误、结构错误 |
| store actions | fetch、create、update、delete、rebuild 状态流转 |
| 表单校验 | 空内容、过短、过长、自定义类别缺失 |
| 分组展示 | groupedItems 正确渲染到类别区块 |

### 15.2 组件测试

1. 首屏 loading 显示骨架屏。
2. 空数据展示空状态和添加按钮。
3. 有数据时按类别分区展示，不出现普通表格。
4. 点击编辑进入编辑态，取消后恢复。
5. 删除前出现确认提示。
6. 缓存状态 dirty 时显示重建按钮。
7. 缓存状态 failed 时显示失败原因和重试按钮。

### 15.3 端到端测试

1. 从侧栏点击“用户画像”，打开标题为“Luna眼中的你”的 Modal。
2. 手动新增“喜欢的东西：用户喜欢无糖咖啡”，列表出现对应卡片。
3. 编辑该卡片为“用户喜欢无糖拿铁”，刷新后保持修改。
4. 删除该卡片后列表消失，空类别不显示或显示弱空态。
5. 点击缓存重建按钮，状态从 rebuilding 变为 valid。
6. 后端返回 500 时页面显示中文错误且不清空原数据。

## 16. 与后端联调验收

| 验收项 | 判断标准 |
| --- | --- |
| 菜单入口 | 侧栏可打开用户画像页面 |
| 获取画像 | GET 接口成功后按类别展示 |
| 手动新增 | POST 成功后 PostgreSQL 有记录，页面刷新显示 |
| 编辑画像 | PUT 成功后页面展示新内容 |
| 删除画像 | DELETE 成功后页面移除，刷新不再出现 |
| 缓存状态 | 页面能展示 valid、dirty、rebuilding、failed |
| 错误处理 | 所有失败显示中文提示，不崩溃 |
| 隐私 | localStorage 不出现画像正文 |

## 17. 实施 Todo

- [ ] 新增 `types/userProfile.ts`，定义类别、状态、请求响应类型。
- [ ] 扩展 [`frontend/src/shared/enum.ts`](../../src/shared/enum.ts) 的用户画像常量。
- [ ] 新增 `userProfileService.ts`，封装 API、TraceID、幂等键和错误解析。
- [ ] 新增 `userProfileStore.ts`，管理列表、分组、缓存状态和操作状态。
- [ ] 扩展 [`frontend/src/renderer/stores/systemStore.ts`](../../src/renderer/stores/systemStore.ts) 的 `ModalPanelType`。
- [ ] 扩展 [`frontend/src/renderer/components/Sidebar/Sidebar.tsx`](../../src/renderer/components/Sidebar/Sidebar.tsx) 新增“用户画像”菜单。
- [ ] 扩展 [`frontend/src/renderer/components/Modal/Modal.tsx`](../../src/renderer/components/Modal/Modal.tsx) 新增 `userProfile` 面板和默认尺寸。
- [ ] 新增 UserProfile 组件目录，实现页面容器、缓存状态、编辑器、分区和卡片。
- [ ] 编写 CSS，确保分组卡片展示和加载、空、失败状态完整。
- [ ] 补充 service、store、组件和端到端测试。
