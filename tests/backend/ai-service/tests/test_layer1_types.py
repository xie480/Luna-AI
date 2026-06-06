"""
第一阶段（Layer 1）综合测试

做什么：验证 Go backend/runtime/internal/types/* 和 utils/snowflake 的 Python 端口
     与原始 Go 实现在行为、常量值、边界条件上 100% 一致。

覆盖范围：
    - types/constants.py: 所有枚举常量定义与 Go 原版完全一致
    - types/errors.py: 错误码枚举、标准响应模型、工厂函数行为
    - utils/snowflake.py: 雪花算法 ID 生成（唯一性、单调递增、并发安全）

Go 原版参考文件：
    - backend/runtime/internal/types/constants.go
    - backend/runtime/internal/types/errors.go
    - backend/runtime/internal/utils/snowflake/snowflake.go
"""

import threading
from typing import Any

import pytest

from app.types.constants import (
    DagRouteHint,
    IntentCategory,
    PrimaryIntent,
    RetrievalType,
    Role,
)
from app.types.errors import (
    ErrorCode,
    ResponseModel,
    create_error_response,
    create_success_response,
)
from app.utils.snowflake import Snowflake, generate_id, generate_string_id, init_global_node


# ============================================================
# 1. Role 枚举测试
# ============================================================

class TestRole:
    """验证 Role 枚举与 Go constants.go 完全一致"""

    def test_role_user(self) -> None:
        """Go: RoleUser = "user" """
        assert Role.USER.value == "user"

    def test_role_assistant(self) -> None:
        """Go: RoleAssistant = "assistant" """
        assert Role.ASSISTANT.value == "assistant"

    def test_role_system(self) -> None:
        """Go: RoleSystem = "system" """
        assert Role.SYSTEM.value == "system"

    def test_all_roles_exist(self) -> None:
        """所有 Go 中定义的 Role 必须全部存在，无冗余"""
        expected = {"user", "assistant", "system"}
        actual = {r.value for r in Role}
        assert actual == expected, f"Role 枚举不匹配，差异: {expected ^ actual}"


# ============================================================
# 2. PrimaryIntent 枚举测试
# ============================================================

class TestPrimaryIntent:
    """验证 PrimaryIntent 枚举与 Go constants.go 完全一致"""

    def test_values(self) -> None:
        """Go 定义的 6 种 PrimaryIntent 值"""
        assert PrimaryIntent.MODIFY_PLAN.value == "MODIFY_PLAN"
        assert PrimaryIntent.GREETING.value == "GREETING"
        assert PrimaryIntent.QUERY_INFO.value == "QUERY_INFO"
        assert PrimaryIntent.EMOTION_VENTING.value == "EMOTION_VENTING"
        assert PrimaryIntent.SYSTEM_COMMAND.value == "SYSTEM_COMMAND"
        assert PrimaryIntent.TOOL_INVOCATION.value == "TOOL_INVOCATION"

    def test_valid_intents_match_go(self) -> None:
        """Go ValidPrimaryIntents() 返回的字符串列表必须完全相同"""
        expected = [
            "MODIFY_PLAN",
            "GREETING",
            "QUERY_INFO",
            "EMOTION_VENTING",
            "SYSTEM_COMMAND",
            "TOOL_INVOCATION",
        ]
        actual = [i.value for i in PrimaryIntent]
        assert actual == expected, f"PrimaryIntent 顺序/值不匹配"


# ============================================================
# 3. IntentCategory 枚举测试
# ============================================================

class TestIntentCategory:
    """验证 IntentCategory 枚举与 Go constants.go 完全一致"""

    def test_values(self) -> None:
        """Go 定义的 4 种 IntentCategory 值"""
        assert IntentCategory.TASK_MANAGEMENT.value == "TASK_MANAGEMENT"
        assert IntentCategory.CHAT.value == "CHAT"
        assert IntentCategory.KNOWLEDGE_QUERY.value == "KNOWLEDGE_QUERY"
        assert IntentCategory.EMOTION_SUPPORT.value == "EMOTION_SUPPORT"

    def test_valid_categories_match_go(self) -> None:
        """Go ValidIntentCategories() 返回的字符串列表必须完全相同"""
        expected = [
            "TASK_MANAGEMENT",
            "CHAT",
            "KNOWLEDGE_QUERY",
            "EMOTION_SUPPORT",
        ]
        actual = [c.value for c in IntentCategory]
        assert actual == expected


