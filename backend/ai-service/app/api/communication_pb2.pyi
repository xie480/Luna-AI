from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class PingRequest(_message.Message):
    __slots__ = ("trace_id", "timestamp")
    TRACE_ID_FIELD_NUMBER: _ClassVar[int]
    TIMESTAMP_FIELD_NUMBER: _ClassVar[int]
    trace_id: str
    timestamp: int
    def __init__(self, trace_id: _Optional[str] = ..., timestamp: _Optional[int] = ...) -> None: ...

class PongResponse(_message.Message):
    __slots__ = ("trace_id", "timestamp", "source")
    TRACE_ID_FIELD_NUMBER: _ClassVar[int]
    TIMESTAMP_FIELD_NUMBER: _ClassVar[int]
    SOURCE_FIELD_NUMBER: _ClassVar[int]
    trace_id: str
    timestamp: int
    source: str
    def __init__(self, trace_id: _Optional[str] = ..., timestamp: _Optional[int] = ..., source: _Optional[str] = ...) -> None: ...

class ChatMessage(_message.Message):
    __slots__ = ("role", "content", "is_error", "error_details")
    ROLE_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    IS_ERROR_FIELD_NUMBER: _ClassVar[int]
    ERROR_DETAILS_FIELD_NUMBER: _ClassVar[int]
    role: str
    content: str
    is_error: bool
    error_details: str
    def __init__(self, role: _Optional[str] = ..., content: _Optional[str] = ..., is_error: bool = ..., error_details: _Optional[str] = ...) -> None: ...

class ChatRequest(_message.Message):
    __slots__ = ("trace_id", "message", "history", "system_prompt", "disambiguated_text")
    TRACE_ID_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    HISTORY_FIELD_NUMBER: _ClassVar[int]
    SYSTEM_PROMPT_FIELD_NUMBER: _ClassVar[int]
    DISAMBIGUATED_TEXT_FIELD_NUMBER: _ClassVar[int]
    trace_id: str
    message: str
    history: _containers.RepeatedCompositeFieldContainer[ChatMessage]
    system_prompt: str
    disambiguated_text: str
    def __init__(self, trace_id: _Optional[str] = ..., message: _Optional[str] = ..., history: _Optional[_Iterable[_Union[ChatMessage, _Mapping]]] = ..., system_prompt: _Optional[str] = ..., disambiguated_text: _Optional[str] = ...) -> None: ...

class InputReconstructionRequest(_message.Message):
    __slots__ = ("trace_id", "user_input", "system_prompt", "memory_prompt", "runtime_prompt")
    TRACE_ID_FIELD_NUMBER: _ClassVar[int]
    USER_INPUT_FIELD_NUMBER: _ClassVar[int]
    SYSTEM_PROMPT_FIELD_NUMBER: _ClassVar[int]
    MEMORY_PROMPT_FIELD_NUMBER: _ClassVar[int]
    RUNTIME_PROMPT_FIELD_NUMBER: _ClassVar[int]
    trace_id: str
    user_input: str
    system_prompt: str
    memory_prompt: str
    runtime_prompt: str
    def __init__(self, trace_id: _Optional[str] = ..., user_input: _Optional[str] = ..., system_prompt: _Optional[str] = ..., memory_prompt: _Optional[str] = ..., runtime_prompt: _Optional[str] = ...) -> None: ...

class InputReconstructionResponse(_message.Message):
    __slots__ = ("trace_id", "json_output", "success", "error_message")
    TRACE_ID_FIELD_NUMBER: _ClassVar[int]
    JSON_OUTPUT_FIELD_NUMBER: _ClassVar[int]
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    ERROR_MESSAGE_FIELD_NUMBER: _ClassVar[int]
    trace_id: str
    json_output: str
    success: bool
    error_message: str
    def __init__(self, trace_id: _Optional[str] = ..., json_output: _Optional[str] = ..., success: bool = ..., error_message: _Optional[str] = ...) -> None: ...

class ShortSummarizeRequest(_message.Message):
    __slots__ = ("trace_id", "summarize_prompt")
    TRACE_ID_FIELD_NUMBER: _ClassVar[int]
    SUMMARIZE_PROMPT_FIELD_NUMBER: _ClassVar[int]
    trace_id: str
    summarize_prompt: str
    def __init__(self, trace_id: _Optional[str] = ..., summarize_prompt: _Optional[str] = ...) -> None: ...

