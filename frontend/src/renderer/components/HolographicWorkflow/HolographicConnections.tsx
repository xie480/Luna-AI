import React, { useEffect, useMemo, useRef, useState } from 'react';
import { CHAT_NODE_STATUS } from '../../../shared/enum';
import type { ChatNodeStatus } from '../../../shared/types';
import type { ChatNodeProjection } from '../../types/chatWorkflow';
import { useChatWorkflowStore } from '../../stores/chatWorkflowStore';
import './HolographicConnections.css';

interface HolographicConnectionsProps {
  nodes: ChatNodeProjection[];
  activeNodeId: string | null;
  width?: number;
}

interface ConnectionPath {
  id: string;
  d: string;
  isActive: boolean;
  isFailed: boolean;
}

const WORKFLOW_END_NODE_TYPE = 'workflow_end';
const FAILED_STATUSES = new Set<ChatNodeStatus>([
  CHAT_NODE_STATUS.FAILED,
  CHAT_NODE_STATUS.DEGRADED,
]);

/**
 * 全息工作流连线层。
 * 做什么：根据当前实际渲染在 DOM 中的节点顺序，生成垂直贝塞尔曲线路径。
 * 为什么这样做：节点链路顺序应以后端事件投影和最终 DOM 顺序为准，避免仅依赖逻辑数组导致主对话生成后链路中断。
 * 输入输出：输入节点投影、当前活跃节点和侧栏宽度，输出 SVG 路径集合。
 * 边界条件：当工作流进入 completed/failed 时，需要把终点节点一起纳入状态判断。
 * 异常行为：无。
 */
