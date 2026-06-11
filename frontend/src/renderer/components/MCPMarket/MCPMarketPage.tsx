/**
 * MCP 市场主页面。
 *
 * 做什么：MCP 市场首页，包含搜索栏、标签分组菜单和工具卡片网格。
 *         根据 items 的 tags 数组进行分组展示。
 * 为什么这样做：用户需要一个集中的市场入口来发现和浏览远程 MCP。
 * 输入输出：从 Store 读取市场列表数据进行渲染。
 *          onNavigateToDetail 回调用于在 MCP 面板内切换到详情视图。
 * 边界条件：列表为空时显示空状态提示。
 */
import React, { useEffect, useState, useCallback, useMemo } from 'react';
import { useMCPMarketStore } from '../../stores/mcpMarketStore';
import { MCPMarketCard } from './MCPMarketCard';
import { MCPMarketSearchBar } from './MCPMarketSearchBar';
import './MCPMarket.css';

/** 每页展示的卡片数量。 */
const PAGE_SIZE = 20;

export const MCPMarketPage: React.FC<MCPMarketPageProps> = ({ onNavigateToDetail }) => {
  const {
    marketItems,
    marketTotal,
    marketPage,
    isMarketLoading,
    marketError,
    fetchMarketList,
    searchMarket,
  } = useMCPMarketStore();

  /** 当前选中的标签，null 表示显示全部。 */
  const [activeTag, setActiveTag] = useState<string | null>(null);
  /** 前端分页页码。 */
  const [localPage, setLocalPage] = useState(1);

  // 初始加载
  useEffect(() => {
    fetchMarketList(1);
  }, [fetchMarketList]);

  /** 处理搜索。 */
  const handleSearch = useCallback(
    async (query: string) => {
      if (query.trim()) {
        await searchMarket(query);
      } else {
        await fetchMarketList(1);
      }
      setActiveTag(null);
      setLocalPage(1);
    },
    [searchMarket, fetchMarketList],
  );

  /** 从所有 items 中提取去重后的标签列表，按出现频次降序排列。 */
  const allTags = useMemo(() => {
    const tagCount = new Map<string, number>();
    for (const item of marketItems) {
      for (const tag of item.tags) {
        tagCount.set(tag, (tagCount.get(tag) || 0) + 1);
      }
    }
    return Array.from(tagCount.entries())
      .sort((a, b) => b[1] - a[1])
      .map(([tag]) => tag);
  }, [marketItems]);

  /** 根据当前选中标签过滤后的 items。 */
  const filteredItems = useMemo(() => {
    if (!activeTag) return marketItems;
    return marketItems.filter((item) => item.tags.includes(activeTag));
  }, [marketItems, activeTag]);

  /** 前端分页切片。 */
  const paginatedItems = useMemo(() => {
    const start = (localPage - 1) * PAGE_SIZE;
    return filteredItems.slice(start, start + PAGE_SIZE);
  }, [filteredItems, localPage]);

  /** 总页数。 */
  const totalPages = Math.ceil(filteredItems.length / PAGE_SIZE);

  return (
    <div className="mcp-market-page">
      <header className="mcp-market-header">
        <h1 className="market-title">MCP 市场</h1>
        <p className="market-subtitle">
          发现并接入远程 MCP 工具，扩展 Luna 的能力边界
        </p>
        <MCPMarketSearchBar onSearch={handleSearch} />
      </header>

      {/* 标签导航 */}
      <nav className="market-tag-tabs">
        <button
          className={`tag-tab ${activeTag === null ? 'active' : ''}`}
          onClick={() => { setActiveTag(null); setLocalPage(1); }}
        >
          全部
        </button>
        {allTags.map((tag) => (
          <button
            key={tag}
            className={`tag-tab ${activeTag === tag ? 'active' : ''}`}
            onClick={() => { setActiveTag(tag); setLocalPage(1); }}
          >
            {tag}
          </button>
        ))}
      </nav>

      {/* 排序栏 */}
      <div className="market-sort-bar">
        <span className="sort-label">
          共 {filteredItems.length} 个远程 MCP Server
          {activeTag && <span className="sort-tag-hint">（标签：{activeTag}）</span>}
        </span>
      </div>

      {/* 加载态 */}
      {isMarketLoading && (
        <div className="market-loading">
          <div className="spinner" />
          <span>加载中……</span>
        </div>
      )}

      {/* 错误态 */}
      {!isMarketLoading && marketError && (
        <div className="market-error">
          <p>加载失败: {marketError}</p>
          <button
            className="btn-retry"
            onClick={() => fetchMarketList(1)}
          >
            重试
          </button>
        </div>
      )}

      {/* 空态 */}
      {!isMarketLoading && !marketError && filteredItems.length === 0 && (
        <div className="market-empty">
          <div className="empty-icon">🔍</div>
          <p>暂无远程 MCP 工具</p>
          <p className="empty-hint">开发者可以提交新的 MCP 到市场</p>
        </div>
      )}

      {/* 卡片网格 */}
      {!isMarketLoading && !marketError && filteredItems.length > 0 && (
        <>
          <div className="market-card-grid">
            {paginatedItems.map((item) => (
              <MCPMarketCard
                key={item.id}
                item={item}
                onNavigateToDetail={onNavigateToDetail}
              />
            ))}
          </div>

          {/* 分页器 */}
          {totalPages > 1 && (
            <div className="market-pagination">
              <button
                className="page-btn"
                disabled={localPage <= 1}
                onClick={() => setLocalPage((p) => p - 1)}
              >
                上一页
              </button>
              <span className="page-info">
                第 {localPage} / {totalPages} 页
              </span>
              <button
                className="page-btn"
                disabled={localPage >= totalPages}
                onClick={() => setLocalPage((p) => p + 1)}
              >
                下一页
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
};
