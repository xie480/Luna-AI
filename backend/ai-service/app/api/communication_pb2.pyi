from collections.abc import Iterable as _Iterable
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar

from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from google.protobuf.internal import containers as _containers

DESCRIPTOR: _descriptor.FileDescriptor

class PingRequest(_message.Message):
    __slots__ = ("timestamp", "trace_id")
    TRACE_ID_FIELD_NUMBER: _ClassVar[int]
    TIMESTAMP_FIELD_NUMBER: _ClassVar[int]
    trace_id: str
    timestamp: int
    def __init__(self, trace_id: str | None = ..., timestamp: int | None = ...) -> None: ...

class PongResponse(_message.Message):
    __slots__ = ("source", "timestamp", "trace_id")
    TRACE_ID_FIELD_NUMBER: _ClassVar[int]
    TIMESTAMP_FIELD_NUMBER: _ClassVar[int]
    SOURCE_FIELD_NUMBER: _ClassVar[int]
    trace_id: str
    timestamp: int
    source: str
    def __init__(self, trace_id: str | None = ..., timestamp: int | None = ..., source: str | None = ...) -> None: ...

class ChatMessage(_message.Message):
    __slots__ = ("content", "error_details", "is_error", "role")
    ROLE_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    IS_ERROR_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAILS_FIELD_NUMBER: _ClassVar[int]
    role: str
    content: str
    is_error: bool
    error_details: str
    def __init__(self, role: str | None = ..., content: str | None = ..., is_error: bool = ..., error_details: str | None = ...) -> None: ...

class ChatRequest(_message.Message):
    __slots__ = ("history", "message", "system_prompt", "trace_id")
    TRACE_ID_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    HISTORY_FIELD_NUMBER: _ClassVar[int]
    SYSTEM_PROMPT_FIELD_NUMBER: _ClassVar[int]
    trace_id: str
    message: str
    history: _containers.RepeatedCompositeFieldContainer[ChatMessage]
    system_prompt: str
    def __init__(self, trace_id: str | None = ..., message: str | None = ..., history: _Iterable[ChatMessage | _Mapping] | None = ..., system_prompt: str | None = ...) -> None: ...

class ShortSummarizeRequest(_message.Message):
    __slots__ = ("summarize_prompt", "trace_id")
    TRACE_ID_FIELD_NUMBER: _ClassVar[int]
    SUMMARIZE_PROMPT_FIELD_NUMBER: _ClassVar[int]
    trace_id: str
    summarize_prompt: str
    def __init__(self, trace_id: str | None = ..., summarize_prompt: str | None = ...) -> None: ...

class ShortSummarizeResponse(_message.Message):
    __slots__ = ("new_core_summary", "new_key_facts", "new_short_term_memory", "trace_id")
    TRACE_ID_FIELD_NUMBER: _ClassVar[int]
    NEW_CORE_SUMMARY_FIELD_NUMBER: _ClassVar[int]
    NEW_KEY_FACTS_FIELD_NUMBER: _ClassVar[int]
    NEW_SHORT_TERM_MEMORY_FIELD_NUMBER: _ClassVar[int]
    trace_id: str
    new_core_summary: str
    new_key_facts: str
    new_short_term_memory: str
    def __init__(self, trace_id: str | None = ..., new_core_summary: str | None = ..., new_key_facts: str | None = ..., new_short_term_memory: str | None = ...) -> None: ...

class ChatStreamResponse(_message.Message):
    __slots__ = ("chunk", "error", "finish_reason", "is_finished", "trace_id", "type")
    TRACE_ID_FIELD_NUMBER: _ClassVar[int]
    TYPE_FIELD_NUMBER: _ClassVar[int]
    CHUNK_FIELD_NUMBER: _ClassVar[int]
    IS_FINISHED_FIELD_NUMBER: _ClassVar[int]
    FINISH_REASON_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    trace_id: str
    type: str
    chunk: str
    is_finished: bool
    finish_reason: str
    error: str
    def __init__(self, trace_id: str | None = ..., type: str | None = ..., chunk: str | None = ..., is_finished: bool = ..., finish_reason: str | None = ..., error: str | None = ...) -> None: ...

