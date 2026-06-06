import { create } from 'zustand';
import { sseManager } from '../services/sseManager';

export type HistoryViewType = 'RECENT' | 'CALENDAR';

export interface HistoryChatMessage {
  id: string;
  role: string;
  content: string;
  created_at: string;
  thought?: string;  // 内心独白字段
  emotion?: string;  // 情绪字段
}

interface HistoryState {
  currentView: HistoryViewType;
  selectedDate: string | null; // 格式: YYYY-MM-DD
  currentYearMonth: string; // 格式: YYYY-MM
  calendarMetadata: Record<string, boolean>; // 某日是否有记录的映射，来源于 Redis
  chatHistory: HistoryChatMessage[]; // 选定日期的详细聊天记录，来源于 PostgreSQL
  isLoadingMetadata: boolean;
  isLoadingHistory: boolean;

  // Actions
  switchView: (view: HistoryViewType) => void;
  setSelectedDate: (date: string | null) => void;
  setCurrentYearMonth: (yearMonth: string) => void;
  fetchCalendarMetadata: (yearMonth: string) => void;
  fetchChatHistory: (date: string) => void;
  
  // 供 WS 接收到数据后调用的内部方法
  setCalendarMetadata: (yearMonth: string, activeDates: string[]) => void;
  setChatHistory: (date: string, messages: HistoryChatMessage[]) => void;
  addCalendarRecord: (date: string) => void;
}

// 获取当前年月 YYYY-MM
const getCurrentYearMonth = () => {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, '0');
  return `${year}-${month}`;
};

export const useHistoryStore = create<HistoryState>((set, get) => ({
  currentView: 'RECENT',
  selectedDate: null,
  currentYearMonth: getCurrentYearMonth(),
  calendarMetadata: {},
  chatHistory: [],
  isLoadingMetadata: false,
  isLoadingHistory: false,

  switchView: (view) => {
    set({ currentView: view });
    // 如果切换到日历视图，且当前没有元数据，则拉取当前月的元数据
    if (view === 'CALENDAR') {
      const { currentYearMonth, fetchCalendarMetadata } = get();
      fetchCalendarMetadata(currentYearMonth);
    }
  },

  setSelectedDate: (date) => {
    set({ selectedDate: date });
    if (date) {
      get().fetchChatHistory(date);
    } else {
      set({ chatHistory: [] });
    }
  },

  setCurrentYearMonth: (yearMonth) => {
    set({ currentYearMonth: yearMonth });
    get().fetchCalendarMetadata(yearMonth);
  },

  fetchCalendarMetadata: async (yearMonth) => {
    set({ isLoadingMetadata: true });
    await sseManager.fetchCalendarMetadata(yearMonth);
    // fetchCalendarMetadata 内部已调用 setCalendarMetadata 更新状态，
    // 但需要确保 isLoadingMetadata 被关闭
    // sseManager.fetchCalendarMetadata 完成后会通过 setCalendarMetadata 关闭 loading
  },

  fetchChatHistory: async (date) => {
    set({ isLoadingHistory: true });
    await sseManager.fetchChatHistory(date);
    // fetchChatHistory 内部已调用 setChatHistory 更新状态
  },

  setCalendarMetadata: (yearMonth, activeDates) => {
    set((state) => {
      const newMetadata = { ...state.calendarMetadata };
      // 清除该月旧数据
      Object.keys(newMetadata).forEach(key => {
        if (key.startsWith(yearMonth)) {
          delete newMetadata[key];
        }
      });
      // 设置新数据
      activeDates.forEach(date => {
        // date 可能是 "01", "15" 这种格式，也可能是 "2026-05-01"
        // 后端返回的是 "DD" 格式
        const fullDate = `${yearMonth}-${date}`;
        newMetadata[fullDate] = true;
      });
      return {
        calendarMetadata: newMetadata,
        isLoadingMetadata: false,
      };
    });
  },

  setChatHistory: (date, messages) => {
    set((state) => {
      if (state.selectedDate === date) {
        return {
          chatHistory: messages,
          isLoadingHistory: false,
        };
      }
      return { isLoadingHistory: false };
    });
  },

  addCalendarRecord: (date) => {
    set((state) => ({
      calendarMetadata: {
        ...state.calendarMetadata,
        [date]: true,
      },
    }));
  },
}));
