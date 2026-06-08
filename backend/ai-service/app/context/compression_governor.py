"""
memory 槽位上下文压缩治理器。

做什么：在最终聊天 Prompt 组装前，对 memory 槽位中的大文本变量执行统一的冗余治理、分变量压缩、
        历史背景合并降级与最终硬截断保护，并把关键动作写入既有遥测链路。
为什么这样做：当前聊天主链路已经能注入长期记忆、外部知识、用户画像与会话摘要，
            但缺少在 Prompt 装配前的统一治理层，导致长对话场景下 memory 槽位容易膨胀。
输入输出：
    - 输入：trace_id、session_id、message_id 与完整 prompt_variables。
    - 输出：CompressionGovernanceResult，包含治理后的变量映射和动作记录。
边界条件：
    - 只治理 memory 槽位变量，不修改 system/runtime 槽位内容。
    - 压缩失败时记录失败审计，但不阻断聊天主链路。
    - 统一历史背景降级时优先复用现有 LONG_TERM_MEMORY 变量承载合并结果，避免改动 Prompt 模板结构。
异常行为：
    - 模型调用、审计写入、Span 写入异常由本模块记录日志后降级继续，不向上抛出阻断聊天链路。
"""

from __future__ import annotations

from time import monotonic
from typing import Final

from app.config.settings import settings
from app.context.compression_audit import (
    create_compression_audit_payload,
    current_timestamp_ms,
    record_compression_audit_payload,
    record_compression_span,
)
from app.context.compression_types import (
    CompressionActionEvent,
    CompressionActionRecord,
    CompressionGovernanceResult,
)
from app.llm.client import compression_llm_client
from app.llm.context_manager import count_tokens
from app.logger import logger
from app.types.constants import (
    COMPRESSION_EVENT_APPLIED,
    COMPRESSION_EVENT_COMPLETED,
    COMPRESSION_EVENT_EXECUTED,
    COMPRESSION_EVENT_FAILED,
    COMPRESSION_EVENT_INPUT_MEASURED,
    COMPRESSION_EVENT_OUTPUT_MEASURED,
    COMPRESSION_EVENT_TRIGGERED,
    COMPRESSION_STATUS_FAILED,
    COMPRESSION_STATUS_SUCCESS,
    COMPRESSION_VARIABLE_HISTORICAL_CONTEXT,
    CompressionScope,
    CompressionStage,
    CompressionTriggerReason,
    Role,
)

MEMORY_SLOT_VARIABLE_KEYS: Final[tuple[str, ...]] = (
    "LONG_TERM_MEMORY",
    "EXTERNAL_KNOWLEDGE",
    "USER_PROFILE",
    "CORE_SUMMARY",
    "KEY_FACTS",
    "MEMORY_SNIPPETS",
)

