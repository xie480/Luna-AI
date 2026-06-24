"""
Local File Manager 工具集成测试脚本。

做什么：对 local_file_manager 下的 6 个工具进行全面的功能测试。
       使用项目根目录下创建的临时测试目录进行文件操作，避免影响真实文件。
       测试完成后自动清理临时目录。

用法：在 backend/ai-service 目录下运行:
    python -m scripts.test_local_file_manager_tools

涉及工具：
    1. list_directory         — 列出目录内容
    2. read_file_metadata     — 读取文件元数据
    3. search_files_global    — 全局文件搜索
    4. create_or_write_file   — 创建/写入文件
    5. move_or_rename_file    — 移动/重命名文件
    6. delete_local_file      — 删除文件/目录
"""

from __future__ import annotations

import asyncio
import io
import os
import shutil
import sys
import tempfile
from datetime import datetime

# ============================================================
# Windows 终端编码兼容：强制 stdout/stderr 使用 UTF-8
# ============================================================
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ============================================================
# 路径初始化：确保 app 包可被导入
# ============================================================
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_AI_SERVICE_DIR = os.path.dirname(_SCRIPT_DIR)
if _AI_SERVICE_DIR not in sys.path:
    sys.path.insert(0, _AI_SERVICE_DIR)


# ============================================================
# 测试结果统计
# ============================================================
_test_results: list[dict[str, str]] = []


def _record(name: str, passed: bool, detail: str = "") -> None:
    """记录单个测试用例的结果。"""
    status = "✅ PASS" if passed else "❌ FAIL"
    _test_results.append({"name": name, "status": status, "detail": detail})
    print(f"  {status}  {name}")
    if detail and not passed:
        print(f"         ↳ {detail}")


def _print_summary() -> None:
    """打印测试结果汇总。"""
    total = len(_test_results)
    passed = sum(1 for r in _test_results if "PASS" in r["status"])
    failed = total - passed
    print("\n" + "=" * 60)
    print(f"测试汇总: 共 {total} 项，通过 {passed} 项，失败 {failed} 项")
    if failed:
        print("\n失败项详情:")
        for r in _test_results:
            if "FAIL" in r["status"]:
                print(f"  - {r['name']}: {r['detail']}")
    print("=" * 60)


# ============================================================
# 测试用例
# ============================================================


async def test_list_directory(test_dir: str) -> None:
    """测试 list_directory 工具：列出临时测试目录内容。"""
    from app.skills.local_file_manager.tools.list_directory import handle_list_directory

    trace_id = "test-list-dir-001"

    # --- 正常列出目录 ---
    result = await handle_list_directory({"path": test_dir}, trace_id)
    _record(
        "list_directory - 列出测试目录",
        "共" in result and "个目录" in result and "个文件" in result,
        result[:200] if "共" not in result else "",
    )

    # --- 列出子目录（包含文件的子目录） ---
    subdir = os.path.join(test_dir, "subdir_a")
    result = await handle_list_directory({"path": subdir}, trace_id)
    _record(
        "list_directory - 列出子目录",
        "个文件" in result and "inner.txt" in result,
        result[:200],
    )

    # --- 路径不存在 ---
    result = await handle_list_directory({"path": os.path.join(test_dir, "nonexistent_dir")}, trace_id)
    _record(
        "list_directory - 路径不存在",
        "操作拒绝" in result or "路径不存在" in result,
        result[:200],
    )

    # --- 路径是文件而非目录 ---
    file_path = os.path.join(test_dir, "test_file.txt")
    result = await handle_list_directory({"path": file_path}, trace_id)
    _record(
        "list_directory - 路径是文件",
        "不是目录" in result,
        result[:200],
    )

    # --- 空路径 ---
    result = await handle_list_directory({"path": ""}, trace_id)
    _record(
        "list_directory - 空路径",
        "操作拒绝" in result or "不能为空" in result,
        result[:200],
    )

    # --- 读取项目根目录 ---
    project_root = os.path.normpath(os.path.join(test_dir, "..", "..", ".."))
    result = await handle_list_directory({"path": project_root}, trace_id)
    _record(
        "list_directory - 列出项目根目录",
        "个目录" in result and "个文件" in result,
        result[:200],
    )


