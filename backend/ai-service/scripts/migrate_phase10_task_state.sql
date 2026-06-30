-- Phase 10 迁移脚本：创建任务级状态快照表和状态跃迁审计日志表。
-- 做什么：创建 task_snapshots 和 state_transition_logs 表，支持任务级状态管理。
-- 为什么这样做：Phase 10 要求将 Plan 运行时快照持久化到 PostgreSQL，
--              并记录所有状态跃迁的审计日志。
-- 执行方式：由 app/main.py 的自动迁移逻辑或手动执行。

-- ============================================================
-- 1. 任务级状态快照表
-- ============================================================

CREATE TABLE IF NOT EXISTS task_snapshots (
    id VARCHAR(64) PRIMARY KEY,
    task_id VARCHAR(64) NOT NULL,
    session_id VARCHAR(64) NOT NULL DEFAULT '',
    trace_id VARCHAR(64) NOT NULL DEFAULT '',
    plan_id VARCHAR(64) NOT NULL DEFAULT '',
    task_status VARCHAR(32) NOT NULL,
    dag_engine_state JSONB NOT NULL,
    executor_runtime JSONB,
    gating_snapshot JSONB,
    snapshot_version INT NOT NULL DEFAULT 1,
    trigger_event VARCHAR(64) NOT NULL DEFAULT '',
    saved_at_ms BIGINT NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT idx_task_snapshots_task_version UNIQUE (task_id, snapshot_version)
);

CREATE INDEX IF NOT EXISTS idx_task_snapshots_session_id ON task_snapshots(session_id);
CREATE INDEX IF NOT EXISTS idx_task_snapshots_plan_id ON task_snapshots(plan_id);
CREATE INDEX IF NOT EXISTS idx_task_snapshots_status ON task_snapshots(task_status);

-- ============================================================
-- 2. 状态跃迁审计日志表
-- ============================================================

CREATE TABLE IF NOT EXISTS state_transition_logs (
    id BIGSERIAL PRIMARY KEY,
    session_id VARCHAR(64) NOT NULL DEFAULT '',
    task_id VARCHAR(64) DEFAULT '',
    turn_id VARCHAR(64) DEFAULT '',
    prev_wsm VARCHAR(32),
    next_wsm VARCHAR(32),
    prev_esm VARCHAR(32),
    next_esm VARCHAR(32),
    trigger_type VARCHAR(16) NOT NULL,
    transition_reason TEXT,
    trace_id VARCHAR(64) DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_state_transition_logs_session ON state_transition_logs(session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_state_transition_logs_task ON state_transition_logs(task_id);
CREATE INDEX IF NOT EXISTS idx_state_transition_logs_trigger ON state_transition_logs(trigger_type);
