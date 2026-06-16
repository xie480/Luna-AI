import { create } from 'zustand';
import { lipSyncProcessor } from '../utils/lipSync';
import { getLive2dModel } from './live2dRef';

export interface PlaybackQueueItem {
  text: string;
  audioUri: string | null;
  batchId: string;
}

interface PlaybackStoreState {
  playbackQueue: PlaybackQueueItem[];
  isPlaying: boolean;
  
  // 入队
  enqueue: (item: PlaybackQueueItem) => void;
  // 消费队列
  processQueue: () => Promise<void>;
  // 清空
  clear: () => void;
}

// 独立的隐藏 Audio 元素用于播放
let sharedAudioElement: HTMLAudioElement | null = null;
function getSharedAudioElement() {
  if (!sharedAudioElement) {
    sharedAudioElement = document.createElement('audio');
    sharedAudioElement.id = 'luna-hidden-tts-audio';
    sharedAudioElement.style.display = 'none';
    document.body.appendChild(sharedAudioElement);
  }
  return sharedAudioElement;
}


export const usePlaybackStore = create<PlaybackStoreState>((set, get) => ({
  playbackQueue: [],
  isPlaying: false,

  enqueue: (item) => {
    set((state) => ({ playbackQueue: [...state.playbackQueue, item] }));
    if (!get().isPlaying) {
      get().processQueue();
    }
  },

  clear: () => {
    set({ playbackQueue: [], isPlaying: false });
    const audioEl = getSharedAudioElement();
    audioEl.pause();
    audioEl.src = '';
    lipSyncProcessor.stop();
  },

  processQueue: async () => {
    const { playbackQueue, isPlaying } = get();
    if (isPlaying || playbackQueue.length === 0) return;

    set({ isPlaying: true });
    const item = playbackQueue[0];

    // 分发事件通知显示气泡文本
    if (item.text.trim().length > 0) {
      const duration = Math.max(3000, item.text.length * 200);
      window.dispatchEvent(
        new CustomEvent('luna:show-bubble', {
          detail: { text: item.text, duration, batchId: item.batchId },
        })
      );
    }

    if (item.audioUri) {
      const audioEl = getSharedAudioElement();
      audioEl.src = item.audioUri;
      
      try {
        const live2dModel = getLive2dModel();
        if (live2dModel) {
            lipSyncProcessor.connect(audioEl);
            lipSyncProcessor.start(live2dModel);
        }
        await audioEl.play();
        
        // 等待播放完成
        await new Promise<void>((resolve) => {
          audioEl.onended = () => resolve();
          audioEl.onerror = () => resolve(); // 出错也跳过
        });
      } catch (e) {
        console.warn('Playback error:', e);
      } finally {
        lipSyncProcessor.stop();
      }
    } else {
        // 如果没有音频，根据文本长度等待一段时间
        const fallbackWaitMs = Math.max(1000, item.text.length * 150);
        await new Promise(r => setTimeout(r, fallbackWaitMs));
    }

    // 弹出当前元素并递归处理
    set((state) => ({
      playbackQueue: state.playbackQueue.slice(1),
      isPlaying: false,
    }));
    
    get().processQueue();
  },
}));
