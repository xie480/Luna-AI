import { create } from 'zustand';
import { lipSyncProcessor } from '../utils/lipSync';
import { getLive2dModel } from './live2dRef';
import { useSystemStore } from './systemStore';

/**
 * LipSync 调优参数。
 * 用于在不同场景下微调口型同步的灵敏度和平滑度，
 * 可根据 TTS 声音特性或 Live2D 模型不同单独配置。
 */
export interface LipSyncTuningParams {
  /** 音量放大乘数（默认 1.8）。声音较小时增大此值使嘴部动作更明显。 */
  multiplier?: number;
  /** 帧间平滑系数 0~1（默认 0.5）。越大越平滑但跟随延迟也越大。 */
  smoothing?: number;
  /** 噪音门限 0~1（默认 0.05）。低于此值的音量视为静音，强制闭嘴。 */
  noiseGateThreshold?: number;
}

/**
 * 播放队列项（流式逐句模式使用）。
 * 做什么：承载后端流式推送单句文本与对应 TTS 音频地址。
 * 为什么这样做：流式模式下每个句子独立入队，逐句播放。
 * 输入输出：无。
 * 边界条件：audioUri 为 null 时仅展示文本，不播放音频。
 * 异常行为：无。
 */
export interface PlaybackQueueItem {
  text: string;
  audioUri: string | null;
  batchId: string;
}

/**
 * 批量入队载荷（统一非流式响应模式使用）。
 * 做什么：一次性接收后端完整回复的所有语义片段与合成音频。
 * 为什么这样做：统一响应模式下不再逐句推送，前端一次性拿到全部数据。
 * 输入输出：无。
 * 边界条件：
 *   - segments 为空数组时跳过气泡渲染
 *   - audioUri 为 null 时跳过 TTS 播放
 * 异常行为：无。
 */
export interface BatchEnqueuePayload {
  /** 语义切分后的文本片段数组。 */
  segments: string[];
  /** 已合成 TTS 音频文件路径或 null。 */
  audioUri: string | null;
  /** 模型内心独白文本。 */
  thoughtText: string;
  /** 本轮交互 ID。 */
  interactionId: string;
  /** assistant 消息 ID。 */
  assistantMessageId: string;
  /** LipSync 调优参数（可选），如不传则使用默认值。 */
  lipSyncParams?: LipSyncTuningParams;
}

interface PlaybackStoreState {
  playbackQueue: PlaybackQueueItem[];
  isPlaying: boolean;
  /** 当前是否处于批量播放模式（统一响应模式）。 */
  isBatchMode: boolean;

  // 流式逐句入队（旧协议保留兼容）
  enqueue: (item: PlaybackQueueItem) => void;
  // 消费流式逐句队列
  processQueue: () => Promise<void>;
  // 统一响应批量入队（新协议）
  enqueueBatch: (payload: BatchEnqueuePayload) => void;
  // 清空所有队列
  clear: () => void;
}

// 独立的隐藏 Audio 元素用于播放
let sharedAudioElement: HTMLAudioElement | null = null;
function getSharedAudioElement() {
  if (!sharedAudioElement) {
    sharedAudioElement = document.createElement('audio');
    sharedAudioElement.id = 'luna-hidden-tts-audio';
    sharedAudioElement.style.display = 'none';
    // 必须设置 crossOrigin，否则 Web Audio API 出于跨域安全限制，提取到的频域数据全是 0
    sharedAudioElement.crossOrigin = 'anonymous';
    document.body.appendChild(sharedAudioElement);
  }
  return sharedAudioElement;
}

/** 气泡之间的最小间隔（毫秒）。 */
const BUBBLE_GAP_MS = 800;

/**
 * 启动 LipSync 的辅助函数，统一多处的重复调用逻辑。
 *
 * 做什么：连接音频元素 → 启动口型同步 → 播放音频 → 注册结束/错误回调。
 * 为什么这样做：多处（enqueueBatch / processQueue）都需要相同的 LipSync 启动逻辑，
 *              抽取为函数避免重复代码。
 * 输入输出：返回 audioEl，便于外部监听播放状态。
 * 边界条件：
 *   - Live2D 模型未加载时仅播放音频，跳过 LipSync。
 *   - 播放失败时仍会调用 lipSyncProcessor.stop() 确保状态复位。
 * 异常行为：播放异常不抛出，仅打印警告。
 */
