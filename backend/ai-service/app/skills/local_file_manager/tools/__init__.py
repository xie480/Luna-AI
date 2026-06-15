"""
Local File Manager 工具模块导出。

做什么：统一导出所有 6 个工具的参数 Schema 和 Handler。
"""

from app.skills.local_file_manager.base import (
    ALL_TOOL_NAMES,
    TOOL_NAME_CREATE_WRITE,
    TOOL_NAME_DELETE_FILE,
    TOOL_NAME_LIST_DIRECTORY,
    TOOL_NAME_MOVE_RENAME,
    TOOL_NAME_READ_METADATA,
    TOOL_NAME_SEARCH_FILES,
)

from .list_directory import (
    PARAMETER_SCHEMA as LIST_DIRECTORY_SCHEMA,
    handle_list_directory,
)
from .read_file_metadata import (
    PARAMETER_SCHEMA as READ_METADATA_SCHEMA,
    handle_read_file_metadata,
)
from .search_files_global import (
    PARAMETER_SCHEMA as SEARCH_FILES_SCHEMA,
    handle_search_files_global,
)
from .move_or_rename_file import (
    PARAMETER_SCHEMA as MOVE_RENAME_SCHEMA,
    handle_move_or_rename_file,
)
from .create_or_write_file import (
    PARAMETER_SCHEMA as CREATE_WRITE_SCHEMA,
    handle_create_or_write_file,
)
from .delete_local_file import (
    PARAMETER_SCHEMA as DELETE_FILE_SCHEMA,
    handle_delete_local_file,
)


# 工具参数 Schema 映射（按工具名索引）
TOOL_PARAMETER_SCHEMAS: dict[str, object] = {
    TOOL_NAME_LIST_DIRECTORY: LIST_DIRECTORY_SCHEMA,
    TOOL_NAME_READ_METADATA: READ_METADATA_SCHEMA,
    TOOL_NAME_SEARCH_FILES: SEARCH_FILES_SCHEMA,
    TOOL_NAME_MOVE_RENAME: MOVE_RENAME_SCHEMA,
    TOOL_NAME_CREATE_WRITE: CREATE_WRITE_SCHEMA,
    TOOL_NAME_DELETE_FILE: DELETE_FILE_SCHEMA,
}

# 工具 Handler 映射（按工具名索引）
TOOL_HANDLERS: dict[str, object] = {
    TOOL_NAME_LIST_DIRECTORY: handle_list_directory,
    TOOL_NAME_READ_METADATA: handle_read_file_metadata,
    TOOL_NAME_SEARCH_FILES: handle_search_files_global,
    TOOL_NAME_MOVE_RENAME: handle_move_or_rename_file,
    TOOL_NAME_CREATE_WRITE: handle_create_or_write_file,
    TOOL_NAME_DELETE_FILE: handle_delete_local_file,
}


__all__ = [
    "ALL_TOOL_NAMES",
    "TOOL_PARAMETER_SCHEMAS",
    "TOOL_HANDLERS",
    "handle_list_directory",
    "handle_read_file_metadata",
    "handle_search_files_global",
    "handle_move_or_rename_file",
    "handle_create_or_write_file",
    "handle_delete_local_file",
]
