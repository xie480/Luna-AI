import React, { useState, KeyboardEvent } from 'react';

/**
 * ArgsInput 组件接口。
 *
 * 做什么：MCP 服务器命令参数输入组件。
 *         每个参数以标签形式展示，支持添加新参数和删除已有参数。
 * 为什么这样做：参数以数组形式存储，标签化的 UI 比逗号分隔更直观易操作。
 * 输入输出：输入参数数组，输出更新后的参数数组。
 * 边界条件：空数组表示无参数；参数内容不应包含空格（空格应作为独立参数）。
 * 异常行为：无。
 */
interface ArgsInputProps {
  value: string[];
  onChange: (args: string[]) => void;
  placeholder?: string;
}

export const ArgsInput: React.FC<ArgsInputProps> = ({ value, onChange, placeholder = '输入参数后按回车' }) => {
  const [inputValue, setInputValue] = useState('');

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && inputValue.trim()) {
      e.preventDefault();
      // 分割包含空格的输入（如果有）
      const newArgs = inputValue.trim().split(/\s+/).filter(Boolean);
      onChange([...value, ...newArgs]);
      setInputValue('');
    } else if (e.key === 'Backspace' && !inputValue && value.length > 0) {
      // 当输入框为空且按删除键时，删除最后一个标签
      onChange(value.slice(0, -1));
    }
  };

  const removeArg = (indexToRemove: number) => {
    onChange(value.filter((_, index) => index !== indexToRemove));
  };

  return (
    <div className="args-input-container">
      {value.map((arg, index) => (
        <span key={index} className="arg-tag">
          {arg}
          <button
            type="button"
            className="arg-tag-remove"
            onClick={() => removeArg(index)}
          >
            &times;
          </button>
        </span>
      ))}
      <input
        type="text"
        className="arg-input-field"
        placeholder={value.length === 0 ? placeholder : ''}
        value={inputValue}
        onChange={(e) => setInputValue(e.target.value)}
        onKeyDown={handleKeyDown}
      />
    </div>
  );
};
