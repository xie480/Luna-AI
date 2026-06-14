-- RAG 文档简介字段迁移脚本
-- 做什么：为已有的 rag_documents 表新增 description 列（VARCHAR(500)，默认空字符串），不破坏现有数据。
-- 为什么这样做：知识库文档需要可选简介字段用于描述文件作用，向下兼容。
-- 边界条件：ALTER TABLE 仅当列不存在时执行；已有数据自动补默认值。
-- 异常行为：如果列已存在则静默跳过，不会报错。

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'rag_documents' AND column_name = 'description'
    ) THEN
        ALTER TABLE rag_documents
        ADD COLUMN description VARCHAR(500) NOT NULL DEFAULT '';
    END IF;
END $$;
