from fastapi import FastAPI, HTTPException, UploadFile, File, Query, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Dict, Optional
from app.services.llm_factory import LLMFactory
from app.services.search_service import SearchService
from fastapi.staticfiles import StaticFiles
from datetime import datetime
from pathlib import Path

from app.core.logger import (
    DEBUG_TRACE_ENABLED,
    clear_trace,
    get_logger,
    get_trace,
    log_event,
    log_structured,
    start_trace,
)
from app.core.middleware import LoggingMiddleware
from app.core.config import settings
from app.api import api_router
from app.core.database import AsyncSessionLocal
from app.models.conversation import Conversation, DialogueType
from app.models.message import Message
from sqlalchemy import select
from app.services.conversation_service import ConversationService
import uuid
import os
from app.services.indexing_service import IndexingService
import sys
from app.lg_agent.lg_states import AgentState, InputState
from app.lg_agent.utils import new_uuid
from app.lg_agent.lg_builder import graph
from langgraph.types import Command
import json


# 配置上传目录 - RAG 功能的
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

# logger 变量就被初始化为一个日志记录器实例。
# 之后，便可以在当前文件中直接使用 logger.info()、logger.error() 等方法来记录日志，而不需要进行其他操作。
logger = get_logger(service="main")

# 创建 FastAPI 应用实例
app = FastAPI(title="AssistGen REST API")

# 添加日志中间件， 使用 LoggingMiddleware 来统一处理日志记录，从而替代 FastAPI 的原生打印日志。
app.add_middleware(LoggingMiddleware)

# CORS设置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 在生产环境中要设置具体的域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 1. 用户注册、登录路由通过 api_router 路由挂载到 /api 前缀
app.include_router(api_router, prefix="/api")

class ReasonRequest(BaseModel):
    messages: List[Dict[str, str]]
    user_id: int

class ChatMessage(BaseModel):
    messages: List[Dict[str, str]]
    user_id: int
    conversation_id: int  # 添加会话ID字段

class RAGChatRequest(BaseModel):
    messages: List[Dict[str, str]]
    index_id: str
    user_id: int

class CreateConversationRequest(BaseModel):
    user_id: int

class UpdateConversationNameRequest(BaseModel):
    name: str

class LangGraphRequest(BaseModel):
    query: str
    user_id: int
    conversation_id: Optional[str] = None
    image: Optional[UploadFile] = None

class LangGraphResumeRequest(BaseModel):
    query: str
    user_id: int
    conversation_id: str
    debug_trace: Optional[bool] = None


def _state_has_interrupt(state) -> bool:
    return bool(state and any(task.interrupts for task in state.tasks))


def _truthy(value) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _debug_trace_requested(request: Request, payload: Optional[dict] = None) -> bool:
    if not DEBUG_TRACE_ENABLED:
        return False
    return (
        _truthy(request.query_params.get("debug_trace"))
        or _truthy(request.headers.get("X-Debug-Trace"))
        or _truthy((payload or {}).get("debug_trace"))
    )


def _debug_trace_sse(request_id: str, conversation_id: Optional[str], thread_id: str) -> str:
    trace_json = json.dumps(
        {
            "request_id": request_id,
            "conversation_id": conversation_id,
            "thread_id": thread_id,
            "events": get_trace(),
        },
        ensure_ascii=False,
    )
    return f"event: trace\ndata: {trace_json}\n\n"


@app.get("/health")
async def health_check():
    return {"status": "ok"}

