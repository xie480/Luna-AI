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
 *    - 空回复文本时仅展示内心独白（如有），不触发气泡
 * 异常行为：Live2D 表情切换失败、TTS 播放失败均静默降级，不抛异常。
 */
import type { ChatUnifiedResponsePayload } from '../../../shared/types';
import { splitReplyIntoSegments, calculateSegmentDuration } from './textSegmenter';
import { getLive2dModel } from '../stores/live2dRef';
import { EMOTION_EXPRESSIONS } from '../constants/emotionExpressions';
import { lipSyncProcessor } from '../utils/lipSync';

/** 气泡之间的最小间隔（毫秒）。 */
const BUBBLE_GAP_MS = 800;

/**
 * 后端情绪标签到 Live2D 表达式名的映射表。
 * 做什么：后端返回的 emotion 是英文标签（如 "Happy"），
 *         Live2D SDK 的 setExpression 需要中文表达式名（如 "开心"）。
 * 为什么这样做：后端与 Live2D 模型之间的命名约定不同，需要一层转换。
 * 边界条件：未匹配到的情绪标签默认使用空字符串（切换回默认表达式）。
 */
const EMOTION_TO_EXPRESSION_MAP: Record<string, string> = {
  Happy: '开心',
  Sad: '难过',
  Angry: '生气',
  Surprised: '惊讶',
  Neutral: '普通',
  Fear: '害怕',
  Disgust: '厌恶',
  Bored: '无聊',
  Confused: '困惑',
  Tired: '疲惫',
};

/**
 * 将后端情绪标签映射为 Live2D 表达式名。
 *
 * 做什么：在映射表中查找对应的中文表达式名，未匹配时返回空字符串。
 * 为什么这样做：空字符串会让 Live2D 回到默认表达式，是安全的降级策略。
 * 输入输出：输入英文字符串情绪标签，输出中文字符串表达式名。
 * 边界条件：未知情绪 → 返回空字符串（默认表达式）。
 * 异常行为：无。
 */
function mapEmotionToExpression(emotion: string): string {
  return EMOTION_TO_EXPRESSION_MAP[emotion] || '';
}

/**
 * 立即切换 Live2D 表情。
 *
 * 做什么：根据后端返回的 emotion 标签，查找对应的 Live2D 表达式并立即应用。
 * 为什么这样做：表情切换应在气泡出现前完成（≤200ms），确保视觉表达先于内容。
 * 输入输出：输入 emotion 情绪标签字符串。
 * 边界条件：
 *    - 模型未加载时跳过（静默降级）
 *    - 空 emotion 不执行切换
 * 异常行为：setExpression 异常时静默捕获，不阻断后续流程。
 */
function applyLive2DExpression(emotion: string): void {
  if (!emotion || emotion.trim().length === 0) {
    return;
  }

  const model = getLive2dModel();
  if (!model) {
    console.warn('[UnifiedResponse] Live2D 模型未加载，跳过表情切换');
    return;
  }

  const expressionName = mapEmotionToExpression(emotion);

  try {
    // Live2D Cubism SDK 模型对象结构：model.internalModel 持有核心 API
    const internalModel = (model as Record<string, unknown>).internalModel;
    if (internalModel && typeof (internalModel as Record<string, unknown>).setExpression === 'function') {
      (internalModel as Record<string, (name: string) => void>).setExpression(expressionName);
    }
  } catch (e) {
    console.warn(
      `[UnifiedResponse] Live2D 表情切换失败: ${emotion} -> ${expressionName}`,
      e,
    );
  }
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
function playTtsAudio(audioUri: string, assistantMessageId: string): void {
  const audioEl = new Audio();
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
 * 为什么这样做：气泡渲染与音频播放解耦但同步触发，确保"看到的和听到的一致"。
 * 输入输出：
 *    - segments：语义片段数组
 *    - audioUri：TTS 音频地址或 null
 *    - thoughtText：内心独白文本
 *    - interactionId / assistantMessageId：用于追踪
 * 边界条件：
 *    - segments 为空时仅展示内心独白（如有），跳过气泡渲染
 *    - 每个气泡最长展示 3 秒
 *    - 气泡间隔 800ms
 * 异常行为：无。
 */
function enqueueBubbleBatch(params: {
  segments: string[];
  audioUri: string | null;
  thoughtText: string;
  interactionId: string;
  assistantMessageId: string;
}): void {
  const { segments, audioUri, thoughtText, interactionId, assistantMessageId } = params;

  // 内心独白：如有则在气泡流开始前单独展示（使用较短的持续时间）
  if (thoughtText && thoughtText.trim().length > 0) {
    window.dispatchEvent(
      new CustomEvent('luna:show-bubble', {
        detail: {
          text: `💭 ${thoughtText.trim()}`,
          duration: Math.min(3000, thoughtText.length * 100),
          batchId: assistantMessageId,
        },
      }),
    );
  }

  // 无有效回复文本时不渲染气泡
  if (segments.length === 0) {
    // 仍需派发流结束信号让批次状态机正常流转
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
 *   1. 立即切换 Live2D 表情（优先级最高）
 *   2. 语义切分回复文本
 *   3. 批量气泡入队 + 触发音频播放
 * 为什么这样做：表情 → 切分 → 气泡 → 音频，这条链路上的每一步都依赖上一步的结果。
 * 输入输出：输入 ChatUnifiedResponsePayload，输出为副作用（事件派发）。
 * 边界条件：
 *    - reply_text 为空时不产生气泡片段
 *    - error 非空时记录日志但不阻断
 * 异常行为：任何步骤失败都会静默降级，不抛异常。
 */
export function handleUnifiedResponse(payload: ChatUnifiedResponsePayload): void {
  const {
    reply_text,
    thought_text,
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

  // ---- 优先级 1：立即切换 Live2D 表情 ----
  applyLive2DExpression(emotion);

  // ---- 优先级 2：语义切分 ----
  const segments = splitReplyIntoSegments(reply_text);

  // ---- 优先级 3：气泡批量入队 + 音画同步 ----
  enqueueBubbleBatch({
    segments,
    audioUri: audio_uri,
    thoughtText: thought_text,
    interactionId: interaction_id,
    assistantMessageId: assistant_message_id,
  });
}