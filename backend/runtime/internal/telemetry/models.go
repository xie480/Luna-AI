package telemetry

import (
	"context"
	"time"

	"gorm.io/gorm"
)

// AuditLog 审计日志模型
type AuditLog struct {
	ID               string    `gorm:"column:id;primaryKey;type:varchar(64)" json:"id"`
	TraceID          string    `gorm:"column:trace_id;not null;type:varchar(64);index:idx_audit_trace" json:"trace_id"`
	Timestamp        time.Time `gorm:"column:timestamp;default:CURRENT_TIMESTAMP;index:idx_audit_time" json:"timestamp"`
	PlanID           string    `gorm:"column:plan_id;type:varchar(64)" json:"plan_id"`
	NodeID           string    `gorm:"column:node_id;type:varchar(64)" json:"node_id"`
	ActionType       string    `gorm:"column:action_type;not null;type:varchar(32)" json:"action_type"`
	Resource         string    `gorm:"column:resource;type:varchar(128)" json:"resource"`
	Operation        string    `gorm:"column:operation;not null;type:varchar(128)" json:"operation"`
	Payload          string    `gorm:"column:payload;type:jsonb" json:"payload"` // JSONB string
	RiskLevel        string    `gorm:"column:risk_level;not null;type:varchar(16)" json:"risk_level"`
	Status           string    `gorm:"column:status;not null;type:varchar(32)" json:"status"`
	ErrorMsg         string    `gorm:"column:error_msg;type:text" json:"error_msg"`
	RequiresApproval bool      `gorm:"column:requires_approval" json:"requires_approval"`
	UserApproved     bool      `gorm:"column:user_approved" json:"user_approved"`
}

// TableName 指定表名
func (AuditLog) TableName() string {
	return "audit_logs"
}

// TraceSpan 链路跨度模型
type TraceSpan struct {
	SpanID       string    `gorm:"column:span_id;primaryKey;type:varchar(64)" json:"span_id"`
	TraceID      string    `gorm:"column:trace_id;not null;type:varchar(64);index:idx_span_trace" json:"trace_id"`
	ParentSpanID string    `gorm:"column:parent_span_id;type:varchar(64)" json:"parent_span_id"`
	Name         string    `gorm:"column:name;not null;type:varchar(128)" json:"name"`
	Service      string    `gorm:"column:service;not null;type:varchar(32)" json:"service"`
	StartTime    time.Time `gorm:"column:start_time;not null" json:"start_time"`
	EndTime      time.Time `gorm:"column:end_time" json:"end_time"`
	DurationMs   int64     `gorm:"column:duration_ms" json:"duration_ms"`
	Status       string    `gorm:"column:status;type:varchar(16)" json:"status"`
	Attributes   string    `gorm:"column:attributes;type:jsonb" json:"attributes"` // JSONB string
}

// TableName 指定表名
func (TraceSpan) TableName() string {
	return "trace_spans"
}

// InitSchema 初始化数据库表结构和清理函数
func InitSchema(db *gorm.DB) error {
	// 自动迁移表结构
	if err := db.AutoMigrate(&AuditLog{}, &TraceSpan{}); err != nil {
		return err
	}

	// 创建防篡改触发器 (PostgreSQL specific)
	// 限制只能更新 status, error_msg, user_approved 字段，且只能删除 3 个月前的数据
	tamperProtectionSQL := `
	CREATE OR REPLACE FUNCTION prevent_audit_log_tampering()
	RETURNS TRIGGER AS $$
	BEGIN
		IF TG_OP = 'DELETE' THEN
			-- 允许清理函数删除 3 个月前的数据
			IF OLD.timestamp >= NOW() - INTERVAL '3 months' THEN
				RAISE EXCEPTION 'Cannot delete recent audit logs (tamper protection)';
			END IF;
			RETURN OLD;
		ELSIF TG_OP = 'UPDATE' THEN
			-- 仅允许更新状态相关字段
			IF NEW.id != OLD.id OR
			   NEW.trace_id != OLD.trace_id OR
			   NEW.timestamp != OLD.timestamp OR
			   NEW.plan_id != OLD.plan_id OR
			   NEW.node_id != OLD.node_id OR
			   NEW.action_type != OLD.action_type OR
			   NEW.resource != OLD.resource OR
			   NEW.operation != OLD.operation OR
			   NEW.payload != OLD.payload OR
			   NEW.risk_level != OLD.risk_level OR
			   NEW.requires_approval != OLD.requires_approval THEN
				RAISE EXCEPTION 'Cannot modify critical fields of audit logs (tamper protection)';
			END IF;
			RETURN NEW;
		END IF;
		RETURN NULL;
	END;
	$$ LANGUAGE plpgsql;

	DROP TRIGGER IF EXISTS audit_log_tamper_protection ON audit_logs;
	CREATE TRIGGER audit_log_tamper_protection
	BEFORE UPDATE OR DELETE ON audit_logs
	FOR EACH ROW EXECUTE FUNCTION prevent_audit_log_tampering();
	`
	if err := db.Exec(tamperProtectionSQL).Error; err != nil {
		return err
	}

	// 创建清理函数 (PostgreSQL specific)
	cleanupAuditLogsSQL := `
	CREATE OR REPLACE FUNCTION cleanup_audit_logs()
	RETURNS void AS $$
	BEGIN
		DELETE FROM audit_logs WHERE timestamp < NOW() - INTERVAL '3 months';
	END;
	$$ LANGUAGE plpgsql;
	`
	if err := db.Exec(cleanupAuditLogsSQL).Error; err != nil {
		return err
	}

	cleanupTraceSpansSQL := `
	CREATE OR REPLACE FUNCTION cleanup_trace_spans()
	RETURNS void AS $$
	BEGIN
		DELETE FROM trace_spans WHERE start_time < NOW() - INTERVAL '7 days';
	END;
	$$ LANGUAGE plpgsql;
	`
	if err := db.Exec(cleanupTraceSpansSQL).Error; err != nil {
		return err
	}

	return nil
}

// RunCleanup 定期执行清理任务
func RunCleanup(ctx context.Context, db *gorm.DB) {
	ticker := time.NewTicker(24 * time.Hour)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			db.Exec("SELECT cleanup_audit_logs();")
			db.Exec("SELECT cleanup_trace_spans();")
		}
	}
}