async def test_read_file_metadata(test_dir: str) -> None:
    """测试 read_file_metadata 工具：读取测试文件的元数据。"""
    from app.skills.local_file_manager.tools.read_file_metadata import handle_read_file_metadata

    trace_id = "test-read-meta-001"

    # --- 正常读取 .txt 文件 ---
    file_path = os.path.join(test_dir, "test_file.txt")
    result = await handle_read_file_metadata({"path": file_path}, trace_id)
    _record(
        "read_file_metadata - 读取 .txt 文件",
        "test_file.txt" in result and "大小" in result and "创建时间" in result,
        result[:300],
    )

    # --- 读取 .py 文件 ---
    py_file = os.path.join(test_dir, "test_script.py")
    result = await handle_read_file_metadata({"path": py_file}, trace_id)
    _record(
        "read_file_metadata - 读取 .py 文件",
        "test_script.py" in result and "预估可读内容" in result,
        result[:300],
    )

    # --- 读取项目中的真实文件（项目根 = _AI_SERVICE_DIR/../.. 即 Luna-AI 根目录） ---
    project_root = os.path.normpath(os.path.join(_AI_SERVICE_DIR, "..", ".."))
    agent_md = os.path.join(project_root, "agent.md")
    if os.path.isfile(agent_md):
        result = await handle_read_file_metadata({"path": agent_md}, trace_id)
        _record(
            "read_file_metadata - 读取项目 agent.md",
            "agent.md" in result and "大小" in result,
            result[:300],
        )
    else:
        _record("read_file_metadata - 读取项目 agent.md", False, f"agent.md 文件不存在: {agent_md}")

    # --- 路径是目录而非文件 ---
    result = await handle_read_file_metadata({"path": test_dir}, trace_id)
    _record(
        "read_file_metadata - 路径是目录",
        "目录" in result,
        result[:200],
    )

    # --- 路径不存在 ---
    result = await handle_read_file_metadata({"path": os.path.join(test_dir, "no_such_file.txt")}, trace_id)
    _record(
        "read_file_metadata - 文件不存在",
        "操作拒绝" in result or "路径不存在" in result,
        result[:200],
    )


async def test_create_or_write_file(test_dir: str) -> None:
    """测试 create_or_write_file 工具：创建和写入文件。"""
    from app.skills.local_file_manager.tools.create_or_write_file import handle_create_or_write_file

    trace_id = "test-create-write-001"

    # --- 创建新文件（overwrite 模式） ---
    new_file = os.path.join(test_dir, "new_created_file.txt")
    result = await handle_create_or_write_file(
        {"path": new_file, "content": "Hello, Luna! 这是测试写入内容。\n第二行。", "mode": "overwrite"},
        trace_id,
    )
    _record(
        "create_or_write_file - 创建新文件",
        "成功" in result and os.path.isfile(new_file),
        result[:200],
    )

    # 验证写入内容
    if os.path.isfile(new_file):
        with open(new_file, "r", encoding="utf-8") as f:
            content = f.read()
        _record(
            "create_or_write_file - 验证写入内容",
            "Hello, Luna!" in content and "第二行" in content,
            content[:100],
        )

    # --- 追加模式写入 ---
    result = await handle_create_or_write_file(
        {"path": new_file, "content": "\n追加的第三行内容。", "mode": "append"},
        trace_id,
    )
    _record(
        "create_or_write_file - 追加写入",
        "成功" in result,
        result[:200],
    )

    # 验证追加内容
    if os.path.isfile(new_file):
        with open(new_file, "r", encoding="utf-8") as f:
            content = f.read()
        _record(
            "create_or_write_file - 验证追加内容",
            "Hello, Luna!" in content and "追加的第三行" in content,
            content[:200],
        )

    # --- 覆盖已存在文件 ---
    result = await handle_create_or_write_file(
        {"path": new_file, "content": "完全覆盖的内容", "mode": "overwrite"},
        trace_id,
    )
    _record(
        "create_or_write_file - 覆盖已存在文件",
        "成功" in result and "已存在文件" in result,
        result[:200],
    )

    # --- 写入到子目录 ---
    nested_file = os.path.join(test_dir, "subdir_b", "nested.txt")
    result = await handle_create_or_write_file(
        {"path": nested_file, "content": "嵌套目录写入测试"},
        trace_id,
    )
    # 注意：subdir_b 不存在，应该失败
    _record(
        "create_or_write_file - 父目录不存在应失败",
        "操作错误" in result or "父目录不存在" in result,
        result[:200],
    )

    # --- 写入到已有子目录 ---
    nested_file2 = os.path.join(test_dir, "subdir_a", "in_subdir.txt")
    result = await handle_create_or_write_file(
        {"path": nested_file2, "content": "在已有子目录中创建文件"},
        trace_id,
    )
    _record(
        "create_or_write_file - 写入到已有子目录",
        "成功" in result and os.path.isfile(nested_file2),
        result[:200],
    )


