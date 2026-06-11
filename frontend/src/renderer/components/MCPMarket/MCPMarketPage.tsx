/**
 * MCP 市场主页面。
 *
 * 做什么：MCP 市场首页，包含搜索栏、分类 Tab、排序选择和工具卡片网格。
 * 为什么这样做：用户需要一个集中的市场入口来发现和浏览远程 MCP。
 * 输入输出：从 Store 读取市场列表数据进行渲染。
 * 边界条件：列表为空时显示空状态提示。
 */
import React, { useEffect, useState, useCallback } from 'react';
import { useMCPMarketStore } from '../../stores/mcpMarketStore';
import {
  MCP_MARKET_CATEGORY,
  MCP_MARKET_CATEGORY_LABEL,
} from '../../../shared/enum';
import { MCPMarketCard } from './MCPMarketCard';
import { MCPMarketSearchBar } from './MCPMarketSearchBar';
import './MCPMarket.css';

/** 每页展示的卡片数量。 */
const PAGE_SIZE = 20;

export const MCPMarketPage: React.FC = () => {
  const {
    marketItems,
    marketTotal,
    marketPage,
    isMarketLoading,
    marketError,
    fetchMarketList,
    searchMarket,
  } = useMCPMarketStore();

  const [activeCategory, setActiveCategory] = useState<string>(MCP_MARKET_CATEGORY.ALL);
  const [sortBy, setSortBy] = useState<string>('trust_score');

  // 分类变化时重新加载
  useEffect(() => {
    fetchMarketList(
      1,
      activeCategory === MCP_MARKET_CATEGORY.ALL ? undefined : activeCategory,
    );
  }, [activeCategory, fetchMarketList]);

  /** 处理搜索。 */
  const handleSearch = useCallback(
    async (query: string) => {
      if (query.trim()) {
        await searchMarket(query);
      } else {
        await fetchMarketList(1);
      }
    },
    [searchMarket, fetchMarketList],
  );

  /** 处理分页变化。 */
  const handlePageChange = useCallback(
    async (page: number) => {
      await fetchMarketList(
        page,
        activeCategory === MCP_MARKET_CATEGORY.ALL ? undefined : activeCategory,
      );
    },
    [activeCategory, fetchMarketList],
  );

  /** 计算总页数。 */
  const totalPages = Math.ceil(marketTotal / PAGE_SIZE);

  return (
    <div className="mcp-market-page">
      <header className="mcp-market-header">
        <h1 className="market-title">MCP 市场</h1>
        <p className="market-subtitle">
          发现并接入远程 MCP 工具，扩展 Luna 的能力边界
        </p>
        <MCPMarketSearchBar onSearch={handleSearch} />
      </header>

      {/* 分类 Tab */}
      <nav className="market-category-tabs">
        {Object.entries(MCP_MARKET_CATEGORY_LABEL).map(([key, label]) => (
          <button
            key={key}
            className={`category-tab ${activeCategory === key ? 'active' : ''}`}
            onClick={() => setActiveCategory(key)}
          >
            {label}
          </button>
        ))}
      </nav>

      {/* 排序栏 */}
      <div className="market-sort-bar">
        <span className="sort-label">共 {marketTotal} 个远程 MCP Server</span>
        <select
          className="sort-select"
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value)}
        >
          <option value="trust_score">按信誉评分</option>
          <option value="github_stars">按 Stars</option>
          <option value="install_count">按接入量</option>
          <option value="updated_at">最近更新</option>
        </select>
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
            onClick={() =>
              fetchMarketList(
                marketPage,
                activeCategory === MCP_MARKET_CATEGORY.ALL
                  ? undefined
                  : activeCategory,
              )
            }
          >
            重试
          </button>
        </div>
      )}

      {/* 空态 */}
      {!isMarketLoading && !marketError && marketItems.length === 0 && (
        <div className="market-empty">
          <div className="empty-icon">🔍</div>
          <p>暂无远程 MCP 工具</p>
          <p className="empty-hint">开发者可以提交新的 MCP 到市场</p>
        </div>
      )}

      {/* 卡片网格 */}
      {!isMarketLoading && !marketError && marketItems.length > 0 && (
        <>
          <div className="market-card-grid">
            {marketItems.map((item) => (
              <MCPMarketCard key={item.id} item={item} />
            ))}
          </div>

          {/* 分页器 */}
          {totalPages > 1 && (
            <div className="market-pagination">
              <button
                className="page-btn"
                disabled={marketPage <= 1}
                onClick={() => handlePageChange(marketPage - 1)}
              >
                上一页
              </button>
              <span className="page-info">
                第 {marketPage} / {totalPages} 页
              </span>
              <button
                className="page-btn"
                disabled={marketPage >= totalPages}
                onClick={() => handlePageChange(marketPage + 1)}
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
