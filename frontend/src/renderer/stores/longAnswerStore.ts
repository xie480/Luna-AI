import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import { LongAnswerItem } from '../../shared/types';

interface LongAnswerPanelState {
  visible: boolean;
  x: number;
  y: number;
  width: number;
  height: number;
  isDragging: boolean;
  isResizing: boolean;
}

interface LongAnswerStore {
  activeId: string | null;
  byId: Record<string, LongAnswerItem>;
  panel: LongAnswerPanelState;
  
  // Actions
  openPanel: (id: string) => void;
  closePanel: () => void;
  appendChunk: (id: string, seq: number, chunk: string) => void;
  updateStatus: (id: string, patch: Partial<LongAnswerItem>) => void;
  bindMessage: (messageId: string, longAnswerId: string) => void;
  
  // Panel Actions
  setPanelState: (patch: Partial<LongAnswerPanelState>) => void;
  togglePanel: () => void;
}

const DEFAULT_PANEL_STATE: LongAnswerPanelState = {
  visible: false,
  x: 32,
  y: 88,
  width: 480,
  // we will adjust height dynamically in component, provide a sensible default
  height: 600,
  isDragging: false,
  isResizing: false,
};

export const useLongAnswerStore = create<LongAnswerStore>()(
  persist(
    (set, get) => ({
      activeId: null,
      byId: {},
      panel: DEFAULT_PANEL_STATE,

      openPanel: (id: string) => {
        set((state) => ({
          activeId: id,
          panel: { ...state.panel, visible: true },
        }));
      },

      closePanel: () => {
        set((state) => ({
          panel: { ...state.panel, visible: false },
        }));
      },

      togglePanel: () => {
        set((state) => ({
          panel: { ...state.panel, visible: !state.panel.visible },
        }));
      },

      appendChunk: (id: string, seq: number, chunk: string) => {
        set((state) => {
          const item = state.byId[id] || {
            id,
            sessionId: '', // We should ideally pass this if missing
            interactionMessageId: '',
            status: 'GENERATING',
            title: 'Luna正在整理中……',
            markdown: '',
            shortSummary: '',
            updatedAt: Date.now(),
          };

          // To be truly robust against out-of-order chunks, we'd need a buffer based on seq.
          // For now, assuming relatively ordered SSE delivery, we simply append.
          // A more robust implementation would keep a Record<number, string> and join them.
          
          return {
            byId: {
              ...state.byId,
              [id]: {
                ...item,
                markdown: item.markdown + chunk,
                updatedAt: Date.now(),
                status: item.status === 'PENDING' ? 'GENERATING' : item.status,
              },
            },
          };
        });
      },

      updateStatus: (id: string, patch: Partial<LongAnswerItem>) => {
        set((state) => {
          const item = state.byId[id];
          if (!item) return state;

          return {
            byId: {
              ...state.byId,
              [id]: {
                ...item,
                ...patch,
                updatedAt: Date.now(),
              },
            },
          };
        });
      },

      bindMessage: (messageId: string, longAnswerId: string) => {
        // This action might just be an update to the item to store messageId
        // The actual sessionStore binding might happen in the component or a facade
        set((state) => {
          const item = state.byId[longAnswerId];
          if (!item) return state;

          return {
            byId: {
              ...state.byId,
              [longAnswerId]: {
                ...item,
                interactionMessageId: messageId,
                updatedAt: Date.now(),
              },
            },
          };
        });
      },

      setPanelState: (patch: Partial<LongAnswerPanelState>) => {
        set((state) => ({
          panel: { ...state.panel, ...patch },
        }));
      },
    }),
    {
      name: 'luna-long-answer-storage',
      // Only persist certain parts if desired, e.g. panel position
      partialize: (state) => ({
        panel: {
          ...state.panel,
          isDragging: false,
          isResizing: false,
          // maybe don't persist 'visible' if we want it closed on restart
        },
        // We could optionally persist `activeId` and `byId` if we want drafts across restarts
      }),
      storage: createJSONStorage(() => localStorage),
    }
  )
);
