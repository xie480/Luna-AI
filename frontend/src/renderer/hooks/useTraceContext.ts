import { useEffect, useRef } from 'react';
import { generateId } from '../../shared/utils/snowflake';
import { useSystemStore } from '../stores/systemStore';

/**
 * useTraceContext: 自动管理 TraceID 生命周期
 * 做什么：在组件的生命周期内维护一个全局 TraceID，并在组件卸载时自动清理。
 * 用于用户操作（如发送消息）时自动关联 TraceID，确保同一次交互的所有日志可追溯。
 */
export function useTraceContext() {
  const traceIdRef = useRef<string>(generateId());
  const { setCurrentTraceID, addSystemLog } = useSystemStore.getState();

  useEffect(() => {
    // 挂载时设置全局 TraceID
    const traceId = traceIdRef.current;
    setCurrentTraceID(traceId);
    addSystemLog(`[Trace] 初始化 TraceID: ${traceId}`);

    return () => {
      // 组件卸载时清除 TraceID（但保留日志，方便调试）
      addSystemLog(`[Trace] 清理 TraceID: ${traceId}`);
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
}
