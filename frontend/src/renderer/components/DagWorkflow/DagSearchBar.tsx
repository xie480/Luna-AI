/**
 * DagSearchBar — 节点搜索与快速定位。
 * 做什么：提供搜索输入框，支持按节点名称、工具名称、Skill 名称搜索，
 *         搜索时匹配的节点卡片高亮。
 * 为什么这样做：当 DAG 包含大量节点时，用户需要快速定位目标节点。
 * 输入输出：搜索关键词存入 dagWorkflowStore.searchQuery，子组件通过 selector 消费。
 * 边界条件：搜索支持模糊匹配（大小写不敏感的 includes）。
 * 异常行为：无。
 */
import React, { useCallback } from 'react';
import { useDagWorkflowStore } from '../../stores/dagWorkflowStore';
import { DagIconSearch, DagIconX } from './DagIcons';
import './DagSearchBar.css';

/**
 * 搜索栏组件。
 */
export const DagSearchBar: React.FC = () => {
  const searchQuery = useDagWorkflowStore((state) => state.searchQuery);
  const setSearchQuery = useDagWorkflowStore((state) => state.setSearchQuery);

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      setSearchQuery(e.target.value);
    },
    [setSearchQuery],
  );

  const handleClear = useCallback(() => {
    setSearchQuery('');
  }, [setSearchQuery]);

  return (
    <div className="dag-search-bar">
      <DagIconSearch className="dag-search-icon" width="14" height="14" />
      <input
        className="dag-search-input"
        type="text"
        placeholder="搜索节点、工具、Skill..."
        value={searchQuery}
        onChange={handleChange}
        aria-label="搜索 DAG 节点"
      />
      {searchQuery.length > 0 && (
        <button
          className="dag-search-clear"
          onClick={handleClear}
          aria-label="清除搜索"
          type="button"
        >
          <DagIconX width="12" height="12" />
        </button>
      )}
    </div>
  );
};
