/**
 * MCP Skill 表格手动填写组件。
 *
 * 做什么：提供表格形式的 Skill 注册界面，支持多行填写、逐行校验和批量提交。
 * 为什么这样做：与 MCP 本地服务器的手动注册表单模式保持一致，降低用户学习成本。
 * 输入输出：用户填写多行 Skill 配置后批量提交到后端。
 * 边界条件：每行至少需填写名称；支持添加/删除行。
 * 异常行为：提交失败时显示错误信息。
 */
import React, { useState, useCallback } from 'react';
import { validateSkillRow } from './skillValidation';
import { useSkillStore } from '../../stores/mcpSkillStore';

interface SkillRow {
  tempId: string;
  config: {
    name: string;
    description: string;
    version: string;
    enabled: boolean;
  };
  validationErrors: Record<string, string>;
}

let rowCounter = 0;
function generateTempId(): string {
  return `skill-row-${++rowCounter}-${Date.now()}`;
}

function createEmptyRow(): SkillRow {
  return {
    tempId: generateTempId(),
    config: { name: '', description: '', version: '1.0.0', enabled: true },
    validationErrors: {},
  };
}

export const SkillManualRegisterForm: React.FC = () => {
  const [rows, setRows] = useState<SkillRow[]>([createEmptyRow()]);
  const { registerSkill, submitStatus, submitError, resetSubmitStatus } =
    useSkillStore();

  /**
   * 更新指定行的字段值。
   */
  const updateRow = useCallback(
    (tempId: string, field: string, value: unknown) => {
      setRows((prev) =>
        prev.map((row) =>
          row.tempId === tempId
            ? { ...row, config: { ...row.config, [field]: value } }
            : row
        )
      );
    },
    []
  );

  /**
   * 添加空行。
   */
  const addRow = useCallback(() => {
    setRows((prev) => [...prev, createEmptyRow()]);
  }, []);

  /**
   * 删除指定行。
   */
  const removeRow = useCallback((tempId: string) => {
    setRows((prev) => prev.filter((row) => row.tempId !== tempId));
  }, []);

  /**
   * 校验并提交所有行。
   */
  const handleSubmit = useCallback(async () => {
    resetSubmitStatus();

    // 校验所有行
    let hasError = false;
    const validatedRows = rows.map((row) => {
      const validation = validateSkillRow(row.config);
      if (!validation.valid) {
        hasError = true;
      }
      return { ...row, validationErrors: validation.errors };
    });
    setRows(validatedRows);

    if (hasError) {
      return;
    }

    // 逐行提交
    for (const row of rows) {
      if (row.config.name) {
        try {
          await registerSkill({
            name: row.config.name.trim(),
            description: row.config.description.trim(),
            version: row.config.version || '1.0.0',
            enabled: row.config.enabled,
          });
        } catch {
          break; // 遇到错误停止后续提交
        }
      }
    }
  }, [rows, registerSkill, resetSubmitStatus]);

  return (
    <div className="manual-register-form">
      <div className="manual-register-form__header">
        <span className="field-label">Skill 名称</span>
        <span className="field-label">描述</span>
        <span className="field-label">版本</span>
        <span className="field-label">启用</span>
        <span className="field-label">操作</span>
      </div>

      {rows.map((row) => (
        <div key={row.tempId} className="manual-register-form__row">
          <input
            type="text"
            placeholder="如 my-analysis-skill"
            value={row.config.name}
            onChange={(e) => updateRow(row.tempId, 'name', e.target.value)}
            className={row.validationErrors.name ? 'input-error' : ''}
          />
          <input
            type="text"
            placeholder="Skill 功能描述"
            value={row.config.description}
            onChange={(e) =>
              updateRow(row.tempId, 'description', e.target.value)
            }
          />
          <input
            type="text"
            placeholder="如 1.0.0"
            value={row.config.version}
            onChange={(e) =>
              updateRow(row.tempId, 'version', e.target.value)
            }
            className={row.validationErrors.version ? 'input-error' : ''}
          />
          <div style={{ display: 'flex', alignItems: 'center', height: 36 }}>
            <label className="edit-server-modal__toggle">
              <input
                type="checkbox"
                checked={row.config.enabled}
                onChange={(e) =>
                  updateRow(row.tempId, 'enabled', e.target.checked)
                }
              />
              <span className="toggle-slider" />
            </label>
          </div>
          <button
            className="btn-remove-row"
            onClick={() => removeRow(row.tempId)}
            title="删除此行"
            disabled={rows.length <= 1}
          >
            ×
          </button>
          {Object.keys(row.validationErrors).length > 0 && (
            <div className="row-errors">
              {Object.values(row.validationErrors).map((msg, i) => (
                <span key={i} className="error-text">
                  {msg}
                </span>
              ))}
            </div>
          )}
        </div>
      ))}

      <div className="manual-register-form__actions">
        <button className="btn-add-row" onClick={addRow}>
          + 添加一行
        </button>
        <button
          className="btn-submit"
          onClick={handleSubmit}
          disabled={submitStatus === 'submitting'}
        >
          {submitStatus === 'submitting' ? '提交中...' : '保存并注册'}
        </button>
        <button
          className="btn-reset"
          onClick={() => setRows([createEmptyRow()])}
        >
          重置
        </button>
      </div>

      {submitStatus === 'error' && (
        <div className="submit-error">{submitError}</div>
      )}
      {submitStatus === 'success' && (
        <div className="submit-success">注册成功！</div>
      )}
    </div>
  );
};
