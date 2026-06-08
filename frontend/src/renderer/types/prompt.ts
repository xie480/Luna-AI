/**
 * Luna AI Prompt 模板与版本类型定义
 * 做什么：定义 Prompt 资产管理的数据结构。
 * 为什么这样做：为前端 Prompt 管理界面提供类型支持，与后端数据模型对齐。
 */

/** Prompt 槽位位置 */
export type SlotPosition = 'system' | 'memory' | 'runtime';

/** Prompt 业务场景分类 */
export type PromptCategory = 'chat' | 'summary' | string;

/** Prompt 模板定义 */
export interface PromptTemplate {
  /** 模板唯一 ID */
  id: string;
  /** 模板名称 */
  name: string;
  /** 业务场景分类 */
  category: PromptCategory;
  /** 槽位位置 */
  slot_position: SlotPosition;
  /** 是否为系统内置模板（不可删除） */
  is_system: boolean;
  /** 当前激活（发布）的版本 ID */
  active_version_id: string;
  /** 创建时间 */
  created_at?: string;
  /** 更新时间 */
  updated_at?: string;
}

/** Prompt 版本定义 */
export interface PromptVersion {
  /** 版本唯一 ID */
  id: string;
  /** 关联的模板 ID */
  template_id: string;
  /** 版本号（递增） */
  version_num: number;
  /** 模板内容（Jinja2 格式） */
  content: string;
  /** 模板变量（逗号分隔的字符串） */
  variables: string;
  /** 版本状态 */
  status: 'draft' | 'published' | 'deprecated' | 'archived';
  /** 创建时间 */
  created_at: string;
}
