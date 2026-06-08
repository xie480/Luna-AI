"""
Luna AI 上下文历史管理与截断策略模块

做什么：管理多轮对话的上下文历史记录，实现基于 Token 数量的滑动窗口截断策略。
为什么这样做：防止模型输入超出上下文窗口限制（如 4K/8K/128K），同时确保 System Prompt
         始终保留、最近的对话不被裁剪，以维持对话连贯性。
输入输出：
    - truncate_context(): 接收 System Prompt、历史记录和当前消息，返回裁剪后的 messages 列表
    - count_tokens(): 计算文本的 Token 数量
边界条件：
    - System Prompt 始终保留在 messages[0] 位置，不可裁剪
    - 至少保留最近 2 轮对话（即使超出 Token 限制）
    - 如果单条消息超长，需要截断该消息本身
异常行为：
    - Token 计数失败时回退到字符长度估算
    - 总 Token 数超过模型限制时静默截断并记录日志
"""


from pydantic import BaseModel

from app.logger import logger

# ============================================================
# 默认常量配置
# ============================================================

# 为模型输出预留的 Token 数
# 最终输入 token = MAX_CONTEXT_TOKENS - RESERVED_OUTPUT_TOKENS
RESERVED_OUTPUT_TOKENS: int = 2048

# 每次截断时至少保留的对话轮数（用户+助手=2条消息为一轮）
MIN_CONVERSATION_ROUNDS: int = 2

# 句子结束符列表（遇到这些字符时触发 buffer 刷新）
SENTENCE_END_CHARS: str = "。！？.!?\n"

# 流式输出缓冲刷新阈值（字符数）
FLUSH_CHAR_THRESHOLD: int = 5

# 当 tiktoken 不可用时的估算系数（中文约 1.5 字符/token，英文约 4 字符/token）
FALLBACK_CHARS_PER_TOKEN: float = 2.0


class ContextTrimMetrics(BaseModel):
    """
    上下文消息级裁剪指标。

    做什么：记录一次 `history` 消息滑动窗口裁剪前后的 Token 变化和裁剪结果。
    为什么这样做：消息级裁剪已经存在稳定逻辑，但压缩审计链路还缺少统一测量口径。
    输入输出：输入由 `measure_truncate_context()` 计算产生，输出为可序列化指标对象。
    边界条件：history 为空时 `removed_history_count=0`，`before_tokens` 与 `after_tokens` 仍按完整消息列表计算。
    异常行为：字段校验失败时由 Pydantic 抛出异常。
    """

    before_tokens: int
    after_tokens: int
    removed_history_count: int
    reserved_output_tokens: int
    max_context_tokens: int
    is_over_limit_after_trim: bool


# ============================================================
# Token 计数与估算
# ============================================================

def count_tokens(text: str, model_name: str = "gpt-3.5-turbo") -> int:
    """
    计算文本的 Token 数量

    做什么：使用 tiktoken 精确计算 Token 数，若 tiktoken 不可用则使用字符估算。
    为什么这样做：精确 Token 计数是截断策略的核心依据，字符估算仅作回退方案。
    输入输出：
        - 输入：text 文本内容，model_name 模型名称
        - 输出：Token 数量
    边界条件：tiktoken 库加载失败时静默回退到字符估算。
    异常行为：记录警告日志但不抛出异常。
    """
    try:
        import tiktoken
        try:
            encoding = tiktoken.encoding_for_model(model_name)
        except KeyError:
            # 如果模型名称不在 tiktoken 已知列表中，使用 cl100k_base
            encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(text))
    except ImportError:
        # tiktoken 未安装，使用字符估算
        logger.warning("tiktoken 库未安装，使用字符估算 Token 数")
        return max(1, int(len(text) / FALLBACK_CHARS_PER_TOKEN))
    except Exception as e:
        # 其他未知错误，回退到字符估算
        logger.warning(f"Token 计数失败，回退到字符估算: {e}")
        return max(1, int(len(text) / FALLBACK_CHARS_PER_TOKEN))


def count_messages_tokens(
    messages: list[dict[str, str]],
    model_name: str = "gpt-3.5-turbo"
) -> int:
    """
    计算消息列表的总 Token 数

    做什么：对 messages 列表中的每条消息逐条计算 Token 并累加。
    为什么这样做：OpenAI 格式的 API 会额外消耗角色的 Token，因此累加 role 和 content。
    输入输出：
        - 输入：messages 消息列表，model_name 模型名称
        - 输出：总 Token 数
    边界条件：空列表返回 0。
    """
    total = 0
    for msg in messages:
        # 每条消息额外消耗约 4 个 Token（role 标记 + 格式开销）
        total += count_tokens(msg.get("content", ""), model_name)
        total += count_tokens(msg.get("role", ""), model_name)
        total += 4  # 消息格式开销
    # 整体格式开销
    total += 2
    return total


