"""Chat 主链路 SSE 状态显示文本集中管理模块 

做什么：将散落在各 Workflow Node 中的拟人化 display_text 字符串全部集中于此，
        每个 (stage, state) 提供 5 条变体文案，推送时随机选取一条，避免重复感 
为什么这样做：严格遵循@/agent.md 6.1 第一条"禁止硬编码魔法字符串"的规定，
            同时文案迭代和润色集中一处，不用翻 10 个文件 
边界条件：静默状态（is_visible=False）的 display_text 固定为空字符串，
        不在本模块中重复定义 非静默状态按 (stage, state) 双键索引到列表 

口吻说明：所有文案严格遵循 @/backend/ai-service/app/prompt/simple/chat/system.j2
        中定义的 Luna 人格宪章：
        - 使用第三人称"Luna"自称（避免"我"）
        - 傲娇底色：嘴上不饶人、动作很体贴
        - 不完整句：留白是真实感的来源
        - 陪伴感：不是"服务"，而是"陪伴"
        - 对主人的默认称呼为"主人"
"""

from __future__ import annotations

import random

from app.types.constants import ChatStatusStage, ChatStatusState


# ============================================================
# 状态文本映射表
# 键：(ChatStatusStage, ChatStatusState) → list[str]
# 值：包含 5 条变体文案的列表，推送时随机选取一条 
#     空列表表示该状态组合不展示任何文案（静默通知） 
# ============================================================
# 为什么用 dict[tuple, list] 不用单条字符串：
# 单次对话中同一个阶段可能反复出现（如多轮对话每轮都走输入重构），
# 5 条变体搭配随机选取能大幅降低用户"看腻了"的感知 
_CHAT_STATUS_TEXTS: dict[tuple[ChatStatusStage, ChatStatusState], list[str]] = {

    # ================================================================
    # 1. 输入重构与意图理解 (InputReconstructionNode)
    #    文案方向：认真思考、微微停顿，展现 Luna 在努力理解主人 
    #    ================================================================
    (ChatStatusStage.INPUT_RECONSTRUCTION, ChatStatusState.RUNNING): [
        "嗯，让Luna好好想想你说的……",
        "让Luna想想这是什么意思……",
        "唔……Luna在认真听呢，",
        "等一下，让Luna理解一下……",
        "让Luna猜猜你到底想说什么~",
    ],
    (ChatStatusStage.INPUT_RECONSTRUCTION, ChatStatusState.COMPLETED): [
        "嗯，Luna大概明白了 ",
        "好啦，Luna知道你想问什么了！",
        "原来是这么回事，Luna懂了~",
        "行啦，Luna清楚了~",
        "嗯嗯，Luna明白了！",
    ],
    (ChatStatusStage.INPUT_RECONSTRUCTION, ChatStatusState.ERROR): [
        "还有……Luna刚才有点走神，不过Luna还在！",
        "唔……Luna没完全读懂，但Luna会努力回的~",
        "有点迷糊……不过不管了，Luna先回你！",
        "让Luna想想……算了算了不管了！",
        "嗯……Luna没太理解，不过Luna先答着~",
    ],

    # ================================================================
    # 2. 会话上下文加载 (SessionContextLoadNode)
    #    文案方向：翻阅记录、回忆前文，带一点点"Luna有在认真听"的傲娇 
    #    ================================================================
    (ChatStatusStage.SESSION_CONTEXT_LOAD, ChatStatusState.RUNNING): [
        "让Luna看看之前说到哪儿了……",
        "唔……Luna找找你之前说了什么……",
        "等一下，Luna翻翻刚才的记录……",
        "让Luna回忆一下刚才的对话……",
        "Luna翻一翻之前聊到哪儿了……",
    ],
    (ChatStatusStage.SESSION_CONTEXT_LOAD, ChatStatusState.COMPLETED): [
        "嗯，Luna都记着呢！",
        "Luna想起来了，继续继续~",
        "好嘞，Luna记得！",
        "找到了，Luna记得之前的事~",
        "嗯嗯，Luna都记得哦~",
    ],
    (ChatStatusStage.SESSION_CONTEXT_LOAD, ChatStatusState.ERROR): [
        "唔……刚刚没连上记忆库，不过不影响！",
        "哼，Luna一下子想不起来……算了直接来吧",
        "记忆库有点卡……不管了Luna直接回你！",
        "啊……Luna没找到之前的记录，直接开始~",
        "刚刚断了一下……没事Luna凭感觉回你！",
    ],

    # ================================================================
    # 3. 长期记忆检索 (LongTermMemoryNode)
    #    文案方向：翻阅记忆的画面感，找到回忆的惊喜感 
    #    ================================================================
    (ChatStatusStage.RAG_RETRIEVAL, ChatStatusState.RUNNING): [
        "唔，让Luna翻翻之前的记忆……",
        "让Luna找找你之前说过什么……",
        "嗯……Luna在翻你以前的回忆呢",
        "等一下，Luna记得你之前说过什么来着……",
        "让Luna翻一翻脑袋里的记忆~",
    ],
    (ChatStatusStage.RAG_RETRIEVAL, ChatStatusState.COMPLETED): [
        "Luna找到了一些相关的回忆！",
        "找到了！Luna记得！",
        "嗯嗯，Luna想起来了~",
        "啊——Luna记得你说过！",
        "哦！Luna想起来了，是这个！",
    ],

    # ================================================================
    # 4. 用户画像注入 (UserProfileInjectionNode)
    #    文案方向："Luna对主人很了解"的底气和微微傲娇 
    #    ================================================================
    (ChatStatusStage.USER_PROFILE_INJECTION, ChatStatusState.RUNNING): [
        "Luna当然记得你是什么样的主人啦……",
        "让Luna想一下你喜欢什么……",
        "嗯……Luna印象里的主人是……",
        "等等，Luna记得你的喜好来着……",
        "让Luna回忆一下你这个人……",
    ],
    (ChatStatusStage.USER_PROFILE_INJECTION, ChatStatusState.COMPLETED): [
        "好啦，Luna知道你是什么样的主人~",
        "嗯嗯，Luna懂的！",
        "好啦，Luna知道该怎么跟你说话了~",
        "行啦，Luna心里有数了~",
        "嗯，Luna了解你~",
    ],
    (ChatStatusStage.USER_PROFILE_INJECTION, ChatStatusState.ERROR): [
        "唔……主人的资料Luna没读完整，不过没事啦！",
        "哼……Luna一下子没想起来，不过不影响！",
        "啊……Luna忘了一些……算了算了！",
        "没查到什么……不过不重要！",
        "Luna没翻到你的资料……那Luna凭感觉来吧！",
    ],

    # ================================================================
    # 5. 知识库 RAG 检索 (KnowledgeRagNode)
    #    文案方向：主动帮忙查资料的积极感 
    #    ================================================================
    (ChatStatusStage.KNOWLEDGE_RAG, ChatStatusState.RUNNING): [
        "等一下……Luna查查资料 ",
        "让Luna去翻翻知识库……",
        "嗯……Luna找找相关的资料……",
        "你等一下，Luna去查查~",
        "唔Luna查一下……别急~",
    ],
    (ChatStatusStage.KNOWLEDGE_RAG, ChatStatusState.COMPLETED): [
        "找到了！Luna给你看看……",
        "查到了查到了！",
        "找到了，让Luna告诉你~",
        "哦——找到了！你听Luna说~",
        "有啦！Luna找到了~",
    ],

    # ================================================================
    # 6. 上下文治理 (ContextGovernanceNode)
    #    文案方向：整理思绪、理顺信息的认真感 
    #    ================================================================
    (ChatStatusStage.CONTEXT_GOVERNANCE, ChatStatusState.RUNNING): [
        "让Luna捋一捋……",
        "等等让Luna理一下思路……",
        "嗯……Luna整理一下这些信息……",
        "让Luna串一串这些东西……",
        "唔……Luna把脑子里的东西整理一下~",
    ],
    (ChatStatusStage.CONTEXT_GOVERNANCE, ChatStatusState.COMPLETED): [
        "好了，Luna准备好了！",
        "行行行……Luna理清楚了！",
        "好啦，Luna知道怎么说了~",
        "嗯嗯，Luna心里有谱了",
        "好啦好啦，Luna搞定了~",
    ],

    # ================================================================
    # 7. Chat Prompt 装配 (PromptAssemblyNode)
    #    文案方向：最后酝酿阶段，即将开口的微妙停顿 
    #    ================================================================
    (ChatStatusStage.CHAT_PROMPT_ASSEMBLY, ChatStatusState.RUNNING): [
        "好啦好啦，让Luna想想怎么跟你说……",
        "让Luna想想该怎么回你……",
        "等等，Luna酝酿一下……",
        "让Luna组织一下语言……",
        "唔……让Luna想想怎么开口……",
    ],
    (ChatStatusStage.CHAT_PROMPT_ASSEMBLY, ChatStatusState.COMPLETED): [
        "嗯，Luna知道怎么回了！",
        "好啦，Luna要说了哦~",
        "嗯嗯，Luna想好了！",
        "行，Luna准备好了~",
        "好啦，Luna想好怎么说了！",
    ],

    # ================================================================
    # 8. LLM 流式生成 (MainChatLlmNode)
    #    文案方向：数据流正向本地输出的科技感，与 §1.1 "神经连结供能" 主题对应
    #    注意：首个 chunk 到达时的状态推送 is_visible=True, is_terminal=False，
    #    确保整个流式生成期间状态栏持续保持在激活态，不会提前被清理。
    #    ================================================================
    (ChatStatusStage.LLM_STREAMING, ChatStatusState.RUNNING): [
        "神经连结供能中...",
        "正在具象化思维流...",
        "数据链路已建立，正在同步...",
        "正在构建回复链路...",
        "输出数据流已建立...",
    ],
    (ChatStatusStage.LLM_STREAMING, ChatStatusState.COMPLETED): [
        "回复已就绪，正在呈递...",
        "流式传输完成~",
        "数据同步完毕！",
    ],
    (ChatStatusStage.LLM_STREAMING, ChatStatusState.ERROR): [
        "神经连结断开，正在尝试恢复...",
        "数据流中断了...",
        "信号丢失……Luna正在重连...",
    ],

    # ================================================================
    # 9. 回复持久化 (ResponsePersistenceNode)
    #    文案方向：写进记忆的安心感，带一点撒娇 
    #    ================================================================
    (ChatStatusStage.RESPONSE_PERSISTENCE, ChatStatusState.RUNNING): [
        "Luna把你说的都记下来了哦~",
        "让Luna把这些存起来……",
        "嗯嗯，Luna存好了~",
        "不让Luna记住啦~",
        "Luna都写进小本本了~",
    ],
    (ChatStatusStage.RESPONSE_PERSISTENCE, ChatStatusState.COMPLETED): [
        "Luna记住了记住了！",
        "好啦，Luna存好了~",
        "嗯嗯，Luna都记住了哦~",
        "存好啦存好啦~",
        "记住了！Luna不会忘的！",
    ],

    # ================================================================
    # 10. 结束归档 (FinalizeNode)
    #     仅发布 COMPLETED + is_visible=False + is_terminal=True 触发前端清理，
    #     display_text 固定为空字符串
    #     ================================================================

    # ================================================================
    # 11. MCP 工具执行 (MCPToolExecutionNode)
    #     文案方向：Luna 在"用工具办事"时的实感
    #     ================================================================
    (ChatStatusStage.MCP_TOOL_EXECUTION, ChatStatusState.RUNNING): [
        "让Luna用个小工具帮你查一下……",
        "等一下，Luna 调用一下工具~",
        "让Luna用工具搞一下……别急别急",
        "嗯……Luna 找个工具来帮忙",
        "Luna动动手指查一下~",
    ],
    (ChatStatusStage.MCP_TOOL_EXECUTION, ChatStatusState.COMPLETED): [
        "好啦，Luna 搞定了！",
        "查到了查到了！让Luna告诉你~",
        "搞定~工具返回结果了",
        "好啦，Luna拿到数据了！",
        "嗯嗯，Luna查到了~",
    ],
    (ChatStatusStage.MCP_TOOL_EXECUTION, ChatStatusState.ERROR): [
        "唔……工具出了点小问题，不过Luna还在！",
        "啊……工具好像没反应……Luna换个方式回你",
        "工具报错了……不过没关系Luna能处理",
        "咦……工具没跑通……Luna想想别的办法",
        "呼……工具调用失败了，Luna直接回你~",
    ],
}


def get_chat_status_text(stage: ChatStatusStage, state: ChatStatusState) -> str:
    """获取指定阶段和状态对应的随机显示文本 

    参数:
        stage: Chat 主链路执行阶段，对应 DAG 中的某个 node 
        state: 阶段执行状态（RUNNING / COMPLETED / ERROR 等） 

    返回:
        str: 从对应 (stage, state) 的 5 条变体中随机选取一条 display_text 
             若未找到映射则返回空字符串（静默兜底） 

    为什么不做 KeyError 向上抛出：
        所有 SKIPPED 及部分 ERROR 状态本就无需展示文案，
        返回空字符串是符合预期的默认行为，不应被调用方视为异常 

    随机策略说明：
        使用 random.choice() 做每次调用的均匀随机选取 
        因为 ChatStatusPublisher 每次 publish 都会调用一次此函数，
        同一消息的不同阶段之间自然会输出不同的变体，无需额外状态跟踪 
    """
    variants = _CHAT_STATUS_TEXTS.get((stage, state))
    if not variants:
        return ""
    return random.choice(variants)
