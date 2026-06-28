"""
Luna AI 数据库 Schema 同步脚本

做什么：独立运行的数据库表结构同步脚本，根据当前项目中所有 ORM 模型定义，
        自动对比 PostgreSQL 实际表结构，执行以下操作：
        1. 创建 ORM 中定义但数据库中缺失的表
        2. 删除数据库中存在但 ORM 中未定义的表（白名单保护）
        3. 为已有表添加 ORM 中定义但数据库中缺失的字段
        4. 删除已有表中 ORM 未定义的多余字段
        5. 同步字段类型差异（如 timestamp without time zone -> timestamp with time zone）
        6. 同步字段 Nullable 属性差异

为什么这样做：开发过程中 ORM 模型频繁变更，手动写 SQL 迁移容易遗漏或出错。
            此脚本提供一键同步能力，确保数据库结构与代码定义完全一致。

使用方式（在 backend/ai-service 目录下执行）：
    python scripts/sync_schema.py

输入输出：
    - 输入：.env 中的数据库连接配置（通过 app.config.settings 自动加载）+ ORM 模型定义
    - 输出：控制台输出同步操作日志，数据库结构被同步修改

边界条件：
    - 需要 PostgreSQL 服务正常运行
    - 需要 .env 文件中正确配置 DB_HOST / DB_PORT / DB_USER / DB_PASSWORD / DB_NAME
    - 白名单表不会被删除（如 langgraph_chat_checkpoints）

异常行为：
    - 单个 DDL 失败时使用 SAVEPOINT 隔离，不影响其他操作
    - 连接失败时输出错误信息并退出
"""

import asyncio
import sys
from pathlib import Path

# ============================================================
# 将项目根目录（backend/ai-service/）加入 sys.path，
# 确保 app 模块可正常导入。
# 脚本位于 backend/ai-service/scripts/sync_schema.py
# ============================================================
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent  # backend/ai-service/
sys.path.insert(0, str(_PROJECT_ROOT))


