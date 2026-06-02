/**
 * Luna AI WebSocket 管理器（已废弃）
 * 
 * 此文件已废弃，由 sseManager.ts 替代。
 * 保留此文件仅用于向后兼容，新代码请勿引用。
 * 
 * 迁移说明：
 * - 所有业务请求 → 使用 fetch HTTP API（见 sseManager.ts）
 * - 实时事件接收 → 使用 EventSource SSE（见 sseManager.ts）
 * 
 * @deprecated 请使用 sseManager 替代
 */
import { SSEManager, sseManager } from './sseManager';

/** @deprecated 请使用 sseManager 替代 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
class WSManager {
  // 保持单例引用指向 sseManager
  private sseManager: SSEManager;

  constructor() {
    this.sseManager = sseManager;
  }

  public connect(port: number = 8081): void {
    this.sseManager.connect(port);
  }

  public disconnect(): void {
    this.sseManager.disconnect();
  }

  public isConnected(): boolean {
    return this.sseManager.isConnected();
  }

  public sendMessage(type: string, payload: unknown): void {
    // 根据消息类型路由到对应的 HTTP API
    import('../../shared/enum').then(({ WS_MSG_TYPE }) => {
      if (type === WS_MSG_TYPE.REQ_GET_CALENDAR_METADATA) {
        const ym = (payload as any)?.year_month;
        if (ym) this.sseManager.fetchCalendarMetadata(ym);
      } else if (type === WS_MSG_TYPE.REQ_GET_CHAT_HISTORY) {
        const date = (payload as any)?.date;
        if (date) this.sseManager.fetchChatHistory(date);
      }
    });
  }

  public sendChatMessage(message: string): void {
    this.sseManager.sendChatMessage(message);
  }

  public sendPing(): void {
    this.sseManager.sendPing();
  }

  public send(data: { type: string; payload: unknown }): void {
    this.sendMessage(data.type, data.payload);
  }
}

/** @deprecated 请使用 sseManager 替代 */
export const wsManager = new WSManager();
