"""
Luna AI WebSocket 服务模块

做什么：封装 FastAPI WebSocket 路由及连接管理器。
为什么这样做：处理前端与后端的实时双向通信，包括聊天、状态同步等。
输入输出：
    - WSServer: WebSocket 服务类
边界条件：
    - 异步处理聊天请求，避免阻塞读循环
    - 并发安全地写入 JSON 数据
异常行为：
    - 解析消息失败时返回错误响应
"""

import asyncio
import json
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from app.logger import logger
from app.memory.manager import Manager as MemoryManager
from app.memory.manager import MemoryEvent, MemoryEventType
from app.prompt.manager import Manager as PromptManager
from app.prompt.types import PromptCategory
from app.repository.chat_history_pg import ChatHistoryPGRepo
from app.repository.chat_history_redis import ChatHistoryRedisRepo, ChatSummary, Interaction
from app.repository.models import InteractionModel
from app.types.constants import (
    WS_MSG_TYPE_CHAT_STREAM,
    WS_MSG_TYPE_CMD_SYNC_INIT_STATE,
    WS_MSG_TYPE_CMD_USER_INPUT,
    WS_MSG_TYPE_ERROR,
    WS_MSG_TYPE_EVT_INIT_STATE,
    WS_MSG_TYPE_EVT_MEMORY_SYNC,
    WS_MSG_TYPE_PING,
    WS_MSG_TYPE_PONG,
    WS_MSG_TYPE_REQ_GET_CALENDAR_METADATA,
    WS_MSG_TYPE_REQ_GET_CHAT_HISTORY,
    WS_MSG_TYPE_RES_CALENDAR_METADATA,
    WS_MSG_TYPE_RES_CHAT_HISTORY,
    Role,
)
from app.utils.snowflake import generate_string_id

router = APIRouter()


class WSMessage(BaseModel):
    """定义 WebSocket 消息结构"""
    type: str
    trace_id: str
    payload: Any


class PingPayload(BaseModel):
    """定义 Ping 消息的 Payload"""
    timestamp: int


class PongPayload(BaseModel):
    """定义 Pong 消息的 Payload"""
    timestamp: int
    source: str


class ErrorPayload(BaseModel):
    """定义 Error 消息的 Payload"""
    code: int
    message: str


class ChatMessage(BaseModel):
    """定义单条对话消息"""
    role: str
    content: str
    thought: str = ""


class CMDUserInputPayload(BaseModel):
    """定义前端 CMD_USER_INPUT 消息的 Payload"""
    sessionId: str
    message: str
    msgId: str
    history: List[ChatMessage] = []


class ChatStreamPayload(BaseModel):
    """定义 Chat 流式响应的 Payload"""
    type: str
    chunk: str
    is_finished: bool
    node_id: str
    error: str = ""


class InteractionQA(BaseModel):
    """用于前端展示的单轮问答结构"""
    msgId: str
    userContent: str
    assistantContent: str
    timestamp: int


class InitStatePayload(BaseModel):
    """定义前端 EVT_INIT_STATE 消息的 Payload"""
    sessionId: str
    recentQA: List[InteractionQA]


class MemorySyncPayload(BaseModel):
    """定义 EVT_MEMORY_SYNC 消息的 Payload"""
    sessionId: str
    memoryId: str
    status: str


class WSConnection:
    """封装 WebSocket，提供并发安全的写操作"""
    def __init__(self, websocket: WebSocket):
        self.ws = websocket
        self.lock = asyncio.Lock()

    async def write_json(self, data: Dict[str, Any]) -> None:
        """并发安全地写入 JSON 数据"""
        async with self.lock:
            await self.ws.send_json(data)

    async def close(self) -> None:
        """关闭连接"""
        await self.ws.close()

    @property
    def remote_addr(self) -> str:
        """获取远程地址"""
        if self.ws.client:
            return f"{self.ws.client.host}:{self.ws.client.port}"
        return "unknown"