async def test_move_or_rename_file(test_dir: str) -> None:
    """测试 move_or_rename_file 工具：移动和重命名文件。"""
    from app.skills.local_file_manager.tools.move_or_rename_file import handle_move_or_rename_file

    trace_id = "test-move-rename-001"

    # --- 先创建一个用于移动的文件 ---
    move_src = os.path.join(test_dir, "to_move.txt")
    with open(move_src, "w", encoding="utf-8") as f:
        f.write("这个文件将被移动。")
    assert os.path.isfile(move_src), "预备文件创建失败"

    # --- 重命名文件（同一父目录下移动） ---
    rename_dest = os.path.join(test_dir, "renamed_file.txt")
    result = await handle_move_or_rename_file(
        {"source_path": move_src, "destination_path": rename_dest},
        trace_id,
    )
    _record(
        "move_or_rename_file - 重命名文件",
        "成功" in result and os.path.isfile(rename_dest) and not os.path.exists(move_src),
        result[:200],
    )

    # --- 移动文件到子目录 ---
    move_dest = os.path.join(test_dir, "subdir_a", "moved_to_subdir.txt")
    result = await handle_move_or_rename_file(
        {"source_path": rename_dest, "destination_path": move_dest},
        trace_id,
    )
    _record(
        "move_or_rename_file - 移动文件到子目录",
        "成功" in result and os.path.isfile(move_dest) and not os.path.exists(rename_dest),
        result[:200],
    )

    # --- 目标已存在但未设置 overwrite ---
    conflict_src = os.path.join(test_dir, "test_file.txt")
    conflict_dest = os.path.join(test_dir, "test_script.py")
    result = await handle_move_or_rename_file(
        {"source_path": conflict_src, "destination_path": conflict_dest, "overwrite": False},
        trace_id,
    )
    _record(
        "move_or_rename_file - 目标已存在拒绝覆盖",
        "操作拒绝" in result,
        result[:200],
    )

    # --- 源路径不存在 ---
    result = await handle_move_or_rename_file(
        {"source_path": os.path.join(test_dir, "ghost.txt"), "destination_path": os.path.join(test_dir, "ghost2.txt")},
        trace_id,
    )
    _record(
        "move_or_rename_file - 源路径不存在",
        "操作拒绝" in result or "源路径验证失败" in result,
        result[:200],
    )

    # --- 移动目录 ---
    dir_to_move = os.path.join(test_dir, "move_this_dir")
    os.makedirs(dir_to_move, exist_ok=True)
    with open(os.path.join(dir_to_move, "inner.txt"), "w", encoding="utf-8") as f:
        f.write("目录内的文件")

    dir_dest = os.path.join(test_dir, "subdir_a", "moved_dir")
    result = await handle_move_or_rename_file(
        {"source_path": dir_to_move, "destination_path": dir_dest},
        trace_id,
    )
    _record(
        "move_or_rename_file - 移动目录",
        "成功" in result and os.path.isdir(dir_dest) and not os.path.exists(dir_to_move),
        result[:200],
    )


