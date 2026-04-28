from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.codex_runner import codex_runner
from app.config import settings
from app.llm_web_agent import llm_web_agent
from app.models import (
    AdminUpdateUserRequest,
    CreateChatRequest,
    LoginRequest,
    LoginResponse,
    OpenAIChatCompletionRequest,
    RegisterRequest,
    SendMessageRequest,
)
from app.store import store

app = FastAPI(title=settings.app_title, version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.app_origin] if settings.app_origin != "*" else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

frontend_dir = settings.frontend_dir
app.mount("/assets", StaticFiles(directory=frontend_dir), name="assets")


@app.on_event("startup")
def ensure_user_sandboxes():
    store.ensure_linux_users_for_existing_accounts()
    for user in store.list_users():
        codex_runner.ensure_user_sandbox(user.user_id)


def extract_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    prefix = "bearer "
    if authorization.lower().startswith(prefix):
        return authorization[len(prefix):].strip()
    return authorization.strip()


def require_user(authorization: str | None):
    token = extract_bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="请先登录")
    user = store.get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="登录状态已失效，请重新登录")
    return user, token


def require_admin(authorization: str | None):
    user, token = require_user(authorization)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user, token


def serialize_chat(chat):
    return {
        "session_id": chat.session_id,
        "title": chat.title,
        "thread_id": chat.thread_id,
        "model": chat.model,
        "created_at": chat.created_at,
        "updated_at": chat.updated_at,
        "messages": [message.model_dump() for message in chat.messages],
    }


def message_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text" and item.get("text"):
                    parts.append(str(item["text"]))
                elif item.get("text"):
                    parts.append(str(item["text"]))
        return "\n".join(parts)
    return str(content or "")


def prompt_from_openai_messages(messages: list[dict]) -> str:
    lines: list[str] = []
    for item in messages:
        role = str(item.get("role") or "user")
        content = message_text(item.get("content")).strip()
        if not content:
            continue
        lines.append(f"{role}:\n{content}")
    return "\n\n".join(lines).strip()


def last_user_message(messages: list[dict]) -> str:
    for item in reversed(messages):
        if item.get("role") == "user":
            text = message_text(item.get("content")).strip()
            if text:
                return text
    return prompt_from_openai_messages(messages)


@app.get("/api/config")
def get_config():
    return {
        "title": settings.app_title,
        "internal_only": settings.internal_only,
        "allow_public_signup": settings.allow_public_signup and not settings.internal_only,
    }