HISTORICAL_CONTEXT_TARGET_KEY: Final[str] = "LONG_TERM_MEMORY"
VARIABLE_SCOPE_MAPPING: Final[dict[str, CompressionScope]] = {
    "LONG_TERM_MEMORY": CompressionScope.LONG_TERM_MEMORY,
    "EXTERNAL_KNOWLEDGE": CompressionScope.EXTERNAL_KNOWLEDGE,
    "USER_PROFILE": CompressionScope.USER_PROFILE,
    "CORE_SUMMARY": CompressionScope.CORE_SUMMARY,
    "KEY_FACTS": CompressionScope.KEY_FACTS,
    "MEMORY_SNIPPETS": CompressionScope.MEMORY_SNIPPETS,
}
VARIABLE_LABEL_MAPPING: Final[dict[str, str]] = {
    "LONG_TERM_MEMORY": "长期记忆",
    "EXTERNAL_KNOWLEDGE": "外部知识",
    "USER_PROFILE": "用户画像",
    "CORE_SUMMARY": "核心梗概",
    "KEY_FACTS": "关键事实",
    "MEMORY_SNIPPETS": "近期对话片段",
}
VARIABLE_SUMMARIZE_TIMEOUT_SECONDS: Final[float] = 60.0
VARIABLE_SUMMARIZE_PROMPT_TEMPLATE: Final[str] = (
    "你是 Luna 后端的上下文压缩器。请在不编造事实的前提下，把以下内容压缩为更短的中文背景摘要。\n"
    "要求：\n"
    "1. 保留人名、时间、事实、限制条件、偏好、任务目标与结论。\n"
    "2. 删除重复、寒暄、无关修饰和低价值赘述。\n"
    "3. 输出纯文本，不要添加标题，不要使用 Markdown。\n"
    "4. 若原文包含列表，请在压缩结果中保留关键条目顺序。\n\n"
    "[变量名称]\n{variable_label}\n\n"
    "[原始内容]\n{text}"
)
HISTORICAL_CONTEXT_PROMPT_TEMPLATE: Final[str] = (
    "你是 Luna 后端的统一历史背景压缩器。请把以下来自不同来源的历史背景合并成一段更短的中文上下文。\n"
    "要求：\n"
    "1. 保留跨来源都重要的事实、用户偏好、知识结论、会话核心背景。\n"
    "2. 明确保留来源差异，不要把互不相同的事实混成一条。\n"
    "3. 输出纯文本，不要添加解释，不要使用 Markdown 列表标记以外的格式。\n"
    "4. 若存在时间或条件限制，必须保留。\n\n"
    "[待合并历史背景]\n{text}"
)


