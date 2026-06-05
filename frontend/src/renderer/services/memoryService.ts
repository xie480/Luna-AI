import { AI_SERVICE_BASE_URL } from '../appConfig';

export interface UncompressedSessionsResponse {
  count: number;
  session_ids: string[];
}

export interface LongTermMemoryItem {
  id: string;
  session_id: string;
  summary: string;
  status: string;
  created_at: string | null;
  updated_at: string | null;
}

export interface LongTermMemoriesResponse {
  items: LongTermMemoryItem[];
  total: number;
  page: int;
  page_size: int;
}

class MemoryService {
  private get baseUrl() {
    return `${AI_SERVICE_BASE_URL}/api/memory`;
  }

  /**
   * 获取未压缩的会话列表
   */
  async getUncompressedSessions(): Promise<UncompressedSessionsResponse> {
    const response = await fetch(`${this.baseUrl}/uncompressed`);
    if (!response.ok) {
      throw new Error(`获取未压缩会话失败: ${response.statusText}`);
    }
    const data = await response.json();
    return data.payload;
  }

  /**
   * 压缩指定会话
   */
  async compressSession(sessionId: string): Promise<void> {
    const response = await fetch(`${this.baseUrl}/compress`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ session_id: sessionId }),
    });
    if (!response.ok) {
      throw new Error(`压缩会话失败: ${response.statusText}`);
    }
  }

  /**
   * 分页获取长期记忆
   */
  async getLongTermMemories(page: number = 1, pageSize: number = 20): Promise<LongTermMemoriesResponse> {
    const response = await fetch(`${this.baseUrl}/long_term?page=${page}&page_size=${pageSize}`);
    if (!response.ok) {
      throw new Error(`获取长期记忆失败: ${response.statusText}`);
    }
    const data = await response.json();
    return data.payload;
  }

  /**
   * 创建长期记忆
   */
  async createLongTermMemory(sessionId: string, summary: string): Promise<void> {
    const response = await fetch(`${this.baseUrl}/long_term`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ session_id: sessionId, summary }),
    });
    if (!response.ok) {
      throw new Error(`创建长期记忆失败: ${response.statusText}`);
    }
  }

  /**
   * 更新长期记忆
   */
  async updateLongTermMemory(id: string, summary: string): Promise<void> {
    const response = await fetch(`${this.baseUrl}/long_term/${id}`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ summary }),
    });
    if (!response.ok) {
      throw new Error(`更新长期记忆失败: ${response.statusText}`);
    }
  }

  /**
   * 删除长期记忆
   */
  async deleteLongTermMemory(id: string): Promise<void> {
    const response = await fetch(`${this.baseUrl}/long_term/${id}`, {
      method: 'DELETE',
    });
    if (!response.ok) {
      throw new Error(`删除长期记忆失败: ${response.statusText}`);
    }
  }
}

export const memoryService = new MemoryService();
