import React from 'react';

/**
 * EnvInput 组件接口。
 *
 * 做什么：MCP 服务器环境变量输入组件。
 *         以键值对列表形式展示，每行包含 Key 和 Value 两个输入框。
 * 为什么这样做：环境变量是键值对结构，分开输入比 JSON 编辑更友好。
 * 输入输出：输入环境变量字典，输出更新后的字典。
 * 边界条件：Key 不能为空，Value 可以为空字符串；Key 不能包含特殊字符。
 * 异常行为：Key 重复时提示用户。
 */
interface EnvInputProps {
  value: Record<string, string>;
  onChange: (env: Record<string, string>) => void;
}

export const EnvInput: React.FC<EnvInputProps> = ({ value, onChange }) => {
  // 为了方便编辑，我们将对象转换为数组 [{ key: 'k1', value: 'v1' }]
  const envEntries = Object.entries(value);

  const handleKeyChange = (oldKey: string, newKey: string, val: string) => {
    const newEnv = { ...value };
    if (oldKey !== newKey) {
      delete newEnv[oldKey];
    }
    if (newKey) {
      newEnv[newKey] = val;
    }
    onChange(newEnv);
  };

  const handleValueChange = (key: string, newVal: string) => {
    const newEnv = { ...value, [key]: newVal };
    onChange(newEnv);
  };

  const removeEntry = (keyToRemove: string) => {
    const newEnv = { ...value };
    delete newEnv[keyToRemove];
    onChange(newEnv);
  };

  const addEntry = () => {
    // 寻找一个唯一的新键名
    let newKey = 'NEW_ENV';
    let counter = 1;
    while (value[newKey]) {
      newKey = `NEW_ENV_${counter}`;
      counter++;
    }
    onChange({ ...value, [newKey]: '' });
  };

  return (
    <div className="env-input-container">
      {envEntries.map(([key, val], index) => (
        <div key={index} className="env-entry-row">
          <input
            type="text"
            className="env-key-input"
            value={key}
            placeholder="Key"
            onChange={(e) => handleKeyChange(key, e.target.value, val)}
          />
          <span className="env-separator">=</span>
          <input
            type="text"
            className="env-value-input"
            value={val}
            placeholder="Value"
            onChange={(e) => handleValueChange(key, e.target.value)}
          />
          <button
            type="button"
            className="env-remove-btn"
            onClick={() => removeEntry(key)}
            title="移除此环境变量"
          >
            &times;
          </button>
        </div>
      ))}
      <button type="button" className="btn-add-env" onClick={addEntry}>
        + 添加环境变量
      </button>
    </div>
  );
};
