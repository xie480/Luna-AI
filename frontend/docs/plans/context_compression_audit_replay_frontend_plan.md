# frontend/docs/plans/context_compression_audit_replay_frontend_plan.md

## 1. 项目背景与目标

### 1.1 背景

当前前端已经具备基础诊断能力与部分可观测性组件，但尚未围绕“超长聊天冗余裁剪 + Token 压缩率审计 + 压缩过程可回放、可审计”形成完整可用的产品化界面。

目前可直接复用的真实基础包括：

- 诊断面板入口 [`DebugPanelInner`](../../src/renderer/components/Settings/DebugPanel/index.tsx) 提供可拖拽、可缩放的统一调试容器。
- 审计日志查看器 [`AuditLogViewer`](../../src/renderer/components/Settings/DebugPanel/AuditLogViewer.tsx) 已具备列表、分页、基础筛选和 Trace 跳转能力。
- 链路查看器 [`TraceViewer`](../../src/renderer/components/Settings/DebugPanel/TraceViewer.tsx) 已具备 Trace 查询、Span 树展示能力。
- 遥测状态仓库 [`useTelemetryStore`](../../src/renderer/stores/telemetryStore.ts) 已具备审计日志、Trace、Metrics 的基础状态组织。
- 共享消息枚举 [`WS_MSG_TYPE`](../../src/shared/enum.ts) 已包含 `EVT_TELEMETRY_TRACE`、`EVT_TELEMETRY_METRICS` 等可观测性相关常量。
- SSE 管理器 [`SSEManager`](../../src/renderer/services/sseManager.ts) 已具备统一事件分发能力，可作为后续扩展入口。

但当前仍存在明显缺口：

1. 诊断面板 [`DebugPanelInner`](../../src/renderer/components/Settings/DebugPanel/index.tsx) 当前只挂载“监控指标”和“异常日志”两个标签，审计日志与链路追踪组件没有进入统一主入口。
2. [`AuditLogViewer`](../../src/renderer/components/Settings/DebugPanel/AuditLogViewer.tsx) 当前面向的是通用审计日志字段，尚未为压缩治理设计列表视图、阶段时间线、回放详情抽屉。
3. [`useTelemetryStore`](../../src/renderer/stores/telemetryStore.ts) 中的 [`AuditLogEntry`](../../src/renderer/stores/telemetryStore.ts) 结构与当前后端 `audit_logs` 返回字段并不完全一致，更未包含压缩治理专属字段。
4. 前端没有任何页面能回答以下问题：
   - 这次回复为什么触发了压缩
   - 先做了会话消息级裁剪，还是先做了 `memory` 槽位压缩
   - 压缩前后 Token 怎么变化
   - 压缩失败后走了哪一级降级
   - 最终注入的是原始变量、分变量压缩结果，还是统一历史背景变量

### 1.2 本方案目标

本方案只聚焦以下三项能力，并要求三项能力收敛进同一轮前端设计中，而不是分散为互不关联的小功能：

1. 超长聊天冗余裁剪的前端可见化
2. Token 压缩率审计的列表化与详情化展示
3. 压缩过程可回放、可审计的界面与交互闭环

### 1.3 本方案不覆盖的范围

以下内容不属于本轮前端方案的必做范围：

- 聊天气泡中实时逐步展示压缩阶段状态
- 与 RAG 思维事件整合为单一超级时间线
- 复杂图形化 Prompt Diff 回放
- 非诊断模式下的普通用户公开入口
- DAG 编排视图与压缩治理节点图谱联动

本轮遵循“先把诊断面板内的压缩审计与回放能力做扎实，再为后续更大范围可视化扩展留接口”的原则。

---

## 2. 现状分析

### 2.1 当前已有可复用能力

#### 2.1.1 诊断面板容器已存在

[`DebugPanelInner`](../../src/renderer/components/Settings/DebugPanel/index.tsx) 已实现：

- 打开关闭控制
- 拖拽
- 缩放
- 标签页切换
- 大尺寸内容承载能力

结论：本轮不需要重新造一个全新面板，直接在现有诊断面板基础上扩容即可。

#### 2.1.2 审计日志列表能力已存在雏形

