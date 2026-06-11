"""
MCP 信任与安全评估引擎。

做什么：对远程 MCP Server 进行安全风险评估和信誉评分，帮助用户判断
        哪些值得接入。评估维度包括：权限需求、代码审计情况、社区活跃度、
        维护周期、用户反馈等。
为什么这样做：未来真正有价值的不是 MCP 数量，而是哪些可以放心接入。
"""

from typing import Any


class TrustScorer:
    """MCP 信誉评分引擎。"""
    
    @staticmethod
    def calculate_trust_score(
        github_stars: int,
        last_commit_days: int,
        has_license: bool,
        security_flags: list[str],
        tool_count: int,
        install_count: int,
        report_count: int = 0,
    ) -> float:
        """
        计算 MCP Server 的信誉评分（0.00 ~ 1.00）。

        做什么：综合多个维度的数据计算出一个可比较的评分。
        为什么这样做：用户面对大量远程 MCP 时需要快速识别优质服务。
        """
        score = 0.5  # 基础分
        
        # GitHub Stars 影响力
        if github_stars >= 10000:
            score += 0.20
        elif github_stars >= 5000:
            score += 0.15
        elif github_stars >= 1000:
            score += 0.10
        elif github_stars >= 100:
            score += 0.05
            
        # 活跃度
        if last_commit_days <= 30:
            score += 0.10
        elif last_commit_days <= 90:
            score += 0.05
        elif last_commit_days > 365:
            score -= 0.10
            
        # 许可证
        if has_license:
            score += 0.05
            
        # 安全标记
        score -= len(security_flags) * 0.10
        
        # 用户接入量（社区验证）
        if install_count >= 500:
            score += 0.10
        elif install_count >= 100:
            score += 0.05
            
        # 举报扣分
        score -= report_count * 0.15
        
        return max(0.0, min(1.0, round(score, 2)))

    @staticmethod
    def analyze_security_flags(schema_response: dict[str, Any]) -> list[str]:
        """
        分析工具权限需求，生成安全标记。
        """
        flags = []
        tools = schema_response.get("tools", [])
        
        for tool in tools:
            name = tool.get("name", "").lower()
            desc = tool.get("description", "").lower()
            
            # 检测潜在的网络请求操作
            if any(k in name or k in desc for k in ["fetch", "request", "download", "http", "curl"]):
                if "network_access" not in flags:
                    flags.append("network_access")
                    
            # 检测潜在的文件修改操作
            if any(k in name or k in desc for k in ["write", "delete", "remove", "update", "modify"]):
                if "file_modification" not in flags:
                    flags.append("file_modification")
                    
            # 检测潜在的命令执行
            if any(k in name or k in desc for k in ["exec", "command", "shell", "run", "bash"]):
                if "command_execution" not in flags:
                    flags.append("command_execution")
                    
        return flags
