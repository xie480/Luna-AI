from typing import List
import re
from pydantic import BaseModel
from app.types.constants import MemoryChunkType
from app.logger import logger

class MemoryChunk(BaseModel):
    chunk_type: MemoryChunkType
    content: str

def parse_long_summary_to_chunks(full_summary: str) -> List[MemoryChunk]:
    """
    做什么：将大模型按 prompt_template 输出的结构化长摘要拆分为独立的语义块。
    输入：符合 '梗概：... \n 关键事实：1.xxx;2.xxx' 格式的字符串。
    异常行为：若格式不合规或未找到特征符，降级为将 full_summary 作为一个单独的 SUMMARY Chunk 返回。
    """
    chunks = []
    
    try:
        # 使用正则拆分"梗概："和"关键事实："部分
        # 兼容可能有换行、空格或没有换行的情况
        pattern = r"梗概：\s*(.*?)\s*关键事实：\s*(.*)"
        match = re.search(pattern, full_summary, re.DOTALL)
        
        if not match:
            # 降级处理：如果没有匹配到，将全部内容作为一个 SUMMARY Chunk
            logger.warning("长摘要解析未匹配到标准格式，降级为单个梗概切片。")
            return [MemoryChunk(chunk_type=MemoryChunkType.SUMMARY, content=full_summary.strip())]
            
        summary_content = match.group(1).strip()
        facts_content = match.group(2).strip()
        
        # 1. 提取梗概
        if summary_content:
            chunks.append(MemoryChunk(chunk_type=MemoryChunkType.SUMMARY, content=summary_content))
            
        # 2. 提取关键事实
        if facts_content:
            # 去除可能的结尾分号，然后按分号拆分
            facts_str = facts_content.rstrip(';')
            raw_facts = facts_str.split(';')
            
            for raw_fact in raw_facts:
                raw_fact = raw_fact.strip()
                if not raw_fact:
                    continue
                    
                # 尝试去除序号前缀，如 "1." 或 "1. "
                fact_pattern = r"^\d+\.\s*(.*)"
                fact_match = re.match(fact_pattern, raw_fact)
                if fact_match:
                    clean_fact = fact_match.group(1).strip()
                else:
                    clean_fact = raw_fact
                    
                if clean_fact:
                    chunks.append(MemoryChunk(chunk_type=MemoryChunkType.FACT, content=clean_fact))
                    
    except Exception as e:
        logger.error(f"解析长摘要失败: {e}，降级为单个梗概切片。原文: {full_summary}")
        return [MemoryChunk(chunk_type=MemoryChunkType.SUMMARY, content=full_summary.strip())]
        
    # 兜底：如果拆出来是空的，至少返回全文
    if not chunks:
        logger.warning("拆分出的切片为空，降级为单个梗概切片。")
        chunks.append(MemoryChunk(chunk_type=MemoryChunkType.SUMMARY, content=full_summary.strip()))
        
    return chunks