[`AuditLogViewer`](../../src/renderer/components/Settings/DebugPanel/AuditLogViewer.tsx) 已具备：

- 列表表格
- 按操作类型和状态筛选
- 分页
- TraceID 跳转

结论：可复用其列表骨架，但需要重构为“压缩审计友好版”。

#### 2.1.3 链路查看器已存在

[`TraceViewer`](../../src/renderer/components/Settings/DebugPanel/TraceViewer.tsx) 已能展示 Span 树和耗时结构。

结论：压缩回放详情页不需要自己重复实现 Span 树，只需提供“从压缩详情跳转到 TraceViewer”的协作路径。

#### 2.1.4 遥测状态管理基础已存在

[`useTelemetryStore`](../../src/renderer/stores/telemetryStore.ts) 已管理：

- `traceSpans`
- `auditLogs`
- `metrics`
- 当前 Trace 过滤条件
- 当前页码与筛选条件

结论：应继续沿用同一 Store，而不是额外创建平行可观测性状态源。

### 2.2 当前缺口

#### 2.2.1 诊断面板入口与组件挂载不完整

虽然 [`AuditLogViewer`](../../src/renderer/components/Settings/DebugPanel/AuditLogViewer.tsx) 与 [`TraceViewer`](../../src/renderer/components/Settings/DebugPanel/TraceViewer.tsx) 已存在，但当前 [`DebugPanelInner`](../../src/renderer/components/Settings/DebugPanel/index.tsx) 实际只挂载：

- 监控指标
- 异常日志

缺少：

- 压缩审计标签页
- 压缩回放详情视图
- Trace 联动入口

#### 2.2.2 审计字段模型与后端返回不完全对齐

[`AuditLogEntry`](../../src/renderer/stores/telemetryStore.ts) 当前字段包含：

- `plan_id`
- `node_id`
- `resource`
- `operation`
- `payload`
- `risk_level`
- `requires_approval`
- `user_approved`

但当前后端 [`get_audit_logs()`](../../../backend/ai-service/app/api/routers/telemetry.py) 仅返回：

- `id`
- `trace_id`
- `action_type`
- `status`
- `details`
- `error_msg`
- `timestamp`

说明：前端现有通用审计结构更像为未来复杂审计准备，当前压缩治理场景必须先做“兼容现状 + 可渐进增强”的字段适配方案。

#### 2.2.3 没有压缩治理专属列表与详情模型

当前没有以下数据结构：

- 压缩动作列表项
- 压缩回放摘要
- 压缩阶段时间线事件
- Token 压缩率统计卡片
- 压缩降级状态标签

#### 2.2.4 没有压缩过程回放入口

当前前端没有任何页面可以结构化呈现：

- 会话消息级裁剪
- 短期摘要压缩
- 长期摘要压缩
- `memory` 槽位分变量压缩
- 统一历史背景降级
- 强制硬截断保护

---

## 3. 问题定义

### 3.1 本轮前端要解决的问题

前端需要围绕后端压缩治理闭环，解决以下三个产品化问题：

1. **看得见**：开发者能够快速看到哪些请求触发了压缩治理。
2. **看得懂**：开发者能够分辨不同压缩阶段、不同作用域、不同降级层级，以及对应 Token 变化。
3. **追得回**：开发者能够从列表进入详情，回放一次压缩链路的结构化过程，并跳转到对应 Trace。

### 3.2 术语统一

为保证前后端一致，本方案前端统一使用以下术语：

- **压缩审计列表**：按请求或动作粒度展示压缩治理记录的表格视图。
- **压缩回放详情**：展示单次压缩链路的摘要、时间线、阶段详情与脱敏预览。
- **阶段时间线**：按执行顺序展示 `message_trim`、`short_summary`、`memory_slot_variable`、`historical_context_merge` 等阶段事件。
- **阶段详情卡片**：展示某阶段前后 Token、压缩率、触发原因、模型信息与成功状态。
- **统一历史背景降级**：指后端将多类历史背景变量合并为单一 `HISTORICAL_CONTEXT` 变量的降级策略。

---

## 4. 设计原则

### 4.1 优先复用现有诊断面板，不新增平行入口

本轮能力统一落在 [`DebugPanelInner`](../../src/renderer/components/Settings/DebugPanel/index.tsx) 内，不新增第二套诊断窗口。