class ShortSummarizeResponse(_message.Message):
    __slots__ = ("trace_id", "new_core_summary", "new_key_facts", "new_short_term_memory")
    TRACE_ID_FIELD_NUMBER: _ClassVar[int]
    NEW_CORE_SUMMARY_FIELD_NUMBER: _ClassVar[int]
    NEW_KEY_FACTS_FIELD_NUMBER: _ClassVar[int]
    NEW_SHORT_TERM_MEMORY_FIELD_NUMBER: _ClassVar[int]
    trace_id: str
    new_core_summary: str
    new_key_facts: str
    new_short_term_memory: str
    def __init__(self, trace_id: _Optional[str] = ..., new_core_summary: _Optional[str] = ..., new_key_facts: _Optional[str] = ..., new_short_term_memory: _Optional[str] = ...) -> None: ...

class ChatStreamResponse(_message.Message):
    __slots__ = ("trace_id", "type", "chunk", "is_finished", "finish_reason", "error")
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
    def __init__(self, trace_id: _Optional[str] = ..., type: _Optional[str] = ..., chunk: _Optional[str] = ..., is_finished: bool = ..., finish_reason: _Optional[str] = ..., error: _Optional[str] = ...) -> None: ...

class ModelConfig(_message.Message):
    __slots__ = ("base_url", "api_key", "model_id", "max_tokens", "temperature", "max_context_tokens")
    BASE_URL_FIELD_NUMBER: _ClassVar[int]
    API_KEY_FIELD_NUMBER: _ClassVar[int]
    MODEL_ID_FIELD_NUMBER: _ClassVar[int]
    MAX_TOKENS_FIELD_NUMBER: _ClassVar[int]
    TEMPERATURE_FIELD_NUMBER: _ClassVar[int]
    MAX_CONTEXT_TOKENS_FIELD_NUMBER: _ClassVar[int]
    base_url: str
    api_key: str
    model_id: str
    max_tokens: int
    temperature: float
    max_context_tokens: int
    def __init__(self, base_url: _Optional[str] = ..., api_key: _Optional[str] = ..., model_id: _Optional[str] = ..., max_tokens: _Optional[int] = ..., temperature: _Optional[float] = ..., max_context_tokens: _Optional[int] = ...) -> None: ...

class SyncPresetConfigRequest(_message.Message):
    __slots__ = ("schema_version", "preset_id", "large_model", "medium_model", "small_model")
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
    def __init__(self, schema_version: _Optional[str] = ..., preset_id: _Optional[str] = ..., large_model: _Optional[_Union[ModelConfig, _Mapping]] = ..., medium_model: _Optional[_Union[ModelConfig, _Mapping]] = ..., small_model: _Optional[_Union[ModelConfig, _Mapping]] = ...) -> None: ...

class SyncPresetConfigResponse(_message.Message):
    __slots__ = ("success", "error_message")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    ERROR_MESSAGE_FIELD_NUMBER: _ClassVar[int]
    success: bool
    error_message: str
    def __init__(self, success: bool = ..., error_message: _Optional[str] = ...) -> None: ...

class LongSummarizeRequest(_message.Message):
    __slots__ = ("session_id", "summarize_prompt")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    SUMMARIZE_PROMPT_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    summarize_prompt: str
    def __init__(self, session_id: _Optional[str] = ..., summarize_prompt: _Optional[str] = ...) -> None: ...

class LongSummarizeResponse(_message.Message):
    __slots__ = ("summary",)
    SUMMARY_FIELD_NUMBER: _ClassVar[int]
    summary: str
    def __init__(self, summary: _Optional[str] = ...) -> None: ...

class EmbeddingRequest(_message.Message):
    __slots__ = ("text",)
    TEXT_FIELD_NUMBER: _ClassVar[int]
    text: str
    def __init__(self, text: _Optional[str] = ...) -> None: ...

class EmbeddingResponse(_message.Message):
    __slots__ = ("vector_json", "success", "error_message")
    VECTOR_JSON_FIELD_NUMBER: _ClassVar[int]
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    ERROR_MESSAGE_FIELD_NUMBER: _ClassVar[int]
    vector_json: str
    success: bool
    error_message: str
    def __init__(self, vector_json: _Optional[str] = ..., success: bool = ..., error_message: _Optional[str] = ...) -> None: ...

class RerankRequest(_message.Message):
    __slots__ = ("query", "documents")
    QUERY_FIELD_NUMBER: _ClassVar[int]
    DOCUMENTS_FIELD_NUMBER: _ClassVar[int]
    query: str
    documents: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, query: _Optional[str] = ..., documents: _Optional[_Iterable[str]] = ...) -> None: ...

class RerankResponse(_message.Message):
    __slots__ = ("scores", "success", "error_message")
    SCORES_FIELD_NUMBER: _ClassVar[int]
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    ERROR_MESSAGE_FIELD_NUMBER: _ClassVar[int]
    scores: _containers.RepeatedScalarFieldContainer[float]
    success: bool
    error_message: str
    def __init__(self, scores: _Optional[_Iterable[float]] = ..., success: bool = ..., error_message: _Optional[str] = ...) -> None: ...
