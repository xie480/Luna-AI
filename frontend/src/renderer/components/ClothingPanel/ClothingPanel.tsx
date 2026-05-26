/**
 * Luna AI 服装配置面板组件
 * 动态扫描 Live2D 模型目录下的全部 .exp3.json 配置文件
 * 每个文件作为一个可切换的配置项，文件名（去掉 .exp3.json）即为显示名称
 * 打勾 = 应用表达式参数到模型，取消打勾 = 还原参数为 0
 */
import React, { useEffect, useState } from 'react';
import { useSystemStore } from '../../stores/systemStore';
import { getLive2dModel } from '../../stores/live2dRef';
import './ClothingPanel.css';

/**
 * 单个配置项信息
 */
interface ClothingConfigItem {
  /** 文件名（去掉 .exp3.json 后缀） */
  id: string;
  /** 显示名称，直接使用文件名 */
  name: string;
}

/**
 * 应用表达式（启用）：将 exp3.json 中的参数值设置到模型上
 */
async function applyExpression(expName: string): Promise<void> {
  const model = getLive2dModel();
  if (!model || !model.internalModel || !model.internalModel.coreModel) {
    console.warn(`[服装配置] 无法应用 ${expName}：模型未就绪`);
    return;
  }

  try {
    // 通过 HTTP 加载对应的 .exp3.json 文件
    const response = await fetch(`/models/luna/${encodeURIComponent(expName + '.exp3.json')}`);
    if (!response.ok) {
      console.warn(`[服装配置] 加载 ${expName}.exp3.json 失败: ${response.status}`);
      return;
    }
    const expData = await response.json();

    if (!expData.Parameters || !Array.isArray(expData.Parameters)) {
      console.warn(`[服装配置] ${expName}.exp3.json 中无有效参数`);
      return;
    }

    const core = model.internalModel.coreModel;
    for (const param of expData.Parameters) {
      const paramId = param.Id;
      const value = param.Value;
      const blend = param.Blend || 'Overwrite';

      if (typeof core.setParameterValueById === 'function') {
        if (blend === 'Add') {
          // Add 模式：在现有值基础上增加
          const currentValue = core.getParameterValueById(paramId);
          core.setParameterValueById(paramId, currentValue + value);
        } else {
          // Overwrite 模式：直接覆盖
          core.setParameterValueById(paramId, value);
        }
      }
    }
  } catch (e) {
    console.warn(`[服装配置] 应用 ${expName} 失败`, e);
  }
}

/**
 * 还原表达式（禁用）：将 exp3.json 中的参数值重置为 0
 */
async function resetExpression(expName: string): Promise<void> {
  const model = getLive2dModel();
  if (!model || !model.internalModel || !model.internalModel.coreModel) {
    console.warn(`[服装配置] 无法还原 ${expName}：模型未就绪`);
    return;
  }

  try {
    const response = await fetch(`/models/luna/${encodeURIComponent(expName + '.exp3.json')}`);
    if (!response.ok) return;
    const expData = await response.json();
    if (!expData.Parameters || !Array.isArray(expData.Parameters)) return;

    const core = model.internalModel.coreModel;
    for (const param of expData.Parameters) {
      const paramId = param.Id;
      if (typeof core.setParameterValueById === 'function') {
        core.setParameterValueById(paramId, 0);
      }
    }
  } catch (e) {
    console.warn(`[服装配置] 还原 ${expName} 失败`, e);
  }
}

/**
 * 服装配置面板组件
 * 动态扫描目录中所有 .exp3.json 文件并展示为可切换项
 */
export const ClothingPanel: React.FC = () => {
  // 从 Store 获取服装配置状态和更新方法
  const clothingConfig = useSystemStore((state) => state.clothingConfig);
  const setClothingConfig = useSystemStore((state) => state.setClothingConfig);
  const showGlobalMessage = useSystemStore((state) => state.showGlobalMessage);

  // 动态加载的文件列表
  const [items, setItems] = useState<ClothingConfigItem[]>([]);
  const [loading, setLoading] = useState<boolean>(true);

  // 统计已启用数
  const enabledCount = items.filter((item) => clothingConfig[item.id] ?? false).length;
  const allEnabled = items.length > 0 && enabledCount === items.length;

  /**
   * 加载配置文件列表
   */
  useEffect(() => {
    let cancelled = false;

    async function loadItems() {
      try {
        // 优先使用 Electron IPC 获取文件列表
        let fileList: string[] = [];
        if (window.electronAPI?.getModelConfigFiles) {
          fileList = await window.electronAPI.getModelConfigFiles();
        } else {
          console.warn('[服装配置] 非 Electron 环境，无法扫描模型目录');
        }

        if (cancelled) return;

        // 显示所有 .exp3.json 文件，文件名直接作为显示名称
        setItems(fileList.map((id) => ({ id, name: id })));
      } catch (e) {
        console.warn('[服装配置] 加载配置文件列表失败', e);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    loadItems();
    return () => { cancelled = true; };
  }, []);

  /**
   * 处理配置项切换
   */
  const handleToggle = async (id: string, enabled: boolean): Promise<void> => {
    // 先更新 store（持久化）
    setClothingConfig(id, enabled);

    // 再应用到模型
    if (enabled) {
      await applyExpression(id);
    } else {
      await resetExpression(id);
    }

    const msg = enabled ? `${id} 已应用` : `${id} 已还原`;
    showGlobalMessage(msg, 1500);
  };

  /**
   * 全选/全不选
   */
  const handleToggleAll = async () => {
    const newState = !allEnabled;
    for (const item of items) {
      if ((clothingConfig[item.id] ?? false) === newState) continue;
      setClothingConfig(item.id, newState);
      if (newState) {
        await applyExpression(item.id);
      } else {
        await resetExpression(item.id);
      }
    }
    showGlobalMessage(allEnabled ? '已全部还原' : '已全部应用', 1500);
  };

  if (loading) {
    return (
      <div className="clothing-panel-content">
        <div className="clothing-loading">正在扫描服装配置文件...</div>
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <div className="clothing-panel-content">
        <div className="clothing-empty">
          <div className="empty-text">未找到服装配置文件</div>
          <div className="empty-hint">请确认模型目录中存在 .exp3.json 文件</div>
        </div>
      </div>
    );
  }

  return (
    <div className="clothing-panel-content">
      {/* 顶部操作栏 */}
      <div className="clothing-toolbar">
        <div className="clothing-hint">
          {enabledCount}/{items.length} 项已启用
        </div>
        <button className="clothing-toggle-all-btn" onClick={handleToggleAll}>
          {allEnabled ? '全部还原' : '全部应用'}
        </button>
      </div>

      {/* 配置列表 */}
      <div className="clothing-list">
        {items.map((item) => {
          const isEnabled = clothingConfig[item.id] ?? false;

          return (
            <div
              key={item.id}
              className={`clothing-item ${isEnabled ? 'enabled' : ''}`}
              onClick={() => handleToggle(item.id, !isEnabled)}
            >
              {/* 左侧：名称 */}
              <div className="clothing-item-left">
                <div className="clothing-item-name">{item.name}</div>
              </div>

              {/* 右侧：复选框 */}
              <label className="clothing-toggle" onClick={(e) => e.stopPropagation()}>
                <input
                  type="checkbox"
                  checked={isEnabled}
                  onChange={(e) => handleToggle(item.id, e.target.checked)}
                  className="clothing-checkbox"
                />
                <span className="clothing-toggle-track">
                  <span className="clothing-toggle-thumb" />
                </span>
              </label>
            </div>
          );
        })}
      </div>
    </div>
  );
};