### 4.2 列表与详情分离，避免一次性塞满表格

压缩治理信息天然有两层：

- 列表：快速定位哪次请求触发了压缩
- 详情：深入查看时间线、阶段指标与回放预览

因此本轮采用“列表 + 详情抽屉/详情面板”的组合，而不是把所有字段直接堆进表格。

### 4.3 优先结构化展示，不依赖原始 JSON 阅读

虽然 MVP 后端可能仍将压缩审计 JSON 放在 `audit_logs.details` 中，但前端不应把原始 JSON 直接暴露给用户，而应做结构化解析与稳定展示。

### 4.4 不展示完整敏感原文，只展示脱敏预览

前端只展示后端已脱敏的：

- `preview_before`
- `preview_after`
- 来源键名
- Token 指标

不在前端尝试还原完整上下文正文。

### 4.5 显式区分 MVP 与增强项

本轮必须完成：

- 压缩审计列表
- 压缩回放详情
- Token 压缩率展示
- Trace 跳转联动

本轮不强制完成：

- 实时事件流展示
- 图形化 Diff
- 聊天气泡侧边联动入口
- 与 RAG 思维事件统一时间线

---

## 5. 详细方案

### 5.1 页面与入口设计

#### 5.1.1 主入口位置

本轮统一放入 [`DebugPanelInner`](../../src/renderer/components/Settings/DebugPanel/index.tsx) 内，新增以下标签：

- `监控指标`
- `异常日志`
- `压缩审计`
- `链路追踪`

说明：

- 现有“监控指标”和“异常日志”保留。
- 新增“压缩审计”作为本轮核心入口。
- 新增“链路追踪”用于直接挂载 [`TraceViewer`](../../src/renderer/components/Settings/DebugPanel/TraceViewer.tsx)。

#### 5.1.2 标签页结构建议

建议把 [`TabType`](../../src/renderer/components/Settings/DebugPanel/index.tsx) 从当前的二元结构扩展为：

```ts
type TabType = 'metrics' | 'errors' | 'compressionAudit' | 'traces';
```

### 5.2 压缩审计列表页设计

建议新增组件：

- [`frontend/src/renderer/components/Settings/DebugPanel/CompressionAuditViewer.tsx`](../../src/renderer/components/Settings/DebugPanel)

#### 5.2.1 列表目标

用于快速回答：

- 哪次请求触发了压缩
- 作用于哪个范围
- 压缩前后 Token 如何变化
- 是否成功
- 最终走到了哪一级降级

#### 5.2.2 列表字段设计

建议表格字段：

1. 时间
2. TraceID
3. SessionID
4. 消息 ID
5. 阶段
6. 作用域
7. 触发原因
8. 原始 Token
9. 最终 Token
10. 总压缩率
11. 状态
12. 操作

#### 5.2.3 列表筛选条件

必须支持：

- 按时间范围筛选
- 按阶段筛选
- 按作用域筛选
- 按状态筛选
- 按触发原因筛选
- 按 TraceID 精确检索
- 按 SessionID 精确检索

#### 5.2.4 状态标签设计

建议状态标签：

- `成功`
- `失败`
- `已跳过`
- `已降级`
- `强制截断`

颜色建议：

- 成功：绿色
- 失败：红色
- 已跳过：灰色
- 已降级：橙色
- 强制截断：紫色或深橙

#### 5.2.5 空态与异常态

- 空态：`暂无压缩治理记录`
- 筛选空态：`当前筛选条件下暂无命中记录`
- 异常态：`压缩审计读取失败，请稍后重试`
- 加载态：骨架屏或占位行，不要只用纯文本抖动

### 5.3 压缩回放详情设计

建议新增组件：

- [`frontend/src/renderer/components/Settings/DebugPanel/CompressionReplayDrawer.tsx`](../../src/renderer/components/Settings/DebugPanel)
- 或者在桌面大尺寸条件下实现为 `CompressionReplayPanel.tsx`

本轮推荐使用**详情抽屉**，理由：

- 可从列表快速打开
- 不打断列表筛选上下文
- 符合当前诊断面板层级结构

#### 5.3.1 详情抽屉结构

建议分为四个区块：

