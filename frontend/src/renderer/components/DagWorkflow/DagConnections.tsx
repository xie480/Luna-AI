/**
 * DagConnections — 节点间连线组件。
 * 做什么：在两个相邻 State 之间绘制垂直连线，表达执行顺序和依赖关系。
 * 为什么这样做：DAG 工作流中的 State 存在顺序执行关系，连线可以帮助用户理解执行流程。
 * 输入输出：通过 fromState 和 toState 属性接收两个相邻 State 的投影数据。
 * 边界条件：连线样式根据 fromState 的状态动态变化。
 * 异常行为：无。
 */
import React from 'react';
import { DAG_NODE_STATUS } from '../../../shared/enum';
import type { DagStateProjection } from '../../types/dagWorkflow';
import './DagConnections.css';

/**
 * 连线组件属性。
 */
interface DagConnectionsProps {
  /** 起始 State */
  fromState: DagStateProjection;
  /** 目标 State */
  toState: DagStateProjection;
}

/**
 * 连线组件。
 * 做什么：在两个相邻 State 之间渲染一个 SVG 连线指示器。
 * 为什么这样做：State 之间存在顺序执行关系，连线帮助用户理解执行流程。
 */
export const DagConnections: React.FC<DagConnectionsProps> = ({ fromState }) => {
  // 根据起始 State 状态决定连线样式
  let lineClass = 'dag-connection-line';
  if (fromState.status === DAG_NODE_STATUS.SUCCEEDED || fromState.status === DAG_NODE_STATUS.DEGRADED) {
    lineClass += ' connection-completed';
  } else if (fromState.status === DAG_NODE_STATUS.RUNNING) {
    lineClass += ' connection-active';
  } else if (fromState.status === DAG_NODE_STATUS.FAILED) {
    lineClass += ' connection-failed';
  }

  return (
    <div className={lineClass}>
      <svg
        className="dag-connection-svg"
        viewBox="0 0 20 24"
        preserveAspectRatio="none"
      >
        <line
          x1="10"
          y1="0"
          x2="10"
          y2="24"
          className="dag-connection-path"
        />
        {/* 箭头 */}
        <polyline
          points="6,18 10,24 14,18"
          className="dag-connection-arrow"
        />
      </svg>
    </div>
  );
};