# ============================================================
# 流式输出缓冲刷新机制
# ============================================================

def should_flush_buffer(buffer: str) -> tuple[bool, str]:
    """
    判断是否需要刷新流式输出缓冲区

    做什么：根据缓冲区内容和阈值判断是否应该 yield 当前累积的文本。
    为什么这样做：避免逐 Token 高频推送增加前端渲染压力，合并为语义完整的短句输出。
    输入输出：
        - 输入：buffer 当前累积的文本字符串
        - 输出：(是否刷新, 触发原因标识)
    边界条件：
        - 空 buffer 不刷新
        - 遇句子结束符优先刷新（即使长度未达阈值）
    """
    if not buffer:
        return False, ""

    # 如果 buffer 长度达到阈值，触发刷新
    if len(buffer) >= FLUSH_CHAR_THRESHOLD:
        return True, "threshold"

    # 如果 buffer 最后一个字符是句子结束符，触发刷新
    if buffer[-1] in SENTENCE_END_CHARS:
        return True, "sentence_end"

    return False, ""


# ============================================================
# 上下文截断核心逻辑
# ============================================================


def measure_truncate_context(
    system_prompt: str,
    history: list[dict[str, str]],
    current_message: str,
    max_context_tokens: int,
    reserved_output: int = RESERVED_OUTPUT_TOKENS,
    min_rounds: int = MIN_CONVERSATION_ROUNDS,
    model_name: str = "gpt-3.5-turbo",
) -> ContextTrimMetrics:
    """
    测量上下文截断前后的 Token 指标。

    做什么：复用与 `truncate_context()` 相同的滑动窗口裁剪策略，只返回测量结果而不改变既有返回值契约。
    为什么这样做：调用方需要把消息级裁剪纳入统一压缩审计，但不能破坏现有聊天主链路。
    输入输出：输入与 `truncate_context()` 一致，输出 `ContextTrimMetrics`。
    边界条件：保留 System Prompt 与当前消息；当历史为空时返回未裁剪指标。
    异常行为：本函数不主动抛业务异常，底层 Token 计数失败会沿用既有字符估算回退逻辑。
    """
    max_input_tokens = max_context_tokens - reserved_output
    system_msg: dict[str, str] = {"role": "system", "content": system_prompt}
    user_msg: dict[str, str] = {"role": "user", "content": current_message}
    candidate_messages: list[dict[str, str]] = [system_msg] + history + [user_msg]
    before_tokens = count_messages_tokens(candidate_messages, model_name)

    if not history:
        return ContextTrimMetrics(
            before_tokens=before_tokens,
            after_tokens=before_tokens,
            removed_history_count=0,
            reserved_output_tokens=reserved_output,
            max_context_tokens=max_context_tokens,
            is_over_limit_after_trim=before_tokens > max_input_tokens,
        )

    if before_tokens <= max_input_tokens:
        return ContextTrimMetrics(
            before_tokens=before_tokens,
            after_tokens=before_tokens,
            removed_history_count=0,
            reserved_output_tokens=reserved_output,
            max_context_tokens=max_context_tokens,
            is_over_limit_after_trim=False,
        )

    min_history_count: int = min_rounds * 2
    truncated_history: list[dict[str, str]] = list(history)
    removed_count: int = 0

    while len(truncated_history) > min_history_count:
        test_messages: list[dict[str, str]] = [system_msg] + truncated_history + [user_msg]
        test_tokens: int = count_messages_tokens(test_messages, model_name)
        if test_tokens <= max_input_tokens:
            break
        truncated_history.pop(0)
        removed_count += 1

    final_messages: list[dict[str, str]] = [system_msg] + truncated_history + [user_msg]
    after_tokens = count_messages_tokens(final_messages, model_name)
    return ContextTrimMetrics(
        before_tokens=before_tokens,
        after_tokens=after_tokens,
        removed_history_count=removed_count,
        reserved_output_tokens=reserved_output,
        max_context_tokens=max_context_tokens,
        is_over_limit_after_trim=after_tokens > max_input_tokens,
    )

