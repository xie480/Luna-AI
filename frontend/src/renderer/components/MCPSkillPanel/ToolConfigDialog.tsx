/**
 * 工具配置对话框组件。
 *
 * 做什么：在 Skill 面板中，展开技能详情后展示该技能关联的工具列表，
 *         每个工具条目旁有一个"配置"按钮，点击弹出此对话框。
 *         对话框根据后端返回的字段 Schema 动态渲染配置表单。
 * 为什么这样做：工具配置不应与 .env 耦合，用户应在前端为每个工具独立设置参数。
 * 输入输出：toolName 和 schema 来自父组件，保存时调用后端 API。
 * 边界条件：无 Schema 时显示"该工具暂无配置项"提示。
 */
import React, { useState, useEffect } from 'react';
import {
  getToolConfig,
  saveToolConfig,
  deleteToolConfig,
  type ToolConfigSchema,
} from '../../services/toolConfigService';

interface ToolConfigDialogProps {
  /** 工具名称，如 "web_search"。 */
  toolName: string;
  /** 对话框是否打开。 */
  open: boolean;
  /** 关闭对话框的回调。 */
  onClose: () => void;
  /** 配置保存成功的回调。 */
  onSaved?: () => void;
}

export const ToolConfigDialog: React.FC<ToolConfigDialogProps> = ({
  toolName,
  open,
  onClose,
  onSaved,
}) => {
  /** 加载状态。 */
  const [loading, setLoading] = useState(false);
  /** 保存状态。 */
  const [saving, setSaving] = useState(false);
  /** 错误信息。 */
  const [error, setError] = useState<string | null>(null);
  /** 配置字段 Schema。 */
  const [schema, setSchema] = useState<ToolConfigSchema | null>(null);
  /** 配置值。 */
  const [values, setValues] = useState<Record<string, string>>({});
  /** 已有配置是否存在。 */
  const [hasExistingConfig, setHasExistingConfig] = useState(false);

  // 打开对话框时加载配置数据
  useEffect(() => {
    if (!open) return;

    setLoading(true);
    setError(null);
    setHasExistingConfig(false);

    getToolConfig(toolName)
      .then((response) => {
        setSchema(response.schema);
        if (response.config && response.config.config_data) {
          // 将已有配置值映射为字符串
          const mapped: Record<string, string> = {};
          for (const [k, v] of Object.entries(response.config.config_data)) {
            mapped[k] = String(v ?? '');
          }
          setValues(mapped);
          setHasExistingConfig(true);
        } else {
          // 使用 Schema 中的默认值
          if (response.schema) {
            const defaults: Record<string, string> = {};
            for (const field of response.schema.fields) {
              defaults[field.key] = field.default ?? '';
            }
            setValues(defaults);
          }
        }
      })
      .catch((err: Error) => {
        setError(err.message || '加载配置失败');
      })
      .finally(() => {
        setLoading(false);
      });
  }, [open, toolName]);

  /** 处理字段值变更。 */
  const handleChange = (key: string, value: string) => {
    setValues((prev) => ({ ...prev, [key]: value }));
  };

  /** 保存配置。 */
  const handleSave = async () => {
    setSaving(true);
    setError(null);

    try {
      // 将字符串值转为正确类型
      const configData: Record<string, unknown> = {};
      if (schema) {
        for (const field of schema.fields) {
          const rawValue = values[field.key] ?? '';
          if (field.type === 'number') {
            configData[field.key] = rawValue ? Number(rawValue) : '';
          } else {
            configData[field.key] = rawValue;
          }
        }
      } else {
        // 无 Schema，直接保存原始值
        Object.assign(configData, values);
      }

      await saveToolConfig(toolName, configData);
      onSaved?.();
      onClose();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '保存配置失败');
    } finally {
      setSaving(false);
    }
  };

  /** 清除配置。 */
  const handleClear = async () => {
    if (!hasExistingConfig) return;

    setSaving(true);
    setError(null);

    try {
      await deleteToolConfig(toolName);
      // 重置为默认值
      if (schema) {
        const defaults: Record<string, string> = {};
        for (const field of schema.fields) {
          defaults[field.key] = field.default ?? '';
        }
        setValues(defaults);
      }
      setHasExistingConfig(false);
      onSaved?.();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '清除配置失败');
    } finally {
      setSaving(false);
    }
  };

  if (!open) return null;

  return (
    <div
      className="modal-overlay"
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        background: 'rgba(0,0,0,0.5)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1000,
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className="modal-content"
        style={{
          background: '#1a1d23',
          borderRadius: 12,
          padding: 24,
          width: 520,
          maxWidth: '90vw',
          maxHeight: '80vh',
          overflowY: 'auto',
          border: '1px solid rgba(255,255,255,0.1)',
        }}
      >
        {/* 标题 */}
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: 20,
          }}
        >
          <h3
            style={{
              margin: 0,
              color: '#e2e8f0',
              fontSize: 18,
              fontWeight: 600,
            }}
          >
            {schema?.title || `配置 ${toolName}`}
          </h3>
          <button
            onClick={onClose}
            style={{
              background: 'none',
              border: 'none',
              color: '#8b95a7',
              fontSize: 20,
              cursor: 'pointer',
              padding: 4,
            }}
          >
            ×
          </button>
        </div>

        {/* 描述 */}
        {schema?.description && (
          <p
            style={{
              color: '#8b95a7',
              fontSize: 13,
              marginBottom: 16,
              lineHeight: 1.5,
            }}
          >
            {schema.description}
          </p>
        )}

        {/* 加载中 */}
        {loading && (
          <p style={{ color: '#8b95a7', textAlign: 'center', padding: 20 }}>
            加载配置中...
          </p>
        )}

        {/* 无 Schema */}
        {!loading && !schema && (
          <p style={{ color: '#8b95a7', textAlign: 'center', padding: 20 }}>
            该工具暂无配置项。
          </p>
        )}

        {/* 配置表单 */}
        {!loading && schema && (
          <div style={{ marginBottom: 20 }}>
            {schema.fields.map((field) => (
              <div key={field.key} style={{ marginBottom: 16 }}>
                <label
                  style={{
                    display: 'block',
                    color: '#cbd5e1',
                    fontSize: 13,
                    marginBottom: 6,
                    fontWeight: 500,
                  }}
                >
                  {field.label}
                  {field.required && (
                    <span style={{ color: '#ef4444', marginLeft: 4 }}>*</span>
                  )}
                </label>
                <input
                  type={field.type === 'password' ? 'password' : 'text'}
                  value={values[field.key] ?? ''}
                  onChange={(e) => handleChange(field.key, e.target.value)}
                  placeholder={field.placeholder}
                  style={{
                    width: '100%',
                    padding: '8px 12px',
                    background: '#0f1117',
                    border: '1px solid rgba(255,255,255,0.1)',
                    borderRadius: 6,
                    color: '#e2e8f0',
                    fontSize: 14,
                    outline: 'none',
                    boxSizing: 'border-box',
                  }}
                />
                {field.description && (
                  <p
                    style={{
                      color: '#64748b',
                      fontSize: 12,
                      marginTop: 4,
                      marginBottom: 0,
                    }}
                  >
                    {field.description}
                  </p>
                )}
              </div>
            ))}
          </div>
        )}

        {/* 错误信息 */}
        {error && (
          <div
            style={{
              background: 'rgba(239,68,68,0.1)',
              border: '1px solid rgba(239,68,68,0.3)',
              borderRadius: 6,
              padding: '8px 12px',
              color: '#fca5a5',
              fontSize: 13,
              marginBottom: 16,
            }}
          >
            {error}
          </div>
        )}

        {/* 操作按钮 */}
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            gap: 12,
          }}
        >
          <div>
            {hasExistingConfig && (
              <button
                onClick={handleClear}
                disabled={saving}
                style={{
                  padding: '8px 16px',
                  background: 'rgba(239,68,68,0.15)',
                  border: '1px solid rgba(239,68,68,0.3)',
                  borderRadius: 6,
                  color: '#fca5a5',
                  fontSize: 13,
                  cursor: saving ? 'not-allowed' : 'pointer',
                  opacity: saving ? 0.6 : 1,
                }}
              >
                清除配置
              </button>
            )}
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              onClick={onClose}
              disabled={saving}
              style={{
                padding: '8px 16px',
                background: 'rgba(148,163,184,0.1)',
                border: '1px solid rgba(148,163,184,0.2)',
                borderRadius: 6,
                color: '#94a3b8',
                fontSize: 13,
                cursor: saving ? 'not-allowed' : 'pointer',
              }}
            >
              取消
            </button>
            <button
              onClick={handleSave}
              disabled={saving || loading}
              style={{
                padding: '8px 16px',
                background: '#3b82f6',
                border: 'none',
                borderRadius: 6,
                color: '#fff',
                fontSize: 13,
                cursor: saving || loading ? 'not-allowed' : 'pointer',
                opacity: saving || loading ? 0.6 : 1,
              }}
            >
              {saving ? '保存中...' : '保存配置'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
