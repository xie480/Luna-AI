import React, { Component, ErrorInfo, ReactNode } from 'react';
import { generateId } from '../../../shared/utils/snowflake';
import { useSystemStore } from '../../stores/systemStore';
import { FrontendErrorEntry } from '../../stores/systemStore';
import { createErrorToast } from '../../stores/errorToastStore';
import { reportErrorLog } from '../../services/errorLogService';

interface Props {
  children: ReactNode;
  /** 错误来源标识，如 'chat_view', 'live2d_view', 'settings_panel' */
  source: string;
  /** 降级渲染的备用 UI */
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

/**
 * ErrorBoundary: React 错误边界组件
 * 做什么：捕获子组件渲染过程中的异常，防止整个应用白屏。
 * 同时：
 *   1. 将异常结构化为 FrontendErrorEntry 写入 systemStore（内存环形缓冲）
 *   2. 通过 ErrorToast 在屏幕顶部展示友好的错误提示
 *   3. 异步持久化到 PostgreSQL error_logs 表（可追溯）
 */
class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    const store = useSystemStore.getState();
    const traceId = store.currentTraceID || generateId();
    const message = error.message || '未知 React 渲染异常';

    // 1. 写入 systemStore（内存环形缓冲，最多 100 条）
    const entry: FrontendErrorEntry = {
      id: generateId(),
      timestamp: Date.now(),
      level: 'ERROR',
      source: this.props.source,
      message,
      stack: error.stack,
      trace_id: traceId,
      component_stack: errorInfo.componentStack || undefined,
    };
    store.addFrontendError(entry);

    // 2. 显示 UI 错误提示（ErrorToast 组件）
    createErrorToast('ERROR', this.props.source, message);

    // 3. 异步持久化到数据库（不阻塞 UI）
    reportErrorLog({
      level: 'ERROR',
      source: this.props.source,
      message,
      detail: `Stack: ${error.stack || '无'}\nComponentStack: ${errorInfo.componentStack || '无'}`,
      trace_id: traceId,
    }).catch(() => { /* 静默降级 */ });
  }

  render(): ReactNode {
    if (this.state.hasError) {
      // 使用自定义 fallback 或默认降级 UI
      return (
        this.props.fallback || (
          <div style={{ padding: 24, color: '#e74c3c', textAlign: 'center' }}>
            <p>组件 <strong>{this.props.source}</strong> 发生异常，系统已记录此错误。</p>
            <button onClick={() => this.setState({ hasError: false, error: null })}>
              重试
            </button>
          </div>
        )
      );
    }
    return this.props.children;
  }
}

export default ErrorBoundary;