@app.post("/api/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest):
    user = store.authenticate_user(payload.email.strip(), payload.password)
    if not user:
        raise HTTPException(status_code=401, detail="账号或密码错误，或当前不允许进入内测")
    user = store.assign_linux_user(user.user_id)
    token = store.issue_token(user.user_id)
    codex_runner.ensure_user_sandbox(user.user_id)
    return LoginResponse(token=token, user=store.user_view(user), internal_only=settings.internal_only)


@app.post("/api/auth/register", response_model=LoginResponse)
def register(payload: RegisterRequest):
    if settings.internal_only or not settings.allow_public_signup:
        raise HTTPException(status_code=403, detail="当前阶段未开放注册")
    try:
        user = store.create_user(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    token = store.issue_token(user.user_id)
    codex_runner.ensure_user_sandbox(user.user_id)
    return LoginResponse(token=token, user=store.user_view(user), internal_only=settings.internal_only)


@app.post("/api/auth/logout")
def logout(authorization: str | None = Header(default=None)):
    _, token = require_user(authorization)
    store.revoke_token(token)
    return {"ok": True}


@app.get("/api/me")
def me(authorization: str | None = Header(default=None)):
    user, _ = require_user(authorization)
    return {"user": store.user_view(user), "internal_only": settings.internal_only}


@app.get("/api/admin/users")
def list_users(authorization: str | None = Header(default=None)):
    require_admin(authorization)
    return {"items": [store.user_view(user).model_dump() for user in store.list_users()]}


@app.patch("/api/admin/users/{user_id}")
def update_user(
    user_id: str,
    payload: AdminUpdateUserRequest,
    authorization: str | None = Header(default=None),
):
    require_admin(authorization)
    try:
        user = store.update_user(user_id, payload)
        codex_runner.ensure_user_sandbox(user.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"user": store.user_view(user)}


@app.get("/api/chat/sessions")
def list_sessions(authorization: str | None = Header(default=None)):
    user, _ = require_user(authorization)
    chats = store.list_chats_for_user(user.user_id)
    return {"items": [serialize_chat(chat) for chat in chats]}


@app.post("/api/chat/sessions")
def create_session(payload: CreateChatRequest, authorization: str | None = Header(default=None)):
    user, _ = require_user(authorization)
    chat = store.create_chat(user.user_id, payload.title)
    return serialize_chat(chat)


@app.get("/api/chat/sessions/{session_id}")
def get_session(session_id: str, authorization: str | None = Header(default=None)):
    user, _ = require_user(authorization)
    chat = store.get_chat(user.user_id, session_id)
    if not chat:
        raise HTTPException(status_code=404, detail="会话不存在")
    return serialize_chat(chat)


@app.post("/api/chat/sessions/{session_id}/messages")
async def send_message(
    session_id: str,
    payload: SendMessageRequest,
    authorization: str | None = Header(default=None),
):
    user, _ = require_user(authorization)
    if user.plan != "plus":
        raise HTTPException(status_code=403, detail="当前账号不是 Plus，暂时不能使用 Codex Agent")

    chat = store.get_chat(user.user_id, session_id)
    if not chat:
        raise HTTPException(status_code=404, detail="会话不存在")

    prompt = payload.content.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="消息不能为空")

    user_message = store.append_message(chat, role="user", content=prompt)
    assistant_message = store.append_message(chat, role="assistant", content="", status="streaming")

    async def event_stream():
        yield f"event: meta\ndata: {json.dumps({'user_message': user_message.model_dump(), 'assistant_message': assistant_message.model_dump(), 'session': serialize_chat(chat)}, ensure_ascii=False)}\n\n"
        try:
            async for event in codex_runner.stream_turn(chat, prompt):
                event_type = event["type"]
                if event_type == "thread":
                    chat.thread_id = event["thread_id"]
                    store.save_chat(chat)
                    yield f"event: thread\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                elif event_type == "assistant":
                    updated = store.update_message(
                        chat,
                        assistant_message.message_id,
                        content=event["content"],
                        status="completed",
                        error=None,
                    )
                    yield f"event: assistant\ndata: {json.dumps({'message': updated.model_dump() if updated else assistant_message.model_dump()}, ensure_ascii=False)}\n\n"
                elif event_type == "done":
                    if event.get("thread_id"):
                        chat.thread_id = event["thread_id"]
                    updated = store.update_message(
                        chat,
                        assistant_message.message_id,
                        content=event.get("content", ""),
                        status="completed",
                        error=None,
                    )
                    store.save_chat(chat)
                    yield f"event: done\ndata: {json.dumps({'message': updated.model_dump() if updated else assistant_message.model_dump(), 'session': serialize_chat(chat)}, ensure_ascii=False)}\n\n"
                elif event_type == "log":
                    yield f"event: log\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                else:
                    yield f"event: event\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as exc:
            updated = store.update_message(
                chat,
                assistant_message.message_id,
                content="",
                status="failed",
                error=str(exc),
            )
            yield f"event: error\ndata: {json.dumps({'message': updated.model_dump() if updated else assistant_message.model_dump(), 'detail': str(exc)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/openai/v1/chat/completions")