def truncate_context(
    system_prompt: str,
    history: list[dict[str, str]],
    current_message: str,
    max_context_tokens: int,
    reserved_output: int = RESERVED_OUTPUT_TOKENS,
    min_rounds: int = MIN_CONVERSATION_ROUNDS,
    model_name: str = "gpt-3.5-turbo"
) -> list[dict[str, str]]:
    """
    对多轮对话上下文进行滑动窗口截断

    做什么：根据 Token 上限对输入上下文进行智能裁剪，确保 System Prompt 始终保留，
          优先移除最旧的对话历史，同时保证至少保留指定的对话轮数。
    为什么这样做：在有限的上下文窗口中最大化保留有效信息，确保对话连贯性。
    输入输出：
        - 输入：
            system_prompt: 系统提示词字符串
            history: 历史消息列表，格式 [{"role": "user"/"assistant", "content": "..."}]
            current_message: 当前用户消息字符串
            max_context_tokens: 上下文窗口最大 Token 总数
            reserved_output: 为输出预留的 Token 数
            min_rounds: 至少保留的对话轮数
            model_name: 模型名称（用于 Token 计数）
        - 输出：裁剪后的 messages 列表，格式适合直接传给 LLM API
    边界条件：
        - System Prompt 为空时使用空字符串占位
        - history 为空时直接返回 [system_prompt, user_message]
        - 如果历史记录极少（不足 min_rounds），保留全部历史
        - 极端情况：若 system_prompt + min_rounds 已超限制，则仅保留 system_prompt + 最新一条消息
    异常行为：记录截断日志但不抛出异常，确保调用方始终能拿到可用的 messages 列表。
    """
    # 计算可用输入长度 = 总限制 - 输出预留
    max_input_tokens = max_context_tokens - reserved_output

    # 构造 System Prompt 消息
    system_msg: dict[str, str] = {"role": "system", "content": system_prompt}

    # 构造当前用户消息
    user_msg: dict[str, str] = {"role": "user", "content": current_message}

    # 如果历史记录为空，直接返回
    if not history:
        logger.info("历史记录为空，跳过截断")
        return [system_msg, user_msg]

    # 计算 system_prompt + 当前消息 + 全部历史的 Token 数
    # 优先尝试包含全部历史
    candidate_messages: list[dict[str, str]] = [system_msg] + history + [user_msg]
    total_tokens: int = count_messages_tokens(candidate_messages, model_name)

    # 如果总 Token 数在限制内，无需截断
    if total_tokens <= max_input_tokens:
        logger.info(
            f"上下文 Token 数 {total_tokens}/{max_input_tokens}，无需截断"
        )
        return candidate_messages

    logger.warning(
        f"上下文 Token 数 {total_tokens} 超过限制 {max_input_tokens}，"
        f"开始滑动窗口截断"
    )

    # 需要截断：从最旧的 history 消息开始移除
    # 至少保留 min_rounds * 2 条历史消息（每轮含 user + assistant）
    min_history_count: int = min_rounds * 2

    # 从最旧历史开始逐条移除，直到 Token 满足限制或仅剩最少历史
    truncated_history: list[dict[str, str]] = list(history)
    removed_count: int = 0

    while len(truncated_history) > min_history_count:
        # 临时计算截断后的 Token 数
        test_messages: list[dict[str, str]] = (
            [system_msg] + truncated_history + [user_msg]
        )
        test_tokens: int = count_messages_tokens(test_messages, model_name)

        if test_tokens <= max_input_tokens:
            break

        # 移除最旧的一条历史消息
        truncated_history.pop(0)
        removed_count += 1

    # 如果移除后仍超限制，但已到最小保留轮数，不再继续移除
    final_messages: list[dict[str, str]] = [system_msg] + truncated_history + [user_msg]
    final_tokens: int = count_messages_tokens(final_messages, model_name)

    logger.warning(
        f"截断完成: 移除 {removed_count} 条历史消息, "
        f"最终 Token {final_tokens}/{max_input_tokens}"
    )

    if final_tokens > max_input_tokens:
        logger.error(
            f"截断后仍超出限制 {final_tokens}/{max_input_tokens}，"
            f"可能需要调整 min_rounds 参数"
        )

    return final_messages


# ============================================================
# 辅助函数
# ============================================================

def format_messages_for_api(
    system_prompt: str,
    history: list[dict[str, str]],
    current_message: str,
    max_context_tokens: int,
    reserved_output: int = RESERVED_OUTPUT_TOKENS,
    model_name: str = "gpt-3.5-turbo"
) -> list[dict[str, str]]:
    """
    完整的消息格式化入口，整合上下文截断

    做什么：接收系统提示词、历史记录和当前消息，返回经过截断处理后适合 LLM API 的消息列表。
    为什么这样做：作为 context_manager 模块的统一入口，简化调用方的使用。
    输入输出：
        - 输入：同 truncate_context()
        - 输出：裁剪后的 messages 列表
    """
    return truncate_context(
        system_prompt=system_prompt,
        history=history,
        current_message=current_message,
        max_context_tokens=max_context_tokens,
        reserved_output=reserved_output,
        model_name=model_name,
    )