def _sync_schema(sync_conn) -> dict[str, list[str]]:
    """
    在同步连接上下文中执行完整的 Schema 差异比对与同步。

    做什么：
        1. 导入所有 ORM 模型的 metadata
        2. 获取数据库现有表与字段
        3. 创建缺失表、删除多余表
        4. 逐表比对字段差异：添加缺失字段、删除多余字段、修改类型与 Nullable

    为什么这样做：此函数作为 run_sync 的回调，在异步引擎的同步上下文中执行 DDL。

    输入输出：
        - 输入：sync_conn（SQLAlchemy 同步连接对象）
        - 输出：包含所有已执行操作的日志字典

    边界条件：
        - 使用 SAVEPOINT 隔离每个 DDL，单个失败不影响全局
        - 白名单表不会被删除
        - JSON 类型不做细粒度差异比对（差异过于复杂）

    异常行为：
        - 单个 DDL 失败时回滚到 SAVEPOINT 并记录错误
    """
    from sqlalchemy import inspect, text as sa_text

    # ============================================================
    # 导入所有 ORM 模型 metadata
    # 这些导入会触发模型注册到对应的 DeclarativeBase.metadata 中
    # ============================================================
    from app.repository.models import Base
    from app.telemetry.worker import Base as TelemetryBase

    # 收集操作日志
    report: dict[str, list[str]] = {
        "tables_created": [],
        "tables_dropped": [],
        "columns_added": [],
        "columns_dropped": [],
        "columns_type_changed": [],
        "columns_nullable_changed": [],
        "errors": [],
        "skipped_tables": [],
    }

    # 自增计数器，用于生成唯一 SAVEPOINT 名称
    _sp_counter = [0]

    def ddl_execute(sql: str, error_ctx: str) -> None:
        """
        使用 SAVEPOINT 安全执行 DDL。

        为什么这样做：PostgreSQL 在 DDL 失败后会将整个事务标记为 aborted，
        后续所有 SQL 都会报 InFailedSQLTransactionError。SAVEPOINT 允许
        单个 DDL 失败时只回滚到该点，不影响事务中其他成功 DDL。
        """
        _sp_counter[0] += 1
        sp_name = f"sp_ddl_{_sp_counter[0]}"
        try:
            sync_conn.exec_driver_sql(f"SAVEPOINT {sp_name}")
            sync_conn.execute(sa_text(sql))
            sync_conn.exec_driver_sql(f"RELEASE SAVEPOINT {sp_name}")
        except Exception as e:
            report["errors"].append(f"{error_ctx}: {e}")
            print(f"  [ERROR] {error_ctx} failed: {e}")
            try:
                sync_conn.exec_driver_sql(f"ROLLBACK TO SAVEPOINT {sp_name}")
            except Exception:
                pass

    inspector = inspect(sync_conn)
    existing_tables = set(inspector.get_table_names())

    # ============================================================
    # 收集本地 ORM 定义的所有表（合并业务模型与遥测模型）
    # ============================================================
    local_tables_map: dict = {}
    local_tables_map.update(Base.metadata.tables)
    local_tables_map.update(TelemetryBase.metadata.tables)

    # 白名单保护：这些表由系统外部管理（如 LangGraph），不可删除
    whitelist_tables = {"langgraph_chat_checkpoints"}

    # ============================================================
    # 步骤 1：创建 ORM 定义但数据库中缺失的表
    # ============================================================
    print("\n" + "=" * 60)
    print("Step 1: Create Missing Tables")
    print("=" * 60)
    try:
        Base.metadata.create_all(sync_conn)
        TelemetryBase.metadata.create_all(sync_conn)
    except Exception as e:
        report["errors"].append(f"Create tables failed: {e}")
        print(f"  [ERROR] Batch create tables failed: {e}")

    # 刷新表列表（create_all 后可能有新表）
    existing_tables_after_create = set(inspector.get_table_names())
    newly_created = existing_tables_after_create - existing_tables
    for t in sorted(newly_created):
        if t in local_tables_map:
            report["tables_created"].append(t)
            print(f"  [OK] Created table: {t}")
    existing_tables = existing_tables_after_create

    # ============================================================
    # 步骤 2：删除数据库中存在但 ORM 中未定义的表
    # ============================================================
    print("\n" + "=" * 60)
    print("Step 2: Drop Redundant Tables")
    print("=" * 60)
    for db_table in sorted(existing_tables):
        if db_table not in local_tables_map and db_table not in whitelist_tables:
            drop_stmt = f'DROP TABLE IF EXISTS "{db_table}" CASCADE'
            print(f"  [DROP] Dropping table: {db_table}")
            ddl_execute(drop_stmt, f"Drop table {db_table}")
            report["tables_dropped"].append(db_table)
        elif db_table in whitelist_tables:
            report["skipped_tables"].append(f"{db_table} (whitelist)")

    # 刷新表列表
    existing_tables = set(inspector.get_table_names())

    # ============================================================
    # 步骤 3：字段级差异比对与同步
    # ============================================================
    print("\n" + "=" * 60)
    print("Step 3: Column-Level Diff & Sync")
    print("=" * 60)
    for table_name, table in sorted(local_tables_map.items()):
        if table_name not in existing_tables:
            # 表不存在但 create_all 可能因外键等约束失败，跳过
            continue

        db_columns_info = inspector.get_columns(table_name)
        db_columns = {col["name"]: col for col in db_columns_info}
        local_col_names = {col.name for col in table.columns}

        has_table_changes = False

        # 3a. 删除数据库中多余的字段
        for db_col_name in sorted(db_columns.keys()):
            if db_col_name not in local_col_names:
                if not has_table_changes:
                    print(f"\n  [{table_name}]")
                    has_table_changes = True
                drop_col_stmt = f'ALTER TABLE "{table_name}" DROP COLUMN "{db_col_name}" CASCADE'
                print(f"    [DROP COL] {db_col_name}")
                ddl_execute(drop_col_stmt, f"Table {table_name} drop column {db_col_name}")
                report["columns_dropped"].append(f"{table_name}.{db_col_name}")

        # 刷新列信息（删除操作后列可能已变化）
        if has_table_changes:
            db_columns_info = inspector.get_columns(table_name)
            db_columns = {col["name"]: col for col in db_columns_info}

        # 3b. 新增缺失字段或修改字段属性
        for col in table.columns:
            col_name = col.name
            if col_name not in db_columns:
                # ---- 新增字段 ----
                if not has_table_changes:
                    print(f"\n  [{table_name}]")
                    has_table_changes = True
                col_type = str(col.type.compile(sync_conn.dialect))

                # 构建默认值子句：
                # 当字段为 NOT NULL 时，必须提供 DEFAULT，否则对已有数据的表会报
                # "column contains null values" 错误。
                # 当字段为 NULLABLE 时也提供默认值以保持一致性。
                default_clause = ""
                if "timestamp" in col_type.lower():
                    default_clause = " DEFAULT NOW()"
                elif "jsonb" in col_type.lower():
                    default_clause = " DEFAULT '{}'::jsonb"
                elif "integer" in col_type.lower() or "numeric" in col_type.lower():
                    default_clause = " DEFAULT 0"
                elif "boolean" in col_type.lower():
                    default_clause = " DEFAULT false"
                else:
                    # VARCHAR / TEXT 等字符串类型
                    default_clause = " DEFAULT ''"

                nullable_str = "" if col.nullable else " NOT NULL"

                alter_stmt = (
                    f'ALTER TABLE "{table_name}" ADD COLUMN "{col_name}" '
                    f"{col_type}{nullable_str}{default_clause}"
                )
                print(f"    [ADD COL] {col_name} ({col_type})")
                ddl_execute(alter_stmt, f"Table {table_name} add column {col_name}")
                report["columns_added"].append(f"{table_name}.{col_name}")

                # 为新字段创建索引（如果 ORM 定义了 index=True）
                if getattr(col, "index", False):
                    index_name = f"ix_{table_name}_{col_name}"
                    index_stmt = (
                        f'CREATE INDEX IF NOT EXISTS "{index_name}" '
                        f'ON "{table_name}" ("{col_name}")'
                    )
                    print(f"    [INDEX] {index_name}")
                    ddl_execute(index_stmt, f"Create index {index_name}")
            else:
                # ---- 已有字段：比对属性差异 ----
                db_col = db_columns[col_name]
                field_changes = []

                # Nullable 差异比对
                db_nullable = db_col.get("nullable", True)
                if col.nullable != db_nullable:
                    if col.nullable:
                        alter_null_stmt = (
                            f'ALTER TABLE "{table_name}" ALTER COLUMN "{col_name}" DROP NOT NULL'
                        )
                        direction = "NOT NULL -> NULL"
                    else:
                        alter_null_stmt = (
                            f'ALTER TABLE "{table_name}" ALTER COLUMN "{col_name}" SET NOT NULL'
                        )
                        direction = "NULL -> NOT NULL"
                    field_changes.append(f"Nullable: {direction}")
                    ddl_execute(
                        alter_null_stmt,
                        f"Table {table_name} column {col_name} change nullable",
                    )
                    report["columns_nullable_changed"].append(
                        f"{table_name}.{col_name} ({direction})"
                    )

                # 类型差异比对
                expected_type_str = str(col.type.compile(sync_conn.dialect)).lower()
                db_type_str = str(db_col["type"]).lower()

                # 提取基础类型（去掉参数部分，如 varchar(255) -> varchar）
                exp_base_type = expected_type_str.split("(")[0].strip()
                db_base_type = db_type_str.split("(")[0].strip()

                # 类型等价映射：不同 SQLAlchemy 与 PostgreSQL 表示法的等价关系
                type_equivalents = {
                    "character varying": "varchar",
                    "integer": "int",
                    "boolean": "bool",
                }
                exp_base_type = type_equivalents.get(exp_base_type, exp_base_type)
                db_base_type = type_equivalents.get(db_base_type, db_base_type)

                # 特殊处理：timestamp without time zone -> timestamp with time zone
                # 如果 ORM 期望带时区但实际库中不带，必须修复（否则时间差 8 小时）
                if (
                    exp_base_type == "timestamp with time zone"
                    and db_base_type == "timestamp without time zone"
                ):
                    fix_tz_stmt = (
                        f'ALTER TABLE "{table_name}" ALTER COLUMN "{col_name}" '
                        f'TYPE TIMESTAMP WITH TIME ZONE USING "{col_name}" AT TIME ZONE \'UTC\''
                    )
                    field_changes.append(f"Timezone fix: {db_type_str} -> {expected_type_str}")
                    ddl_execute(
                        fix_tz_stmt,
                        f"Table {table_name} column {col_name} timezone fix",
                    )
                    report["columns_type_changed"].append(
                        f"{table_name}.{col_name} ({db_type_str} -> {expected_type_str})"
                    )
                elif (
                    exp_base_type != db_base_type
                    and "json" not in exp_base_type
                    and "json" not in db_base_type
                ):
                    # 通用类型比对：忽略 JSON 类型的复杂差异
                    alter_type_stmt = (
                        f'ALTER TABLE "{table_name}" ALTER COLUMN "{col_name}" '
                        f'TYPE {expected_type_str} USING "{col_name}"::{expected_type_str}'
                    )
                    field_changes.append(f"Type: {db_type_str} -> {expected_type_str}")
                    ddl_execute(
                        alter_type_stmt,
                        f"Table {table_name} column {col_name} change type",
                    )
                    report["columns_type_changed"].append(
                        f"{table_name}.{col_name} ({db_type_str} -> {expected_type_str})"
                    )

                # 打印字段级变更
                if field_changes:
                    if not has_table_changes:
                        print(f"\n  [{table_name}]")
                        has_table_changes = True
                    for change in field_changes:
                        print(f"    [ALTER COL] {col_name}: {change}")

    # ============================================================
    # 步骤 4：手动创建非 ORM 管理的系统表（langgraph_chat_checkpoints）
    # ============================================================
    print("\n" + "=" * 60)
    print("Step 4: Non-ORM System Tables")
    print("=" * 60)
    checkpoint_ddl = (
        'CREATE TABLE IF NOT EXISTS "langgraph_chat_checkpoints" ('
        "checkpoint_id VARCHAR(64) PRIMARY KEY, "
        "thread_id VARCHAR(64) NOT NULL, "
        "checkpoint_ns VARCHAR(255) NOT NULL, "
        "trace_id VARCHAR(64) NOT NULL, "
        "interaction_id VARCHAR(64) NOT NULL, "
        "node_type VARCHAR(100) NOT NULL, "
        "payload JSONB NOT NULL, "
        "created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()"
        ")"
    )
    ddl_execute(checkpoint_ddl, "Create langgraph_chat_checkpoints table")
    print("  [OK] langgraph_chat_checkpoints table checked")

    idx1 = (
        'CREATE INDEX IF NOT EXISTS "idx_langgraph_chat_checkpoints_trace" '
        'ON "langgraph_chat_checkpoints" (trace_id)'
    )
    ddl_execute(idx1, "Create langgraph_chat_checkpoints trace_id index")

    idx2 = (
        'CREATE INDEX IF NOT EXISTS "idx_langgraph_chat_checkpoints_thread_ns" '
        'ON "langgraph_chat_checkpoints" (thread_id, checkpoint_ns, created_at)'
    )
    ddl_execute(idx2, "Create langgraph_chat_checkpoints thread_ns index")
    print("  [OK] langgraph_chat_checkpoints indexes checked")

    return report


