/**
 * MCP 市场搜索栏。
 *
 * 做什么：提供关键词搜索能力，支持能力级语义搜索。
 *         用户输入"能查询数据库的工具"等自然语言，后端返回匹配结果。
 * 为什么这样做：用户不仅按名称搜索，更需要按能力搜索。
 * 边界条件：防抖 300ms 后触发搜索，避免高频请求。
 */
import React, { useState, useCallback, useRef } from 'react';

interface SearchBarProps {
  onSearch: (query: string) => void;
}

export const MCPMarketSearchBar: React.FC<SearchBarProps> = ({ onSearch }) => {
  const [query, setQuery] = useState('');
  const timerRef = useRef<ReturnType<typeof setTimeout>>();

  /** 输入变化时防抖触发表单提交。 */
  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const value = e.target.value;
      setQuery(value);

      // 防抖 300ms
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => {
        onSearch(value.trim());
      }, 300);
    },
    [onSearch],
  );

  /** 回车直接提交搜索。 */
  const handleSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      onSearch(query.trim());
    },
    [query, onSearch],
  );

  return (
    <form className="mcp-market-search" onSubmit={handleSubmit}>
      <input
        type="text"
        className="search-input"
        placeholder={'搜索 MCP 工具（支持按能力搜索，如「能查询数据库的工具」）'}
        value={query}
        onChange={handleChange}
      />
      <button type="submit" className="search-button">
        搜索
      </button>
    </form>
  );
};