# ============================================================
# 4. DagRouteHint 枚举测试
# ============================================================

class TestDagRouteHint:
    """验证 DagRouteHint 枚举与 Go constants.go 完全一致"""

    def test_values(self) -> None:
        """Go 定义的 4 种 DagRouteHint 值"""
        assert DagRouteHint.MULTI_SOURCE_RETRIEVAL_WORKFLOW.value == "MULTI_SOURCE_RETRIEVAL_WORKFLOW"
        assert DagRouteHint.FAST_CHAT.value == "FAST_CHAT"
        assert DagRouteHint.AGENTIC_WORKFLOW.value == "AGENTIC_WORKFLOW"
        assert DagRouteHint.GATING_APPROVAL.value == "GATING_APPROVAL"

    def test_valid_hints_match_go(self) -> None:
        """Go ValidDagRouteHints() 返回的字符串列表必须完全相同"""
        expected = [
            "MULTI_SOURCE_RETRIEVAL_WORKFLOW",
            "FAST_CHAT",
            "AGENTIC_WORKFLOW",
            "GATING_APPROVAL",
        ]
        actual = [h.value for h in DagRouteHint]
        assert actual == expected


# ============================================================
# 5. RetrievalType 枚举测试
# ============================================================

class TestRetrievalType:
    """验证 RetrievalType 枚举与 Go constants.go 完全一致"""

    def test_values(self) -> None:
        """Go 定义的 3 种 RetrievalType 值"""
        assert RetrievalType.LONG_TERM_MEMORY.value == "LONG_TERM_MEMORY"
        assert RetrievalType.EXTERNAL_KNOWLEDGE.value == "EXTERNAL_KNOWLEDGE"
        assert RetrievalType.EXPERIENCE_REFLECTION.value == "EXPERIENCE_REFLECTION"

    def test_valid_types_match_go(self) -> None:
        """Go ValidRetrievalTypes() 返回的字符串列表必须完全相同"""
        expected = [
            "LONG_TERM_MEMORY",
            "EXTERNAL_KNOWLEDGE",
            "EXPERIENCE_REFLECTION",
        ]
        actual = [r.value for r in RetrievalType]
        assert actual == expected


# ============================================================
# 6. ErrorCode 枚举测试
# ============================================================

class TestErrorCode:
    """验证 ErrorCode 枚举与 Go errors.go 完全一致"""

    def test_success(self) -> None:
        """Go: CodeSuccess ErrorCode = 0"""
        assert ErrorCode.SUCCESS.value == 0

    def test_system_error(self) -> None:
        """Go: CodeSystemError ErrorCode = 1000"""
        assert ErrorCode.SYSTEM_ERROR.value == 1000

    def test_config_load_failed(self) -> None:
        """Go: CodeConfigLoadFailed ErrorCode = 1001"""
        assert ErrorCode.CONFIG_LOAD_FAILED.value == 1001

    def test_db_connect_failed(self) -> None:
        """Go: CodeDBConnectFailed ErrorCode = 1002"""
        assert ErrorCode.DB_CONNECT_FAILED.value == 1002

    def test_business_error(self) -> None:
        """Go: CodeBusinessError ErrorCode = 2000"""
        assert ErrorCode.BUSINESS_ERROR.value == 2000

    def test_state_invalid(self) -> None:
        """Go: CodeStateInvalid ErrorCode = 2001"""
        assert ErrorCode.STATE_INVALID.value == 2001

    def test_permission_denied(self) -> None:
        """Go: CodePermissionDenied ErrorCode = 2002"""
        assert ErrorCode.PERMISSION_DENIED.value == 2002

    def test_external_error(self) -> None:
        """Go: CodeExternalError ErrorCode = 3000"""
        assert ErrorCode.EXTERNAL_ERROR.value == 3000

    def test_llm_call_failed(self) -> None:
        """Go: CodeLLMCallFailed ErrorCode = 3001"""
        assert ErrorCode.LLM_CALL_FAILED.value == 3001

    def test_tool_execute_failed(self) -> None:
        """Go: CodeToolExecuteFailed ErrorCode = 3002"""
        assert ErrorCode.TOOL_EXECUTE_FAILED.value == 3002

    def test_all_codes_match_go(self) -> None:
        """验证所有错误码的值与 Go 完全一致（按代码段分组）"""
        # 成功
        assert ErrorCode.SUCCESS.value == 0

        # 系统级错误 (1000-1999)
        assert ErrorCode.SYSTEM_ERROR.value == 1000
        assert ErrorCode.CONFIG_LOAD_FAILED.value == 1001
        assert ErrorCode.DB_CONNECT_FAILED.value == 1002

        # 业务逻辑错误 (2000-2999)
        assert ErrorCode.BUSINESS_ERROR.value == 2000
        assert ErrorCode.STATE_INVALID.value == 2001
        assert ErrorCode.PERMISSION_DENIED.value == 2002

        # 外部依赖错误 (3000-3999)
        assert ErrorCode.EXTERNAL_ERROR.value == 3000
        assert ErrorCode.LLM_CALL_FAILED.value == 3001
        assert ErrorCode.TOOL_EXECUTE_FAILED.value == 3002