@app.post("/api/chat")
async def chat_endpoint(request: ChatMessage):
    """聊天接口"""
    try:
        log_event(
            logger,
            "INFO",
            "chat_request",
            user_id=request.user_id,
            conversation_id=request.conversation_id,
            message_count=len(request.messages),
        )
        chat_service = LLMFactory.create_chat_service()
        
        return StreamingResponse(
            chat_service.generate_stream(
                messages=request.messages,
                user_id=request.user_id,
                conversation_id=request.conversation_id,
                on_complete=ConversationService.save_message
            ),
            media_type="text/event-stream"
        )
    except Exception as e:
        log_event(logger, "ERROR", "chat_error", reason=str(e), exception=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/reason")
async def reason_endpoint(request: ReasonRequest):
    """推理接口"""
    try:
        log_event(
            logger,
            "INFO",
            "reason_request",
            user_id=request.user_id,
            message_count=len(request.messages),
        )
        reasoner = LLMFactory.create_reasoner_service()
        
        log_structured("reason_request", {
            "user_id": request.user_id,
            "message_count": len(request.messages),
            "last_message_len": len(request.messages[-1]["content"]) if request.messages else 0
        })
        
        return StreamingResponse(
            reasoner.generate_stream(request.messages),
            media_type="text/event-stream"
        )
    
    except Exception as e:
        log_event(logger, "ERROR", "reason_error", user_id=request.user_id, reason=str(e), exception=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/search")
async def search_endpoint(request: ChatMessage):
    """带搜索功能的聊天接口"""
    try:
        query = request.messages[0]["content"]
        log_event(
            logger,
            "INFO",
            "search_request",
            user_id=request.user_id,
            conversation_id=request.conversation_id,
            message_count=len(request.messages),
            query_len=len(query),
        )
        search_service = LLMFactory.create_search_service()
        return StreamingResponse(
            search_service.generate_stream(
                query=query,
                user_id=request.user_id,
                conversation_id=request.conversation_id,
                # on_complete=ConversationService.save_message
            ),
            media_type="text/event-stream"
        )
    
    except Exception as e:
        log_event(logger, "ERROR", "search_error", reason=str(e), exception=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/upload")
async def upload_file(
    file: UploadFile = File(...),
    user_id: int = Form(...)
):
    """上传文件并准备 RAG 处理"""
    try:
        log_event(
            logger,
            "INFO",
            "file_upload_started",
            user_id=user_id,
            filename=file.filename,
            content_type=file.content_type,
        )
        
        # 1. 创建基于UUID的一级目录
        user_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"user_{user_id}"))
        first_level_dir = UPLOAD_DIR / user_uuid
        
        # 2. 创建基于时间戳的二级目录
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        second_level_dir = first_level_dir / timestamp
        second_level_dir.mkdir(parents=True, exist_ok=True)
        
        # 3. 生成带时间戳的文件名
        original_name, ext = os.path.splitext(file.filename)
        new_filename = f"{original_name}_{timestamp}{ext}"
        file_path = second_level_dir / new_filename
        
        # 保存文件
        content = await file.read()
        with open(file_path, "wb") as f:
            f.write(content)
            
        # 获取文件信息
        file_info = {
            "filename": new_filename,
            "original_name": file.filename,
            "size": len(content),
            "type": file.content_type,
            "path": str(file_path).replace('\\', '/'),
            "user_id": user_id,
            "user_uuid": user_uuid,
            "upload_time": timestamp,
            "directory": str(second_level_dir)
        }
        
        # 4. 处理文件索引
        indexing_service = IndexingService()
        index_result = await indexing_service.process_file(file_info)
        
        # 合并结果
        result = {**file_info, "index_result": index_result}
        
        log_event(
            logger,
            "INFO",
            "file_upload_finished",
            user_id=user_id,
            filename=new_filename,
            size=len(content),
        )
        return result
        
    except Exception as e:
        log_event(logger, "ERROR", "file_upload_error", user_id=user_id, reason=str(e), exception=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/chat-rag")
async def rag_chat_endpoint(request: RAGChatRequest):
    """基于文档的问答接口"""
    try:
        log_event(
            logger,
            "INFO",
            "rag_chat_request",
            user_id=request.user_id,
            index_id=request.index_id,
            message_count=len(request.messages),
        )
        rag_chat_service = RAGChatService()
        
        return StreamingResponse(
            rag_chat_service.generate_stream(
                request.messages,
                request.index_id
            ),
            media_type="text/event-stream"
        )
    except Exception as e:
        log_event(logger, "ERROR", "rag_chat_error", user_id=request.user_id, reason=str(e), exception=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/conversations")
async def create_conversation(request: CreateConversationRequest):
    """创建新会话"""
    try:
        conversation_id = await ConversationService.create_conversation(request.user_id)
        return {"conversation_id": conversation_id}
    except Exception as e:
        log_event(logger, "ERROR", "conversation_create_error", user_id=request.user_id, reason=str(e), exception=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/conversations/user/{user_id}")
async def get_user_conversations(user_id: int):
    """获取用户的所有会话"""
    try:
        conversations = await ConversationService.get_user_conversations(user_id)
        return conversations
    except Exception as e:
        log_event(logger, "ERROR", "conversation_list_error", user_id=user_id, reason=str(e), exception=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/conversations/{conversation_id}/messages")
async def get_conversation_messages(conversation_id: int, user_id: int):
    """获取会话的所有消息"""
    try:
        messages = await ConversationService.get_conversation_messages(conversation_id, user_id)
        return messages
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        log_event(logger, "ERROR", "conversation_messages_error", conversation_id=conversation_id, user_id=user_id, reason=str(e), exception=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/conversations/{conversation_id}")
async def delete_conversation(conversation_id: int):
    """删除会话及其所有消息"""
    try:
        conversation_service = ConversationService()
        await conversation_service.delete_conversation(conversation_id)
        return {"message": "会话已删除"}
    except Exception as e:
        log_event(logger, "ERROR", "conversation_delete_error", conversation_id=conversation_id, reason=str(e), exception=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/conversations/{conversation_id}/name")
async def update_conversation_name(
    conversation_id: int,
    request: UpdateConversationNameRequest
):
    """修改会话名称"""
    try:
        conversation_service = ConversationService()
        await conversation_service.update_conversation_name(conversation_id, request.name)
        return {"message": "会话名称已更新"}
    except Exception as e:
        log_event(logger, "ERROR", "conversation_rename_error", conversation_id=conversation_id, reason=str(e), exception=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/langgraph/query")
async def langgraph_query(
    request: Request,
    query: Optional[str] = Form(None),
    user_id: Optional[int] = Form(None),
    conversation_id: Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None)
):
    """使用LangGraph处理用户查询，支持图片上传"""
    try:
        # 兼容纯文本查询的 JSON 请求。图片上传仍然走 multipart/form-data。
        content_type = request.headers.get("content-type", "")
        payload = {}
        if "application/json" in content_type:
            payload = await request.json()
            query = query or payload.get("query")
            user_id = user_id or payload.get("user_id")
            conversation_id = conversation_id or payload.get("conversation_id")

            # 兼容原 /api/chat 的 messages 结构，避免前端切换接口后仍传旧字段导致 422。
            if not query and payload.get("messages"):
                messages = payload.get("messages", [])
                for message in reversed(messages):
                    if message.get("role") == "user" and message.get("content"):
                        query = message["content"]
                        break

        if not query:
            raise HTTPException(status_code=400, detail="Missing required field: query")
        if user_id is None:
            raise HTTPException(status_code=400, detail="Missing required field: user_id")

        debug_trace = _debug_trace_requested(request, payload)
        request_id = getattr(request.state, "request_id", request.headers.get("X-Request-ID", "-"))
        request_logger = logger.bind(
            request_id=request_id,
            user_id=user_id,
            conversation_id=conversation_id,
        )
        log_event(
            request_logger,
            "INFO",
            "langgraph_started",
            query_len=len(query),
            has_image=image is not None,
        )
        
        # 处理图片上传
        image_path = None
        if image:
            # 创建图片存储目录
            image_dir = Path("uploads/images")
            image_dir.mkdir(parents=True, exist_ok=True)
            
            # 生成带时间戳的文件名
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            original_name, ext = os.path.splitext(image.filename)
            new_filename = f"{original_name}_{timestamp}{ext}"
            image_path = image_dir / new_filename
            
            # 保存图片
            content = await image.read()
            with open(image_path, "wb") as f:
                f.write(content)
            
            log_event(
                request_logger,
                "INFO",
                "image_saved",
                filename=new_filename,
                size=len(content),
            )
        
        # 使用conversation_id作为thread_id，如果没有提供则创建新的
        thread_id = conversation_id if conversation_id else new_uuid()
        thread_config = {
            "configurable": {
                "thread_id": thread_id, 
                "user_id": user_id,
                "image_path": str(image_path) if image_path else None
            }
        }
        request_logger = request_logger.bind(thread_id=thread_id)
        
        # 获取当前线程状态。LangGraph 的 StateSnapshot.values 才是真正的业务状态；
        # 不能用 tuple 下标判断，否则普通完成态会因为没有 interrupt 被误判成新会话。
        state_history = None
        has_existing_state = False
        has_interrupt = False
        try:
            # 检查是否有现有的会话状态
            if thread_id:
                state_history = graph.get_state(thread_config)
                if state_history and state_history.values.get("messages"):
                    has_existing_state = True
                    log_event(request_logger, "INFO", "conversation_state_found")
                if _state_has_interrupt(state_history):
                    has_interrupt = True
        except Exception as e:
            log_event(request_logger, "WARNING", "conversation_state_load_failed", reason=str(e))
        
        # 准备输入状态。只有 LangGraph interrupt 恢复才使用 Command(resume=...)；
        # 普通多轮对话应继续传入新的用户消息，由 checkpointer 按 thread_id 追加到历史状态。
        if has_interrupt:
            log_event(request_logger, "INFO", "stream_started", mode="resume_interrupted")
            async def process_stream():
                if debug_trace:
                    start_trace()
                try:
                    result = await graph.ainvoke(
                        Command(resume=query),
                        config=thread_config
                    )
                    messages = result.get("messages", [])
                    final_message = messages[-1].content if messages else ""
                    log_event(
                        request_logger,
                        "INFO",
                        "stream_finished",
                        mode="resume_interrupted",
                        message_count=len(messages),
                        content_len=len(final_message),
                    )
                    if final_message:
                        content_json = json.dumps(final_message, ensure_ascii=False)
                        yield f"data: {content_json}\n\n"
                except Exception as e:
                    log_event(request_logger, "ERROR", "stream_error", reason=str(e), exception=True)
                    error_json = json.dumps({"type": "error", "message": str(e)}, ensure_ascii=False)
                    yield f"data: {error_json}\n\n"
                        
                # 处理中断情况
                state = graph.get_state(thread_config)
                if _state_has_interrupt(state):
                    interrupt_json = json.dumps({"interruption": True, "conversation_id": thread_id})
                    yield f"data: {interrupt_json}\n\n"
                if debug_trace:
                    yield _debug_trace_sse(request_id, conversation_id, thread_id)
                clear_trace()
        else:
            if has_existing_state:
                log_event(request_logger, "INFO", "conversation_state_used")
            else:
                log_event(request_logger, "INFO", "conversation_state_created")
            input_state = InputState(messages=query)
            
            # 流式处理查询
            async def process_stream():
                if debug_trace:
                    start_trace()
                try:
                    log_event(request_logger, "INFO", "stream_started", mode="new_input")
                    result = await graph.ainvoke(
                        input=input_state,
                        config=thread_config
                    )
                    messages = result.get("messages", [])
                    final_message = messages[-1].content if messages else ""
                    log_event(
                        request_logger,
                        "INFO",
                        "stream_finished",
                        mode="new_input",
                        message_count=len(messages),
                        content_len=len(final_message),
                    )
                    if final_message:
                        content_json = json.dumps(final_message, ensure_ascii=False)
                        yield f"data: {content_json}\n\n"
                except Exception as e:
                    log_event(request_logger, "ERROR", "stream_error", reason=str(e), exception=True)
                    error_json = json.dumps({"type": "error", "message": str(e)}, ensure_ascii=False)
                    yield f"data: {error_json}\n\n"
                        
                # 处理中断情况
                state = graph.get_state(thread_config)
                if _state_has_interrupt(state):
                    interrupt_json = json.dumps({"interruption": True, "conversation_id": thread_id})
                    yield f"data: {interrupt_json}\n\n"
                if debug_trace:
                    yield _debug_trace_sse(request_id, conversation_id, thread_id)
                clear_trace()
        
        response = StreamingResponse(
            process_stream(),
            media_type="text/event-stream"
        )
        
        # 添加会话ID到响应头，方便前端获取
        response.headers["X-Conversation-ID"] = thread_id
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        log_event(logger, "ERROR", "langgraph_query_error", reason=str(e), exception=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/langgraph/resume")
async def langgraph_resume(http_request: Request, request: LangGraphResumeRequest):
    """继续执行LangGraph流程"""
    try:
        debug_trace = _debug_trace_requested(http_request, {"debug_trace": request.debug_trace})
        request_id = getattr(http_request.state, "request_id", http_request.headers.get("X-Request-ID", "-"))
        request_logger = logger.bind(
            request_id=request_id,
            user_id=request.user_id,
            conversation_id=request.conversation_id,
            thread_id=request.conversation_id,
        )
        log_event(request_logger, "INFO", "langgraph_resume_started", query_len=len(request.query))
        
        # 使用会话ID作为线程ID
        thread_config = {"configurable": {"thread_id": request.conversation_id}}
        
        # 流式处理恢复
        async def process_resume():
            if debug_trace:
                start_trace()
            try:
                log_event(request_logger, "INFO", "stream_started", mode="resume")
                async for c, metadata in graph.astream(Command(resume=request.query), stream_mode="messages", config=thread_config):
                    # 只处理最终展示给用户的内容
                    if c.content and not c.additional_kwargs.get("tool_calls"):
                        # 同样使用json.dumps处理内容
                        content_json = json.dumps(c.content, ensure_ascii=False)
                        yield f"data: {content_json}\n\n"
                    
                    # 工具调用单独处理，不发送给前端
                    elif c.additional_kwargs.get("tool_calls"):
                        tool_data = c.additional_kwargs.get("tool_calls")[0]["function"].get("arguments")
                        log_event(request_logger, "DEBUG", "tool_called", tool_args_len=len(tool_data or ""))
                log_event(request_logger, "INFO", "stream_finished", mode="resume")
            except Exception as e:
                log_event(request_logger, "ERROR", "stream_error", reason=str(e), exception=True)
                error_json = json.dumps({"type": "error", "message": str(e)}, ensure_ascii=False)
                yield f"data: {error_json}\n\n"
            finally:
                if debug_trace:
                    yield _debug_trace_sse(request_id, request.conversation_id, request.conversation_id)
                clear_trace()
        
        return StreamingResponse(
            process_resume(),
            media_type="text/event-stream"
        )
        
    except Exception as e:
        log_event(logger, "ERROR", "langgraph_resume_error", reason=str(e), exception=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/upload/image")
async def upload_image(
    image: UploadFile = File(...),
    user_id: int = Form(...),
    conversation_id: Optional[str] = Form(None)
):
    """上传图片并返回图片存储路径"""
    try:
        # 创建图片存储目录
        image_dir = Path("uploads/images")
        if conversation_id:
            image_dir = image_dir / conversation_id
        image_dir.mkdir(parents=True, exist_ok=True)
        
        # 生成带时间戳的文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        original_name, ext = os.path.splitext(image.filename)
        new_filename = f"{original_name}_{timestamp}{ext}"
        image_path = image_dir / new_filename
        
        # 保存图片
        content = await image.read()
        with open(image_path, "wb") as f:
            f.write(content)
        
        # 获取图片信息
        image_info = {
            "filename": new_filename,
            "original_name": image.filename,
            "size": len(content),
            "type": image.content_type,
            "path": str(image_path).replace('\\', '/'),
            "user_id": user_id,
            "conversation_id": conversation_id,
            "upload_time": timestamp
        }
        
        log_event(
            logger,
            "INFO",
            "image_upload_finished",
            user_id=user_id,
            conversation_id=conversation_id,
            filename=new_filename,
            size=len(content),
            content_type=image.content_type,
        )
        
        return image_info
        
    except Exception as e:
        log_event(
            logger,
            "ERROR",
            "image_upload_error",
            user_id=user_id,
            conversation_id=conversation_id,
            reason=str(e),
            exception=True,
        )
        raise HTTPException(status_code=500, detail=str(e))

# 最后挂载静态文件，并确保使用绝对路径
STATIC_DIR = Path(__file__).parent / "static" / "dist"
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