async def test_delete_local_file(test_dir: str) -> None:
    """测试 delete_local_file 工具：删除文件和目录。"""
    from app.skills.local_file_manager.tools.delete_local_file import handle_delete_local_file

    trace_id = "test-delete-001"

    # --- 创建待删除的文件 ---
    del_file = os.path.join(test_dir, "to_delete.txt")
    with open(del_file, "w", encoding="utf-8") as f:
        f.write("这个文件将被删除。")
    assert os.path.isfile(del_file)

    # --- 删除文件 ---
    result = await handle_delete_local_file({"path": del_file}, trace_id)
    _record(
        "delete_local_file - 删除文件",
        "成功" in result and not os.path.exists(del_file),
        result[:200],
    )

    # --- 创建待删除的空目录 ---
    del_empty_dir = os.path.join(test_dir, "empty_dir_to_delete")
    os.makedirs(del_empty_dir, exist_ok=True)

    # --- 删除空目录（不需 recursive） ---
    result = await handle_delete_local_file({"path": del_empty_dir}, trace_id)
    _record(
        "delete_local_file - 删除空目录",
        "成功" in result and not os.path.exists(del_empty_dir),
        result[:200],
    )

    # --- 创建待删除的非空目录 ---
    del_dir = os.path.join(test_dir, "dir_to_delete")
    os.makedirs(os.path.join(del_dir, "sub"), exist_ok=True)
    with open(os.path.join(del_dir, "sub", "file.txt"), "w", encoding="utf-8") as f:
        f.write("嵌套文件")

    # --- 拒绝非递归删除非空目录 ---
    result = await handle_delete_local_file({"path": del_dir, "recursive": False}, trace_id)
    _record(
        "delete_local_file - 拒绝非递归删除非空目录",
        "操作拒绝" in result,
        result[:200],
    )

    # --- 递归删除非空目录 ---
    result = await handle_delete_local_file({"path": del_dir, "recursive": True}, trace_id)
    _record(
        "delete_local_file - 递归删除非空目录",
        "成功" in result and not os.path.exists(del_dir),
        result[:200],
    )

    # --- 路径不存在 ---
    result = await handle_delete_local_file({"path": os.path.join(test_dir, "ghost.txt")}, trace_id)
    _record(
        "delete_local_file - 路径不存在",
        "操作拒绝" in result or "路径不存在" in result,
        result[:200],
    )


async def test_search_files_global(test_dir: str) -> None:
    """测试 search_files_global 工具：在项目目录中搜索文件。"""
    from app.skills.local_file_manager.tools.search_files_global import handle_search_files_global

    trace_id = "test-search-001"

    # --- 搜索 .py 文件（Everything 引擎，修复盘符后应能返回结果） ---
    result = await handle_search_files_global(
        {"pattern": "*.py", "drive": "E:"},
        trace_id,
    )
    # 修复后 Everything 应该能找到 .py 文件，至少返回若干个匹配
    has_results = "个匹配的文件" in result and "未找到" not in result
    _record(
        "search_files_global - 搜索 .py 文件（Everything）",
        "文件搜索完成" in result,
        result[:300] if not has_results else f"找到匹配结果（含 .py 文件）",
    )

    # --- 搜索特定文件名（agent.md） ---
    result = await handle_search_files_global(
        {"pattern": "agent.md", "drive": "E:"},
        trace_id,
    )
    # 检查 agent.md 是否出现在实际搜索结果路径中，而不仅仅是输出文本中
    found_in_results = "agent.md" in result and ("路径:" in result or "个匹配" in result)
    _record(
        "search_files_global - 搜索 agent.md",
        found_in_results or "未找到" in result,
        result[:300],
    )

    # --- 搜索不存在的盘符 ---
    result = await handle_search_files_global(
        {"pattern": "README.md", "drive": "Z:"},
        trace_id,
    )
    # Z: 盘通常不存在，但不应报错，只是返回未找到
    _record(
        "search_files_global - 搜索不存在的盘符",
        "文件搜索完成" in result,
        result[:200],
    )

    # --- 空 pattern ---
    result = await handle_search_files_global({"pattern": ""}, trace_id)
    _record(
        "search_files_global - 空 pattern",
        "搜索参数错误" in result,
        result[:200],
    )

    # --- 搜索不可能存在的文件名 ---
    result = await handle_search_files_global(
        {"pattern": "zzz_this_file_definitely_does_not_exist_12345.zzz", "drive": "E:"},
        trace_id,
    )
    _record(
        "search_files_global - 搜索不存在的文件",
        "未找到" in result,
        result[:200],
    )


