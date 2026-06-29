/**
 * Agent Loop SVG 图标集合。
 *
 * 做什么：为 Agent Loop 面板提供全部赛博朋克风格的 SVG 图标组件。
 * 为什么这样做：agent.md 明确禁止使用 emoji，所有图标必须使用 SVG 实现。
 * 输入输出：纯展示组件，无副作用。
 * 边界条件：所有图标统一 viewBox="0 0 24 24"，接受标准 SVG 属性透传。
 * 异常行为：无。
 */
import React from 'react';

/**
 * Agent Loop 主图标：循环箭头 + 目标锚点。
 * 用于工具栏标题。
 */
export const IconAgentLoop: React.FC<React.SVGProps<SVGSVGElement>> = (props) => (
  <svg viewBox="0 0 24 24" fill="none" {...props}>
    <path
      d="M12 2a10 10 0 0 1 7.07 2.93"
      stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"
    />
    <path d="M19.07 4.93L22 2M19.07 4.93L22 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    <path
      d="M12 22a10 10 0 0 1-7.07-2.93"
      stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"
    />
    <path d="M4.93 19.07L2 22M4.93 19.07L2 16" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    <circle cx="12" cy="12" r="3.5" stroke="currentColor" strokeWidth="1.5" />
    <circle cx="12" cy="12" r="1" fill="currentColor" />
    <circle cx="12" cy="12" r="7" stroke="currentColor" strokeWidth="0.8" strokeDasharray="2 3" opacity="0.4" />
  </svg>
);

/**
 * 目标图标：靶心。
 * 用于全局目标卡片标题。
 */
export const IconTarget: React.FC<React.SVGProps<SVGSVGElement>> = (props) => (
  <svg viewBox="0 0 24 24" fill="none" {...props}>
    <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="1.5" opacity="0.3" />
    <circle cx="12" cy="12" r="6" stroke="currentColor" strokeWidth="1.5" opacity="0.5" />
    <circle cx="12" cy="12" r="2.5" stroke="currentColor" strokeWidth="1.5" />
    <circle cx="12" cy="12" r="0.8" fill="currentColor" />
  </svg>
);

/**
 * 锁定图标。
 * 用于目标锁定态标识。
 */
export const IconLock: React.FC<React.SVGProps<SVGSVGElement>> = (props) => (
  <svg viewBox="0 0 24 24" fill="none" {...props}>
    <rect x="5" y="11" width="14" height="10" rx="2" stroke="currentColor" strokeWidth="1.5" />
    <path d="M8 11V7a4 4 0 0 1 8 0v4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    <circle cx="12" cy="16" r="1.5" fill="currentColor" />
  </svg>
);

/**
 * 关闭图标（X）。
 * 用于工具栏关闭按钮。
 */
export const IconClose: React.FC<React.SVGProps<SVGSVGElement>> = (props) => (
  <svg viewBox="0 0 24 24" fill="none" {...props}>
    <path d="M18 6L6 18M6 6l12 12" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
  </svg>
);

/**
 * 展开/收起箭头图标。
 * 通过 rotation 控制方向。
 */
