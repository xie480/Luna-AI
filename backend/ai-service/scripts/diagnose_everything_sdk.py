"""
Everything SDK 诊断脚本。

做什么：逐步检测 Everything SDK DLL 加载、服务状态和查询结果，
       定位 count=0 的根因。

用法：python scripts/diagnose_everything_sdk.py
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import os
import platform
import sys

# ============================================================
# Windows 终端编码兼容
# ============================================================
import io
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

EVERYTHING_DLL_PATH = r"D:\Everything-SDK\dll\Everything64.dll"

EVERYTHING_REQUEST_FULL_PATH_AND_FILE_NAME = 0x00000004
EVERYTHING_REQUEST_SIZE = 0x00000010
EVERYTHING_REQUEST_DATE_MODIFIED = 0x00000040

# Everything IPC 窗口消息常量
EVERYTHING_WM_USER = 0x0400
EVERYTHING_IPC_IS_EVERYTHING_RUNNING = 0x0400 + 1  # WM_USER + 1

def main() -> None:
    print("=" * 60)
    print("Everything SDK 诊断")
    print("=" * 60)

    # Step 1: 检查操作系统
    print(f"\n[1] 操作系统: {platform.system()} {platform.architecture()}")
    if platform.system() != "Windows":
        print("    ✗ 非 Windows 系统，Everything SDK 不可用")
        return

    # Step 2: 检查 DLL 文件
    print(f"\n[2] DLL 路径: {EVERYTHING_DLL_PATH}")
    if not os.path.isfile(EVERYTHING_DLL_PATH):
        print("    ✗ DLL 文件不存在")
        return
    print("    ✓ DLL 文件存在")

    # Step 3: 检查 Everything 进程
    print("\n[3] Everything 进程检测:")
    try:
        # 使用 Windows API 查找 Everything IPC 窗口
        hwnd = ctypes.windll.user32.FindWindowW("EVERYTHING_TASKBAR_NOTIFICATION", None)
        if hwnd:
            print(f"    ✓ Everything IPC 窗口存在 (hwnd={hwnd})，服务正在运行")
        else:
            print("    ✗ Everything IPC 窗口不存在，Everything 搜索服务未运行！")
            print("    → 这就是 count=0 的根因。请启动 Everything 搜索服务。")
    except Exception as exc:
        print(f"    ⚠ 窗口检测异常: {exc}")

    # Step 4: 加载 DLL
    print(f"\n[4] 加载 DLL:")
    try:
        dll = ctypes.WinDLL(EVERYTHING_DLL_PATH)
        print("    ✓ DLL 加载成功")
    except Exception as exc:
        print(f"    ✗ DLL 加载失败: {exc}")
        return

    # Step 5: 绑定函数
    print("\n[5] 绑定 SDK 函数:")
    try:
        dll.Everything_SetSearchW.argtypes = [ctypes.wintypes.LPCWSTR]
        dll.Everything_SetRequestFlags.argtypes = [ctypes.wintypes.DWORD]
        dll.Everything_SetMax.argtypes = [ctypes.wintypes.DWORD]
        dll.Everything_QueryW.argtypes = [ctypes.wintypes.BOOL]
        dll.Everything_QueryW.restype = ctypes.wintypes.BOOL
        dll.Everything_GetNumResults.restype = ctypes.wintypes.DWORD
        dll.Everything_GetResultFullPathNameW.argtypes = [
            ctypes.wintypes.DWORD, ctypes.wintypes.LPWSTR, ctypes.wintypes.DWORD
        ]
        dll.Everything_GetResultSize.argtypes = [
            ctypes.wintypes.DWORD, ctypes.POINTER(ctypes.c_uint64)
        ]
        dll.Everything_GetResultDateModified.argtypes = [
            ctypes.wintypes.DWORD, ctypes.POINTER(ctypes.c_uint64)
        ]
        print("    ✓ 所有函数绑定成功")
    except Exception as exc:
        print(f"    ✗ 函数绑定失败: {exc}")
        return

    # Step 6: 执行简单查询（不带盘符过滤）
    print("\n[6] 查询测试 1 - 搜索 '*.*'（无盘符限制）:")
    dll.Everything_SetSearchW("*.*")
    dll.Everything_SetRequestFlags(EVERYTHING_REQUEST_FULL_PATH_AND_FILE_NAME)
    dll.Everything_SetMax(5)
    query_ok = dll.Everything_QueryW(True)
    print(f"    QueryW 返回: {query_ok}")
    num = dll.Everything_GetNumResults()
    print(f"    结果数: {num}")

    if num > 0:
        path_buf = ctypes.create_unicode_buffer(32768)
        for i in range(min(num, 3)):
            dll.Everything_GetResultFullPathNameW(i, path_buf, 32768)
            print(f"    [{i}] {path_buf.value}")
    else:
        print("    → 结果为 0，Everything 服务可能未运行或未建立索引")

    # Step 7: 测试带盘符的查询
    print("\n[7] 查询测试 2 - 搜索 'E:\\ *.py'（带盘符）:")
    dll.Everything_SetSearchW(r"E:\ *.py")
    dll.Everything_SetMax(5)
    query_ok = dll.Everything_QueryW(True)
    print(f"    QueryW 返回: {query_ok}")
    num = dll.Everything_GetNumResults()
    print(f"    结果数: {num}")

    if num > 0:
        path_buf = ctypes.create_unicode_buffer(32768)
        for i in range(min(num, 3)):
            dll.Everything_GetResultFullPathNameW(i, path_buf, 32768)
            print(f"    [{i}] {path_buf.value}")

    # Step 8: 测试不带反斜杠的盘符查询（旧版 Bug）
    print("\n[8] 查询测试 3 - 搜索 'E: *.py'（不带反斜杠，旧版代码）:")
    dll.Everything_SetSearchW("E: *.py")
    dll.Everything_SetMax(5)
    query_ok = dll.Everything_QueryW(True)
    print(f"    QueryW 返回: {query_ok}")
    num = dll.Everything_GetNumResults()
    print(f"    结果数: {num}")

    # Step 9: 总结
    print("\n" + "=" * 60)
    print("诊断总结:")
    if not hwnd:
        print("  根因: Everything 搜索服务 (Everything.exe) 未运行。")
        print("  解决: 启动 Everything 软件后重新测试。")
        print("  代码层面: 建议在 _search_everything_sync 中增加 IPC 窗口检测，")
        print("           服务未运行时直接回退到 scandir 引擎，避免无意义的 SDK 调用。")
    else:
        print("  Everything 服务正在运行，但查询返回 0。")
        print("  可能原因: Everything 未建立 E: 盘索引，或 DLL 版本不匹配。")
    print("=" * 60)


if __name__ == "__main__":
    main()