async def openai_chat_completions(
    request: Request,
    authorization: str | None = Header(default=None),
):
    user, _ = require_user(authorization)
    if user.plan != "plus":
        raise HTTPException(status_code=403, detail="当前账号不是 Plus，暂时不能使用 Codex Agent")

    payload_dict = await request.json()
    payload = OpenAIChatCompletionRequest(**payload_dict)

    if llm_web_agent.is_agent_model(payload.model):
        if not llm_web_agent.enabled():
            return JSONResponse(
                {"error": {"message": "ChatGPT Web Agent is disabled.", "type": "agent_disabled"}},
                status_code=403,
            )
        if payload.stream:
            return StreamingResponse(
                llm_web_agent.stream_completion_chunks(payload_dict),
                media_type="text/event-stream",
            )

        try:
            response = await llm_web_agent.create_completion(payload_dict)
            final_text = llm_web_agent.content_with_artifacts(response)
            if response.get("choices"):
                response["choices"][0]["message"]["content"] = final_text
            return JSONResponse(response)
        except Exception as exc:
            return JSONResponse(
                {"error": {"message": str(exc), "type": "llm_web_agent_error"}},
                status_code=502,
            )

    prompt = prompt_from_openai_messages(payload.messages)
    if not prompt:
        raise HTTPException(status_code=400, detail="消息不能为空")

    title = last_user_message(payload.messages).splitlines()[0][:48] or "NextChat"
    chat = store.create_chat(user.user_id, title)
    store.append_message(chat, role="user", content=last_user_message(payload.messages))

    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())
    model = payload.model or "codex-agent"

    async def completion_events():
        final_text = ""
        try:
            async for event in codex_runner.stream_turn(chat, prompt):
                event_type = event["type"]
                if event_type == "thread":
                    chat.thread_id = event["thread_id"]
                    store.save_chat(chat)
                elif event_type in {"assistant", "done"}:
                    content = event.get("content", "")
                    delta = content[len(final_text) :] if content.startswith(final_text) else content
                    final_text = content
                    if delta:
                        chunk = {
                            "id": completion_id,
                            "object": "chat.completion.chunk",
                            "created": created,
                            "model": model,
                            "choices": [{"index": 0, "delta": {"content": delta}, "finish_reason": None}],
                        }
                        yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                    if event_type == "done":
                        store.append_message(chat, role="assistant", content=final_text)
                        done = {
                            "id": completion_id,
                            "object": "chat.completion.chunk",
                            "created": created,
                            "model": model,
                            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                        }
                        yield f"data: {json.dumps(done, ensure_ascii=False)}\n\n"
                        yield "data: [DONE]\n\n"
        except Exception as exc:
            error = {"error": {"message": str(exc), "type": "codex_error"}}
            yield f"data: {json.dumps(error, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

    if payload.stream:
        return StreamingResponse(completion_events(), media_type="text/event-stream")

    final_text = ""
    async for event in codex_runner.stream_turn(chat, prompt):
        if event["type"] in {"assistant", "done"}:
            final_text = event.get("content", final_text)
    store.append_message(chat, role="assistant", content=final_text)
    return JSONResponse(
        {
            "id": completion_id,
            "object": "chat.completion",
            "created": created,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": final_text},
                    "finish_reason": "stop",
                }
            ],
        }
    )


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/generated-images/{user_id}/{image_path:path}")
def generated_image(user_id: str, image_path: str):
    user = store.get_user(user_id)
    if not user or not user.linux_username:
        raise HTTPException(status_code=404, detail="图片不存在")

    images_root = (
        settings.linux_sandbox_root
        / user.linux_username
        / "home"
        / ".codex"
        / "generated_images"
    ).resolve()
    candidate = (images_root / Path(image_path)).resolve()
    if images_root not in candidate.parents or not candidate.is_file():
        raise HTTPException(status_code=404, detail="图片不存在")
    if candidate.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise HTTPException(status_code=404, detail="图片不存在")
    return FileResponse(candidate)


@app.get("/{path_name:path}")
def frontend(path_name: str):
    candidate = frontend_dir / path_name
    if path_name and candidate.exists() and candidate.is_file():
        return FileResponse(candidate)
    return FileResponse(frontend_dir / "index.html")
