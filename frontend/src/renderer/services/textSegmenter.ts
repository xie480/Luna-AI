/**
 * 语义文本切分器
 *
 * 做什么：将 LLM 完整回复文本按语义标点切分为独立片段，供气泡分段渲染使用。
 * 为什么这样做：统一响应模式下后端返回完整文本，前端需要按语义边界拆分，
 *             确保每个气泡展示一个完整的语义单元，不截断句子。
 * 输入输出：
 *    - 输入：原始完整文本字符串
 *    - 输出：语义片段数组 string[]
 * 边界条件：
 *    - 空字符串或仅空白字符返回空数组
 *    - 超长无标点文本（> 50 字符）强制在 50 字符处切分
 *    - 标点符号保留在片段末尾（不放到下一个片段开头）
 *    - 过短片段（< 4 字符）合并到前一个片段
 * 异常行为：无异常抛出，所有边界情况均安全处理。
 */

/** 语义句子终止标点正则（保留标点在片段末尾）。 */
const SENTENCE_END_RE = /([。！？!?\n]+)/;

/** 连续换行正则（段落分隔符）。 */
const PARAGRAPH_BREAK_RE = /\n{2,}/;

/** 单个片段最大字符数（无标点长文本时强制截断）。 */
const MAX_SEGMENT_LENGTH = 50;

/** 单句最小字符数（太短的句子合并到前一句）。 */
const MIN_SEGMENT_LENGTH = 4;

/**
 * 将完整回复文本按语义边界切分为片段数组。
 *
 * 做什么：三步切分策略——
 *   1. 按连续换行（段落）切分
 *   2. 每个段落内部按句子终止标点切分
 *   3. 最终校验：超长片段强制截断，过短片段合并
 * 为什么这样做：气泡分段需要稳定、可预期的文本粒度，每段在 4~50 字符之间。
 * 输入输出：输入原始文本字符串，输出切分后的片段数组。
 * 边界条件：
 *   - 空文本返回空数组
 *   - 无标点长文本在 50 字符处强制断开
 *   - 末尾残留短文本自动合并
 * 异常行为：无。
 */
export function splitReplyIntoSegments(text: string): string[] {
  if (!text || text.trim().length === 0) {
    return [];
  }

  // 步骤 1：按段落分隔切分（连续换行）
  const paragraphs = text.split(PARAGRAPH_BREAK_RE).filter((p) => p.trim().length > 0);

  // 步骤 2：每个段落内按句子标点切分
  const segments: string[] = [];
  for (const paragraph of paragraphs) {
    const parts = paragraph.split(SENTENCE_END_RE);

    let currentSegment = '';
    for (let i = 0; i < parts.length; i++) {
      const part = parts[i];
      if (!part) continue;

      currentSegment += part;

      // 检查是否遇到句子结束标点，或当前累积长度已达到上限
      if (SENTENCE_END_RE.test(part) || currentSegment.length >= MAX_SEGMENT_LENGTH) {
        const trimmed = currentSegment.trim();
        if (trimmed.length > 0) {
          if (trimmed.length < MIN_SEGMENT_LENGTH && segments.length > 0) {
            // 太短的片段合并到前一个片段末尾
            segments[segments.length - 1] += trimmed;
          } else {
            segments.push(trimmed);
          }
        }
        currentSegment = '';
      }
    }

    // 处理段落末尾可能的残留文本（没有遇到句子终止标点的情况）
    if (currentSegment.trim().length > 0) {
      const trimmed = currentSegment.trim();
      if (trimmed.length < MIN_SEGMENT_LENGTH && segments.length > 0) {
        segments[segments.length - 1] += trimmed;
      } else {
        segments.push(trimmed);
      }
    }
  }

  // 步骤 3：最终校验 — 确保每段不超过 MAX_SEGMENT_LENGTH
  const finalSegments: string[] = [];
  for (const seg of segments) {
    if (seg.length <= MAX_SEGMENT_LENGTH) {
      finalSegments.push(seg);
    } else {
      // 超长片段强制按每 50 字符截断
      for (let i = 0; i < seg.length; i += MAX_SEGMENT_LENGTH) {
        finalSegments.push(seg.substring(i, i + MAX_SEGMENT_LENGTH));
      }
    }
  }

  return finalSegments;
}

/**
 * 计算单个语义片段的推荐展示时长（毫秒）。
 *
 * 做什么：根据片段文本长度计算气泡应展示的时长。
 * 为什么这样做：短文本不需要展示 3 秒，长文本需要足够阅读时间但不超过上限。
 * 输入输出：输入片段文本，输出推荐展示时长（毫秒）。
 * 边界条件：
 *   - 文本长度 ≥ 20 字符：固定 3000ms
 *   - 文本长度 < 20 字符：按比例计算，最低 1500ms
 * 异常行为：无。
 */
export function calculateSegmentDuration(text: string): number {
  const MAX_BUBBLE_DISPLAY_MS = 3000;
  const MIN_BUBBLE_DISPLAY_MS = 1500;
  const LONG_TEXT_THRESHOLD = 20;

  if (text.length >= LONG_TEXT_THRESHOLD) {
    return MAX_BUBBLE_DISPLAY_MS;
  }

  const ratio = text.length / LONG_TEXT_THRESHOLD;
  return Math.max(MIN_BUBBLE_DISPLAY_MS, Math.round(MAX_BUBBLE_DISPLAY_MS * ratio));
}