import { create } from 'zustand';
import {
  KnowledgeDocumentView,
  KnowledgeFilterState,
  IngestionProgressSnapshot,
  RAG_POLL_INTERVAL_MS,
  RAG_POLL_TIMEOUT_MS,
  RagUrlIngestionPayload,
  RAG_MAX_UPLOAD_BYTES
} from '../types/rag';
import { ragService } from '../services/ragService';
import { useRagConfigStore } from './ragConfigStore';

interface KnowledgeState {
  documents: KnowledgeDocumentView[];
  filterState: KnowledgeFilterState;
  
  // 待处理队列（未真正调用后端入库 API 前）
  pendingFiles: File[];
  pendingUrls: string[];

  globalUploadProgress: number; // 0-100
  isPolling: boolean;

  /** 当前正在执行更新操作的文档 ID 集合，用于 UI 展示更新中状态。 */
  updatingDocIds: Set<string>;
  
  /** 当前选中的要更新的文档对象上下文，用于"更新面板"的渲染 */
  documentToUpdate: KnowledgeDocumentView | null;

  // Actions
  setFilterState: (filter: Partial<KnowledgeFilterState>) => void;
  setDocumentToUpdate: (doc: KnowledgeDocumentView | null) => void;
  fetchKnowledgeList: () => Promise<void>;

  addPendingFile: (file: File) => void;
  removePendingFile: (index: number) => void;
  addPendingUrl: (url: string) => void;
  removePendingUrl: (index: number) => void;
  clearPendingQueue: () => void;

  submitAllPending: () => Promise<void>;
  deleteKnowledge: (documentId: string) => Promise<void>;
  updateKnowledge: (documentId: string, newFile: File) => Promise<void>;

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
  
  pendingFiles: [],
  pendingUrls: [],
  
  globalUploadProgress: 0,
  isPolling: false,

  /** 当前正在执行更新操作的文档 ID 集合，初始为空。 */
  updatingDocIds: new Set<string>(),
  
  documentToUpdate: null,

  setFilterState: (filter) => set((state) => ({ filterState: { ...state.filterState, ...filter } })),
  setDocumentToUpdate: (doc) => set({ documentToUpdate: doc }),
  
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
  
