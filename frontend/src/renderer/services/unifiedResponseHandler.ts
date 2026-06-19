/**
 * 统一响应处理器
 *
 * 做什么：接收后端 unified_response 事件载荷，按优先级协调
 *         Live2D 表情切换 → 语义切分 → 气泡批量入队 → 音频播放。
 * 为什么这样做：将 SSE 数据接收与 UI 渲染解耦，确保 Live2D 表情优先于气泡展示，
 *             实现"表情先出、气泡跟上、音频同步"的音画同步效果。
 * 输入输出：
 *    - 输入：ChatUnifiedResponsePayload（来自后端 SSE 推送）
 *    - 输出：触发 Live2D 表情切换、气泡队列入队、TTS 音频播放
 * 边界条件：
 *    - emotion 为空字符串时不切换表情
 *    - audio_uri 为 null 时跳过 TTS 播放，降级为纯文本模式
 *    - Live2D 模型未加载时跳过表情切换，不阻断后续流程
 *    - 空回复文本时不触发气泡
 * 异常行为：Live2D 表情切换失败、TTS 播放失败均静默降级，不抛异常。
 */
import type { ChatUnifiedResponsePayload } from '../../../shared/types';
import { splitReplyIntoSegments, calculateSegmentDuration } from './textSegmenter';
import { useSystemStore } from '../stores/systemStore';
import { getLive2dModel } from '../stores/live2dRef';
import { lipSyncProcessor } from '../utils/lipSync';

/** 气泡之间的最小间隔（毫秒）。 */
const BUBBLE_GAP_MS = 800;

/**
 * 更新 store 中的情绪状态，触发 Live2DView 的表情渲染。
 *
 * 做什么：通过 systemStore.setEmotion() 更新全局情绪状态，
 *         Live2DView 组件监听 currentEmotion 的变化，
 *         通过 applyEmotionExpressions() 使用 EMOTION_EXPRESSIONS 映射表
 *         应用基于参数的表情动画（眼、嘴、脸红等）。
 * 为什么这样做：Live2DView 已有完整的表情渲染机制（EMOTION_EXPRESSIONS 映射表 +
 *             参数补间动画），只需更新 store 即可触发。
 *            避免直接调用模型 setExpression() API 导致的两套机制冲突。
 * 输入输出：输入 emotion 情绪标签字符串；输出为 store 状态更新。
 * 边界条件：
 *    - 空 emotion 不执行切换
 *    - 自动规范化首字母大写
 * 异常行为：无。
 */
function updateLive2DEmotion(emotion: string): void {
  if (!emotion || emotion.trim().length === 0) {
    return;
  }
  const trimmed = emotion.trim();
  const normalized = trimmed.charAt(0).toUpperCase() + trimmed.slice(1).toLowerCase();
  useSystemStore.getState().setEmotion(normalized as any); // eslint-disable-line @typescript-eslint/no-explicit-any
}

/**
 * 播放 TTS 音频并启动 LipSync 嘴型同步。
 *
 * 做什么：创建隐藏 Audio 元素加载音频 URI，播放并同步 Live2D 嘴型。
 * 为什么这样做：首个气泡渲染时立即触发播放，确保音画同步。
 * 输入输出：
 *    - 输入：audioUri 音频地址、assistantMessageId 用于追踪
 * 边界条件：
 *    - Live2D 模型未加载时跳过 LipSync，仅播放音频
 *    - 播放失败静默降级
 * 异常行为：播放异常不影响气泡渲染流程。
 */
let sharedUnifiedAudioElement: HTMLAudioElement | null = null;
function getSharedUnifiedAudioElement() {
  if (!sharedUnifiedAudioElement) {
    sharedUnifiedAudioElement = document.createElement('audio');
    sharedUnifiedAudioElement.id = 'luna-unified-tts-audio';
    sharedUnifiedAudioElement.style.display = 'none';
    // 必须设置 crossOrigin，否则 Web Audio API 出于跨域安全限制，提取到的频域数据全是 0
    sharedUnifiedAudioElement.crossOrigin = 'anonymous';
    document.body.appendChild(sharedUnifiedAudioElement);
  }
  return sharedUnifiedAudioElement;
}

function playTtsAudio(audioUri: string, assistantMessageId: string): void {
  const audioEl = getSharedUnifiedAudioElement();
  audioEl.src = audioUri;

  const live2dModel = getLive2dModel();
  if (live2dModel) {
    lipSyncProcessor.connect(audioEl);
    lipSyncProcessor.start(live2dModel);
  }

  audioEl.play().catch((e: unknown) => {
    console.warn(`[UnifiedResponse] TTS 音频播放失败: ${audioUri}`, e);
  });

  audioEl.onended = () => {
    lipSyncProcessor.stop();
  };

  audioEl.onerror = () => {
    lipSyncProcessor.stop();
  };
}