def _print_summary(report: dict[str, list[str]]) -> None:
    """
    打印同步结果汇总。

    做什么：将 _sync_schema 返回的操作日志以结构化方式输出到控制台。
    为什么这样做：清晰展示所有变更，便于开发者确认同步结果。
    """
    print("\n" + "=" * 60)
    print("Schema Sync Summary")
    print("=" * 60)

    sections = [
        ("Tables Created", report["tables_created"]),
        ("Tables Dropped", report["tables_dropped"]),
        ("Columns Added", report["columns_added"]),
        ("Columns Dropped", report["columns_dropped"]),
        ("Type Changes", report["columns_type_changed"]),
        ("Nullable Changes", report["columns_nullable_changed"]),
        ("Skipped (whitelist)", report["skipped_tables"]),
        ("Errors", report["errors"]),
    ]

    has_changes = False
    for label, items in sections:
        if items:
            has_changes = True
            print(f"\n  {label} ({len(items)}):")
            for item in items:
                print(f"    - {item}")

    if not has_changes:
        print("\n  Database schema is already in sync with ORM definitions. No changes needed.")

    total_ops = sum(len(v) for k, v in report.items() if k != "errors")
    total_errors = len(report["errors"])
    print(f"\n  Total: {total_ops} operations, {total_errors} errors")