1. **总览摘要区**
2. **阶段时间线区**
3. **阶段详情区**
4. **联动跳转区**

#### 5.3.2 总览摘要区字段

展示：

- TraceID
- SessionID
- MessageID
- 总原始 Token
- 总最终 Token
- 总压缩率
- 最终采用策略
- 是否成功
- 失败原因
- 触发时间

#### 5.3.3 阶段时间线区

时间线按顺序展示以下可能事件：

- `message_trim`
- `short_summary`
- `long_summary`
- `memory_slot_variable`
- `historical_context_merge`
- `hard_truncation`

每个时间线节点展示：

- 阶段名称
- 作用域
- 状态
- 时间戳
- 前后 Token
- 分阶段压缩率

#### 5.3.4 阶段详情区

点击某个时间线节点后，右侧或下方显示阶段详情卡片：

- 触发原因
- 模型提供方
- 模型地址摘要
- 模型 ID
- 来源键名列表
- `preview_before`
- `preview_after`
- 是否成功
- 失败原因

#### 5.3.5 联动跳转区

提供：

- `查看链路追踪` 按钮，跳转到 [`TraceViewer`](../../src/renderer/components/Settings/DebugPanel/TraceViewer.tsx) 并自动填充当前 TraceID。
- `复制 TraceID`
- `复制压缩摘要`（仅复制结构化摘要，不复制预览原文）

### 5.4 Token 压缩率展示方案

#### 5.4.1 列表层展示

在列表中直接展示：

- `原始 Token`
- `最终 Token`
- `总压缩率`

总压缩率建议显示为百分比，例如：

- `42.7%`

并在颜色上区分：

- 低压缩：灰色
- 中压缩：蓝色
- 高压缩：橙色
- 强制截断：红色强调

#### 5.4.2 详情层展示

在详情中必须展示：

- 原始 Token 数
- 裁剪后 Token 数
- 摘要后 Token 数
- 最终 Token 数
- 总压缩率
- 各阶段压缩率

建议新增卡片组件：

- `CompressionMetricSummaryCard`
- `CompressionStageMetricCard`

### 5.5 冗余裁剪前端可见化方案

虽然“冗余识别策略”属于后端逻辑，但前端必须把策略结果表达出来，而不是只显示压缩率。

#### 5.5.1 必须区分的三类动作

在详情中显式区分：

1. **会话消息级裁剪**
2. **摘要压缩级裁剪**
3. **槽位级压缩治理**

#### 5.5.2 在 UI 中的表达方式

建议使用阶段标签：

- `消息裁剪`
- `短摘要压缩`
- `长摘要压缩`
- `变量压缩`
- `统一历史背景`
- `强制截断`

并在阶段详情中展示：

- 处理前范围
- 处理后范围
- 来源变量键名
- 是否发生降级

### 5.6 数据模型改造方案

#### 5.6.1 现有问题

[`AuditLogEntry`](../../src/renderer/stores/telemetryStore.ts) 当前结构更偏向通用审计，并不适合直接承载压缩治理场景。

#### 5.6.2 建议新增前端类型

建议新增文件：[`frontend/src/renderer/types/compressionAudit.ts`](../../src/renderer/types)

建议定义：

```ts
export type CompressionStage =
  | 'message_trim'
  | 'short_summary'
  | 'long_summary'
  | 'memory_slot_variable'
  | 'historical_context_merge'
  | 'hard_truncation';

export type CompressionScope =
  | 'session_history'
  | 'long_term_memory'
  | 'external_knowledge'
  | 'user_profile'
  | 'memory_slot'
  | 'historical_context';

export type CompressionAuditStatus = 'SUCCESS' | 'FAILED' | 'SKIPPED';

export interface CompressionAuditListItem {
  id: string;
  trace_id: string;
  session_id: string;
  message_id: string;
  stage: CompressionStage;
  scope: CompressionScope;
  trigger_reason: string;
  raw_tokens: number;
  final_tokens: number;
  total_compression_ratio: number;
  status: CompressionAuditStatus;
  timestamp: string;
  replay_snapshot_id: string;
}

export interface CompressionReplayEvent {
  stage: CompressionStage;
  scope: CompressionScope;
  trigger_reason: string;
  raw_tokens: number;
  after_trim_tokens: number;
  after_summary_tokens: number;
  final_tokens: number;
  stage_compression_ratio: number;
  total_compression_ratio: number;
  model_provider: string;
  model_base_url: string;
  model_id: string;
  preview_before: string;
  preview_after: string;
  is_success: boolean;
  failure_reason: string;
  timestamp_ms: number;
}

export interface CompressionReplayDetail {
  trace_id: string;
  session_id: string;
  message_id: string;
  summary: {
    raw_tokens: number;
    final_tokens: number;
    total_compression_ratio: number;
    final_strategy: string;
    is_success: boolean;
    failure_reason: string;
  };
  events: CompressionReplayEvent[];
}
```

