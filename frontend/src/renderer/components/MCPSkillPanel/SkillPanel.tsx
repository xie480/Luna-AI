/**
 * MCP Skill 管理面板组件。
 *
 * 做什么：整合 MCP Skill 的注册和列表展示功能，支持表格手动填写和 JSON 批量导入两种注册模式。
 * 为什么这样做：与 MCP 本地服务器面板的设计模式保持一致，降低用户学习成本。
 * 输入输出：加载 Skill 列表、注册/删除 Skill。
 * 边界条件：初始化时自动加载已注册列表。
 * 异常行为：列表加载失败时展示错误信息。
 */
import React, { useEffect, useState } from 'react';
import { useSkillStore } from '../../stores/mcpSkillStore';
import { SkillManualRegisterForm } from './SkillManualRegisterForm';
import { SkillJsonImportPanel } from './SkillJsonImportPanel';
import { SkillList } from './SkillList';

/** 注册模式类型 */
type RegisterMode = 'manual' | 'json_import';

export const SkillPanel: React.FC = () => {
  const [registerMode, setRegisterMode] = useState<RegisterMode>('manual');

  const { skills, isLoading, loadError, loadSkills, deleteSkill } =
    useSkillStore();

  // 初始化加载已注册列表
  useEffect(() => {
    loadSkills();
  }, [loadSkills]);

  return (
    <div className="local-server-panel">
      {/* 注册模式切换 */}
      <div className="local-server-panel__mode-switch">
        <button
          className={`mode-btn ${registerMode === 'manual' ? 'mode-btn--active' : ''}`}
          onClick={() => setRegisterMode('manual')}
        >
          表格手动填写
        </button>
        <button
          className={`mode-btn ${registerMode === 'json_import' ? 'mode-btn--active' : ''}`}
          onClick={() => setRegisterMode('json_import')}
        >
          JSON 批量导入
        </button>
      </div>

      {/* 注册表单区域 */}
      <div className="local-server-panel__register-section">
        {registerMode === 'manual' ? (
          <SkillManualRegisterForm />
        ) : (
          <SkillJsonImportPanel />
        )}
      </div>

      {/* 已注册 Skill 列表 */}
      <div className="local-server-panel__list-section">
        <h3 className="section-title">已注册的 MCP Skill</h3>
        {isLoading ? (
          <div className="loading-indicator">加载中...</div>
        ) : loadError ? (
          <div className="error-message">{loadError}</div>
        ) : (
          <SkillList
            skills={skills}
            onDelete={deleteSkill}
            onRefresh={loadSkills}
          />
        )}
      </div>
    </div>
  );
};