# ============================================================
# 7. ResponseModel 与工厂函数测试
# ============================================================

class TestResponseModel:
    """验证 ResponseModel 与 Go errors.go 中的 Response 结构完全一致"""

    def test_success_response_structure(self) -> None:
        """Go: NewSuccessResponse 创建成功响应"""
        resp = create_success_response({"key": "value"}, "trace-123")
        assert isinstance(resp, ResponseModel)
        assert resp.code == ErrorCode.SUCCESS.value  # 0
        assert resp.msg == "success"
        assert resp.data == {"key": "value"}
        assert resp.trace_id == "trace-123"

    def test_error_response_structure(self) -> None:
        """Go: NewErrorResponse 创建错误响应"""
        resp = create_error_response(ErrorCode.SYSTEM_ERROR, "系统错误", "trace-456")
        assert isinstance(resp, ResponseModel)
        assert resp.code == ErrorCode.SYSTEM_ERROR.value  # 1000
        assert resp.msg == "系统错误"
        assert resp.data is None
        assert resp.trace_id == "trace-456"

    def test_response_model_serializable(self) -> None:
        """验证 ResponseModel 可以通过 model_dump() 序列化为 JSON 兼容 dict"""
        resp = create_success_response([1, 2, 3], "trace-serial")
        dumped = resp.model_dump()
        assert isinstance(dumped, dict)
        assert dumped["code"] == 0
        assert dumped["msg"] == "success"
        assert dumped["data"] == [1, 2, 3]
        assert dumped["trace_id"] == "trace-serial"

    def test_error_response_with_different_codes(self) -> None:
        """验证所有错误码都能正确生成响应"""
        for code in ErrorCode:
            resp = create_error_response(code, f"测试 {code.name}", "trace")
            assert resp.code == code.value
            assert resp.msg == f"测试 {code.name}"
            assert resp.data is None


# ============================================================
# 8. 雪花算法 ID 生成器测试
# ============================================================