export const HolographicConnections: React.FC<HolographicConnectionsProps> = ({
  nodes,
  activeNodeId,
  width,
}) => {
  const svgRef = useRef<SVGSVGElement>(null);
  const [paths, setPaths] = useState<ConnectionPath[]>([]);
  const activePlan = useChatWorkflowStore((state) => state.activePlan);

  const nodeStatusMap = useMemo(() => {
    const map = new Map<string, ChatNodeStatus>();
    nodes.forEach((node) => {
      map.set(node.nodeType, node.status);
    });
    if (activePlan?.status === 'completed') {
      map.set(WORKFLOW_END_NODE_TYPE, CHAT_NODE_STATUS.SUCCEEDED);
    }
    if (activePlan?.status === 'failed') {
      map.set(WORKFLOW_END_NODE_TYPE, CHAT_NODE_STATUS.FAILED);
    }
    return map;
  }, [activePlan?.status, nodes]);

  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) {
      return;
    }

    const canvasElement = svg.parentElement;
    if (!canvasElement) {
      return;
    }

    const calculateConnections = () => {
      const svgRect = svg.getBoundingClientRect();
      const domNodes = Array.from(
        canvasElement.querySelectorAll<HTMLElement>('.node-list > .holographic-node-container[data-node-type]')
      ).filter((element) => element.offsetParent !== null);

      const nextPaths: ConnectionPath[] = [];

      for (let index = 0; index < domNodes.length - 1; index += 1) {
        const fromElement = domNodes[index];
        const toElement = domNodes[index + 1];
        const fromId = fromElement.dataset.nodeType;
        const toId = toElement.dataset.nodeType;

        if (!fromId || !toId) {
          continue;
        }

        const fromRect = fromElement.getBoundingClientRect();
        const toRect = toElement.getBoundingClientRect();

        const startX = fromRect.left + fromRect.width / 2 - svgRect.left;
        const startY = fromRect.bottom - svgRect.top;
        const endX = toRect.left + toRect.width / 2 - svgRect.left;
        const endY = toRect.top - svgRect.top;
        const curveFactor = Math.max(24, Math.abs(endY - startY) * 0.45);

        // Check if the current node is a condition node
        const isConditionNode = fromElement.classList.contains('node-type-condition');

        if (isConditionNode && index + 1 < domNodes.length) {
          // Find the previous node (source of the branch)
          const prevElement = index > 0 ? domNodes[index - 1] : null;

          if (prevElement) {
            const prevRect = prevElement.getBoundingClientRect();
            const prevX = prevRect.left + prevRect.width / 2 - svgRect.left;
            const prevY = prevRect.bottom - svgRect.top;

            const conditionCenterX = fromRect.left + fromRect.width / 2 - svgRect.left;
            const conditionCenterY = fromRect.top + fromRect.height / 2 - svgRect.top;
            
            // 旋转 45° 菱形（88×88）的半对角线长度 ≈ 88 / √2 ≈ 62
            const diamondHalfDiagonal = 62;
            
            // 菱形上端点（顶部顶点）：center 向上偏移半对角线
            const diamondTopX = conditionCenterX;
            const diamondTopY = conditionCenterY - diamondHalfDiagonal;
            // 菱形下端点（底部顶点）：center 向下偏移半对角线
            const diamondBottomX = conditionCenterX;
            const diamondBottomY = conditionCenterY + diamondHalfDiagonal;
            
            const conditionStatus = nodeStatusMap.get(fromId);
            
            // 1. 分支线（前置节点 → 条件节点上端点）
            const branchCurveFactor = Math.max(24, Math.abs(diamondTopY - prevY) * 0.45);
            const branchPath = `M ${prevX} ${prevY} C ${prevX} ${prevY + branchCurveFactor}, ${diamondTopX} ${diamondTopY - branchCurveFactor}, ${diamondTopX} ${diamondTopY}`;
            
            nextPaths.push({
              id: `${prevElement.dataset.nodeType}->${fromId}`,
              d: branchPath,
              isActive:
                activePlan?.status !== 'completed' &&
                activePlan?.status !== 'failed' &&
                fromId === activeNodeId,
              isFailed: conditionStatus ? FAILED_STATUSES.has(conditionStatus) : false,
            });
            
            // 2. 合并线（条件节点下端点 → 目标节点）
            const toRect = toElement.getBoundingClientRect();
            const endX = toRect.left + toRect.width / 2 - svgRect.left;
            const endY = toRect.top - svgRect.top;
            
            const mergeCurveFactor = Math.max(24, Math.abs(endY - diamondBottomY) * 0.45);
            const mergePath = `M ${diamondBottomX} ${diamondBottomY} C ${diamondBottomX} ${diamondBottomY + mergeCurveFactor}, ${endX} ${endY - mergeCurveFactor}, ${endX} ${endY}`;
            
            const targetStatus = nodeStatusMap.get(toId);
            
            nextPaths.push({
              id: `${fromId}->${toId}`,
              d: mergePath,
              isActive:
                activePlan?.status !== 'completed' &&
                activePlan?.status !== 'failed' &&
                toId === activeNodeId &&
                conditionStatus !== 'not_entered_by_condition', // Only active if actually entered
              isFailed: targetStatus ? FAILED_STATUSES.has(targetStatus) : false,
            });
            
            // 3. Main trunk path (bypassing condition) — 向左弯曲绕过菱形节点
            const bypassLeftOffset = Math.min(60, prevRect.width * 0.35); // 向左偏移量
            const bypassStartX = prevX - bypassLeftOffset;
            const bypassEndX = endX - bypassLeftOffset;
            
            const bypassCurveFactor = Math.max(24, Math.abs(endY - prevY) * 0.45);
            const bypassPath = `M ${prevX} ${prevY} C ${bypassStartX} ${prevY + bypassCurveFactor}, ${bypassEndX} ${endY - bypassCurveFactor}, ${endX} ${endY}`;
            
            nextPaths.push({
              id: `${prevElement.dataset.nodeType}->${toId}_bypass`,
              d: bypassPath,
              isActive:
                activePlan?.status !== 'completed' &&
                activePlan?.status !== 'failed' &&
                toId === activeNodeId &&
                conditionStatus === 'not_entered_by_condition', // Active if condition was bypassed
              isFailed: targetStatus ? FAILED_STATUSES.has(targetStatus) : false,
            });
          }
        } else {
          // Normal sequential path
          const isNextNodeCondition = toElement.classList.contains('node-type-condition');
          
          // Only draw normal line if the next node is NOT a condition node
          // Condition nodes handle their own incoming lines from the previous node
          if (!isNextNodeCondition) {
            const startX = fromRect.left + fromRect.width / 2 - svgRect.left;
            const startY = fromRect.bottom - svgRect.top;
            const endX = toRect.left + toRect.width / 2 - svgRect.left;
            const endY = toRect.top - svgRect.top;
            const curveFactor = Math.max(24, Math.abs(endY - startY) * 0.45);

            const d = `M ${startX} ${startY} C ${startX} ${startY + curveFactor}, ${endX} ${endY - curveFactor}, ${endX} ${endY}`;
            const targetStatus = nodeStatusMap.get(toId);

            nextPaths.push({
              id: `${fromId}->${toId}`,
              d,
              isActive:
                activePlan?.status !== 'completed' &&
                activePlan?.status !== 'failed' &&
                toId === activeNodeId,
              isFailed: targetStatus ? FAILED_STATUSES.has(targetStatus) : false,
            });
          }
        }
      }

      setPaths(nextPaths);
    };

    const runMeasure = () => {
      requestAnimationFrame(calculateConnections);
    };

    runMeasure();
    const timeoutId = window.setTimeout(runMeasure, 60);
    window.addEventListener('resize', runMeasure);

    const resizeObserver = new ResizeObserver(runMeasure);
    resizeObserver.observe(canvasElement);
    const nodeListElement = canvasElement.querySelector('.node-list');
    if (nodeListElement) {
      resizeObserver.observe(nodeListElement);
    }

    const mutationObserver = new MutationObserver(runMeasure);
    if (nodeListElement) {
      mutationObserver.observe(nodeListElement, {
        childList: true,
        subtree: true,
        attributes: true,
        attributeFilter: ['class', 'style', 'data-node-type'],
      });
    }

    return () => {
      window.clearTimeout(timeoutId);
      window.removeEventListener('resize', runMeasure);
      resizeObserver.disconnect();
      mutationObserver.disconnect();
    };
  }, [activeNodeId, activePlan?.status, nodeStatusMap, nodes, width]);

  return (
    <svg className="holographic-connections-svg" ref={svgRef} style={{ overflow: 'visible' }}>
      <defs>
        <filter id="glow" x="-20%" y="-20%" width="140%" height="140%">
          <feGaussianBlur stdDeviation="3" result="blur" />
          <feComposite in="SourceGraphic" in2="blur" operator="over" />
        </filter>
        <radialGradient id="energyGlow">
          <stop offset="0%" stopColor="#ffffff" />
          <stop offset="50%" stopColor="#00ffff" />
          <stop offset="100%" stopColor="transparent" />
        </radialGradient>
      </defs>

      {paths.map((path) => (
        <g key={path.id}>
          <path d={path.d} className={`connection-line-base ${path.isFailed ? 'failed' : ''}`} />
          {path.isActive && (
            <path d={path.d} className="connection-line-active" filter="url(#glow)" />
          )}
          {path.isActive && (
            <circle r="4" fill="url(#energyGlow)" filter="url(#glow)">
              <animateMotion
                dur="1.5s"
                repeatCount="indefinite"
                path={path.d}
                keyPoints="0;1"
                keyTimes="0;1"
                calcMode="linear"
              />
            </circle>
          )}
        </g>
      ))}
    </svg>
  );
};