async def main() -> None:
    """
    主入口：创建数据库连接并执行 Schema 同步。

    做什么：
        1. 通过 app.config.settings 加载数据库配置（自动读取 .env）
        2. 创建 SQLAlchemy 异步引擎
        3. 在 run_sync 上下文中执行 Schema 同步
        4. 打印结果汇总

    为什么这样做：独立脚本需自行管理数据库连接生命周期。
    """
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    # 通过项目 settings 模块加载 .env 配置（pydantic_settings 自动处理）
    from app.config.settings import settings

    conn_str = settings.postgres_conn_str
    # 隐藏密码用于日志输出
    masked = conn_str
    if "://" in conn_str and "@" in conn_str:
        start = conn_str.find("://") + 3
        at = conn_str.find("@")
        creds = conn_str[start:at]
        if ":" in creds:
            user = creds.split(":", 1)[0]
            masked = conn_str[:start] + f"{user}:[REDACTED]" + conn_str[at:]

    print("=" * 60)
    print("Luna AI - Database Schema Sync Tool")
    print("=" * 60)
    print(f"  Target: {masked}")

    # 使用 NullPool 避免脚本退出时连接池回收问题
    engine = create_async_engine(conn_str, poolclass=NullPool, echo=False)

    try:
        # 测试连接
        async with engine.connect() as conn:
            from sqlalchemy import text as sa_text
            result = await conn.execute(sa_text("SELECT current_database()"))
            db_name = result.scalar()
            print(f"  Connected to database: {db_name}")

        # 执行 Schema 同步
        async with engine.begin() as conn:
            report = await conn.run_sync(_sync_schema)

        _print_summary(report)

    except Exception as e:
        print(f"\n  [ERROR] Database connection failed: {e}")
        print("  Please check DB_HOST / DB_PORT / DB_USER / DB_PASSWORD / DB_NAME in .env file")
        sys.exit(1)
    finally:
        await engine.dispose()
        print("\n  Connection closed.")


if __name__ == "__main__":
    asyncio.run(main())
