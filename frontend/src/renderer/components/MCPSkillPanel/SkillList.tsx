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

  // 详情数据（从后端获取）
  const [skillDetails, setSkillDetails] = useState<Record<string, SkillInfo>>({});
  const [loadingDetails, setLoadingDetails] = useState<Record<string, boolean>>({});

  // 展开时获取详情列表
  useEffect(() => {
    if (!expandedId) return;
    if (skillDetails[expandedId]) return;

    const fetchDetail = async () => {
      setLoadingDetails((prev) => ({ ...prev, [expandedId]: true }));
      try {
        const { getSkillDetail } = await import('../../services/mcpSkillService');
        const detail = await getSkillDetail(expandedId);
        setSkillDetails((prev) => ({ ...prev, [expandedId]: detail as unknown as SkillInfo }));
      } catch (err) {
        console.error('Failed to load skill details:', err);
      } finally {
        setLoadingDetails((prev) => ({ ...prev, [expandedId]: false }));
      }
    };
    
    fetchDetail();
  }, [expandedId, skillDetails]);

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
              {loadingDetails[skill.id] ? (
                <div style={{ fontSize: 12, color: '#64748b', padding: '8px 0' }}>加载详情中...</div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                  {/* 关联工具 */}
                  <div>
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
                    {(!skillDetails[skill.id]?.tools || skillDetails[skill.id].tools!.length === 0) ? (
                      <div style={{ fontSize: 12, color: '#475569', padding: '4px 0' }}>
                        暂无关联工具
                      </div>
                    ) : (
                      skillDetails[skill.id].tools!.map((tool) => (
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
                            <span style={{ fontSize: 13, color: '#e2e8f0', fontWeight: 500 }}>
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

                  {/* 关联 Prompts */}
                  <div>
                    <div
                      style={{
                        fontSize: 12,
                        color: '#64748b',
                        marginBottom: 8,
                        fontWeight: 500,
                      }}
                    >
                      关联 Prompts
                    </div>
                    {(!skillDetails[skill.id]?.prompts || skillDetails[skill.id].prompts!.length === 0) ? (
                      <div style={{ fontSize: 12, color: '#475569', padding: '4px 0' }}>
                        暂无关联 Prompt
                      </div>
                    ) : (
                      skillDetails[skill.id].prompts!.map((prompt) => (
                        <div
                          key={prompt.id}
                          style={{
                            display: 'flex',
                            flexDirection: 'column',
                            gap: 4,
                            padding: '8px',
                            marginBottom: 4,
                            borderRadius: 6,
                            background: 'rgba(255,255,255,0.03)',
                          }}
                        >
                          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                            <span style={{ fontSize: 11, color: '#10b981', background: 'rgba(16,185,129,0.1)', padding: '2px 6px', borderRadius: 4 }}>
                              {prompt.phase}
                            </span>
                          </div>
                          <div style={{ fontSize: 12, color: '#94a3b8', whiteSpace: 'pre-wrap', maxHeight: '100px', overflowY: 'auto' }}>
                            {prompt.content}
                          </div>
                        </div>
                      ))
                    )}
                  </div>

                  {/* 关联 Resources */}
                  <div>
                    <div
                      style={{
                        fontSize: 12,
                        color: '#64748b',
                        marginBottom: 8,
                        fontWeight: 500,
                      }}
                    >
                      关联 Resources
                    </div>
                    {(!skillDetails[skill.id]?.resources || skillDetails[skill.id].resources!.length === 0) ? (
                      <div style={{ fontSize: 12, color: '#475569', padding: '4px 0' }}>
                        暂无关联 Resource
                      </div>
                    ) : (
                      skillDetails[skill.id].resources!.map((resource) => (
                        <div
                          key={resource.id}
                          style={{
                            display: 'flex',
                            flexDirection: 'column',
                            gap: 2,
                            padding: '6px 8px',
                            marginBottom: 4,
                            borderRadius: 6,
                            background: 'rgba(255,255,255,0.03)',
                          }}
                        >
                          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                            <span style={{ fontSize: 13, color: '#e2e8f0', fontWeight: 500 }}>
                              {resource.name}
                            </span>
                            <span style={{ fontSize: 11, color: '#3b82f6', background: 'rgba(59,130,246,0.1)', padding: '2px 6px', borderRadius: 4 }}>
                              {resource.resource_type}
                            </span>
                          </div>
                          <span style={{ fontSize: 12, color: '#94a3b8', wordBreak: 'break-all' }}>
                            URI: {resource.uri}
                          </span>
                        </div>
                      ))
                    )}
                  </div>
                </div>
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