#### 5.6.3 遥测 Store 改造建议

建议扩展 [`useTelemetryStore`](../../src/renderer/stores/telemetryStore.ts)：

新增状态：

- `compressionAudits`
- `compressionAuditTotal`
- `compressionAuditPage`
- `compressionAuditPageSize`
- `compressionAuditFilters`
- `isLoadingCompressionAudits`
- `selectedCompressionReplay`
- `isCompressionReplayOpen`

新增动作：

- `setCompressionAudits()`
- `setCompressionAuditFilters()`
- `setCompressionAuditPage()`
- `setLoadingCompressionAudits()`
- `setSelectedCompressionReplay()`
- `setCompressionReplayOpen()`

### 5.7 服务层改造方案

建议新增服务文件：[`frontend/src/renderer/services/compressionAuditService.ts`](../../src/renderer/services)

职责：

- 拉取压缩审计列表
- 拉取压缩回放详情
- 负责把后端 `audit_logs.details` 中的压缩 JSON 解析为前端结构化对象

建议接口：

- `fetchCompressionAudits()`
- `fetchCompressionReplay(traceId: string)`
- `normalizeCompressionAudit()`
- `normalizeCompressionReplay()`

### 5.8 与现有 `AuditLogViewer` 的关系

本轮不建议继续在 [`AuditLogViewer`](../../src/renderer/components/Settings/DebugPanel/AuditLogViewer.tsx) 上无限堆字段，原因是：

- 通用审计和压缩审计关注点不同
- 压缩回放需要明显更深的详情层
- 继续混用会导致组件职责过重

建议策略：

- 保留 [`AuditLogViewer`](../../src/renderer/components/Settings/DebugPanel/AuditLogViewer.tsx) 作为“通用审计”组件
- 新增 [`CompressionAuditViewer`](../../src/renderer/components/Settings/DebugPanel) 作为“压缩治理专用审计”组件

---

## 6. 数据结构或接口变更

### 6.1 新增前端枚举建议

建议新增文件：[`frontend/src/shared/enum.ts`](../../src/shared/enum.ts)

可新增常量：

- `COMPRESSION_STAGE_LABEL`
- `COMPRESSION_SCOPE_LABEL`
- `COMPRESSION_STATUS_LABEL`

说明：

- 与后端枚举值一一对应
- 避免组件内部散落魔法字符串

### 6.2 后端接口消费约定

本轮前端约定消费以下接口：

- `GET /api/v1/telemetry/compression_audits`
- `GET /api/v1/telemetry/compression_replays/{trace_id}`

字段要求：

- 阶段、作用域、状态必须返回稳定枚举值
- Token 数字段必须为 number
- 比率字段必须为 number
- 脱敏预览字段必须是后端已处理好的安全文本

### 6.3 与当前通用审计接口的兼容策略

MVP 阶段若后端仍通过 [`get_audit_logs()`](../../../backend/ai-service/app/api/routers/telemetry.py) 返回压缩 JSON，前端先在 [`compressionAuditService.ts`](../../src/renderer/services) 中解析 `details` 字段并映射为压缩审计结构。

后端未来若新增专用接口，则前端只需替换服务层实现，不改列表与详情组件。

---

## 7. 审计与可观测性方案

### 7.1 列表层审计目标

压缩审计列表必须能支持以下追问：

- 哪类请求最容易触发压缩
- 哪个阶段最容易失败
- 强制硬截断出现频率如何
- 长期记忆、外部知识、用户画像谁最容易成为膨胀源

### 7.2 详情层可观测性目标

