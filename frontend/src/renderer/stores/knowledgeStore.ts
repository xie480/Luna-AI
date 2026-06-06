import { create } from 'zustand';
import { 
  KnowledgeDocumentView, 
  KnowledgeFilterState, 
  IngestionProgressSnapshot,
  RAG_POLL_INTERVAL_MS,
  RAG_POLL_TIMEOUT_MS,
  RagUrlIngestionPayload
} from '../types/rag';
import { ragService } from '../services/ragService';
import { useRagConfigStore } from './ragConfigStore';

interface KnowledgeState {
  documents: KnowledgeDocumentView[];
  filterState: KnowledgeFilterState;
  
  globalUploadProgress: number; // 0-100
  isPolling: boolean;
  
  // Actions
  setFilterState: (filter: Partial<KnowledgeFilterState>) => void;
  fetchKnowledgeList: () => Promise<void>;
  submitLocalFile: (file: File) => Promise<void>;
  submitUrl: (url: string) => Promise<void>;
  deleteKnowledge: (documentId: string) => Promise<void>;
  
  // Polling loop
  startPolling: () => void;
  stopPolling: () => void;
  
  // Computed (accessed via function or component subscription)
  getFilteredDocuments: () => KnowledgeDocumentView[];
  getProgressSnapshot: () => IngestionProgressSnapshot;
}

// 记录各个文档开始轮询的时间，用于超时检查
const pollingStartTimes: Record<string, number> = {};
let pollIntervalId: number | null = null;

export const useKnowledgeStore = create<KnowledgeState>((set, get) => ({
  documents: [],
  filterState: {
    keyword: '',
    sourceType: 'all',
    status: 'all'
  },
  
  globalUploadProgress: 0,
  isPolling: false,
  
  setFilterState: (filter) => set((state) => ({ filterState: { ...state.filterState, ...filter } })),
  
  fetchKnowledgeList: async () => {
    try {
      const docs = await ragService.listKnowledge(100);
      const views: KnowledgeDocumentView[] = docs.map(doc => ({
        ...doc,
        display_status: doc.status
      }));
      set({ documents: views });
      
      // 检查是否有处于处理中的任务，如果有则启动轮询
      const hasPending = views.some(doc => doc.status === 'parsing' || doc.status === 'embedding');
      if (hasPending && !get().isPolling) {
        get().startPolling();
      }
    } catch (err) {
      console.error('Fetch knowledge list failed', err);
      // Backend disconnected or error, mark parsing/embedding as offline_suspended
      set((state) => ({
        documents: state.documents.map(doc => 
          (doc.status === 'parsing' || doc.status === 'embedding')
            ? { ...doc, display_status: 'offline_suspended' }
            : doc
        )
      }));
    }
  },
  
  submitLocalFile: async (file: File) => {
    const config = useRagConfigStore.getState().buildRequestPayload();
    const res = await ragService.submitLocalFile(file, config);
    
    // 添加一个占位的 document 到列表中
    const newDoc: KnowledgeDocumentView = {
      schema_version: 'rag.v1',
      id: res.document_id,
      filename: file.name,
      source_type: 'local_file',
      status: 'parsing',
      display_status: 'parsing',
      estimated_tokens: 0,
      error_log: null,
      created_at: new Date().toISOString()
    };
    
    set((state) => ({ documents: [newDoc, ...state.documents] }));
    pollingStartTimes[res.document_id] = Date.now();
    get().startPolling();
  },
  
  submitUrl: async (url: string) => {
    const config = useRagConfigStore.getState().buildRequestPayload();
    const payload: RagUrlIngestionPayload = {
      ...config,
      url
    };
    const res = await ragService.submitUrl(payload);
    
    const newDoc: KnowledgeDocumentView = {
      schema_version: 'rag.v1',
      id: res.document_id,
      filename: url,
      source_type: 'url',
      status: 'parsing',
      display_status: 'parsing',
      estimated_tokens: 0,
      error_log: null,
      created_at: new Date().toISOString()
    };
    
    set((state) => ({ documents: [newDoc, ...state.documents] }));
    pollingStartTimes[res.document_id] = Date.now();
    get().startPolling();
  },
  
  deleteKnowledge: async (documentId: string) => {
    await ragService.deleteKnowledge(documentId);
    set((state) => ({
      documents: state.documents.filter(d => d.id !== documentId)
    }));
  },
  
  startPolling: () => {
    if (get().isPolling) return;
    set({ isPolling: true });
    
    pollIntervalId = window.setInterval(async () => {
      const state = get();
      const pendingDocs = state.documents.filter(d => d.status === 'parsing' || d.status === 'embedding');
      
      if (pendingDocs.length === 0) {
        state.stopPolling();
        return;
      }
      
      try {
        const freshDocs = await ragService.listKnowledge(100);
        set({
          documents: freshDocs.map(doc => ({
            ...doc,
            display_status: doc.status
          }))
        });
      } catch (err) {
        // 请求失败，可能是网络问题，检查超时
        const now = Date.now();
        let timeoutOccurred = false;
        
        const updatedDocs = state.documents.map(doc => {
          if (doc.status === 'parsing' || doc.status === 'embedding') {
            const startTime = pollingStartTimes[doc.id] || now;
            if (now - startTime > RAG_POLL_TIMEOUT_MS) {
              timeoutOccurred = true;
              return { ...doc, display_status: 'offline_suspended' as const };
            }
          }
          return doc;
        });
        
        set({ documents: updatedDocs });
        
        if (timeoutOccurred) {
          // 清除超时的
          pendingDocs.forEach(d => {
            const startTime = pollingStartTimes[d.id] || now;
            if (now - startTime > RAG_POLL_TIMEOUT_MS) {
              delete pollingStartTimes[d.id];
            }
          });
        }
      }
    }, RAG_POLL_INTERVAL_MS);
  },
  
  stopPolling: () => {
    if (pollIntervalId !== null) {
      clearInterval(pollIntervalId);
      pollIntervalId = null;
    }
    set({ isPolling: false });
  },
  
  getFilteredDocuments: () => {
    const { documents, filterState } = get();
    return documents.filter(doc => {
      if (filterState.sourceType !== 'all' && doc.source_type !== filterState.sourceType) return false;
      if (filterState.status !== 'all' && doc.display_status !== filterState.status) return false;
      if (filterState.keyword && !doc.filename.toLowerCase().includes(filterState.keyword.toLowerCase())) return false;
      return true;
    });
  },
  
  getProgressSnapshot: () => {
    const { documents } = get();
    let active = 0;
    let completed = 0;
    let failed = 0;
    
    documents.forEach(d => {
      if (d.status === 'parsing' || d.status === 'embedding') active++;
      else if (d.status === 'completed') completed++;
      else if (d.status === 'failed') failed++;
    });
    
    const total = documents.length;
    const globalPercent = total === 0 ? 0 : Math.round((completed / total) * 100);
    
    return {
      activeCount: active,
      completedCount: completed,
      failedCount: failed,
      globalPercent
    };
  }
}));