class WSServer:
    """封装 WebSocket 服务"""

    def __init__(
        self,
        redis_repo: Optional[ChatHistoryRedisRepo] = None,
        pg_repo: Optional[ChatHistoryPGRepo] = None,
        prompt_mgr: Optional[PromptManager] = None,
        memory_manager: Optional[MemoryManager] = None,
    ):
        self.redis_repo = redis_repo
        self.pg_repo = pg_repo
        self.prompt_mgr = prompt_mgr
        self.memory_manager = memory_manager
        
        self.clients: set[WSConnection] = set()
        self.clients_lock = asyncio.Lock()
        self.background_tasks: set[asyncio.Task] = set()

        # 注册记忆事件监听
        if self.memory_manager:
            # 使用 asyncio.create_task 包装以避免阻塞
            async def _register():
                await self.memory_manager.on_event(self.handle_memory_event)
            
            # 在事件循环中运行
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(_register())
            except RuntimeError:
                # 如果没有运行的事件循环，则忽略（通常在测试中）
                pass

    async def handle_memory_event(self, event: MemoryEvent) -> None:
        """处理记忆系统事件，广播给所有连接的客户端"""
        if event.type == MemoryEventType.EVENT_MEMORY_SYNC:
            payload = event.payload
            if not isinstance(payload, dict):
                return

            session_id = payload.get("session_id", "")
            memory_id = payload.get("memory_id", "")
            status = payload.get("status", "")

            sync_payload = MemorySyncPayload(
                sessionId=session_id,
                memoryId=memory_id,
                status=status,
            )

            msg = WSMessage(
                type=WS_MSG_TYPE_EVT_MEMORY_SYNC,
                trace_id=generate_string_id(),
                payload=sync_payload.model_dump(),
            )

            await self.broadcast(msg)

    async def broadcast(self, msg: WSMessage) -> None:
        """广播消息到所有连接的客户端"""
        async with self.clients_lock:
            clients_copy = list(self.clients)

        msg_dict = msg.model_dump()
        for conn in clients_copy:
            try:
                await conn.write_json(msg_dict)
            except Exception as e:
                logger.error(f"广播消息失败 error={e}")

    async def handle_ws(self, websocket: WebSocket) -> None:
        """处理 WebSocket 连接"""
        await websocket.accept()
        ws_conn = WSConnection(websocket)

        async with self.clients_lock:
            self.clients.add(ws_conn)

        logger.info(f"WebSocket 客户端已连接 remote_addr={ws_conn.remote_addr}")

        try:
            while True:
                data = await websocket.receive_text()
                try:
                    msg_dict = json.loads(data)
                    msg = WSMessage(**msg_dict)
                except Exception as e:
                    logger.error(f"解析 WebSocket 消息失败 error={e}")
                    await self.send_error(ws_conn, "", 4000, "Invalid JSON format")
                    continue

                await self.handle_message(ws_conn, msg)
        except WebSocketDisconnect:
            logger.info("WebSocket 客户端已断开连接")
        except Exception as e:
            logger.error(f"读取 WebSocket 消息失败 error={e}")
        finally:
            async with self.clients_lock:
                if ws_conn in self.clients:
                    self.clients.remove(ws_conn)

    async def handle_message(self, conn: WSConnection, msg: WSMessage) -> None:
        """分发处理消息"""
        logger.info(f"收到 WebSocket 消息 type={msg.type} trace_id={msg.trace_id}")

        if msg.type == WS_MSG_TYPE_PING:
            await self.handle_ping(conn, msg)
        elif msg.type == WS_MSG_TYPE_CMD_USER_INPUT:
            # 异步处理聊天请求，避免阻塞读循环
            task = asyncio.create_task(self.handle_chat_request(conn, msg))
            self.background_tasks.add(task)
            task.add_done_callback(self.background_tasks.discard)
        elif msg.type == WS_MSG_TYPE_CMD_SYNC_INIT_STATE:
            await self.handle_sync_init_state(conn, msg)
        elif msg.type == WS_MSG_TYPE_REQ_GET_CALENDAR_METADATA:
            await self.handle_get_calendar_metadata(conn, msg)
        elif msg.type == WS_MSG_TYPE_REQ_GET_CHAT_HISTORY:
            await self.handle_get_chat_history(conn, msg)
        else:
            logger.warning(f"未知的消息类型 type={msg.type}")
            await self.send_error(conn, msg.trace_id, 4001, "Unknown message type")

    async def handle_get_calendar_metadata(self, conn: WSConnection, msg: WSMessage) -> None:
        """处理获取日历元数据的请求"""
        try:
            year_month = msg.payload.get("year_month", "")
            if not year_month:
                raise ValueError("year_month is empty")
        except Exception as e:
            logger.error(f"解析 REQ_GET_CALENDAR_METADATA Payload 失败 error={e}")
            await self.send_error(conn, msg.trace_id, 4004, "Invalid REQ_GET_CALENDAR_METADATA payload")
            return

        active_dates = []
        if self.pg_repo:
            try:
                active_dates = await self.pg_repo.get_active_dates_by_month(year_month)
            except Exception as e:
                logger.error(f"从 PostgreSQL 获取活跃日期失败 error={e}")
                await self.send_error(conn, msg.trace_id, 5002, "Failed to fetch calendar metadata from database")
                return

        resp_payload = {
            "year_month": year_month,
            "active_dates": active_dates,
        }

        resp_msg = WSMessage(
            type=WS_MSG_TYPE_RES_CALENDAR_METADATA,
            trace_id=msg.trace_id,
            payload=resp_payload,
        )

        try:
            await conn.write_json(resp_msg.model_dump())
        except Exception as e:
            logger.error(f"发送 RES_CALENDAR_METADATA 消息失败 error={e}")

    async def handle_get_chat_history(self, conn: WSConnection, msg: WSMessage) -> None:
        """处理获取指定日期详细聊天记录的请求"""
        try:
            date_str = msg.payload.get("date", "")
            if not date_str:
                raise ValueError("date is empty")
        except Exception as e:
            logger.error(f"解析 REQ_GET_CHAT_HISTORY Payload 失败 error={e}")
            await self.send_error(conn, msg.trace_id, 4005, "Invalid REQ_GET_CHAT_HISTORY payload")
            return

        interactions: List[InteractionModel] = []
        if self.pg_repo:
            try:
                interactions = await self.pg_repo.get_interactions_by_date(date_str)
            except Exception as e:
                logger.error(f"从 PostgreSQL 获取详细聊天记录失败 error={e}")
                await self.send_error(conn, msg.trace_id, 5003, "Failed to fetch chat history from database")
                return

        messages = []
        for interaction in interactions:
            # User message
            messages.append({
                "id": interaction.message_id,
                "role": Role.USER.value,
                "content": interaction.user_content,
                "created_at": interaction.created_at.isoformat(),
            })

            # Assistant message
            content = interaction.assistant_content
            if interaction.error:
                content = interaction.error

            messages.append({
                "id": interaction.id,
                "role": Role.ASSISTANT.value,
                "content": content,
                "created_at": interaction.created_at.isoformat(),
            })

        resp_payload = {
            "date": date_str,
            "messages": messages,
        }

        resp_msg = WSMessage(
            type=WS_MSG_TYPE_RES_CHAT_HISTORY,
            trace_id=msg.trace_id,
            payload=resp_payload,
        )

        try:
            await conn.write_json(resp_msg.model_dump())
        except Exception as e:
            logger.error(f"发送 RES_CHAT_HISTORY 消息失败 error={e}")

    async def handle_sync_init_state(self, conn: WSConnection, msg: WSMessage) -> None:
        """处理前端初始状态同步请求"""
        session_id = datetime.now().strftime("%Y%m%d")
        try:
            req_session_id = msg.payload.get("sessionId", "")
            if req_session_id:
                session_id = req_session_id
        except Exception:
            pass

        recent_history: List[Interaction] = []
        if self.redis_repo:
            try:
                _, recent_history = await self.redis_repo.get_context(session_id)
            except Exception as e:
                logger.error(f"从 Redis 获取上下文失败 error={e}")

        start_index = 0
        if len(recent_history) > 3:
            start_index = len(recent_history) - 3
        last_3_history = recent_history[start_index:]

        recent_qa = []
        for h in last_3_history:
            recent_qa.append(InteractionQA(
                msgId=h.msgId,
                userContent=h.userContent,
                assistantContent=h.assistantContent,
                timestamp=h.timestamp,
            ))

        payload = InitStatePayload(
            sessionId=session_id,
            recentQA=recent_qa,
        )

        resp_msg = WSMessage(
            type=WS_MSG_TYPE_EVT_INIT_STATE,
            trace_id=msg.trace_id,
            payload=payload.model_dump(),
        )

        try:
            await conn.write_json(resp_msg.model_dump())
        except Exception as e:
            logger.error(f"发送 EVT_INIT_STATE 消息失败 error={e}")

    async def handle_ping(self, conn: WSConnection, msg: WSMessage) -> None:
        """处理 Ping 请求"""
        try:
            payload = PingPayload(**msg.payload)
        except Exception as e:
            logger.error(f"解析 Ping Payload 失败 error={e}")
            await self.send_error(conn, msg.trace_id, 4002, "Invalid Ping payload")
            return

        pong_payload = PongPayload(
            timestamp=int(time.time() * 1000),
            source="python-ai-service",
        )

        pong_msg = WSMessage(
            type=WS_MSG_TYPE_PONG,
            trace_id=msg.trace_id,
            payload=pong_payload.model_dump(),
        )

        try:
            await conn.write_json(pong_msg.model_dump())
        except Exception as e:
            logger.error(f"发送 Pong 消息失败 error={e}")

    async def handle_chat_request(self, conn: WSConnection, msg: WSMessage) -> None:
        """处理聊天请求"""
        try:
            cmd_payload = CMDUserInputPayload(**msg.payload)
        except Exception as e:
            logger.error(f"解析 CMD_USER_INPUT Payload 失败 error={e}")
            await self.send_error(conn, msg.trace_id, 4003, "Invalid CMD_USER_INPUT payload")
            return

        user_msg_id = cmd_payload.msgId
        if not user_msg_id:
            user_msg_id = generate_string_id()

        summary = ChatSummary()
        recent_history: List[Interaction] = []
        if self.redis_repo:
            try:
                summary, recent_history = await self.redis_repo.get_context(cmd_payload.sessionId)
            except Exception as e:
                logger.error(f"从 Redis 获取上下文失败 error={e}")

        proto_history = []
        for h in recent_history:
            proto_history.append(communication_pb2.ChatMessage(
                role=Role.USER.value,
                content=h.userContent,
            ))
            assistant_msg = communication_pb2.ChatMessage(
                role=Role.ASSISTANT.value,
                content=h.assistantContent,
            )
            if h.error:
                assistant_msg.is_error = True
                assistant_msg.error_details = h.error
            proto_history.append(assistant_msg)

        memory_snippets_parts = []
        for i, h in enumerate(recent_history):
            memory_snippets_parts.append(f"[对话 {i+1}]\n")
            memory_snippets_parts.append(f"用户: {h.userContent}\n")
            if h.assistantContent:
                memory_snippets_parts.append(f"Luna: {h.assistantContent}\n")
            if h.thought:
                memory_snippets_parts.append(f"(内心独白: {h.thought})\n")
            if h.emotion:
                memory_snippets_parts.append(f"(心情: {h.emotion})\n")
            if h.error:
                memory_snippets_parts.append(f"(错误: {h.error})\n")
            if h.timestamp:
                timestamp_str = datetime.fromtimestamp(h.timestamp).strftime("%Y-%m-%d %H:%M:%S %A")
                memory_snippets_parts.append(f"(时间: {timestamp_str})\n")
            memory_snippets_parts.append("\n")
        
        memory_snippets = "".join(memory_snippets_parts)

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S %A")
        prompt_variables = {
            "CURRENT_TIME": current_time,
            "CORE_SUMMARY": summary.core_summary,
            "KEY_FACTS": summary.key_facts,
            "MEMORY_SNIPPETS": memory_snippets,
        }

        # 1. 组装 Input Reconstruction Prompt
        input_recon_system_prompt = ""
        input_recon_memory_prompt = ""
        input_recon_runtime_prompt = ""
        
        if self.prompt_mgr:
            try:
                input_recon_system_prompt = await self.prompt_mgr.assemble_prompt(
                    PromptCategory.INPUT_RECONSTRUCTION, {}
                )

                input_recon_memory_prompt = await self.prompt_mgr.assemble_prompt(
                    PromptCategory.INPUT_RECONSTRUCTION, {
                        "CORE_SUMMARY": summary.core_summary,
                        "KEY_FACTS": summary.key_facts,
                        "MEMORY_SNIPPETS": memory_snippets,
                    }
                )

                # 动态注入枚举值
                from app.types.constants import PrimaryIntent, IntentCategory, DagRouteHint, RetrievalType
                primary_intents = [i.value for i in PrimaryIntent]
                categories = [c.value for c in IntentCategory]
                dag_route_hints = [h.value for h in DagRouteHint]
                retrieval_types = [r.value for r in RetrievalType]

                input_recon_runtime_prompt = await self.prompt_mgr.assemble_prompt(
                    PromptCategory.INPUT_RECONSTRUCTION, {
                        "USER_INPUT": cmd_payload.message,
                        "PRIMARY_INTENTS": '"' + '", "'.join(primary_intents) + '"',
                        "CATEGORIES": '"' + '", "'.join(categories) + '"',
                        "DAG_ROUTE_HINTS": '"' + '", "'.join(dag_route_hints) + '"',
                        "RETRIEVAL_TYPES": '"' + '", "'.join(retrieval_types) + '"',
                    }
                )
            except Exception as e:
                logger.error(f"组装 Input Reconstruction Prompt 失败 error={e}")

        # 2. 调用 Input Reconstruction Agent
        from app.agent.input_reconstructor import InputReconstructorAgent
        from app.llm.client import llm_client
        
        agent = InputReconstructorAgent(llm_client)
        try:
            recon_result = await agent.process(
                trace_id=msg.trace_id,
                user_input=cmd_payload.message,
                system_prompt=input_recon_system_prompt,
                memory_prompt=input_recon_memory_prompt,
                runtime_prompt=input_recon_runtime_prompt
            )
        except Exception as e:
            logger.error(f"调用 InputReconstruction 失败 error={e}")
            await self.send_error(conn, msg.trace_id, 5001, "Input reconstruction failed")
            return

        # 3. 解析 Input Reconstruction 结果并组装 Chat Prompt
        disambiguated_text = cmd_payload.message
        try:
            recon_data = recon_result.model_dump()
            emotion_state = recon_data.get("emotion_state", {})
            reconstruction = recon_data.get("reconstruction", {})
            
            disambiguated_text = reconstruction.get("disambiguated_text", cmd_payload.message)
            
            # 注入情绪特征
            prompt_variables["EMOTION_PRIMARY"] = emotion_state.get("primary_emotion", "")
            prompt_variables["EMOTION_INTENSITY"] = f"{emotion_state.get('intensity', 0.0):.2f}"
            prompt_variables["EMOTION_VALENCE"] = f"{emotion_state.get('valence', 0.0):.2f}"
            prompt_variables["EMOTION_AROUSAL"] = f"{emotion_state.get('arousal', 0.0):.2f}"
            prompt_variables["EMOTION_TRIGGER"] = emotion_state.get("emotion_trigger", "")
        except Exception as e:
            logger.error(f"解析 InputReconstruction JSON 失败 error={e}")

        full_system_prompt = ""
        if self.prompt_mgr:
            try:
                full_system_prompt = await self.prompt_mgr.assemble_prompt(
                    PromptCategory.CHAT, prompt_variables
                )
            except Exception as e:
                logger.error(f"组装 Chat Prompt 失败 error={e}")

        logger.info(f"开始流式对话 trace_id={msg.trace_id}")

        start_time = time.time()
        is_first_chunk = True
        full_assistant_content = ""
        full_assistant_thought = ""
        full_assistant_emotion = ""
        stream_error = None

        try:
            from app.llm.client import llm_client
            from app.llm.stream_parser import StreamParser
            
            # 转换历史记录格式
            history_dicts = []
            for h in recent_history:
                history_dicts.append({"role": Role.USER.value, "content": h.userContent})
                content = h.assistantContent
                if h.error:
                    content = h.error
                history_dicts.append({"role": Role.ASSISTANT.value, "content": content})
                
            parser = StreamParser(msg.trace_id)
            
            async for chunk_data in llm_client.stream_chat_with_context(
                system_prompt=full_system_prompt,
                history=history_dicts,
                current_message=cmd_payload.message,
                trace_id=msg.trace_id,
                disambiguated_text=disambiguated_text,
            ):
                if is_first_chunk and chunk_data.get("chunk"):
                    ttft = int((time.time() - start_time) * 1000)
                    logger.info(f"首字延迟 (TTFT) trace_id={msg.trace_id} ttft_ms={ttft}")
                    is_first_chunk = False

                raw_chunk = chunk_data.get("chunk", "")
                
                # 使用 StreamParser 解析原始 LLM 输出块
                msgs = parser.feed(raw_chunk)
                for msg_type, content in msgs:
                    if msg_type == "reply_chunk":
                        full_assistant_content += content
                    elif msg_type == "thought_content":
                        full_assistant_thought += content
                    elif msg_type == "emotion_update":
                        full_assistant_emotion = content
                        
                    if msg_type != "thought_content":
                        chat_payload = ChatStreamPayload(
                            type=msg_type,
                            chunk=content,
                            is_finished=False,
                            node_id=cmd_payload.msgId,
                            error="",
                        )

                        stream_msg = WSMessage(
                            type=WS_MSG_TYPE_CHAT_STREAM,
                            trace_id=msg.trace_id,
                            payload=chat_payload.model_dump(),
                        )

                        try:
                            await conn.write_json(stream_msg.model_dump())
                        except Exception as e:
                            logger.error(f"发送 CHAT_STREAM 消息失败 error={e}")
                            return

                # 如果流结束，发送剩余缓冲并标记结束
                if chunk_data.get("is_finished", False):
                    flush_msgs = parser.flush()
                    
                    if not flush_msgs:
                        chat_payload = ChatStreamPayload(
                            type="reply_chunk",
                            chunk="",
                            is_finished=True,
                            node_id=cmd_payload.msgId,
                            error=chunk_data.get("error") or "",
                        )

                        stream_msg = WSMessage(
                            type=WS_MSG_TYPE_CHAT_STREAM,
                            trace_id=msg.trace_id,
                            payload=chat_payload.model_dump(),
                        )

                        try:
                            await conn.write_json(stream_msg.model_dump())
                        except Exception:
                            pass
                    else:
                        for f_type, f_content in flush_msgs:
                            if f_type == "reply_chunk":
                                full_assistant_content += f_content
                            elif f_type == "thought_content":
                                full_assistant_thought += f_content
                            elif f_type == "emotion_update":
                                full_assistant_emotion = f_content
                                
                            chat_payload = ChatStreamPayload(
                                type=f_type,
                                chunk=f_content,
                                is_finished=True,
                                node_id=cmd_payload.msgId,
                                error=chunk_data.get("error") or "",
                            )

                            stream_msg = WSMessage(
                                type=WS_MSG_TYPE_CHAT_STREAM,
                                trace_id=msg.trace_id,
                                payload=chat_payload.model_dump(),
                            )

                            try:
                                await conn.write_json(stream_msg.model_dump())
                            except Exception:
                                pass
                    break

        except Exception as e:
            logger.error(f"ChatStream 处理异常 error={e}")
            await self.send_chat_stream_error(conn, msg.trace_id, cmd_payload.msgId, str(e))
            stream_error = e

        # 异步持久化
        async def _persist():
            nonlocal full_assistant_content
            now_ts = int(time.time())
            
            error_json = ""
            if stream_error:
                err_data = {
                    "error": "generation_failed",
                    "details": str(stream_error),
                }
                error_json = json.dumps(err_data)
                if not full_assistant_content:
                    full_assistant_content = error_json
            elif not full_assistant_content:
                err_data = {
                    "error": "generation_failed",
                    "details": "Assistant returned empty content",
                }
                error_json = json.dumps(err_data)
                full_assistant_content = error_json

            interaction = Interaction(
                msgId=user_msg_id,
                userContent=cmd_payload.message,
                assistantContent=full_assistant_content,
                thought=full_assistant_thought,
                emotion=full_assistant_emotion,
                error=error_json,
                timestamp=now_ts,
            )

            interaction_model = InteractionModel(
                id=generate_string_id(),
                session_id=cmd_payload.sessionId,
                message_id=user_msg_id,
                user_content=cmd_payload.message,
                assistant_content=full_assistant_content,
                thought=full_assistant_thought,
                emotion=full_assistant_emotion,
                error=error_json,
                # created_at will be set by DB default
            )

            if self.pg_repo:
                try:
                    await self.pg_repo.save_interaction(interaction_model)
                except Exception as e:
                    logger.error(f"异步保存 Interaction 到 PG 失败 error={e}")

            if self.redis_repo:
                try:
                    length = await self.redis_repo.save_interaction(cmd_payload.sessionId, interaction)
                    from app.repository.chat_history_redis import MEM_WORKING_WINDOW_SIZE
                    if length > MEM_WORKING_WINDOW_SIZE:
                        await self.trigger_compression(cmd_payload.sessionId, msg.trace_id)
                except Exception as e:
                    logger.error(f"异步保存 Interaction 到 Redis 失败 error={e}")

        # 启动异步持久化任务
        task = asyncio.create_task(_persist())
        self.background_tasks.add(task)
        task.add_done_callback(self.background_tasks.discard)

    async def trigger_compression(self, session_id: str, trace_id: str) -> None:
        """触发摘要压缩流程"""
        logger.info(f"触发摘要压缩 session_id={session_id} trace_id={trace_id}")

        if not self.redis_repo:
            return

        try:
            summary, history = await self.redis_repo.get_context(session_id)
        except Exception as e:
            logger.error(f"获取上下文失败，无法进行压缩 error={e}")
            return

        from app.repository.chat_history_redis import MEM_WORKING_WINDOW_SIZE, MEM_COMPRESS_BATCH_SIZE

        if len(history) <= MEM_WORKING_WINDOW_SIZE:
            logger.info(f"历史记录未超过阈值，无需压缩 history_count={len(history)} threshold={MEM_WORKING_WINDOW_SIZE}")
            return

        compress_count = MEM_COMPRESS_BATCH_SIZE
        if len(history) < compress_count:
            compress_count = len(history)

        logger.info(f"准备压缩历史记录 compress_count={compress_count} total_history={len(history)}")

        messages_text_parts = []
        for i in range(compress_count):
            interaction = history[i]
            messages_text_parts.append(f"用户: {interaction.userContent}\n")
            messages_text_parts.append(f"Luna: {interaction.assistantContent}\n")
            if interaction.thought:
                messages_text_parts.append(f"(内心独白: {interaction.thought})\n")
            messages_text_parts.append("\n")
        
        messages_text = "".join(messages_text_parts)

        summarize_variables = {
            "CURRENT_CORE_SUMMARY": summary.core_summary,
            "CURRENT_KEY_FACTS": summary.key_facts,
            "MESSAGES_TEXT": messages_text,
        }

        full_summarize_prompt = ""
        if self.prompt_mgr:
            try:
                full_summarize_prompt = await self.prompt_mgr.assemble_prompt(
                    PromptCategory.SHORT_SUMMARY, summarize_variables
                )
            except Exception as e:
                logger.error(f"组装 Summarize Prompt 失败 error={e}")

        from app.api.internal_service import internal_service
        try:
            new_core_summary, new_key_facts = await internal_service.short_summarize(trace_id, full_summarize_prompt)
        except Exception as e:
            logger.error(f"调用 ShortSummarize 失败 error={e}")
            return

        if not new_core_summary.strip() or not new_key_facts.strip():
            logger.warning(f"返回的摘要存在空字段，放弃本次更新 session_id={session_id}")
            return

        new_summary = ChatSummary(
            core_summary=new_core_summary,
            key_facts=new_key_facts,
        )

        try:
            await self.redis_repo.update_summary_and_trim(session_id, new_summary, compress_count)
            logger.info(f"摘要压缩完成 session_id={session_id} trimmed_count={compress_count}")
        except Exception as e:
            logger.error(f"更新摘要并裁剪历史失败 error={e}")

    async def send_chat_stream_error(self, conn: WSConnection, trace_id: str, node_id: str, error_msg: str) -> None:
        """发送聊天流错误"""
        chat_payload = ChatStreamPayload(
            type="reply_chunk",
            chunk="",
            is_finished=True,
            node_id=node_id,
            error=error_msg,
        )

        stream_msg = WSMessage(
            type=WS_MSG_TYPE_CHAT_STREAM,
            trace_id=trace_id,
            payload=chat_payload.model_dump(),
        )

        try:
            await conn.write_json(stream_msg.model_dump())
        except Exception:
            pass

    async def send_error(self, conn: WSConnection, trace_id: str, code: int, message: str) -> None:
        """发送错误消息"""
        err_payload = ErrorPayload(
            code=code,
            message=message,
        )

        err_msg = WSMessage(
            type=WS_MSG_TYPE_ERROR,
            trace_id=trace_id,
            payload=err_payload.model_dump(),
        )

        try:
            await conn.write_json(err_msg.model_dump())
        except Exception:
            pass


# 全局 WSServer 实例，将在 main.py 中初始化
ws_server: Optional[WSServer] = None


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket 路由端点"""
    if ws_server:
        await ws_server.handle_ws(websocket)
    else:
        await websocket.close(code=1011, reason="Server not initialized")
