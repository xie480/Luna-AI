import React, { Component, ErrorInfo, ReactNode } from 'react';
import { generateId } from '../../../shared/utils/snowflake';
import { useSystemStore } from '../../stores/systemStore';
import { FrontendErrorEntry } from '../../stores/systemStore';

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
 * 同时将异常结构化为 FrontendErrorEntry 写入 systemStore，供诊断面板查阅。
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
    // 将异常结构化为 FrontendErrorEntry
    const entry: FrontendErrorEntry = {
      id: generateId(),
      timestamp: Date.now(),
      level: 'ERROR',
      source: this.props.source,
      message: error.message || '未知 React 渲染异常',
      stack: error.stack,
      trace_id: useSystemStore.getState().currentTraceID || undefined,
      component_stack: errorInfo.componentStack || undefined,
    };

    // 写入 systemStore（环形缓冲，最多 100 条）
    useSystemStore.getState().addFrontendError(entry);
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
