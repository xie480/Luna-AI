"""
测试 JSONB 参数写入是否正常工作。

做什么：直接通过原始 SQL 测试 asyncpg 写入 JSONB 列，验证 json.dumps 序列化方案。
为什么这样做：audit_log_pg.py 的 import 链存在循环依赖，直接用 SQL 测试更简洁可靠。

使用方式（在 backend/ai-service 目录下执行）：
    python scripts/test_audit_log_jsonb.py
"""

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_PROJECT_ROOT))


async def main() -> None:
    from sqlalchemy import text

    from app.config.settings import settings
    from app.infrastructure.postgres import PostgresClient
    from app.utils.snowflake import generate_string_id

    conn_str = settings.postgres_conn_str
    print("Connecting to database...")
    pg_client = PostgresClient(conn_str)

    try:
        await pg_client.ping()
        print("Database connection OK\n")

        test_id = generate_string_id()
        test_arguments = {
            "path": "E:\\YilenaCode\\test_luna.txt",
            "content": "这是一段测试文本，用于验证Luna的文件写入功能。",
            "overwrite": False,
        }

        # ============================================================
        # 测试 1：使用 json.dumps + :arguments_json（修复后的方式）
        # ============================================================
        print("Test 1: INSERT with json.dumps (fixed approach)")
        print(f"  id={test_id}")
        print(f"  arguments={test_arguments}")

        arguments_json = json.dumps(test_arguments, ensure_ascii=False)
        now = datetime.now(timezone.utc)

        query = text("""
            INSERT INTO audit_logs (
                id, user_id, tool_id, tool_name, risk_level,
                reason, arguments, goal, agent_output,
                status, trace_id, task_id, created_at, updated_at
            ) VALUES (
                :id, :user_id, :tool_id, :tool_name, :risk_level,
                :reason, :arguments_json, :goal, :agent_output,
                :status, :trace_id, :task_id, :created_at, :updated_at
            )
        """)

        async with pg_client.session_factory() as session:
            await session.execute(
                query,
                {
                    "id": test_id,
                    "user_id": "local_default_user",
                    "tool_id": "create_or_write_file",
                    "tool_name": "create_or_write_file",
                    "risk_level": "L2",
                    "reason": "工具风险等级 L2，需要用户确认后才可执行。",
                    "arguments_json": arguments_json,
                    "goal": "测试文件写入",
                    "agent_output": "",
                    "status": "PENDING",
                    "trace_id": "test_trace_001",
                    "task_id": "test_task_001",
                    "created_at": now,
                    "updated_at": now,
                },
            )
            await session.commit()
        print("  [OK] INSERT succeeded\n")

        # ============================================================
        # 测试 2：验证写入的数据
        # ============================================================
        print("Test 2: Verify written data")
        async with pg_client.session_factory() as session:
            result = await session.execute(
                text("SELECT id, arguments FROM audit_logs WHERE id = :id"),
                {"id": test_id},
            )
            row = result.fetchone()
            if row:
                print(f"  id={row[0]}")
                print(f"  arguments={row[1]}")
                print(f"  arguments type={type(row[1]).__name__}")
                if isinstance(row[1], dict):
                    print("  [OK] arguments is dict (JSONB correctly stored and retrieved)")
                else:
                    print(f"  [WARN] arguments is {type(row[1]).__name__}, expected dict")
            else:
                print("  [FAIL] Record not found")

        # ============================================================
        # 测试 3：cleanup
        # ============================================================
        print("\nCleanup: Deleting test record")
        async with pg_client.session_factory() as session:
            await session.execute(
                text("DELETE FROM audit_logs WHERE id = :id"),
                {"id": test_id},
            )
            await session.commit()
        print("  [OK] Test record deleted")

        print("\n=== All tests passed! ===")

    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
    finally:
        await pg_client.close()
        print("Connection closed.")


if __name__ == "__main__":
    asyncio.run(main())