class ModelConfig(_message.Message):
    __slots__ = ("api_key", "base_url", "max_tokens", "model_id", "temperature")
    BASE_URL_FIELD_NUMBER: _ClassVar[int]
    API_KEY_FIELD_NUMBER: _ClassVar[int]
    MODEL_ID_FIELD_NUMBER: _ClassVar[int]
    MAX_TOKENS_FIELD_NUMBER: _ClassVar[int]
    TEMPERATURE_FIELD_NUMBER: _ClassVar[int]
    base_url: str
    api_key: str
    model_id: str
    max_tokens: int
    temperature: float
    def __init__(self, base_url: str | None = ..., api_key: str | None = ..., model_id: str | None = ..., max_tokens: int | None = ..., temperature: float | None = ...) -> None: ...

class SyncPresetConfigRequest(_message.Message):
    __slots__ = ("large_model", "medium_model", "preset_id", "schema_version", "small_model")
    SCHEMA_VERSION_FIELD_NUMBER: _ClassVar[int]
    PRESET_ID_FIELD_NUMBER: _ClassVar[int]
    LARGE_MODEL_FIELD_NUMBER: _ClassVar[int]
    MEDIUM_MODEL_FIELD_NUMBER: _ClassVar[int]
    SMALL_MODEL_FIELD_NUMBER: _ClassVar[int]
    schema_version: str
    preset_id: str
    large_model: ModelConfig
    medium_model: ModelConfig
    small_model: ModelConfig
    def __init__(self, schema_version: str | None = ..., preset_id: str | None = ..., large_model: ModelConfig | _Mapping | None = ..., medium_model: ModelConfig | _Mapping | None = ..., small_model: ModelConfig | _Mapping | None = ...) -> None: ...

class SyncPresetConfigResponse(_message.Message):
    __slots__ = ("error_message", "success")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    ERROR_MESSAGE_FIELD_NUMBER: _ClassVar[int]
    success: bool
    error_message: str
    def __init__(self, success: bool = ..., error_message: str | None = ...) -> None: ...

class LongSummarizeRequest(_message.Message):
    __slots__ = ("session_id", "summarize_prompt")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    SUMMARIZE_PROMPT_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    summarize_prompt: str
    def __init__(self, session_id: str | None = ..., summarize_prompt: str | None = ...) -> None: ...

class LongSummarizeResponse(_message.Message):
    __slots__ = ("summary",)
    SUMMARY_FIELD_NUMBER: _ClassVar[int]
    summary: str
    def __init__(self, summary: str | None = ...) -> None: ...

class EmbeddingRequest(_message.Message):
    __slots__ = ("text",)
    TEXT_FIELD_NUMBER: _ClassVar[int]
    text: str
    def __init__(self, text: str | None = ...) -> None: ...

class EmbeddingResponse(_message.Message):
    __slots__ = ("error_message", "success", "vector_json")
    VECTOR_JSON_FIELD_NUMBER: _ClassVar[int]
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    ERROR_MESSAGE_FIELD_NUMBER: _ClassVar[int]
    vector_json: str
    success: bool
    error_message: str
    def __init__(self, vector_json: str | None = ..., success: bool = ..., error_message: str | None = ...) -> None: ...

class RerankRequest(_message.Message):
    __slots__ = ("documents", "query")
    QUERY_FIELD_NUMBER: _ClassVar[int]
    DOCUMENTS_FIELD_NUMBER: _ClassVar[int]
    query: str
    documents: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, query: str | None = ..., documents: _Iterable[str] | None = ...) -> None: ...

class RerankResponse(_message.Message):
    __slots__ = ("error_message", "scores", "success")
    SCORES_FIELD_NUMBER: _ClassVar[int]
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    ERROR_MESSAGE_FIELD_NUMBER: _ClassVar[int]
    scores: _containers.RepeatedScalarFieldContainer[float]
    success: bool
    error_message: str
    def __init__(self, scores: _Iterable[float] | None = ..., success: bool = ..., error_message: str | None = ...) -> None: ...
