"""后处理提交节点实现。"""

from typing import Dict, Any, Optional
from app.workflow.nodes.base import ChatWorkflowNode
from app.workflow.constants import ChatWorkflowNodeType


class PostprocessCommitNode(ChatWorkflowNode):
    """后处理提交节点 - 处理工作流的最终结果并执行提交操作。"""
    
    def __init__(self, node_id: str, config: Optional[Dict[str, Any]] = None):
        """初始化后处理提交节点。
        
        Args:
            node_id: 节点唯一标识符
            config: 节点配置参数
        """
        super().__init__(node_type=ChatWorkflowNodeType.POSTPROCESS_COMMIT)
        self.node_id = node_id
        self.config = config or {}
    
    async def __call__(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """执行后处理和提交操作。
        
        Args:
            context: 工作流上下文
            
        Returns:
            更新后的上下文
        """
        # 在这里实现后处理逻辑
        # 例如：格式化输出、持久化结果、清理资源等
        
        # 标记流程已完成
        context.setdefault("execution_log", []).append({
            "node_id": self.node_id,
            "status": "completed",
            "output_keys": list(context.keys())
        })
        
        return context