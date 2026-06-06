import React, { useState, useEffect } from 'react';
import { memoryService } from '../../services/memoryService';

export const ManualMemory: React.FC = () => {
  const [uncompressedCount, setUncompressedCount] = useState<number>(0);
  const [sessionIds, setSessionIds] = useState<string[]>([]);
  const [isCompressing, setIsCompressing] = useState<boolean>(false);
  const [progress, setProgress] = useState<{ current: number; total: number; currentSession: string } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fetchUncompressedSessions = async () => {
    try {
      const data = await memoryService.getUncompressedSessions();
      setUncompressedCount(data.count);
      setSessionIds(data.session_ids);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message || '获取未压缩会话失败');
    }
  };

  useEffect(() => {
    fetchUncompressedSessions();
  }, []);

  const handleCompress = async () => {
    if (sessionIds.length === 0) return;

    setIsCompressing(true);
    setError(null);
    setProgress({ current: 0, total: sessionIds.length, currentSession: '' });

    let successCount = 0;

    for (let i = 0; i < sessionIds.length; i++) {
      const sessionId = sessionIds[i];
      setProgress({ current: i + 1, total: sessionIds.length, currentSession: sessionId });
      
      try {
        await memoryService.compressSession(sessionId);
        successCount++;
      } catch (err: unknown) {
        console.error(`压缩会话 ${sessionId} 失败:`, err);
        // 继续压缩下一个，不中断整个流程
      }
    }

    setIsCompressing(false);
    setProgress(null);
    
    if (successCount < sessionIds.length) {
      setError(`压缩完成，但有 ${sessionIds.length - successCount} 个会话压缩失败，请查看控制台日志。`);
    }
    
    // 重新获取最新状态
    fetchUncompressedSessions();
  };

  return (
    <div className="manual-memory-container">
      <div className="status-card">
        <h3>积压未压缩会话</h3>
        <div className="status-number">{uncompressedCount}</div>
        <div className="status-text">天</div>
        
        {error && <div style={{ color: 'var(--error-color)', marginTop: '12px', fontSize: '14px' }}>{error}</div>}
        
        <div style={{ marginTop: '24px' }}>
          <button 
            className="compress-btn" 
            onClick={handleCompress}
            disabled={isCompressing || uncompressedCount === 0}
          >
            {isCompressing ? '压缩中...' : '开始压缩'}
          </button>
        </div>

        {progress && (
          <div className="progress-container">
            <div className="progress-text">
              正在压缩 {progress.currentSession} ({progress.current}/{progress.total})
            </div>
            <div className="progress-bar-bg">
              <div 
                className="progress-bar-fill" 
                style={{ width: `${(progress.current / progress.total) * 100}%` }}
              ></div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
