-- 1. 清除那些由于配置写入导致的错误 MCP Server 记录
-- 警告：如果以前业务上强依赖这些记录（通常不会，因为之前架构根本走不通），需要做特殊备份。
DELETE FROM mcp_server_configs 
WHERE transport_type = 'sse' 
  AND endpoint_url LIKE '%smithery%';

-- 2. 为 skills 表扩充缺失的架构映射字段
ALTER TABLE skills ADD COLUMN IF NOT EXISTS source VARCHAR(50) DEFAULT 'local';
ALTER TABLE skills ADD COLUMN IF NOT EXISTS toolbox_id VARCHAR(128);
ALTER TABLE skills ADD COLUMN IF NOT EXISTS proxy_meta JSONB DEFAULT '{}'::jsonb;

-- 创建索引以加速发现引擎的匹配查询
CREATE INDEX IF NOT EXISTS idx_skills_source_toolbox ON skills (source, toolbox_id);

-- （可选）清理废弃的 tools 记录
-- DELETE FROM mcp_tool_registrations WHERE is_external = true;
