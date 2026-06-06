import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import {
  RagChunkStrategy,
  SlidingWindowParams,
  StructuredParams,
  SemanticParams,
  RegexParams,
  ChunkPreviewUnit,
  RagChunkRequestPayload
} from '../types/rag';
import { ragService } from '../services/ragService';

export interface RagConfigState {
  // 当前激活的策略
  activeChunkStrategy: RagChunkStrategy;
  
  // 各策略参数
  slidingParams: SlidingWindowParams;
  structuredParams: StructuredParams;
  semanticParams: SemanticParams;
  regexParams: RegexParams;
  
  // 预览沙盒状态
  isPreviewLoading: boolean;
  previewError: string | null;
  previewResults: ChunkPreviewUnit[];
  previewTotalChunks: number;
  previewWarnings: string[];

  // 动作
  setActiveStrategy: (strategy: RagChunkStrategy) => void;
  updateSlidingParams: (params: Partial<SlidingWindowParams>) => void;
  updateStructuredParams: (params: Partial<StructuredParams>) => void;
  updateSemanticParams: (params: Partial<SemanticParams>) => void;
  updateRegexParams: (params: Partial<RegexParams>) => void;
  
  fetchPreviewChunks: (testText: string) => Promise<void>;
  clearPreview: () => void;
  
  // 辅助方法：生成用于 API 请求的 config
  buildRequestPayload: () => RagChunkRequestPayload;
}

export const useRagConfigStore = create<RagConfigState>()(
  persist(
    (set, get) => ({
      activeChunkStrategy: 'structured_ast',
      
      slidingParams: { chunkSize: 500, chunkOverlap: 50 },
      structuredParams: { includeMetadata: true, keepTablesIntact: true },
      semanticParams: { delimiters: ['\n\n', '\n', '.', '!', '?'], enableParentChild: true },
      regexParams: { startRegex: '', endRegex: '', maxTokenFallback: 1000 },
      
      isPreviewLoading: false,
      previewError: null,
      previewResults: [],
      previewTotalChunks: 0,
      previewWarnings: [],

      setActiveStrategy: (strategy) => set({ activeChunkStrategy: strategy }),
      
      updateSlidingParams: (params) => set((state) => ({ slidingParams: { ...state.slidingParams, ...params } })),
      updateStructuredParams: (params) => set((state) => ({ structuredParams: { ...state.structuredParams, ...params } })),
      updateSemanticParams: (params) => set((state) => ({ semanticParams: { ...state.semanticParams, ...params } })),
      updateRegexParams: (params) => set((state) => ({ regexParams: { ...state.regexParams, ...params } })),

      buildRequestPayload: () => {
        const state = get();
        const payload: RagChunkRequestPayload = {
          schema_version: 'rag.v1',
          strategy: state.activeChunkStrategy,
          chunk_size: 500,
          overlap: 50,
        };
        
        // Populate parameters based on strategy
        switch (state.activeChunkStrategy) {
          case 'sliding_window':
            payload.chunk_size = state.slidingParams.chunkSize;
            payload.overlap = state.slidingParams.chunkOverlap;
            break;
          case 'structured_ast':
            payload.chunk_size = state.slidingParams.chunkSize;
            payload.overlap = state.slidingParams.chunkOverlap;
            // Additional meta params logic if needed
            break;
          case 'semantic_parent_child':
            payload.chunk_size = state.slidingParams.chunkSize;
            payload.overlap = state.slidingParams.chunkOverlap;
            break;
          case 'regex':
            payload.chunk_size = state.slidingParams.chunkSize;
            payload.overlap = state.slidingParams.chunkOverlap;
            payload.regex_pattern = state.regexParams.startRegex; // assuming startRegex holds pattern
            payload.max_fallback_tokens = state.regexParams.maxTokenFallback;
            break;
        }
        return payload;
      },

      fetchPreviewChunks: async (testText) => {
        if (!testText.trim()) {
          set({ previewError: '预览文本不能为空', previewResults: [], previewTotalChunks: 0, previewWarnings: [] });
          return;
        }
        
        set({ isPreviewLoading: true, previewError: null });
        try {
          const state = get();
          const basePayload = state.buildRequestPayload();
          const payload = {
            ...basePayload,
            text: testText,
            timeout_seconds: 8.0
          };
          
          const response = await ragService.getChunkPreview(payload);
          set({ 
            previewResults: response.chunks, 
            previewTotalChunks: response.total_chunks,
            previewWarnings: response.warnings,
            isPreviewLoading: false 
          });
        } catch (err: unknown) {
          const message = err instanceof Error ? err.message : String(err);
          set({ previewError: message, isPreviewLoading: false });
        }
      },
      
      clearPreview: () => set({ previewResults: [], previewTotalChunks: 0, previewWarnings: [], previewError: null }),
    }),
    { 
      name: 'luna-rag-config-storage',
      partialize: (state) => ({
        activeChunkStrategy: state.activeChunkStrategy,
        slidingParams: state.slidingParams,
        structuredParams: state.structuredParams,
        semanticParams: state.semanticParams,
        regexParams: state.regexParams,
      }),
    }
  )
);
