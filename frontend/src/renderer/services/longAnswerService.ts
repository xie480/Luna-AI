import { AI_SERVICE_BASE_URL } from '../appConfig';
import { generateId } from '../../shared/utils/snowflake';
import { useSystemStore } from '../stores/systemStore';

export class LongAnswerService {
  private backendUrl: string = AI_SERVICE_BASE_URL;

  public async fetchLongAnswerById(id: string): Promise<any> {
    const traceId = useSystemStore.getState().currentTraceID || `web-${generateId()}`;
    const resp = await fetch(`${this.backendUrl}/api/long_answer/${encodeURIComponent(id)}`, {
      method: 'GET',
      headers: {
        'X-Trace-ID': traceId,
      },
    });

    if (!resp.ok) {
      throw new Error(`获取长回答失败: HTTP ${resp.status}`);
    }

    const data = await resp.json();
    return data.payload;
  }

  public async fetchLongAnswerByMessageId(messageId: string): Promise<any> {
    const traceId = useSystemStore.getState().currentTraceID || `web-${generateId()}`;
    const resp = await fetch(`${this.backendUrl}/api/long_answer/by_message/${encodeURIComponent(messageId)}`, {
      method: 'GET',
      headers: {
        'X-Trace-ID': traceId,
      },
    });

    if (!resp.ok) {
      throw new Error(`通过消息ID获取长回答失败: HTTP ${resp.status}`);
    }

    const data = await resp.json();
    return data.payload;
  }

  public async retryLongAnswer(id: string): Promise<void> {
    const traceId = useSystemStore.getState().currentTraceID || `web-${generateId()}`;
    const resp = await fetch(`${this.backendUrl}/api/long_answer/${encodeURIComponent(id)}/retry`, {
      method: 'POST',
      headers: {
        'X-Trace-ID': traceId,
      },
    });

    if (!resp.ok) {
      throw new Error(`重试长回答失败: HTTP ${resp.status}`);
    }
  }

  public async cancelLongAnswer(id: string): Promise<void> {
    const traceId = useSystemStore.getState().currentTraceID || `web-${generateId()}`;
    const resp = await fetch(`${this.backendUrl}/api/long_answer/${encodeURIComponent(id)}/cancel`, {
      method: 'POST',
      headers: {
        'X-Trace-ID': traceId,
      },
    });

    if (!resp.ok) {
      throw new Error(`取消长回答失败: HTTP ${resp.status}`);
    }
  }
}

export const longAnswerService = new LongAnswerService();
