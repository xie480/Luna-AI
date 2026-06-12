/**
 * 编辑本地 MCP 服务器的弹窗组件。
 *
 * 做什么：以模态弹窗形式展示服务器编辑表单，用户可修改 name、command、args、
 *         env、description 等字段，点击"保存"后调用后端 PATCH 接口更新。
 * 为什么这样做：LocalServerList 的"编辑"按钮需要一个独立的弹窗承载编辑表单，
 *              避免与注册表单共用状态的排版冲突。
 * 输入输出：
 *     - 输入：server（待编辑的服务器信息）、onClose（关闭回调）
 *     - 输出：onSaved 回调在保存成功后触发
 * 边界条件：
 *     - name 必填，command 必填，否则保存按钮禁用并显示校验提示
 *     - args 和 env 允许为空
 *     - 保存过程中按钮变为"保存中..."并禁用
 * 异常行为：网络错误或后端返回错误时在弹窗底部显示错误文案。
 */
import React, { useState, useCallback, useEffect } from 'react';
import type { LocalServerInfo } from '../../../shared/types';
import { ArgsInput } from './ArgsInput';
import { EnvInput } from './EnvInput';
import { useLocalServerStore } from '../../stores/mcpLocalServerStore';

interface EditServerModalProps {
  /** 待编辑的服务器信息。 */
  server: LocalServerInfo;
  /** 关闭弹窗的回调。 */
  onClose: () => void;
  /** 保存成功后的回调（可选，用于额外刷新操作）。 */
  onSaved?: () => void;
}

export const EditServerModal: React.FC<EditServerModalProps> = ({
  server,
  onClose,
  onSaved,
}) => {
  // 表单字段状态，初始值从 server prop 填充
  const [name, setName] = useState(server.name);
  const [command, setCommand] = useState(server.command);
  const [args, setArgs] = useState<string[]>(server.args);
  const [env, setEnv] = useState<Record<string, string>>(server.env);
  const [description, setDescription] = useState(server.description);
  const [enabled, setEnabled] = useState(server.enabled);

  // 保存状态
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const { updateServer } = useLocalServerStore();

  // 校验状态
  const nameMissing = !name.trim();
  const commandMissing = !command.trim();
  const hasChanges =
    name !== server.name ||
    command !== server.command ||
    JSON.stringify(args) !== JSON.stringify(server.args) ||
    JSON.stringify(env) !== JSON.stringify(server.env) ||
    description !== server.description ||
    enabled !== server.enabled;

  /**
   * 点击遮罩层关闭弹窗。
   */
  const handleOverlayClick = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      if (e.target === e.currentTarget) {
        onClose();
      }
    },
    [onClose]
  );

  /**
   * 处理保存操作。
   */
  const handleSave = useCallback(async () => {
    // 前端校验
    if (!name.trim() || !command.trim()) {
      setError('服务器名称和启动命令不能为空');
      return;
    }

    setSaving(true);
    setError('');

    try {
      await updateServer(server.id, {
        name: name !== server.name ? name : undefined,
        command: command !== server.command ? command : undefined,
        args: JSON.stringify(args) !== JSON.stringify(server.args) ? args : undefined,
        env: JSON.stringify(env) !== JSON.stringify(server.env) ? env : undefined,
        description: description !== server.description ? description : undefined,
        enabled: enabled !== server.enabled ? enabled : undefined,
      });
      onSaved?.();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存失败，请重试');
    } finally {
      setSaving(false);
    }
  }, [name, command, args, env, description, enabled, server, updateServer, onSaved, onClose]);

  /**
   * 按 Escape 键关闭弹窗。
   */
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  return (
    <div className="edit-server-modal-overlay" onClick={handleOverlayClick}>
      <div className="edit-server-modal">
        {/* 弹窗头部 */}
        <div className="edit-server-modal__header">
          <h3 className="edit-server-modal__title">编辑本地服务器</h3>
          <button className="edit-server-modal__close" onClick={onClose}>
            ✕
          </button>
        </div>

        {/* 弹窗内容区 */}
        <div className="edit-server-modal__body">
          {/* 服务器名称 */}
          <div className="edit-server-modal__field">
            <label className="edit-server-modal__label">
              服务器名称 <span className="required">*</span>
            </label>
            <input
              type="text"
              className={`edit-server-modal__input ${nameMissing ? 'input-error' : ''}`}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="如 my-data-service"
            />
            {nameMissing && <span className="edit-server-modal__hint">名称不能为空</span>}
          </div>

          {/* 启动命令 */}
          <div className="edit-server-modal__field">
            <label className="edit-server-modal__label">
              启动命令 <span className="required">*</span>
            </label>
            <input
              type="text"
              className={`edit-server-modal__input ${commandMissing ? 'input-error' : ''}`}
              value={command}
              onChange={(e) => setCommand(e.target.value)}
              placeholder="如 npx, node, python"
            />
            {commandMissing && <span className="edit-server-modal__hint">启动命令不能为空</span>}
          </div>

          {/* 命令参数 */}
          <div className="edit-server-modal__field">
            <label className="edit-server-modal__label">命令参数</label>
            <ArgsInput value={args} onChange={setArgs} placeholder="输入参数后按回车添加" />
          </div>

          {/* 环境变量 */}
          <div className="edit-server-modal__field">
            <label className="edit-server-modal__label">环境变量</label>
            <EnvInput value={env} onChange={setEnv} />
          </div>

          {/* 描述 */}
          <div className="edit-server-modal__field">
            <label className="edit-server-modal__label">描述</label>
            <input
              type="text"
              className="edit-server-modal__input"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="服务器功能描述（可选）"
            />
          </div>

          {/* 启用开关 */}
          <div className="edit-server-modal__field edit-server-modal__field--inline">
            <label className="edit-server-modal__label">启用状态</label>
            <label className="edit-server-modal__toggle">
              <input
                type="checkbox"
                checked={enabled}
                onChange={(e) => setEnabled(e.target.checked)}
              />
              <span className="toggle-slider"></span>
              <span className="toggle-text">{enabled ? '已启用' : '已禁用'}</span>
            </label>
          </div>

          {/* 错误提示 */}
          {error && <div className="edit-server-modal__error">{error}</div>}
        </div>

        {/* 弹窗底部操作栏 */}
        <div className="edit-server-modal__footer">
          <button className="edit-server-modal__btn btn-cancel" onClick={onClose}>
            取消
          </button>
          <button
            className="edit-server-modal__btn btn-save"
            onClick={handleSave}
            disabled={saving || nameMissing || commandMissing || !hasChanges}
          >
            {saving ? '保存中...' : '保存'}
          </button>
        </div>
      </div>
    </div>
  );
};
