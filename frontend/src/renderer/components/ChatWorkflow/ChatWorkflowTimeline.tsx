import React, { useMemo } from 'react';
import { CHAT_WORKFLOW_NODE_LABEL } from '../../../shared/enum';
import { useChatWorkflowStore } from '../../stores/chatWorkflowStore';
import './ChatWorkflow.css';

/**
 * Chat Workflow 时间线组件。
 * 做什么：按 trace_id 渲染本轮节点时间线、条件判断与后处理摘要。
 * 为什么这样做：调试抽屉需要可回放的轻量事件列表，且不能污染普通聊天正文。
 * 输入输出：输入 traceId，输出时间线列表视图。
 * 边界条件：traceId 为空或未找到事件时展示空态。
 * 异常行为：无。
 */
export const ChatWorkflowTimeline: React.FC<{ traceId?: string }> = ({ traceId }) => {
  const timeline = useChatWorkflowStore((state) => (traceId ? state.debugTimelineByTraceId[traceId] : undefined));

  /**
   * 对时间线做只读排序视图。
   * 做什么：保证渲染顺序稳定，避免未来批量写入时出现前后颠倒。
   * 为什么这样做：调试查看需要按时间顺序理解节点流转。
   * 输入输出：输入 store 时间线，输出排序后的事件数组。
   * 边界条件：无事件时返回空数组。
   * 异常行为：无。
   */
  const events = useMemo(() => {
    return [...(timeline?.events || [])].sort((left, right) => left.timestampMs - right.timestampMs);
  }, [timeline?.events]);

  /**
   * 格式化毫秒时间戳。
   * 做什么：把后端时间戳转换为本地可读时间文本。
   * 为什么这样做：调试面板需要快速定位事件先后顺序。
   * 输入输出：输入毫秒时间戳，输出本地时间字符串。
   * 边界条件：时间戳非法时回退为原值字符串。
   * 异常行为：无。
   */
  const formatTime = (timestampMs: number): string => {
    try {
      return new Date(timestampMs).toLocaleTimeString('zh-CN', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      });
    } catch {
      return String(timestampMs);
    }
  };

  if (!traceId || events.length === 0) {
    return <div className="chat-workflow-timeline__empty">当前还没有可展示的节点时间线。</div>;
  }

  return (
    <div className="chat-workflow-timeline">
      {events.map((event) => (
        <div key={event.eventId} className="chat-workflow-timeline__item">
          <div className="chat-workflow-timeline__header">
            <div className="chat-workflow-timeline__title">{event.title}</div>
            <div className="chat-workflow-timeline__time">{formatTime(event.timestampMs)}</div>
          </div>
          {event.nodeType && (
            <div className="chat-workflow-timeline__node">
              节点：{CHAT_WORKFLOW_NODE_LABEL[event.nodeType]}
            </div>
          )}
          <div className="chat-workflow-timeline__detail">{event.detail}</div>
          {event.payloadSummary && <div className="chat-workflow-timeline__payload">{event.payloadSummary}</div>}
        </div>
      ))}
    </div>
  );
};
