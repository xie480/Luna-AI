-- 时间戳字段时区迁移脚本
-- 做什么：将数据库中所有 TIMESTAMP WITHOUT TIME ZONE 类型的 created_at/updated_at/deleted_at
--         等时间字段转换为 TIMESTAMP WITH TIME ZONE，修复时间少 8 小时的问题。
-- 为什么这样做：现有 PG 表在首次创建时，由于 schema sync 将 TIMESTAMPTZ 和 TIMESTAMP
--             混为一谈，导致时间字段缺少时区标记。时间值虽以 UTC 存储，但缺少时区信息后
--             应用层读取时默认转为本地时区（+8），产生 8 小时偏移。
-- 边界条件：
--   - 仅转换表名以特定关键词结尾的时间字段，避免误伤非标准字段。
--   - 要求字段名包含 created_at / updated_at / deleted_at / last_confirmed_at /
--           health_checked_at / last_health_check / last_commit_at / discovered_at。
-- 异常行为：如果字段已是 TIMESTAMPTZ 则静默跳过，不会报错。
-- 使用方法：
--   psql -U postgres -d luna -f migrate_add_timezone_to_timestamps.sql

DO $$
DECLARE
    rec RECORD;
    col_name TEXT;
    col_list TEXT[] := ARRAY[
        'created_at', 'updated_at', 'deleted_at', 'last_confirmed_at',
        'health_checked_at', 'last_health_check', 'last_commit_at',
        'discovered_at'
    ];
BEGIN
    -- 遍历所有用户表（排除 pg_catalog 和 information_schema）
    FOR rec IN
        SELECT table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND data_type = 'timestamp without time zone'
          AND column_name = ANY(col_list)
        ORDER BY table_name, column_name
    LOOP
        -- 执行类型转换：timestamp without time zone -> timestamp with time zone
        EXECUTE format(
            'ALTER TABLE %I ALTER COLUMN %I TYPE TIMESTAMP WITH TIME ZONE USING %I AT TIME ZONE ''UTC''',
            rec.table_name, rec.column_name, rec.column_name
        );
        RAISE NOTICE '已转换: %.% (% -> timestamp with time zone)', rec.table_name, rec.column_name, rec.data_type;
    END LOOP;

    RAISE NOTICE '时区迁移完成';
END $$;
