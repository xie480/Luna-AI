"""Chat 主链路 SSE 状态显示文本集中管理模块。

做什么：将散落在各 Workflow Node 中的拟人化 display_text 字符串全部集中于此，
        确保 Luna 的"口吻"统一管理、一处修改全局生效。
为什么这样做：严格遵循@/agent.md 6.1 第一条"禁止硬编码魔法字符串"的规定，
            同时便于文案迭代和润色，不至于修改一句话要翻 10 个文件。
边界条件：静默状态（is_visible=False）的 display_text 固定为空字符串，
        不在本模块中重复定义。非静默状态按 (stage, state) 双键索引。

口吻说明：所有文案严格遵循 @/backend/ai-service/app/prompt/simple/chat/system.j2
        中定义的 Luna 人格宪章：
        - 使用第三人称"Luna"自称（避免"我"）
        - 傲娇底色：嘴上不饶人、动作很体贴
        - 不完整句：留白是真实感的来源
        - 陪伴感：不是"服务"，而是"陪伴"
        - 对主人的默认称呼为"主人"
"""

from __future__ import annotations

from app.types.constants import ChatStatusStage, ChatStatusState


# ============================================================
# 状态文本映射表
# 键：(ChatStatusStage, ChatStatusState) → display_text
# 值：空字符串表示该状态组合不展示任何文案（静默通知）
# ============================================================
# 为什么用 dict 不用模块级常量：双键索引比按前缀命名更紧凑，
# 调用方只需一行 lookup 即可获取正确的文案，无需 switch/case。
_CHAT_STATUS_TEXTS: dict[tuple[ChatStatusStage, ChatStatusState], str] = {
    # ================================================================
    # 1. 输入重构与意图理解 (InputReconstructionNode)
    #    — "让我好好想想你说的……" 展现 Luna 认真的思考状态
    #    — "大概明白了" 带一点点不确定的余地，符合少女说话风格
    #    ================================================================
    (ChatStatusStage.INPUT_RECONSTRUCTION, ChatStatusState.RUNNING):
        "嗯，让我好好想想你说的……",
    (ChatStatusStage.INPUT_RECONSTRUCTION, ChatStatusState.COMPLETED):
        "嗯，大概明白了！",

    # ================================================================
    # 2. 会话上下文加载 (SessionContextLoadNode)
    #    — "看看之前说到哪儿了" 暗示 Luna 会认真回顾过去
    #    — "都记着呢" 带一点傲娇的"当然啦"语气
    #    ================================================================
    (ChatStatusStage.SESSION_CONTEXT_LOAD, ChatStatusState.RUNNING):
        "让Luna看看之前说到哪儿了……",
    (ChatStatusStage.SESSION_CONTEXT_LOAD, ChatStatusState.COMPLETED):
        "嗯，Luna都记着呢！",

    # ================================================================
    # 3. 长期记忆检索 (LongTermMemoryNode)
    #    — "翻翻之前的记忆" 拟人化翻阅动作
    #    — "找到了一些相关的回忆" 仿佛在记忆宝库里淘到了宝贝
    #    ================================================================
    (ChatStatusStage.RAG_RETRIEVAL, ChatStatusState.RUNNING):
        "唔，让我翻翻之前的记忆……",
    (ChatStatusStage.RAG_RETRIEVAL, ChatStatusState.COMPLETED):
        "找到了一些相关的回忆！",

    # ================================================================
    # 4. 用户画像注入 (UserProfileInjectionNode)
    #    — "当然记得主人的喜好" Luna 对主人的了解引以为傲
    #    — "知道你是什么样的主人" 带一点"我早就看透你了"的俏皮
    #    ================================================================
    (ChatStatusStage.USER_PROFILE_INJECTION, ChatStatusState.RUNNING):
        "Luna当然记得主人的喜好啦……",
    (ChatStatusStage.USER_PROFILE_INJECTION, ChatStatusState.COMPLETED):
        "好啦，Luna知道你是什么样的主人~",

    # ================================================================
    # 5. 知识库 RAG 检索 (KnowledgeRagNode)
    #    — "查查资料" 一种主动帮忙的语气
    #    — "找到了" 简短利落，带一点小得意
    #    ================================================================
    (ChatStatusStage.KNOWLEDGE_RAG, ChatStatusState.RUNNING):
        "等一下……Luna查查资料。",
    (ChatStatusStage.KNOWLEDGE_RAG, ChatStatusState.COMPLETED):
        "找到了！Luna给你看看……",

    # ================================================================
    # 6. 上下文治理 (ContextGovernanceNode)
    #    — "捋一捋" 生活化的表达，贴合少女用词习惯
    #    — "准备好了" 暗示接下来要正式回复了
    #    ================================================================
    (ChatStatusStage.CONTEXT_GOVERNANCE, ChatStatusState.RUNNING):
        "让Luna捋一捋……",
    (ChatStatusStage.CONTEXT_GOVERNANCE, ChatStatusState.COMPLETED):
        "好了，Luna准备好了！",

    # ================================================================
    # 7. Chat Prompt 装配 (PromptAssemblyNode)
    #    — "想想怎么跟你说" Luna 在斟酌措辞
    #    — "知道怎么回了" 信心满满，带一点小骄傲
    #    ================================================================
    (ChatStatusStage.CHAT_PROMPT_ASSEMBLY, ChatStatusState.RUNNING):
        "好啦好啦，让Luna想想怎么跟你说……",
    (ChatStatusStage.CHAT_PROMPT_ASSEMBLY, ChatStatusState.COMPLETED):
        "嗯，Luna知道怎么回了！",

    # ================================================================
    # 8. LLM 流式生成 (MainChatLlmNode)
    #    RUNNING + is_visible=False + is_terminal=True 用于清理前置状态，
    #    因此 display_text 固定为空字符串，不在此表中定义。
    #    ================================================================

    # ================================================================
    # 9. 回复持久化 (ResponsePersistenceNode)
    #    — "把你说的都记下来了" 展现 Luna 的细心
    #    — "记住了记住了" 带一点"知道啦别催"的撒娇感
    #    ================================================================
    (ChatStatusStage.RESPONSE_PERSISTENCE, ChatStatusState.RUNNING):
        "Luna把你说的都记下来了哦~",
    (ChatStatusStage.RESPONSE_PERSISTENCE, ChatStatusState.COMPLETED):
        "记住了记住了！",

    # ================================================================
    # 10. 结束归档 (FinalizeNode)
    #     仅发布 COMPLETED + is_visible=False + is_terminal=True 触发前端清理，
    #     display_text 固定为空字符串。
    #     ================================================================

    # ================================================================
    # 异常状态文案（ERROR）
    #     ERROR 状态的可见性取决于场景：
    #     - 输入重构等前端可感知的流程：可见，带安抚口吻
    #     - 后台降级（检索/治理）：不可见，静默处理
    #     ================================================================
    (ChatStatusStage.INPUT_RECONSTRUCTION, ChatStatusState.ERROR):
        "嗯……刚才有点走神，不过我还在！",
    (ChatStatusStage.SESSION_CONTEXT_LOAD, ChatStatusState.ERROR):
        "唔……刚刚没连上记忆库，不过不影响！",
    (ChatStatusStage.USER_PROFILE_INJECTION, ChatStatusState.ERROR):
        "唔……主人的资料Luna没读完整，不过不妨事！",

    # ================================================================
    # 跳过状态文案（SKIPPED）
    #     所有 SKIPPED 状态均为 is_visible=False 静默通知，
    #     display_text 固定为空字符串，不在此表中定义。
    #     ================================================================
}


def get_chat_status_text(stage: ChatStatusStage, state: ChatStatusState) -> str:
    """获取指定阶段和状态对应的显示文本。

    参数:
        stage: Chat 主链路执行阶段，对应 DAG 中的某个 node。
        state: 阶段执行状态（RUNNING / COMPLETED / ERROR 等）。

    返回:
        str: 对应 (stage, state) 的拟人化 display_text。
             若未找到映射则返回空字符串（静默兜底）。

    为什么不做 KeyError 向上抛出：
        所有 SKIPPED 及部分 ERROR 状态本就无需展示文案，
        返回空字符串是符合预期的默认行为，不应被调用方视为异常。
    """
    return _CHAT_STATUS_TEXTS.get((stage, state), "")