/**
 * 将语义片段数组批量入队到气泡渲染系统。
 *
 * 做什么：把切分好的片段依次送入气泡队列，首个气泡渲染时触发 TTS 音频播放。
 *        注意：只渲染 reply 字段的文本内容，不渲染 thought 思考内容。
 * 为什么这样做：气泡渲染与音频播放解耦但同步触发，确保"看到的和听到的一致"。
 *             thought 是模型的内心独白，不应展示在气泡中。
 * 输入输出：
 *    - segments：语义片段数组（仅基于 reply_text 切分）
 *    - audioUri：TTS 音频地址或 null
 *    - interactionId / assistantMessageId：用于追踪
 * 边界条件：
 *    - segments 为空时跳过气泡渲染
 *    - 每个气泡最长展示 3 秒
 *    - 气泡间隔 800ms
 * 异常行为：无。
 */
function enqueueBubbleBatch(params: {
  segments: string[];
  audioUri: string | null;
  interactionId: string;
  assistantMessageId: string;
}): void {
  const { segments, audioUri, interactionId, assistantMessageId } = params;

  // 如果气泡渲染被关闭，不展示气泡但仍需派发流结束信号让批次状态机正常流转
  const showBubbleRender = useSystemStore.getState().showBubbleRender;

  // 无有效回复文本或气泡渲染关闭时不渲染气泡，但仍需派发流结束信号让批次状态机正常流转
  if (segments.length === 0 || !showBubbleRender) {
    window.dispatchEvent(
      new CustomEvent('luna:bubble-stream-finished', {
        detail: { batchId: assistantMessageId, finishedAt: Date.now() },
      }),
    );
    return;
  }

  let isFirstBubble = true;

  for (const segment of segments) {
    const duration = calculateSegmentDuration(segment);
    const batchId = `${assistantMessageId}-${interactionId}`;

    // 通过现有的 luna:show-bubble 事件将片段送入气泡队列
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
        // 使用 setTimeout(0) 确保气泡 DOM 已经挂载到页面上
        setTimeout(() => {
          playTtsAudio(audioUri, assistantMessageId);
        }, 0);
      }
    }
  }

  // 所有片段入队后，派发流结束信号
  // 使用延迟确保最后一个气泡也已进入队列
  setTimeout(() => {
    window.dispatchEvent(
      new CustomEvent('luna:bubble-stream-finished', {
        detail: { batchId: `${assistantMessageId}-${interactionId}`, finishedAt: Date.now() },
      }),
    );
  }, BUBBLE_GAP_MS);
}

/**
 * 处理统一响应载荷的主入口函数。
 *
 * 做什么：按优先级顺序处理后端 unified_response 事件——
 *   1. 更新 store 情绪状态，触发 Live2DView 表情渲染（优先级最高，仅基于 reply 内容）
 *   2. 语义切分回复文本（忽略 thought_text，不展示内心独白）
 *   3. 批量气泡入队 + 触发音频播放（仅渲染 reply 内容）
 * 为什么这样做：表情 → 切分 → 气泡 → 音频，这条链路上的每一步都依赖上一步的结果。
 *              thought_text（模型内心独白）不应展示在气泡中。
 * 输入输出：输入 ChatUnifiedResponsePayload，输出为副作用（事件派发）。
 * 边界条件：
 *    - reply_text 为空时不产生气泡片段
 *    - error 非空时记录日志但不阻断
 * 异常行为：任何步骤失败都会静默降级，不抛异常。
 */
export function handleUnifiedResponse(payload: ChatUnifiedResponsePayload): void {
  const {
    reply_text,
    emotion,
    audio_uri,
    interaction_id,
    assistant_message_id,
    error,
    e2e_latency_ms,
  } = payload;

  // ---- 错误检查：如果后端返回了错误，记录日志 ----
  if (error && error.trim().length > 0) {
    console.error(`[UnifiedResponse] 后端返回错误: ${error}, e2e_latency_ms=${e2e_latency_ms}`);
  }

  // ---- 优先级 1：更新 store 情绪状态 → Live2DView 自动渲染对应表情 ----
  updateLive2DEmotion(emotion);

  // ---- 优先级 2：语义切分（仅切分 reply_text，不包含 thought_text） ----
  const segments = splitReplyIntoSegments(reply_text);

  // ---- 优先级 3：气泡批量入队 + 音画同步（仅展示 reply 内容） ----
  enqueueBubbleBatch({
    segments,
    audioUri: audio_uri,
    interactionId: interaction_id,
    assistantMessageId: assistant_message_id,
  });
}