class MemorySlotCompressionGovernor:
    """
    memory 槽位压缩治理器。

    做什么：封装 memory 槽位的分级治理流程，并把真实执行节点的指标同步到审计链路。
    为什么这样做：聊天主链路只需要调用一个治理入口，避免压缩细节散落在 [chat_request()](backend/ai-service/app/api/http_api.py:312) 中。
    输入输出：输入 prompt_variables，输出治理后的变量与动作记录。
    边界条件：本类无共享可变状态，可按请求创建实例。
    异常行为：内部异常尽量被捕获并记录，避免影响主聊天流程。
    """

    async def govern(
        self,
        *,
        trace_id: str,
        session_id: str,
        message_id: str,
        prompt_variables: dict[str, str],
    ) -> CompressionGovernanceResult:
        """
        执行 memory 槽位压缩治理。

        做什么：对 memory 槽位变量进行测量、确定性冗余过滤、分变量压缩、历史背景合并降级与硬截断。
        为什么这样做：优先治理易膨胀的 memory 槽位，避免直接粗暴地整体截断最终 Prompt。
        输入输出：输入链路标识与 Prompt 变量，输出治理后的变量映射和动作记录。
        边界条件：配置开关关闭或总 Token 未超阈值时直接跳过。
        异常行为：治理内部异常记录日志后返回原始变量，保证聊天主链路继续执行。
        """
        updated_variables = {key: self._normalize_text(value) for key, value in prompt_variables.items()}
        action_records: list[CompressionActionRecord] = []
        memory_variables = self._extract_memory_slot_variables(updated_variables)
        before_tokens = self._count_slot_tokens(memory_variables)

        if not settings.memory_slot_compression_enabled:
            logger.info(
                f"memory 槽位压缩治理已关闭 trace_id={trace_id} session_id={session_id} message_id={message_id}"
            )
            return CompressionGovernanceResult(
                updated_variables=updated_variables,
                action_records=action_records,
                before_tokens=before_tokens,
                after_tokens=before_tokens,
                skipped=True,
                final_strategy="disabled",
            )

        if before_tokens <= settings.memory_slot_max_tokens:
            logger.info(
                f"memory 槽位 Token 未超阈值，跳过压缩治理 trace_id={trace_id} session_id={session_id} "
                f"message_id={message_id} before_tokens={before_tokens} threshold={settings.memory_slot_max_tokens}"
            )
            return CompressionGovernanceResult(
                updated_variables=updated_variables,
                action_records=action_records,
                before_tokens=before_tokens,
                after_tokens=before_tokens,
                skipped=True,
                final_strategy="within_limit",
            )

        try:
            working_variables = self._apply_deterministic_reduction(memory_variables)
            after_dedup_tokens = self._count_slot_tokens(working_variables)
            final_strategy = "deterministic_reduction"

            if after_dedup_tokens > settings.memory_slot_max_tokens:
                for variable_key in MEMORY_SLOT_VARIABLE_KEYS:
                    variable_text = working_variables.get(variable_key, "")
                    variable_tokens = count_tokens(variable_text) if variable_text else 0
                    if not variable_text or variable_tokens <= settings.memory_slot_single_variable_max_tokens:
                        continue
                    compressed_text = await self._compress_single_variable(
                        trace_id=trace_id,
                        session_id=session_id,
                        message_id=message_id,
                        variable_key=variable_key,
                        variable_text=variable_text,
                        action_records=action_records,
                    )
                    working_variables[variable_key] = compressed_text
                    final_strategy = CompressionStage.MEMORY_SLOT_VARIABLE.value

            after_variable_tokens = self._count_slot_tokens(working_variables)
            if after_variable_tokens > settings.memory_slot_max_tokens:
                working_variables = await self._merge_historical_context(
                    trace_id=trace_id,
                    session_id=session_id,
                    message_id=message_id,
                    working_variables=working_variables,
                    action_records=action_records,
                )
                final_strategy = CompressionStage.HISTORICAL_CONTEXT_MERGE.value

            after_merge_tokens = self._count_slot_tokens(working_variables)
            if after_merge_tokens > settings.memory_slot_max_tokens:
                working_variables = self._force_hard_truncate_historical_context(
                    trace_id=trace_id,
                    session_id=session_id,
                    message_id=message_id,
                    working_variables=working_variables,
                    action_records=action_records,
                )
                final_strategy = CompressionStage.HARD_TRUNCATION.value

            updated_variables.update(working_variables)
            after_tokens = self._count_slot_tokens(self._extract_memory_slot_variables(updated_variables))
            logger.info(
                f"memory 槽位压缩治理完成 trace_id={trace_id} session_id={session_id} message_id={message_id} "
                f"before_tokens={before_tokens} after_tokens={after_tokens} final_strategy={final_strategy}"
            )
            return CompressionGovernanceResult(
                updated_variables=updated_variables,
                action_records=action_records,
                before_tokens=before_tokens,
                after_tokens=after_tokens,
                skipped=False,
                final_strategy=final_strategy,
            )
        except Exception as exc:
            logger.error(
                f"memory 槽位压缩治理异常，已降级使用原始变量 trace_id={trace_id} session_id={session_id} "
                f"message_id={message_id} error={exc}"
            )
            return CompressionGovernanceResult(
                updated_variables=updated_variables,
                action_records=action_records,
                before_tokens=before_tokens,
                after_tokens=before_tokens,
                skipped=False,
                final_strategy="error_fallback",
            )

    def _extract_memory_slot_variables(self, prompt_variables: dict[str, str]) -> dict[str, str]:
        """
        提取 memory 槽位相关变量。

        做什么：从完整 Prompt 变量映射中只提取当前需要治理的大文本变量。
        为什么这样做：system/runtime 变量不应参与本轮压缩治理。
        输入输出：输入完整变量映射，输出 memory 槽位子集。
        边界条件：不存在的键自动补空字符串，保证后续逻辑可预测。
        异常行为：本函数不主动抛业务异常。
        """
        return {key: self._normalize_text(prompt_variables.get(key, "")) for key in MEMORY_SLOT_VARIABLE_KEYS}

    def _apply_deterministic_reduction(self, variables: dict[str, str]) -> dict[str, str]:
        """
        执行确定性冗余过滤。

        做什么：依次执行空值过滤、完全重复过滤和包含关系过滤。
        为什么这样做：先用低风险、可解释的确定性策略削减冗余，再动用模型压缩。
        输入输出：输入 memory 槽位变量，输出去重后的变量映射。
        边界条件：保留首个出现的长文本，后续重复或被完整覆盖文本清空。
        异常行为：本函数不主动抛业务异常。
        """
        reduced = {key: self._normalize_text(value) for key, value in variables.items()}
        seen_values: dict[str, str] = {}
        for key in MEMORY_SLOT_VARIABLE_KEYS:
            value = reduced.get(key, "")
            if not value:
                reduced[key] = ""
                continue
            existing_key = seen_values.get(value)
            if existing_key is not None:
                reduced[key] = ""
                continue
            seen_values[value] = key

        for key in MEMORY_SLOT_VARIABLE_KEYS:
            value = reduced.get(key, "")
            if not value:
                continue
            for other_key in MEMORY_SLOT_VARIABLE_KEYS:
                if other_key == key:
                    continue
                other_value = reduced.get(other_key, "")
                if not other_value:
                    continue
                if len(other_value) > len(value) and value in other_value:
                    reduced[key] = ""
                    break
        return reduced

    async def _compress_single_variable(
        self,
        *,
        trace_id: str,
        session_id: str,
        message_id: str,
        variable_key: str,
        variable_text: str,
        action_records: list[CompressionActionRecord],
    ) -> str:
        """
        压缩单个超限变量。

        做什么：对单个超出阈值的 memory 槽位变量调用小模型生成压缩文本，并记录审计与 Span。
        为什么这样做：保留现有 Prompt 变量结构不变，优先定位是哪一类上下文导致膨胀。
        输入输出：输入变量名和原始文本，输出压缩后文本；失败时返回原始文本。
        边界条件：模型返回空字符串视为失败，不应用空结果覆盖原文。
        异常行为：模型调用异常只记录审计失败并返回原文。
        """
        stage = CompressionStage.MEMORY_SLOT_VARIABLE
        scope = VARIABLE_SCOPE_MAPPING[variable_key]
        source_keys = [variable_key]
        start_monotonic = monotonic()
        raw_tokens = count_tokens(variable_text)
        trigger_timestamp_ms = current_timestamp_ms()
        events = [
            self._build_event(COMPRESSION_EVENT_TRIGGERED, trigger_timestamp_ms, f"变量 {variable_key} 超过单变量阈值"),
            self._build_event(
                COMPRESSION_EVENT_INPUT_MEASURED,
                current_timestamp_ms(),
                f"测量变量 {variable_key} 压缩前 Token",
                {"raw_tokens": raw_tokens},
            ),
        ]
        prompt = VARIABLE_SUMMARIZE_PROMPT_TEMPLATE.format(
            variable_label=VARIABLE_LABEL_MAPPING[variable_key],
            text=variable_text,
        )
        try:
            summary_text = await compression_llm_client.summarize(
                messages=[{"role": Role.USER.value, "content": prompt}],
                response_format={"type": "text"},
                timeout=VARIABLE_SUMMARIZE_TIMEOUT_SECONDS,
            )
            summary_text = self._normalize_text(summary_text)
            if not summary_text:
                raise RuntimeError(f"变量压缩结果为空 variable_key={variable_key}")
            after_summary_tokens = count_tokens(summary_text)
            events.extend(
                [
                    self._build_event(COMPRESSION_EVENT_EXECUTED, current_timestamp_ms(), f"变量 {variable_key} 压缩模型执行完成"),
                    self._build_event(
                        COMPRESSION_EVENT_OUTPUT_MEASURED,
                        current_timestamp_ms(),
                        f"测量变量 {variable_key} 压缩后 Token",
                        {"after_summary_tokens": after_summary_tokens},
                    ),
                    self._build_event(COMPRESSION_EVENT_APPLIED, current_timestamp_ms(), f"变量 {variable_key} 压缩结果已应用"),
                    self._build_event(COMPRESSION_EVENT_COMPLETED, current_timestamp_ms(), f"变量 {variable_key} 压缩完成"),
                ]
            )
            payload = create_compression_audit_payload(
                trace_id=trace_id,
                session_id=session_id,
                message_id=message_id,
                stage=stage,
                scope=scope,
                trigger_reason=CompressionTriggerReason.SINGLE_VARIABLE_TOKEN_OVER_LIMIT,
                source_keys=source_keys,
                before_text=variable_text,
                after_text=summary_text,
                raw_tokens=raw_tokens,
                after_summary_tokens=after_summary_tokens,
                final_tokens=after_summary_tokens,
                is_success=True,
                events=events,
                timestamp_ms=trigger_timestamp_ms,
            )
            duration_ms = max(1, int((monotonic() - start_monotonic) * 1000))
            self._record_action(payload, COMPRESSION_STATUS_SUCCESS, duration_ms, action_records)
            return summary_text
        except Exception as exc:
            events.append(self._build_event(COMPRESSION_EVENT_FAILED, current_timestamp_ms(), f"变量 {variable_key} 压缩失败", {"error": str(exc)}))
            payload = create_compression_audit_payload(
                trace_id=trace_id,
                session_id=session_id,
                message_id=message_id,
                stage=stage,
                scope=scope,
                trigger_reason=CompressionTriggerReason.SINGLE_VARIABLE_TOKEN_OVER_LIMIT,
                source_keys=source_keys,
                before_text=variable_text,
                after_text=variable_text,
                raw_tokens=raw_tokens,
                final_tokens=raw_tokens,
                is_success=False,
                failure_reason=str(exc),
                events=events,
                timestamp_ms=trigger_timestamp_ms,
            )
            duration_ms = max(1, int((monotonic() - start_monotonic) * 1000))
            self._record_action(payload, COMPRESSION_STATUS_FAILED, duration_ms, action_records)
            logger.warning(
                f"memory 槽位单变量压缩失败，已保留原文 trace_id={trace_id} session_id={session_id} "
                f"message_id={message_id} variable_key={variable_key} error={exc}"
            )
            return variable_text

    async def _merge_historical_context(
        self,
        *,
        trace_id: str,
        session_id: str,
        message_id: str,
        working_variables: dict[str, str],
        action_records: list[CompressionActionRecord],
    ) -> dict[str, str]:
        """
        执行统一历史背景降级。

        做什么：把多个历史背景类变量合并为一段统一上下文，并写回 LONG_TERM_MEMORY 变量承载。
        为什么这样做：Prompt 模板当前没有独立的 HISTORICAL_CONTEXT 占位符，最小闭环实现需复用现有变量链路。
        输入输出：输入当前变量映射，输出降级后的变量映射。
        边界条件：无可合并内容时直接返回原映射。
        异常行为：模型调用失败时记录失败审计并返回原映射，后续由硬截断保护兜底。
        """
        merge_source_keys = [key for key in MEMORY_SLOT_VARIABLE_KEYS if working_variables.get(key, "")]
        if not merge_source_keys:
            return working_variables

        merged_blocks = []
        for key in merge_source_keys:
            merged_blocks.append(f"[{VARIABLE_LABEL_MAPPING[key]}]\n{working_variables[key]}")
        merged_text = "\n\n".join(merged_blocks)
        raw_tokens = count_tokens(merged_text)
        stage = CompressionStage.HISTORICAL_CONTEXT_MERGE
        start_monotonic = monotonic()
        trigger_timestamp_ms = current_timestamp_ms()
        events = [
            self._build_event(COMPRESSION_EVENT_TRIGGERED, trigger_timestamp_ms, "memory 槽位总 Token 超过阈值，进入统一历史背景降级"),
            self._build_event(
                COMPRESSION_EVENT_INPUT_MEASURED,
                current_timestamp_ms(),
                "测量统一历史背景合并前 Token",
                {"raw_tokens": raw_tokens, "source_keys": merge_source_keys},
            ),
        ]
        prompt = HISTORICAL_CONTEXT_PROMPT_TEMPLATE.format(text=merged_text)
        try:
            summary_text = await compression_llm_client.summarize(
                messages=[{"role": Role.USER.value, "content": prompt}],
                response_format={"type": "text"},
                timeout=VARIABLE_SUMMARIZE_TIMEOUT_SECONDS,
            )
            summary_text = self._normalize_text(summary_text)
            if not summary_text:
                raise RuntimeError("统一历史背景压缩结果为空")
            final_tokens = count_tokens(summary_text)
            next_variables = dict(working_variables)
            for key in merge_source_keys:
                next_variables[key] = ""
            next_variables[HISTORICAL_CONTEXT_TARGET_KEY] = summary_text
            events.extend(
                [
                    self._build_event(COMPRESSION_EVENT_EXECUTED, current_timestamp_ms(), "统一历史背景压缩模型执行完成"),
                    self._build_event(
                        COMPRESSION_EVENT_OUTPUT_MEASURED,
                        current_timestamp_ms(),
                        "测量统一历史背景压缩后 Token",
                        {"after_summary_tokens": final_tokens},
                    ),
                    self._build_event(COMPRESSION_EVENT_APPLIED, current_timestamp_ms(), "统一历史背景已写回 LONG_TERM_MEMORY 变量"),
                    self._build_event(COMPRESSION_EVENT_COMPLETED, current_timestamp_ms(), "统一历史背景降级完成"),
                ]
            )
            payload = create_compression_audit_payload(
                trace_id=trace_id,
                session_id=session_id,
                message_id=message_id,
                stage=stage,
                scope=CompressionScope.HISTORICAL_CONTEXT,
                trigger_reason=CompressionTriggerReason.MEMORY_SLOT_TOKEN_OVER_LIMIT,
                source_keys=merge_source_keys,
                before_text=merged_text,
                after_text=summary_text,
                raw_tokens=raw_tokens,
                after_summary_tokens=final_tokens,
                final_tokens=final_tokens,
                is_success=True,
                events=events,
                timestamp_ms=trigger_timestamp_ms,
            )
            duration_ms = max(1, int((monotonic() - start_monotonic) * 1000))
            self._record_action(payload, COMPRESSION_STATUS_SUCCESS, duration_ms, action_records)
            return next_variables
        except Exception as exc:
            events.append(self._build_event(COMPRESSION_EVENT_FAILED, current_timestamp_ms(), "统一历史背景降级失败", {"error": str(exc)}))
            payload = create_compression_audit_payload(
                trace_id=trace_id,
                session_id=session_id,
                message_id=message_id,
                stage=stage,
                scope=CompressionScope.HISTORICAL_CONTEXT,
                trigger_reason=CompressionTriggerReason.MEMORY_SLOT_TOKEN_OVER_LIMIT,
                source_keys=merge_source_keys,
                before_text=merged_text,
                after_text=merged_text,
                raw_tokens=raw_tokens,
                final_tokens=raw_tokens,
                is_success=False,
                failure_reason=str(exc),
                events=events,
                timestamp_ms=trigger_timestamp_ms,
            )
            duration_ms = max(1, int((monotonic() - start_monotonic) * 1000))
            self._record_action(payload, COMPRESSION_STATUS_FAILED, duration_ms, action_records)
            logger.warning(
                f"统一历史背景降级失败，后续将尝试硬截断保护 trace_id={trace_id} session_id={session_id} "
                f"message_id={message_id} error={exc}"
            )
            return working_variables

    def _force_hard_truncate_historical_context(
        self,
        *,
        trace_id: str,
        session_id: str,
        message_id: str,
        working_variables: dict[str, str],
        action_records: list[CompressionActionRecord],
    ) -> dict[str, str]:
        """
        对统一历史背景执行最终硬截断保护。

        做什么：在所有压缩与合并动作后仍超限时，对承载历史背景的变量做最终 Token 级截断。
        为什么这样做：确保最终 Prompt 可控，且硬截断只作为最后兜底而非常规路径。
        输入输出：输入当前变量映射，输出截断后的变量映射。
        边界条件：优先截断 LONG_TERM_MEMORY；若为空则退回拼接所有非空 memory 变量再写回。
        异常行为：本方法不抛业务异常，任何异常都以原变量返回并记录失败审计。
        """
        stage = CompressionStage.HARD_TRUNCATION
        start_monotonic = monotonic()
        trigger_timestamp_ms = current_timestamp_ms()
        source_keys = [key for key in MEMORY_SLOT_VARIABLE_KEYS if working_variables.get(key, "")]
        base_text = working_variables.get(HISTORICAL_CONTEXT_TARGET_KEY, "")
        if not base_text:
            merged_parts = [
                f"[{VARIABLE_LABEL_MAPPING[key]}]\n{working_variables[key]}"
                for key in source_keys
                if working_variables.get(key, "")
            ]
            base_text = "\n\n".join(merged_parts)
        raw_tokens = count_tokens(base_text)
        events = [
            self._build_event(COMPRESSION_EVENT_TRIGGERED, trigger_timestamp_ms, "统一历史背景压缩后仍超限，进入硬截断保护"),
            self._build_event(
                COMPRESSION_EVENT_INPUT_MEASURED,
                current_timestamp_ms(),
                "测量硬截断前 Token",
                {"raw_tokens": raw_tokens, "source_keys": source_keys},
            ),
        ]
        try:
            truncated_text = self._truncate_text_to_token_limit(base_text, settings.historical_context_max_tokens)
            final_tokens = count_tokens(truncated_text)
            next_variables = dict(working_variables)
            for key in MEMORY_SLOT_VARIABLE_KEYS:
                next_variables[key] = ""
            next_variables[HISTORICAL_CONTEXT_TARGET_KEY] = truncated_text
            events.extend(
                [
                    self._build_event(COMPRESSION_EVENT_OUTPUT_MEASURED, current_timestamp_ms(), "测量硬截断后 Token", {"after_trim_tokens": final_tokens}),
                    self._build_event(COMPRESSION_EVENT_APPLIED, current_timestamp_ms(), "硬截断结果已应用到统一历史背景变量"),
                    self._build_event(COMPRESSION_EVENT_COMPLETED, current_timestamp_ms(), "硬截断保护完成"),
                ]
            )
            payload = create_compression_audit_payload(
                trace_id=trace_id,
                session_id=session_id,
                message_id=message_id,
                stage=stage,
                scope=CompressionScope.HISTORICAL_CONTEXT,
                trigger_reason=CompressionTriggerReason.FINAL_PROMPT_TOKEN_OVER_LIMIT,
                source_keys=source_keys or [COMPRESSION_VARIABLE_HISTORICAL_CONTEXT],
                before_text=base_text,
                after_text=truncated_text,
                raw_tokens=raw_tokens,
                after_trim_tokens=final_tokens,
                final_tokens=final_tokens,
                is_success=True,
                events=events,
                timestamp_ms=trigger_timestamp_ms,
            )
            duration_ms = max(1, int((monotonic() - start_monotonic) * 1000))
            self._record_action(payload, COMPRESSION_STATUS_SUCCESS, duration_ms, action_records)
            return next_variables
        except Exception as exc:
            events.append(self._build_event(COMPRESSION_EVENT_FAILED, current_timestamp_ms(), "硬截断保护失败", {"error": str(exc)}))
            payload = create_compression_audit_payload(
                trace_id=trace_id,
                session_id=session_id,
                message_id=message_id,
                stage=stage,
                scope=CompressionScope.HISTORICAL_CONTEXT,
                trigger_reason=CompressionTriggerReason.FINAL_PROMPT_TOKEN_OVER_LIMIT,
                source_keys=source_keys or [COMPRESSION_VARIABLE_HISTORICAL_CONTEXT],
                before_text=base_text,
                after_text=base_text,
                raw_tokens=raw_tokens,
                final_tokens=raw_tokens,
                is_success=False,
                failure_reason=str(exc),
                events=events,
                timestamp_ms=trigger_timestamp_ms,
            )
            duration_ms = max(1, int((monotonic() - start_monotonic) * 1000))
            self._record_action(payload, COMPRESSION_STATUS_FAILED, duration_ms, action_records)
            logger.warning(
                f"memory 槽位硬截断保护失败，已保留原始变量 trace_id={trace_id} session_id={session_id} "
                f"message_id={message_id} error={exc}"
            )
            return working_variables

    def _truncate_text_to_token_limit(self, text: str, max_tokens: int) -> str:
        """
        将纯文本截断到指定 Token 上限内。

        做什么：使用二分法按字符前缀查找满足 Token 上限的最大文本片段。
        为什么这样做：项目现有只提供 Token 计数，没有 tokenizer decode，二分前缀截断是最稳妥的最小闭环实现。
        输入输出：输入原始文本与最大 Token 数，输出截断后的文本。
        边界条件：max_tokens 小于等于 0 时返回空字符串；原文未超限则原样返回。
        异常行为：本函数不主动抛业务异常。
        """
        normalized_text = self._normalize_text(text)
        if max_tokens <= 0 or not normalized_text:
            return ""
        if count_tokens(normalized_text) <= max_tokens:
            return normalized_text

        left = 0
        right = len(normalized_text)
        best = ""
        while left <= right:
            middle = (left + right) // 2
            candidate = normalized_text[:middle].strip()
            candidate_tokens = count_tokens(candidate) if candidate else 0
            if candidate_tokens <= max_tokens:
                best = candidate
                left = middle + 1
            else:
                right = middle - 1
        return best

    def _count_slot_tokens(self, variables: dict[str, str]) -> int:
        """
        统计 memory 槽位总 Token 数。

        做什么：对 memory 槽位所有候选变量逐一计算 Token 并累加。
        为什么这样做：压缩治理入口基于总量阈值触发，必须先统一口径测量。
        输入输出：输入变量映射，输出总 Token 数。
        边界条件：空字符串记为 0。
        异常行为：本函数不主动抛业务异常。
        """
        return sum(count_tokens(value) for value in variables.values() if value)

    def _normalize_text(self, value: str | None) -> str:
        """
        标准化文本值。

        做什么：把 None 转为空字符串，并清理首尾空白。
        为什么这样做：避免后续 Token 统计和字符串比较因空值类型不一致而出现分支污染。
        输入输出：输入可空字符串，输出标准化字符串。
        边界条件：非字符串值由调用方提前控制，本函数只处理 str | None。
        异常行为：本函数不主动抛业务异常。
        """
        if value is None:
            return ""
        return value.strip()

    def _record_action(
        self,
        payload,
        status: str,
        duration_ms: int,
        action_records: list[CompressionActionRecord],
    ) -> None:
        """
        统一记录压缩动作。

        做什么：同时把压缩动作写入返回结果列表、审计日志和 Span 链路。
        为什么这样做：保证聊天主链路中的所有压缩动作都能形成“记录 + 存储 + 查询 + 回放”的完整闭环。
        输入输出：输入审计载荷、状态与耗时，无返回值。
        边界条件：审计/Span 写入失败由底层 helper 降级处理，不在此处重复吞错。
        异常行为：本函数不主动抛业务异常。
        """
        action_records.append(CompressionActionRecord(payload=payload, status=status))
        record_compression_audit_payload(payload, status=status)
        record_compression_span(payload, duration_ms=duration_ms, status=status)

    def _build_event(
        self,
        event_type: str,
        timestamp_ms: int,
        detail: str,
        payload: dict | None = None,
    ) -> CompressionActionEvent:
        """
        构建压缩动作事件。

        做什么：统一封装阶段事件，避免各动作手工拼装字段不一致。
        为什么这样做：回放时间线需要稳定的事件结构。
        输入输出：输入事件类型、时间戳、说明和可选载荷，输出 CompressionActionEvent。
        边界条件：payload 为空时使用空字典。
        异常行为：字段校验失败时由 Pydantic 抛出异常。
        """
        return CompressionActionEvent(
            event_type=event_type,
            timestamp_ms=timestamp_ms,
            detail=detail,
            payload=payload or {},
        )
