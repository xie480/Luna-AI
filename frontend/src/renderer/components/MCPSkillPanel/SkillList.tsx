/**
 * 已注册的 MCP Skill 列表组件。
 *
 * 做什么：展示已注册的 MCP Skill 列表，每行包含名称、描述、版本、启用状态，
 *         "详情"和"删除"操作按钮。点击"详情"展开该 Skill 关联的工具列表，
 *         每个工具条目旁显示"配置"按钮，点击后弹出配置对话框。
 * 为什么这样做：将列表展示、展开、删除确认和工具配置入口封装在同一个组件中。
 * 输入输出：skills 列表、onDelete 和 onRefresh 回调来自父组件。
 * 边界条件：空列表显示占位文案；删除中的 Skill 按钮禁用。
 */
import React, { useState, useEffect } from 'react';
import type { SkillInfo } from '../../../shared/types';
import { ToolConfigDialog } from './ToolConfigDialog';

interface SkillListProps {
  skills: SkillInfo[];
  onDelete: (skillId: string) => Promise<void>;
  onRefresh: () => Promise<void>;
}

/** 工具简略信息（从 Skill metadata 中提取）。 */
interface ToolBrief {
  name: string;
  description: string;
  core_purpose: string;
}

export const SkillList: React.FC<SkillListProps> = ({
  skills,
  onDelete,
  onRefresh,
}) => {
  // 删除确认状态
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  // 展开详情状态
  const [expandedId, setExpandedId] = useState<string | null>(null);

  // 配置对话框状态
  const [configDialogTool, setConfigDialogTool] = useState<string | null>(null);

  // 工具的模拟数据（后续可以从后端 Skill 详情 API 获取）
  // 目前为内置工具，后续会通过 API 返回 SkillDetail 中的 tools 列表
  const [toolMapping, setToolMapping] = useState<Record<string, ToolBrief[]>>({});

  // 展开时获取工具列表（模拟数据，后续可从后端获取）
  useEffect(() => {
    if (!expandedId) return;
    if (toolMapping[expandedId]) return;

    // 当前内置 Skills 的工具关联（后续由后端 API 返回）
    const builtInTools: Record<string, ToolBrief[]> = {
      // 当 web_search 作为一个 Skill 注册时，关联的工具
    };

    // 根据技能名称猜测关联的工具
    const skill = skills.find((s) => s.id === expandedId);
    if (skill) {
      const guessedTools: ToolBrief[] = [];
      // web_search 内置工具
      if (skill.name === 'web_search' || skill.name.includes('搜索') || skill.name.includes('search')) {
        guessedTools.push({
          name: 'web_search',
          description: '通过 SearXNG 元搜索引擎执行网络搜索，获取最新互联网信息。',
          core_purpose: '搜索互联网获取最新信息',
        });
      }
      // time 工具
      if (skill.name === 'get_current_time' || skill.name.includes('时间') || skill.name.includes('time')) {
        guessedTools.push({
          name: 'get_current_time',
          description: '获取当前系统时间，可指定返回格式和时区。',
          core_purpose: '查询当前日期和时间',
        });
      }
      setToolMapping((prev) => ({
        ...prev,
        [expandedId]: guessedTools,
      }));
    }
  }, [expandedId, skills, toolMapping]);

  if (skills.length === 0) {
    return (
      <div className="local-server-list__empty">
        暂无注册的 MCP Skill，请在上方填写配置并保存。
      </div>
    );
  }

  return (
    <div className="local-server-list">
      {skills.map((skill) => (
        <div key={skill.id}>
          {/* Skill 主行 */}
          <div className="local-server-list__item">
            <div className="server-info">
              <span
                className={`server-status ${skill.enabled ? 'status-enabled' : 'status-disabled'}`}
              >
                <svg
                  width="10"
                  height="10"
                  viewBox="0 0 24 24"
                  fill={skill.enabled ? '#22c55e' : '#a0a0a0'}
                  stroke="none"
                >
                  <circle cx="12" cy="12" r="8" />
                </svg>
              </span>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <span className="server-name">{skill.name}</span>
                <span
                  style={{
                    fontSize: 12,
                    color: '#8b95a7',
                    maxWidth: 300,
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {skill.description || '暂无描述'}
                </span>
              </div>
              <span
                style={{
                  fontSize: 12,
                  color: '#64748b',
                  background: 'rgba(148, 163, 184, 0.1)',
                  padding: '2px 8px',
                  borderRadius: 4,
                }}
              >
                v{skill.version}
              </span>
            </div>
            <div className="server-actions">
              {/* 展开/收起详情按钮 */}
              <button
                className="btn-edit"
                onClick={() =>
                  setExpandedId(expandedId === skill.id ? null : skill.id)
                }
                title="查看工具列表"
                style={{ marginRight: 8 }}
              >
                {expandedId === skill.id ? '收起' : '详情'}
              </button>

              {/* 删除按钮 */}
              {confirmDeleteId === skill.id ? (
                <span className="delete-confirm-group">
                  <button
                    className="btn-delete-confirm"
                    onClick={async () => {
                      setDeletingId(skill.id);
                      setConfirmDeleteId(null);
                      try {
                        await onDelete(skill.id);
                      } finally {
                        setDeletingId(null);
                      }
                    }}
                    disabled={deletingId === skill.id}
                  >
                    {deletingId === skill.id ? '删除中...' : '确认删除'}
                  </button>
                  <button
                    className="btn-delete-cancel"
                    onClick={() => setConfirmDeleteId(null)}
                  >
                    取消
                  </button>
                </span>
              ) : (
                <button
                  className="btn-delete"
                  onClick={() => setConfirmDeleteId(skill.id)}
                  disabled={deletingId === skill.id}
                >
                  {deletingId === skill.id ? '删除中...' : '删除'}
                </button>
              )}
            </div>
          </div>

          {/* 展开的工具列表 */}
          {expandedId === skill.id && (
            <div
              style={{
                padding: '8px 16px 12px 44px',
                background: 'rgba(0,0,0,0.15)',
                borderBottom: '1px solid rgba(255,255,255,0.05)',
              }}
            >
              <div
                style={{
                  fontSize: 12,
                  color: '#64748b',
                  marginBottom: 8,
                  fontWeight: 500,
                }}
              >
                关联工具
              </div>
              {(toolMapping[skill.id] ?? []).length === 0 ? (
                <div
                  style={{
                    fontSize: 12,
                    color: '#475569',
                    padding: '8px 0',
                  }}
                >
                  暂无关联工具（通过 MCP 工具注册中心关联）
                </div>
              ) : (
                (toolMapping[skill.id] ?? []).map((tool) => (
                  <div
                    key={tool.name}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      padding: '6px 8px',
                      marginBottom: 4,
                      borderRadius: 6,
                      background: 'rgba(255,255,255,0.03)',
                    }}
                  >
                    <div
                      style={{
                        display: 'flex',
                        flexDirection: 'column',
                        gap: 2,
                        flex: 1,
                        minWidth: 0,
                      }}
                    >
                      <span
                        style={{
                          fontSize: 13,
                          color: '#e2e8f0',
                          fontWeight: 500,
                        }}
                      >
                        {tool.name}
                      </span>
                      <span
                        style={{
                          fontSize: 11,
                          color: '#64748b',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                        }}
                      >
                        {tool.core_purpose || tool.description}
                      </span>
                    </div>
                    <button
                      className="btn-edit"
                      onClick={() => setConfigDialogTool(tool.name)}
                      style={{
                        fontSize: 12,
                        padding: '4px 10px',
                        whiteSpace: 'nowrap',
                        marginLeft: 8,
                      }}
                      title={`配置 ${tool.name}`}
                    >
                      配置
                    </button>
                  </div>
                ))
              )}
            </div>
          )}
        </div>
      ))}

      {/* 配置对话框 */}
      {configDialogTool && (
        <ToolConfigDialog
          toolName={configDialogTool}
          open={true}
          onClose={() => setConfigDialogTool(null)}
          onSaved={() => {
            // 配置保存后刷新
          }}
        />
      )}
    </div>
  );
};