export const IconChevron: React.FC<React.SVGProps<SVGSVGElement> & { direction?: 'down' | 'right' }> = ({ direction = 'down', ...props }) => (
  <svg viewBox="0 0 24 24" fill="none" {...props}>
    {direction === 'down' ? (
      <path d="M6 9l6 6 6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    ) : (
      <path d="M9 6l6 6-6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    )}
  </svg>
);

/**
 * 版本/重规划图标：分支箭头。
 * 用于计划头部版本号和 Replan 历史。
 */
export const IconBranch: React.FC<React.SVGProps<SVGSVGElement>> = (props) => (
  <svg viewBox="0 0 24 24" fill="none" {...props}>
    <circle cx="7" cy="6" r="2.5" stroke="currentColor" strokeWidth="1.5" />
    <circle cx="17" cy="10" r="2.5" stroke="currentColor" strokeWidth="1.5" />
    <circle cx="7" cy="18" r="2.5" stroke="currentColor" strokeWidth="1.5" />
    <path d="M7 8.5V15.5M7 8.5C7 8.5 7 10 9.5 10H14.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
  </svg>
);

/**
 * 预算/计数器图标：仪表盘。
 * 用于预算状态栏。
 */
export const IconGauge: React.FC<React.SVGProps<SVGSVGElement>> = (props) => (
  <svg viewBox="0 0 24 24" fill="none" {...props}>
    <path d="M12 22a9 9 0 1 1 0-18 9 9 0 0 1 0 18z" stroke="currentColor" strokeWidth="1.5" />
    <path d="M12 12l3-5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    <circle cx="12" cy="12" r="1.5" fill="currentColor" />
  </svg>
);

/**
 * 思考图标：大脑/灯泡。
 * 用于 Think 区块标题。
 */
export const IconThink: React.FC<React.SVGProps<SVGSVGElement>> = (props) => (
  <svg viewBox="0 0 24 24" fill="none" {...props}>
    <path
      d="M9 21h6M10 17h4M12 3a6 6 0 0 1 4 10.5V17H8v-3.5A6 6 0 0 1 12 3z"
      stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"
    />
  </svg>
);

/**
 * 工具图标：扳手。
 * 用于工具调用区块标题。
 */
export const IconTool: React.FC<React.SVGProps<SVGSVGElement>> = (props) => (
  <svg viewBox="0 0 24 24" fill="none" {...props}>
    <path
      d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"
      stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"
    />
  </svg>
);

/**
 * 观察图标：眼睛。
 * 用于 Observe 区块标题。
 */
export const IconObserve: React.FC<React.SVGProps<SVGSVGElement>> = (props) => (
  <svg viewBox="0 0 24 24" fill="none" {...props}>
    <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" stroke="currentColor" strokeWidth="1.5" />
    <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="1.5" />
  </svg>
);

/**
 * 评估图标：柱状图/评分。
 * 用于 Evaluate 区块标题。
 */
export const IconEvaluate: React.FC<React.SVGProps<SVGSVGElement>> = (props) => (
  <svg viewBox="0 0 24 24" fill="none" {...props}>
    <rect x="3" y="12" width="4" height="9" rx="1" stroke="currentColor" strokeWidth="1.5" />
    <rect x="10" y="6" width="4" height="15" rx="1" stroke="currentColor" strokeWidth="1.5" />
    <rect x="17" y="3" width="4" height="18" rx="1" stroke="currentColor" strokeWidth="1.5" />
  </svg>
);

/**
 * 成功/通过图标：圆圈内对勾。
 */
export const IconCheck: React.FC<React.SVGProps<SVGSVGElement>> = (props) => (
  <svg viewBox="0 0 24 24" fill="none" {...props}>
    <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="1.5" />
    <path d="M8 12l3 3 5-5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

/**
 * 失败/错误图标：圆圈内叉号。
 */
export const IconXCircle: React.FC<React.SVGProps<SVGSVGElement>> = (props) => (
  <svg viewBox="0 0 24 24" fill="none" {...props}>
    <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="1.5" />
    <path d="M15 9l-6 6M9 9l6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
  </svg>
);

/**
 * 警告图标：三角感叹号。
 */
export const IconWarning: React.FC<React.SVGProps<SVGSVGElement>> = (props) => (
  <svg viewBox="0 0 24 24" fill="none" {...props}>
    <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
    <line x1="12" y1="9" x2="12" y2="13" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    <circle cx="12" cy="17" r="1" fill="currentColor" />
  </svg>
);

/**
 * 等待/进行中图标：沙漏。
 */
export const IconPending: React.FC<React.SVGProps<SVGSVGElement>> = (props) => (
  <svg viewBox="0 0 24 24" fill="none" {...props}>
    <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="1.5" opacity="0.4" />
    <circle cx="12" cy="12" r="2" fill="currentColor" opacity="0.6" />
  </svg>
);

/**
 * 重试图标：循环箭头。
 */
export const IconRetry: React.FC<React.SVGProps<SVGSVGElement>> = (props) => (
  <svg viewBox="0 0 24 24" fill="none" {...props}>
    <path d="M1 4v6h6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

/**
 * 修复图标：医疗十字。
 */
export const IconRepair: React.FC<React.SVGProps<SVGSVGElement>> = (props) => (
  <svg viewBox="0 0 24 24" fill="none" {...props}>
    <path
      d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"
      stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"
      opacity="0.7"
    />
    <path d="M8 8l2 2M14 8l-2 2M11 7v4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
  </svg>
);

/**
 * 时间图标：时钟。
 */
export const IconClock: React.FC<React.SVGProps<SVGSVGElement>> = (props) => (
  <svg viewBox="0 0 24 24" fill="none" {...props}>
    <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="1.5" />
    <path d="M12 6v6l4 2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

/**
 * 验收报告图标：文档 + 对勾。
 */
export const IconReport: React.FC<React.SVGProps<SVGSVGElement>> = (props) => (
  <svg viewBox="0 0 24 24" fill="none" {...props}>
    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
    <path d="M14 2v6h6" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
    <path d="M9 15l2 2 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

/**
 * 统计图标：饼图。
 */
export const IconStats: React.FC<React.SVGProps<SVGSVGElement>> = (props) => (
  <svg viewBox="0 0 24 24" fill="none" {...props}>
    <path d="M21.21 15.89A10 10 0 1 1 8 2.83" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    <path d="M22 12A10 10 0 0 0 12 2v10z" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  );

/**
 * 问号图标：圆圈内问号。
 * 用于工具调用等待审批状态（替代叉叉，表示"需要用户决策"）。
 */
export const IconQuestion: React.FC<React.SVGProps<SVGSVGElement>> = (props) => (
  <svg viewBox="0 0 24 24" fill="none" {...props}>
    <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="1.5" />
    <path d="M9 9a3 3 0 0 1 5.12 2.13c0 2-3 2.5-3 4.37" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    <circle cx="12" cy="18" r="0.8" fill="currentColor" />
  </svg>
);
  
  /**
   * 循环迭代图标：循环箭头（用于 Loop Iteration 标识）。
   * 做什么：在步骤卡片中标识循环迭代次数和迭代区块标题。
   */
  export const IconLoop: React.FC<React.SVGProps<SVGSVGElement>> = (props) => (
    <svg viewBox="0 0 24 24" fill="none" {...props}>
      <path
        d="M17 2l4 4-4 4"
        stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"
      />
      <path
        d="M3 11V9a4 4 0 0 1 4-4h14"
        stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"
      />
      <path
        d="M7 22l-4-4 4-4"
        stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"
      />
      <path
        d="M21 13v2a4 4 0 0 1-4 4H3"
        stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"
      />
    </svg>
  );
