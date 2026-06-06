import json
import logging
import os
import re
import sys
from contextvars import ContextVar
from typing import Any

from loguru import logger

# 创建一个上下文变量，用于存储 trace_id
trace_id_var: ContextVar[str] = ContextVar("trace_id", default="UNKNOWN")

# 敏感信息脱敏正则
SENSITIVE_PATTERNS = [
    (re.compile(r"sk-[a-zA-Z0-9]{32,}"), "[REDACTED_API_KEY]"),
    (re.compile(r"Bearer\s+[a-zA-Z0-9\-\._~+/]+"), "Bearer [REDACTED_TOKEN]"),
]

# Windows 控制台设备文件句柄（绕过 Uvicorn Reload 的 stdout 管道丢失问题）
_CONSOLE_HANDLE: Any = None


def _get_console_encoding() -> str:
    """
    获取 Windows 控制台的实际输出代码页编码。

    做什么：查询 Windows 控制台的 GetConsoleOutputCP() 返回值，
            确定终端实际使用的编码（通常为 cp936/GBK）。
            日志中若包含中文，使用 utf-8 写入 CONOUT$ 会导致乱码，
            因为终端按系统代码页（如 cp936）解码收到的字节流。
    为什么这样做：保证中文日志在 Windows 终端正常显示，不出现乱码。
    """
    if os.name == "nt":
        try:
            import ctypes
            cp = ctypes.windll.kernel32.GetConsoleOutputCP()
            if cp:
                return f"cp{cp}"
        except Exception as exc:
            sys.stderr.write(f"警告: 控制台编码探测失败，使用 utf-8。error={exc}\n")
    return "utf-8"


def _get_console_handle():
    """
    获取 Windows 控制台设备句柄。

    做什么：在 Windows 下直接打开 CONOUT$ 设备文件，绕过 Uvicorn WatchFiles
            Reloader 对 sys.stdout 的管道重定向。当子进程的 stdout 通过管道
            传递给父进程时，管道在 async 事件循环中可能进入阻塞态，导致日志
            丢失。CONOUT$ 是 Windows 内核原生支持的物理控制台设备，不受
            subprocess.PIPE 影响。
    为什么这样做：解决 Uvicorn reload=True 在 Windows 下子进程日志无法实时
                 输出的问题。启动阶段日志可通过管道输出，但请求处理期间管道
                 缓冲区不可用。直接写 CONOUT$ 可 100% 保障日志实时输出。
    边界条件：
        - 仅在 Windows 且存在 CONOUT$ 设备时生效
        - 如果打开失败（如无控制台），回退到 sys.stdout
        - macOS/Linux 不使用此机制，因为不存在 CONOUT$ 设备
    """
    global _CONSOLE_HANDLE
    if _CONSOLE_HANDLE is not None:
        return _CONSOLE_HANDLE

    # 仅在 Windows 环境下尝试打开 CONOUT$
    if os.name == "nt":
        try:
            # 获取控制台实际编码（cp936/GBK），保证中文日志正常显示
            encoding = _get_console_encoding()
            # CONOUT$ 是 Windows 内核设备文件，代表当前进程的控制台输出缓冲区
            # 使用 os.open 而非 open()，避免缓冲和编码问题
            handle = os.open("CONOUT$", os.O_WRONLY | os.O_BINARY)
            # 包装为文本写入流，enable=True 表示写入时进行行结束符转换（\n -> \r\n）
            _CONSOLE_HANDLE = os.fdopen(handle, "w", encoding=encoding, errors="replace", buffering=1)
            return _CONSOLE_HANDLE
        except Exception as exc:
            # 如果失败（如无控制台），回退到 sys.stderr，不阻塞启动
            _CONSOLE_HANDLE = sys.stderr
            sys.stderr.write(f"警告: CONOUT$ 打开失败，日志回退到 sys.stderr。error={exc}\n")

    # 非 Windows 环境直接使用 sys.stdout
    _CONSOLE_HANDLE = sys.stdout
    return _CONSOLE_HANDLE


def sanitize_message(msg: str) -> str:
    """对日志消息进行脱敏"""
    if not isinstance(msg, str):
        return msg
    for pattern, replacement in SENSITIVE_PATTERNS:
        msg = pattern.sub(replacement, msg)
    return msg

def format_record(record: dict[str, Any]) -> str:
    """自定义 JSON 格式化器"""
    # 提取上下文中的 trace_id
    trace_id = record["extra"].get("trace_id", trace_id_var.get())
    parent_span_id = record["extra"].get("parent_span_id", "")

    log_record = {
        "timestamp": record["time"].isoformat(),
        "level": record["level"].name,
        "trace_id": trace_id,
        "parent_span_id": parent_span_id,
        "module": record["name"],
        "message": sanitize_message(record["message"]),
    }

    if record["exception"]:
        log_record["exc_info"] = str(record["exception"])

    # 将 extra 中的其他字段也加入日志
    for key, value in record["extra"].items():
        if key not in ["trace_id", "parent_span_id"]:
            log_record[key] = sanitize_message(str(value))

    record["extra"]["json_str"] = json.dumps(log_record, ensure_ascii=False)
    return "{extra[json_str]}\n"

class InterceptHandler(logging.Handler):
    """拦截标准 logging 并路由到 loguru"""
    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )

def setup_logger(level: str = "INFO") -> Any:
    """
    初始化全局日志

    做什么：配置并返回 loguru logger 实例。
    为什么这样做：统一 Python 服务的日志格式，确保所有日志都以 JSON 格式输出，
                 并包含 trace_id，同时进行脱敏。在 Windows 下使用 CONOUT$ 设备
                 直写绕过 Uvicorn Reload 的 stdout 管道丢失问题。
    输入输出：输入日志级别字符串（如 "INFO"），输出配置好的 logger 对象。
    边界条件：
        - 移除默认的 handler，添加自定义的 JSON handler
        - console handler 使用 CONOUT$ 直写（Windows）
        - 文件 handler 保持异步写入
    异常行为：
        - CONOUT$ 打开失败时自动回退到 sys.stderr
        - 回退后日志不丢失，仅可能受缓冲影响
    """
    # 移除默认的 handler
    logger.remove()

    # 获取控制台输出句柄（Windows 下使用 CONOUT$ 直写）
    console_output = _get_console_handle()

    # 控制台 handler：使用 CONOUT$ 直写（Windows）或 stdout（其他平台）
    logger.add(
        console_output,
        format=format_record,
        level=level.upper(),
        enqueue=True,           # 开启异步写入，防止 CONOUT$ 阻塞事件循环
        catch=True,             # 捕获写入异常，防止日志写入失败导致业务中断
        colorize=False,         # 关闭 ANSI 颜色避免控制台乱码
    )

    # 文件 handler：异步写入，保存完整日志记录供调试追溯
    logger.add(
        "luna_ai_debug.log",
        format=format_record,
        level=level.upper(),
        enqueue=True,           # 文件写入保持异步，不影响性能
        rotation="50 MB",       # 单文件 50MB 后自动轮转
        retention=5,            # 保留最近 5 个文件
    )

    # 拦截标准 logging
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)

    return logger

# 导出 logger 供其他模块使用
# 其他模块可以直接 from app.logger import logger