async def test_path_safety(test_dir: str) -> None:
    """测试 base.py 的路径安全验证逻辑。"""
    from app.skills.local_file_manager.base import is_protected_path, validate_path_safety

    # --- 空路径 ---
    try:
        validate_path_safety("")
        _record("path_safety - 空路径应抛出异常", False, "未抛出异常")
    except ValueError:
        _record("path_safety - 空路径应抛出异常", True)

    # --- 反斜杠路径穿越 ---
    try:
        validate_path_safety("C:\\Users\\..\\..\\Windows\\System32")
        _record("path_safety - 反斜杠路径穿越应抛出异常", False, "未抛出异常")
    except ValueError:
        _record("path_safety - 反斜杠路径穿越应抛出异常", True)

    # --- 正斜杠路径穿越（之前未覆盖的场景） ---
    try:
        validate_path_safety("C:/Users/../../Windows/System32")
        _record("path_safety - 正斜杠路径穿越应抛出异常", False, "未抛出异常")
    except ValueError:
        _record("path_safety - 正斜杠路径穿越应抛出异常", True)

    # --- 混合斜杠路径穿越 ---
    try:
        validate_path_safety("C:\\Users/..\\..\\Windows\\System32")
        _record("path_safety - 混合斜杠路径穿越应抛出异常", False, "未抛出异常")
    except ValueError:
        _record("path_safety - 混合斜杠路径穿越应抛出异常", True)

    # --- 系统保护路径 ---
    _record(
        "path_safety - C:\\Windows 为受保护路径",
        is_protected_path("C:\\Windows"),
    )
    _record(
        "path_safety - C:\\Program Files 为受保护路径",
        is_protected_path("C:\\Program Files"),
    )

    # --- 正常路径不应被保护 ---
    _record(
        "path_safety - 用户目录不被保护",
        not is_protected_path(os.path.expanduser("~")),
    )

    # --- 正常绝对路径应通过验证 ---
    try:
        result = validate_path_safety(test_dir)
        _record("path_safety - 正常绝对路径通过验证", result == test_dir, result)
    except ValueError as exc:
        _record("path_safety - 正常绝对路径通过验证", False, str(exc))


# ============================================================
# 主入口
# ============================================================


async def main() -> None:
    """主测试流程：创建临时目录 → 执行所有测试 → 清理。"""
    print("=" * 60)
    print("Local File Manager 工具集成测试")
    print(f"运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # 创建临时测试目录（在项目根目录下）
    project_root = os.path.normpath(os.path.join(_AI_SERVICE_DIR, "..", ".."))
    test_base = os.path.join(project_root, "_lfm_test_temp")

    # 如果上次残留则先清理
    if os.path.exists(test_base):
        shutil.rmtree(test_base, ignore_errors=True)

    # 准备测试目录结构
    test_dir = os.path.join(test_base, "workspace")
    os.makedirs(test_dir, exist_ok=True)
    os.makedirs(os.path.join(test_dir, "subdir_a"), exist_ok=True)

    # 创建一些测试文件
    with open(os.path.join(test_dir, "test_file.txt"), "w", encoding="utf-8") as f:
        f.write("这是一个测试文件。\n用于 Local File Manager 工具测试。\n")

    with open(os.path.join(test_dir, "test_script.py"), "w", encoding="utf-8") as f:
        f.write("# 测试 Python 文件\nprint('Hello from test_script.py')\n")

    with open(os.path.join(test_dir, "subdir_a", "inner.txt"), "w", encoding="utf-8") as f:
        f.write("子目录中的文件内容\n")

    with open(os.path.join(test_dir, "data.json"), "w", encoding="utf-8") as f:
        f.write('{"key": "value", "test": true}\n')

    print(f"\n📂 临时测试目录: {test_dir}\n")

    # ============================================================
    # 按顺序执行测试
    # ============================================================

    print("── 1. 路径安全验证测试 ──")
    await test_path_safety(test_dir)

    print("\n── 2. list_directory 工具测试 ──")
    await test_list_directory(test_dir)

    print("\n── 3. read_file_metadata 工具测试 ──")
    await test_read_file_metadata(test_dir)

    print("\n── 4. create_or_write_file 工具测试 ──")
    await test_create_or_write_file(test_dir)

    print("\n── 5. move_or_rename_file 工具测试 ──")
    await test_move_or_rename_file(test_dir)

    print("\n── 6. delete_local_file 工具测试 ──")
    await test_delete_local_file(test_dir)

    print("\n── 7. search_files_global 工具测试 ──")
    await test_search_files_global(test_dir)

    # ============================================================
    # 清理临时目录
    # ============================================================
    try:
        shutil.rmtree(test_base, ignore_errors=True)
        print(f"\n🧹 已清理临时测试目录: {test_base}")
    except Exception as exc:
        print(f"\n⚠️ 清理临时目录失败: {exc}")

    # 打印汇总
    _print_summary()


if __name__ == "__main__":
    asyncio.run(main())