压缩回放详情必须回答：

- 本次链路先发生了什么
- 哪一步产生了主要 Token 收缩
- 哪一步失败后进入了降级
- 最终采用的是分变量压缩还是统一历史背景

### 7.3 与 Trace 的联动目标

压缩回放详情必须能跳转到 [`TraceViewer`](../../src/renderer/components/Settings/DebugPanel/TraceViewer.tsx)，用于查看：

- 每阶段耗时
- 是否存在模型调用延迟
- 是否存在异常重试

---

## 8. 回放机制设计

### 8.1 回放页面结构

本轮采用“列表 + 详情抽屉”的回放形式。

#### 8.1.1 详情抽屉区块

- 顶部总览摘要
- 中部阶段时间线
- 下部阶段详情折叠区
- 底部操作区

### 8.2 时间线设计

建议使用纵向时间线，节点内容包括：

- 阶段标签
- 时间戳
- 状态标签
- 前后 Token
- 阶段压缩率

当前端宽度不足时，时间线节点折叠为简版模式，只显示：

- 阶段名
- 状态
- 压缩率

点击后展开完整详情。

### 8.3 详情抽屉中的最小回放集合

前端必须完整展示以下最小回放信息：

1. 触发原因
2. 阶段名称
3. 作用域
4. 来源键名
5. 原始 Token
6. 裁剪后 Token
7. 摘要后 Token
8. 最终 Token
9. 分阶段压缩率
10. 总压缩率
11. 模型信息
12. 脱敏前后预览
13. 成功状态
14. 失败原因

### 8.4 敏感内容展示策略

前端严格遵循后端脱敏结果，不在前端做逆向拼接，不展示：

- 完整上下文正文
- 原始记忆全文
- 完整 Prompt 正文
- 任何可能恢复完整私密信息的字段组合

### 8.5 回放失败态

若回放详情接口失败，显示：

- 标题：`压缩回放加载失败`
- 内容：错误摘要
- 操作：`重试`、`关闭`

若接口返回空数据，显示：

- `当前链路未生成可回放快照`

---

## 9. 前后端协作点

### 9.1 后端需要提供的最小字段集合

前端依赖后端至少返回：

- `trace_id`
- `session_id`
- `message_id`
- `stage`
- `scope`
- `trigger_reason`
- `raw_tokens`
- `after_trim_tokens`
- `after_summary_tokens`
- `final_tokens`
- `total_compression_ratio`
- `stage_compression_ratio`
- `model_provider`
- `model_base_url`
- `model_id`
- `preview_before`
- `preview_after`
- `is_success`
- `failure_reason`
- `timestamp_ms`

### 9.2 前端需要保证的消费行为

- 不假设某一阶段一定存在
- 不假设所有链路都包含统一历史背景降级
- 不假设所有压缩动作都有模型信息
- 对缺省字段提供空态兜底

### 9.3 本轮不做的协作点

- 不要求前端基于 SSE 实时增量构建回放
- 不要求把压缩回放写回聊天消息元数据
- 不要求和 [`EVT_RAG_THOUGHT`](../../../backend/ai-service/app/types/constants.py) 做同屏统一播放

---

## 10. 实施步骤

### 10.1 MVP 必做

#### 步骤一：扩展诊断面板标签结构

建议改动位置：

- [`frontend/src/renderer/components/Settings/DebugPanel/index.tsx`](../../src/renderer/components/Settings/DebugPanel/index.tsx)

输出：

- 新增 `压缩审计` 标签
- 新增 `链路追踪` 标签
- 挂载 [`CompressionAuditViewer`](../../src/renderer/components/Settings/DebugPanel) 与 [`TraceViewer`](../../src/renderer/components/Settings/DebugPanel/TraceViewer.tsx)

#### 步骤二：新增压缩审计类型与 Store 状态

建议改动位置：

- 新增 [`frontend/src/renderer/types/compressionAudit.ts`](../../src/renderer/types)
- 修改 [`frontend/src/renderer/stores/telemetryStore.ts`](../../src/renderer/stores/telemetryStore.ts)

输出：

- 压缩审计列表结构
- 压缩回放详情结构
- 对应分页、筛选、详情开关状态

#### 步骤三：新增压缩审计服务层

