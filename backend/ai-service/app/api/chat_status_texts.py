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

    # ================================================================
    # 12. MCP 前置判断 (MCPIntentJudge)
    #     文案方向：Luna 在判断是否需要使用能力
    #     ================================================================
    (ChatStatusStage.MCP_INTENT_JUDGE, ChatStatusState.RUNNING): [
        "让Luna想想该用什么能力帮你……",
        "嗯……让Luna判断一下要不要动工具~",
        "Luna看看这情况需不需要召唤能力……",
        "等等……让Luna决定一下要不要动手~",
        "唔……Luna想想该不该上工具呢~",
    ],
    (ChatStatusStage.MCP_INTENT_JUDGE, ChatStatusState.COMPLETED): [
        "Luna想好了！让Luna来操作~",
        "行，Luna决定好了！",
        "嗯嗯，Luna知道该怎么搞了~",
        "好啦，Luna心里有数了！",
        "决定了！看Luna的~",
    ],

    # ================================================================
    # 13. MCP Skill 执行 (MCPSkillExecutionNode)
    #     文案方向：区分初筛->加载->执行三阶段的渐进感
    #     ================================================================
    (ChatStatusStage.MCP_SKILL_EXECUTION, ChatStatusState.RUNNING): [
        "让Luna找找哪个技能最合适……",
        "嗯……Luna翻翻技能库~",
        "让Luna挑挑看哪个技能最好使……",
        "唔……Luna看看有什么技能可用~",
        "让Luna选个最顺手的技能……",
    ],
    (ChatStatusStage.MCP_SKILL_EXECUTION, ChatStatusState.COMPLETED): [
        "好啦，Luna的技能搞定了！",
        "搞定~技能调用完毕！",
        "好啦好啦，Luna完事了！",
        "嗯嗯，Luna的技能用完了~",
        "行啦，Luna搞定了~",
    ],
    (ChatStatusStage.MCP_SKILL_EXECUTION, ChatStatusState.ERROR): [
        "唔……技能出了点岔子，不过Luna想想别的办法",
        "哎……技能没跑通……Luna换个方式",
        "技能调用失败了……没关系Luna能处理",
        "咦……技能没反应……Luna直接回你吧",
        "呼……技能没搞定，不过Luna还在！",
    ],

    # ================================================================
    # 14. MCP Skill 子阶段 — 初筛 (MCP_SKILL_SCREENING)
    #     文案方向：从技能库里挑最合适的
    #     ================================================================
    (ChatStatusStage.MCP_SKILL_SCREENING, ChatStatusState.RUNNING): [
        "让Luna找找哪个技能最合适……",
        "嗯……Luna翻翻技能库~",
        "让Luna挑挑看哪个技能最好使……",
        "唔……Luna看看有什么技能可用~",
        "让Luna选个最顺手的技能……",
    ],

    # ================================================================
    # 15. MCP Skill 子阶段 — 加载 (MCP_SKILL_LOADING)
    #     文案方向：展开技能详情，规划执行步骤
    #     ================================================================
    (ChatStatusStage.MCP_SKILL_LOADING, ChatStatusState.RUNNING): [
        "让Luna展开技能详情看看……",
        "嗯……Luna看看这个技能怎么用~",
        "让Luna翻翻技能的使用说明……",
        "唔……Luna看看这个技能有哪些工具……",
        "让Luna研究一下技能的具体用法~",
    ],

    # ================================================================
    # 16. MCP Skill 子阶段 — 资源加载 (MCP_SKILL_RESOURCE_LOADING)
    #     文案方向：翻阅文件资料
    #     ================================================================
    (ChatStatusStage.MCP_SKILL_RESOURCE_LOADING, ChatStatusState.RUNNING): [
        "Luna在读文件资料……",
        "让Luna翻翻相关的文件……",
        "嗯……Luna看看这些文件里有什么~",
        "Luna正在读取资料……稍等一下",
        "让Luna从文件里找找你需要的信息……",
    ],

    # ================================================================
    # 17. MCP Skill 子阶段 — 工具执行 (MCP_SKILL_TOOL_EXECUTING)
    #     文案方向：正在操作工具
    #     ================================================================
    (ChatStatusStage.MCP_SKILL_TOOL_EXECUTING, ChatStatusState.RUNNING): [
        "Luna开始干活了……共 {{ TOTAL_STEPS }} 步",
        "Luna动动手开始操作~",
        "让Luna操作一下……",
        "嗯……Luna正在搞这个~",
        "Luna开始执行了……",
    ],

    # ================================================================
    # 18. MCP Skill 子阶段 — 退回 (MCP_SKILL_FALLBACK)
    #     文案方向：换思路重试
    #     ================================================================
    (ChatStatusStage.MCP_SKILL_FALLBACK, ChatStatusState.RUNNING): [
        "唔……Luna换个思路试试",
        "嗯……这条路好像不对，Luna换一个~",
        "让Luna换个方式试试……",
        "等等……Luna觉得有更好的办法~",
        "不行不行，Luna换个思路！",
    ],

    # ================================================================
    # 19. MCP Skill 子阶段 — 执行进度 (复用 MCP_SKILL_TOOL_EXECUTING + CURRENT_STEP/STEP_GOAL)
    #     文案方向：显示具体步骤名称
    #     ================================================================

    # ================================================================
    # 20. MCP Skill 执行结果摘要 (MCP_SKILL_SUMMARY)
    #     文案方向：Luna 在整理和汇总执行结果时的自然过渡
    #     ================================================================
    (ChatStatusStage.MCP_SKILL_SUMMARY, ChatStatusState.RUNNING): [
        "让Luna把结果理一理……",
        "唔……Luna整理一下拿到的数据~",
        "让Luna捋一捋刚得到的结果……",
        "嗯……Luna在汇总执行结果~",
        "等一下，Luna整理一下信息……",
    ],
    (ChatStatusStage.MCP_SKILL_SUMMARY, ChatStatusState.COMPLETED): [
        "好啦，Luna整理好了！",
        "嗯嗯，Luna都梳理清楚了~",
        "搞定！Luna整理完了~",
        "好啦好啦，Luna总结完了！",
        "行，Luna搞明白了~",
    ],
}

# ================================================================
# 运行时拼接文案辅助函数
# ================================================================

def format_step_progress(current_step: int, total_steps: int, step_goal: str = "") -> str:
    """生成步骤执行进度文案。

    做什么：拼接当前执行步骤的进度文本。
    参数:
        current_step: 当前执行的步骤序号（从 1 开始）。
        total_steps: 总步骤数。
        step_goal: 当前步骤的执行目标。
    返回:
        str: 如 "Luna正在执行第 2/5 步：搜索项目文档"
    """
    goal_suffix = f"：{step_goal}" if step_goal else ""
    return f"Luna正在执行第 {current_step}/{total_steps} 步{goal_suffix}"


def format_execution_start(total_steps: int) -> str:
    """生成执行开始时的文案。"""
    return f"Luna开始干活了……共 {total_steps} 步"


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