class TestSnowflake:
    """
    验证 Snowflake 实现与 Go snowflake.go 完全一致。

    Go 原版关键行为：
    - Epoch: 1704067200000 (2024-01-01 00:00:00 UTC)
    - NodeBits: 10, SequenceBits: 12
    - TimestampShift: 22, NodeShift: 12
    - 序列号溢出时自旋等待下一毫秒
    - 全局单例：InitGlobalNode / GenerateID / GenerateStringID
    """

    def test_unique_ids(self) -> None:
        """Go: TestSnowflake - 两次 Generate 产生不同 ID，且单调递增"""
        node = Snowflake(1)
        id1 = node.generate()
        id2 = node.generate()

        assert id1 != id2, "生成的 ID 相同，违反唯一性"
        assert id1 < id2, "ID 不是单调递增的"

    def test_invalid_node_id_negative(self) -> None:
        """Go: 节点 ID 小于 0 抛出错误"""
        with pytest.raises(ValueError, match="Node ID must be between 0 and 1023"):
            Snowflake(-1)

    def test_invalid_node_id_overflow(self) -> None:
        """Go: 节点 ID 大于 1023 抛出错误"""
        with pytest.raises(ValueError, match="Node ID must be between 0 and 1023"):
            Snowflake(1024)

    def test_node_id_zero_boundary(self) -> None:
        """Go: 节点 ID 为 0（边界值）应该正常工作"""
        node = Snowflake(0)
        id1 = node.generate()
        id2 = node.generate()
        assert id1 != id2

    def test_node_id_max_boundary(self) -> None:
        """Go: 节点 ID 为 1023（边界值）应该正常工作"""
        node = Snowflake(1023)
        id1 = node.generate()
        id2 = node.generate()
        assert id1 != id2

    def test_concurrency(self) -> None:
        """
        Go: TestSnowflakeConcurrency - 100 goroutines, 1000 IDs each = 100000 IDs
        验证并发安全：无重复 ID，等于预期总数
        """
        node = Snowflake(1)
        num_threads = 100
        ids_per_thread = 1000

        generated_ids: list[int] = []
        lock = threading.Lock()

        def generate_worker() -> None:
            local_ids = [node.generate() for _ in range(ids_per_thread)]
            with lock:
                generated_ids.extend(local_ids)

        threads = []
        for _ in range(num_threads):
            t = threading.Thread(target=generate_worker)
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        expected_total = num_threads * ids_per_thread
        assert len(generated_ids) == expected_total, (
            f"预期 {expected_total} 个 ID，实际 {len(generated_ids)}"
        )
        assert len(set(generated_ids)) == expected_total, (
            f"存在重复 ID，唯一数 {len(set(generated_ids))} < 总数 {expected_total}"
        )

    def test_global_node(self) -> None:
        """Go: TestGlobalNode - 全局单例的 InitGlobalNode / GenerateID / GenerateStringID"""
        init_global_node(2)

        id1 = generate_id()
        id2 = generate_id()

        assert id1 != id2, "全局节点生成了重复 ID"
        assert isinstance(id1, int), f"GenerateID 返回类型不是 int，而是 {type(id1)}"

        str_id = generate_string_id()
        assert isinstance(str_id, str), f"GenerateStringID 返回类型不是 str，而是 {type(str_id)}"
        assert len(str_id) > 0, "GenerateStringID 返回了空字符串"
        # 验证字符串可以解析回整数
        parsed = int(str_id)
        assert parsed > 0, f"GenerateStringID 无法解析回正整数: {str_id}"

    def test_id_structure(self) -> None:
        """
        验证生成的 ID 结构符合雪花算法定义：
        - 正数（最高位为 0）
        - 可以通过位移解析出时间戳、节点 ID、序列号
        """
        import time

        node = Snowflake(1)
        before = int(time.time() * 1000)
        id_ = node.generate()
        after = int(time.time() * 1000)

        # 验证 ID 为正数（最高位为 0）
        assert id_ > 0, f"ID {id_} 不是正数"

        # 验证 ID 在 64 位范围内
        assert id_ <= 0x7FFFFFFFFFFFFFFF, f"ID {id_} 超出 64 位有符号整数范围"

        # 解析时间戳
        timestamp = (id_ >> 22) + node.EPOCH
        assert before <= timestamp <= after + 1, (
            f"解析出的时间戳 {timestamp} 不在预期范围 [{before}, {after}]"
        )

        # 解析节点 ID
        parsed_node = (id_ >> 12) & 0x3FF  # 10 bits mask
        assert parsed_node == 1, f"解析出的节点 ID {parsed_node} 不等于 1"

        # 解析序列号
        parsed_seq = id_ & 0xFFF  # 12 bits mask
        assert 0 <= parsed_seq <= 4095, f"序列号 {parsed_seq} 超出范围 0-4095"

    def test_default_fallback_node(self) -> None:
        """Go: GenerateID 未调用 InitGlobalNode 时使用节点 1 作为默认值"""
        # 重新导入以重置全局状态
        import importlib
        import app.utils.snowflake as sf_module
        importlib.reload(sf_module)

        # 不调用 init_global_node，直接调用 generate_id
        id_ = sf_module.generate_id()
        assert id_ > 0

        # 验证节点 ID 为 1（默认 fallback）
        parsed_node = (id_ >> 12) & 0x3FF
        assert parsed_node == 1, f"默认 fallback 节点不是 1，而是 {parsed_node}"


# 引入 threading（在文件顶部条件导入以避免 lint 警告）
import threading