建议改动位置：

- 新增 [`frontend/src/renderer/services/compressionAuditService.ts`](../../src/renderer/services)

输出：

- 列表查询
- 详情查询
- JSON 结构化适配

#### 步骤四：实现压缩审计列表组件

建议新增：

- [`frontend/src/renderer/components/Settings/DebugPanel/CompressionAuditViewer.tsx`](../../src/renderer/components/Settings/DebugPanel)

输出：

- 列表表格
- 筛选条
- 分页器
- 状态标签
- 空态、异常态、加载态

#### 步骤五：实现压缩回放详情抽屉

建议新增：

- [`frontend/src/renderer/components/Settings/DebugPanel/CompressionReplayDrawer.tsx`](../../src/renderer/components/Settings/DebugPanel)

输出：

- 总览区
- 时间线区
- 阶段详情区
- Trace 跳转联动

### 10.2 后续增强项

- 与聊天消息级联动
- 与 RAG 思维事件统一时间线
- 图形化 Token 变化折线图
- 压缩前后来源分布可视化
- 回放详情导出为调试快照文件

---

## 11. 风险与回滚

### 11.1 主要风险

1. 压缩审计字段过多，诊断面板信息密度过高，影响可读性。
2. 后端仍用通用 `audit_logs.details` 承载 JSON，前端解析需要兼容多种格式。
3. 详情抽屉若展示过多内容，可能导致小窗口下可用性差。
4. 压缩回放接口未就绪时，前端容易出现空视图或字段不对齐问题。

### 11.2 风险控制策略

- 列表层只展示关键字段，其余放入详情抽屉。
- 服务层集中做字段兼容，不把兼容逻辑散落到组件中。
- 对回放详情采用延迟加载与空态兜底。
- 前端所有新能力均以可选标签形式挂载，不影响现有监控与异常日志能力。

### 11.3 回滚方案

如出现问题，可按以下顺序回滚：

1. 在 [`DebugPanelInner`](../../src/renderer/components/Settings/DebugPanel/index.tsx) 中隐藏 `压缩审计` 标签。
2. 保留类型与服务层代码，不挂载 UI。
3. 保留 `TraceViewer` 与现有通用审计功能不变。
4. 若后端字段不稳定，前端服务层降级返回空列表与提示文案，不抛出未捕获异常。

---

## 12. 验收标准

### 12.1 超长聊天冗余裁剪可见化

满足以下条件视为通过：

1. 列表或详情中能明确区分会话消息级裁剪、摘要压缩级裁剪、槽位级压缩治理。
2. 当发生统一历史背景降级时，前端能明确展示该阶段与最终策略。
3. 当发生强制硬截断时，前端能清晰标注异常等级，不与普通压缩混淆。

### 12.2 Token 压缩率审计展示

满足以下条件视为通过：

1. 列表中可查看原始 Token、最终 Token、总压缩率。
2. 详情中可查看原始 Token、裁剪后 Token、摘要后 Token、最终 Token、总压缩率、分阶段压缩率。
3. 状态标签、阶段标签、作用域标签都有稳定中文文案。

### 12.3 压缩过程可回放、可审计

满足以下条件视为通过：

1. 用户可从压缩审计列表打开某条记录的回放详情。
2. 回放详情至少包含总览、阶段时间线、阶段详情、Trace 跳转入口。
3. 前端展示的是后端脱敏预览，而非完整原文。
4. 即使后端只返回结构化 JSON 字符串，前端也能完成解析与渲染。

### 12.4 与当前代码结构兼容

满足以下条件视为通过：

1. 不破坏现有 [`DebugPanelInner`](../../src/renderer/components/Settings/DebugPanel/index.tsx) 的基本拖拽与缩放行为。
2. 不破坏现有 [`AuditLogViewer`](../../src/renderer/components/Settings/DebugPanel/AuditLogViewer.tsx) 和 [`TraceViewer`](../../src/renderer/components/Settings/DebugPanel/TraceViewer.tsx) 的既有功能。
3. 新增 Store 状态与服务层逻辑集中管理，不把压缩治理逻辑散落到多个页面组件中。
4. 当后端压缩审计接口不可用时，前端能优雅降级为可解释的空态与异常态。