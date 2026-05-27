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
    __slots__ = ("role", "content")
    ROLE_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    role: str
    content: str
    def __init__(self, role: _Optional[str] = ..., content: _Optional[str] = ...) -> None: ...

class ChatRequest(_message.Message):
    __slots__ = ("trace_id", "message", "history", "system_prompt", "core_summary", "key_facts")
    TRACE_ID_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    HISTORY_FIELD_NUMBER: _ClassVar[int]
    SYSTEM_PROMPT_FIELD_NUMBER: _ClassVar[int]
    CORE_SUMMARY_FIELD_NUMBER: _ClassVar[int]
    KEY_FACTS_FIELD_NUMBER: _ClassVar[int]
    trace_id: str
    message: str
    history: _containers.RepeatedCompositeFieldContainer[ChatMessage]
    system_prompt: str
    core_summary: str
    key_facts: str
    def __init__(self, trace_id: _Optional[str] = ..., message: _Optional[str] = ..., history: _Optional[_Iterable[_Union[ChatMessage, _Mapping]]] = ..., system_prompt: _Optional[str] = ..., core_summary: _Optional[str] = ..., key_facts: _Optional[str] = ...) -> None: ...

class SummarizeContextRequest(_message.Message):
    __slots__ = ("trace_id", "current_core_summary", "current_key_facts", "messages_to_compress")
    TRACE_ID_FIELD_NUMBER: _ClassVar[int]
    CURRENT_CORE_SUMMARY_FIELD_NUMBER: _ClassVar[int]
    CURRENT_KEY_FACTS_FIELD_NUMBER: _ClassVar[int]
    MESSAGES_TO_COMPRESS_FIELD_NUMBER: _ClassVar[int]
    trace_id: str
    current_core_summary: str
    current_key_facts: str
    messages_to_compress: _containers.RepeatedCompositeFieldContainer[ChatMessage]
    def __init__(self, trace_id: _Optional[str] = ..., current_core_summary: _Optional[str] = ..., current_key_facts: _Optional[str] = ..., messages_to_compress: _Optional[_Iterable[_Union[ChatMessage, _Mapping]]] = ...) -> None: ...

class SummarizeContextResponse(_message.Message):
    __slots__ = ("trace_id", "new_core_summary", "new_key_facts")
    TRACE_ID_FIELD_NUMBER: _ClassVar[int]
    NEW_CORE_SUMMARY_FIELD_NUMBER: _ClassVar[int]
    NEW_KEY_FACTS_FIELD_NUMBER: _ClassVar[int]
    trace_id: str
    new_core_summary: str
    new_key_facts: str
    def __init__(self, trace_id: _Optional[str] = ..., new_core_summary: _Optional[str] = ..., new_key_facts: _Optional[str] = ...) -> None: ...

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