  addPendingFile: (file: File) => {
    if (file.size > RAG_MAX_UPLOAD_BYTES) {
      throw new Error(`文件大小超过限制 (最大 50MB)`);
    }
    const validExts = ['.txt', '.md', '.pdf', '.docx'];
    const name = file.name.toLowerCase();
    if (!validExts.some(ext => name.endsWith(ext))) {
      throw new Error(`不支持的文件格式，仅支持 txt, md, pdf, docx`);
    }
    set((state) => ({ pendingFiles: [...state.pendingFiles, file] }));
  },
  removePendingFile: (index: number) => set((state) => ({ pendingFiles: state.pendingFiles.filter((_, i) => i !== index) })),
  addPendingUrl: (url: string) => {
    try {
      const parsed = new URL(url);
      if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
        throw new Error('仅支持 http 或 https 协议');
      }
    } catch (e) {
      if (e instanceof Error && e.message === '仅支持 http 或 https 协议') {
        throw e;
      }
      throw new Error(`非法的网址格式: ${url}`);
    }
    set((state) => ({ pendingUrls: [...state.pendingUrls, url] }));
  },
  removePendingUrl: (index: number) => set((state) => ({ pendingUrls: state.pendingUrls.filter((_, i) => i !== index) })),
  clearPendingQueue: () => set({ pendingFiles: [], pendingUrls: [] }),
  
  submitAllPending: async () => {
    const { pendingFiles, pendingUrls } = get();
    if (pendingFiles.length === 0 && pendingUrls.length === 0) return;
    
    const config = useRagConfigStore.getState().buildRequestPayload();
    const newDocs: KnowledgeDocumentView[] = [];
    
    // 提交所有文件
    for (const file of pendingFiles) {
      try {
        const res = await ragService.submitLocalFile(file, config);
        newDocs.push({
          schema_version: 'rag.v1',
          id: res.document_id,
          filename: file.name,
          source_type: 'local_file',
          status: 'parsing',
          display_status: 'parsing',
          estimated_tokens: 0,
          error_log: null,
          created_at: new Date().toISOString()
        });
        pollingStartTimes[res.document_id] = Date.now();
      } catch (err) {
        console.error(`提交文件 ${file.name} 失败`, err);
        throw new Error(`提交文件 ${file.name} 失败: ${err instanceof Error ? err.message : String(err)}`);
      }
    }
    
    // 提交所有 URL
    for (const url of pendingUrls) {
      try {
        const res = await ragService.submitUrl({ ...config, url });
        newDocs.push({
          schema_version: 'rag.v1',
          id: res.document_id,
          filename: url,
          source_type: 'url',
          status: 'parsing',
          display_status: 'parsing',
          estimated_tokens: 0,
          error_log: null,
          created_at: new Date().toISOString()
        });
        pollingStartTimes[res.document_id] = Date.now();
      } catch (err) {
        console.error(`提交 URL ${url} 失败`, err);
        throw new Error(`提交 URL ${url} 失败: ${err instanceof Error ? err.message : String(err)}`);
      }
    }
    
    set((state) => ({
      documents: [...newDocs, ...state.documents],
      pendingFiles: [],
      pendingUrls: []
    }));
    
    get().startPolling();
  },
  
  deleteKnowledge: async (documentId: string) => {
    await ragService.deleteKnowledge(documentId);
    set((state) => ({
      documents: state.documents.filter(d => d.id !== documentId)
    }));
    // 刷新列表确保 UI 一致性
    get().fetchKnowledgeList();
  },

  /**
   * 更新指定文档的内容（基于 Blue-Green Update 策略）。
   *
   * 做什么：上传新文件替换已存在文档的内容，后端在后台完成切片与向量化后通过原子状态翻转上线。
   * 为什么这样做：更新期间旧文档保持 ACTIVE 服务不中断，详见 rag_deduplication_and_update_plan.md。
   * 输入输出：输入为文档 ID 和新文件，成功后自动刷新知识库列表。
   * 边界条件：仅允许对状态为 'completed' 的文档发起更新；更新期间 updatingDocIds 记录状态供 UI 展示。
   * 异常行为：文件大小/格式校验失败或后端返回错误时抛出中文异常。
   */
  updateKnowledge: async (documentId: string, newFile: File) => {
    // 文件大小校验
    if (newFile.size > RAG_MAX_UPLOAD_BYTES) {
      throw new Error(`文件大小超过限制 (最大 50MB)`);
    }
    const validExts = ['.txt', '.md', '.pdf', '.docx'];
    const name = newFile.name.toLowerCase();
    if (!validExts.some(ext => name.endsWith(ext))) {
      throw new Error(`不支持的文件格式，仅支持 txt, md, pdf, docx`);
    }

    // 标记该文档为"更新中"
    const { updatingDocIds } = get();
    const newUpdatingIds = new Set(updatingDocIds);
    newUpdatingIds.add(documentId);
    set({ updatingDocIds: newUpdatingIds });

    try {
      const config = useRagConfigStore.getState().buildRequestPayload();
      await ragService.updateKnowledge(documentId, newFile, config);

      // 更新成功后刷新列表以反映新版本状态
      await get().fetchKnowledgeList();
    } catch (err) {
      // 更新失败后也刷新列表（可能有部分失败信息）
      await get().fetchKnowledgeList();
      throw err;
    } finally {
      // 无论成功或失败，都从 updatingDocIds 中移除标记
      const { updatingDocIds: currentIds } = get();
      const updatedIds = new Set(currentIds);
      updatedIds.delete(documentId);
      set({ updatingDocIds: updatedIds });
    }
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