function startPlaybackWithLipSync(
  audioUri: string,
  lipSyncParams?: LipSyncTuningParams,
): HTMLAudioElement {
  const audioEl = getSharedAudioElement();
  audioEl.src = audioUri;

  const live2dModel = getLive2dModel();
  if (live2dModel) {
    lipSyncProcessor.connect(audioEl);
    lipSyncProcessor.start(
      live2dModel,
      lipSyncParams?.multiplier ?? 1.8,
      lipSyncParams?.smoothing ?? 0.5,
      lipSyncParams?.noiseGateThreshold ?? 0.05,
    );
  }

  audioEl.play().catch((e: unknown) => {
    console.warn('[PlaybackStore] TTS 音频播放失败:', e);
  });

  audioEl.onended = () => {
    lipSyncProcessor.stop();
  };
  audioEl.onerror = () => {
    lipSyncProcessor.stop();
  };

  return audioEl;
}

export const usePlaybackStore = create<PlaybackStoreState>((set, get) => ({
  playbackQueue: [],
  isPlaying: false,
  isBatchMode: false,

  /**
   * 流式逐句入队（旧协议保留兼容）。
   *
   * 做什么：将单个句子加入播放队列，自动触发消费。
   * 为什么这样做：流式模式下后端逐句推送，前端逐句渲染。
   * 输入输出：输入 PlaybackQueueItem，输出为副作用。
   * 边界条件：已在播放中时不会重复触发 processQueue。
   * 异常行为：无。
   */
  enqueue: (item) => {
    set((state) => ({ playbackQueue: [...state.playbackQueue, item] }));
    if (!get().isPlaying) {
      get().processQueue();
    }
  },

  /**
   * 清空所有播放队列并停止音频。
   *
   * 做什么：清除流式队列、停止音频播放、停止 LipSync 并重置嘴部为闭合。
   * 为什么这样做：用户中断或切换会话时需要干净的状态重置。
   * 输入输出：无。
   * 边界条件：sharedAudioElement 可能尚未创建。
   * 异常行为：无。
   */
  clear: () => {
    set({ playbackQueue: [], isPlaying: false, isBatchMode: false });
    const audioEl = getSharedAudioElement();
    audioEl.pause();
    audioEl.src = '';
    // lipSyncProcessor.stop() 内部会重置嘴部参数为 ParamMouthOpenY = 0
    lipSyncProcessor.stop();
  },

  /**
   * 统一响应批量入队（新协议）。
   *
   * 做什么：一次性接收所有语义片段和已合成 TTS 音频，按顺序分发气泡事件，
   *         并在首个气泡渲染后触发 TTS 音频播放与 LipSync 口型同步。
   * 为什么这样做：统一响应模式不再逐句推送，前端收到完整回复后自行编排气泡节奏。
   * 输入输出：输入 BatchEnqueuePayload，输出为窗口事件副作用。
   * 边界条件：
   *   - segments 为空时仅展示内心独白并派发流结束信号
   *   - audioUri 为 null 时跳过 TTS 播放
   *   - 每个气泡最长展示 3 秒，间隔 800ms
   * 异常行为：TTS 播放失败静默降级，不阻断气泡渲染。
   */
  enqueueBatch: (payload: BatchEnqueuePayload) => {
    const { segments, audioUri, thoughtText, interactionId, assistantMessageId, lipSyncParams } = payload;
    const batchId = `${assistantMessageId}-${interactionId}`;

    set({ isBatchMode: true });

    // 检查气泡渲染是否开启
    const showBubbleRender = useSystemStore.getState().showBubbleRender;
    // 如果气泡渲染关闭，只触发流结束信号，不展示任何气泡
    if (!showBubbleRender) {
      window.dispatchEvent(
        new CustomEvent('luna:bubble-stream-finished', {
          detail: { batchId, finishedAt: Date.now() },
        }),
      );
      set({ isBatchMode: false });
      return;
    }

    // ---- 内心独白：如有则在气泡流开始前单独展示 ----
    if (thoughtText && thoughtText.trim().length > 0) {
      window.dispatchEvent(
        new CustomEvent('luna:show-bubble', {
          detail: {
            text: `💭 ${thoughtText.trim()}`,
            duration: Math.min(3000, thoughtText.length * 100),
            batchId,
          },
        }),
      );
    }

    // ---- 无有效回复文本：直接结束 ----
    if (segments.length === 0) {
      window.dispatchEvent(
        new CustomEvent('luna:bubble-stream-finished', {
          detail: { batchId, finishedAt: Date.now() },
        }),
      );
      set({ isBatchMode: false });
      return;
    }

    // ---- 逐段分发气泡事件 ----
    let isFirstBubble = true;

    for (const segment of segments) {
      const duration = Math.min(3000, Math.max(1500, segment.length * 150));

      window.dispatchEvent(
        new CustomEvent('luna:show-bubble', {
          detail: {
            text: segment,
            duration,
            batchId,
          },
        }),
      );

      // 首个气泡渲染后立即触发 TTS 音频播放（音画同步的关键时刻）
      if (isFirstBubble) {
        isFirstBubble = false;
        if (audioUri) {
          // 使用 setTimeout(0) 确保气泡 DOM 已挂载
          setTimeout(() => {
            startPlaybackWithLipSync(audioUri, lipSyncParams);
          }, 0);
        }
      }
    }

    // ---- 所有片段入队后派发流结束信号 ----
    setTimeout(() => {
      window.dispatchEvent(
        new CustomEvent('luna:bubble-stream-finished', {
          detail: { batchId, finishedAt: Date.now() },
        }),
      );
      set({ isBatchMode: false });
    }, BUBBLE_GAP_MS);
  },

  /**
   * 消费流式逐句队列（旧协议保留兼容）。
   *
   * 做什么：从队列头部取出一个句子，展示气泡并播放对应音频与 LipSync。
   * 为什么这样做：流式模式下每句独立播放，播完后再消费下一句。
   * 输入输出：无。
   * 边界条件：队列为空或已在播放中时直接返回。
   * 异常行为：音频播放失败后继续处理下一句。
   */
  processQueue: async () => {
    const { playbackQueue, isPlaying } = get();
    if (isPlaying || playbackQueue.length === 0) return;

    set({ isPlaying: true });
    const item = playbackQueue[0];

    // 检查气泡渲染是否开启
    const showBubbleRender = useSystemStore.getState().showBubbleRender;

    // 仅当气泡渲染开启时，才分发气泡展示事件
    if (showBubbleRender && item.text.trim().length > 0) {
      const duration = Math.max(3000, item.text.length * 200);
      window.dispatchEvent(
        new CustomEvent('luna:show-bubble', {
          detail: { text: item.text, duration, batchId: item.batchId },
        })
      );
    }

    if (item.audioUri) {
      try {
        // 使用统一的辅助函数启动播放与 LipSync
        const audioEl = startPlaybackWithLipSync(item.audioUri);

        // 等待播放完成
        // 注意：startPlaybackWithLipSync 已经注册了 onended / onerror，
        // 这里用 Promise 包装等待播放完成，然后自动进入下一句
        await new Promise<void>((resolve) => {
          audioEl.onended = () => resolve();
          audioEl.onerror = () => resolve(); // 出错也跳过，继续播下一句
        });
      } catch (e) {
        console.warn('[PlaybackStore] 流式播放出错:', e);
      }
    } else {
        // 如果没有音频，根据文本长度等待一段时间
        const fallbackWaitMs = Math.max(1000, item.text.length * 150);
        await new Promise(r => setTimeout(r, fallbackWaitMs));
    }

    // 弹出当前元素并递归处理下一句
    set((state) => ({
      playbackQueue: state.playbackQueue.slice(1),
      isPlaying: false,
    }));

    get().processQueue();
  },
}));
