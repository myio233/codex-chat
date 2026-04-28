from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


PlanType = Literal["free", "plus"]
RoleType = Literal["admin", "user"]
MessageRole = Literal["user", "assistant", "system"]


class UserRecord(BaseModel):
    user_id: str
    email: str
    name: str
    role: RoleType = "user"
    password_hash: str
    plan: PlanType = "free"
    enabled: bool = True
    linux_username: str | None = None
    sub2api_user_id: int | None = None
    sub2api_email: str | None = None
    sub2api_password: str | None = None
    sub2api_api_key: str | None = None
    created_at: float
    updated_at: float


class SessionToken(BaseModel):
    token: str
    user_id: str
    created_at: float
    expires_at: float


class ChatMessage(BaseModel):
    message_id: str
    role: MessageRole
    content: str
    status: Literal["completed", "streaming", "failed"] = "completed"
    error: str | None = None
    created_at: float


class ChatSession(BaseModel):
    session_id: str
    user_id: str
    title: str = "New chat"
    thread_id: str | None = None
    model: str = "codex-agent"
    created_at: float
    updated_at: float
    messages: list[ChatMessage] = Field(default_factory=list)


class AppStateRecord(BaseModel):
    users: list[UserRecord] = Field(default_factory=list)
    tokens: list[SessionToken] = Field(default_factory=list)
    chats: list[ChatSession] = Field(default_factory=list)


class LoginRequest(BaseModel):
    email: str
    password: str


class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str


class UserView(BaseModel):
    user_id: str
    email: str
    name: str
    role: RoleType
    plan: PlanType
    enabled: bool
    linux_username: str | None = None


class LoginResponse(BaseModel):
    token: str
    user: UserView
    internal_only: bool


class AdminUpdateUserRequest(BaseModel):
    plan: PlanType | None = None
    enabled: bool | None = None


class CreateChatRequest(BaseModel):
    title: str | None = None


class SendMessageRequest(BaseModel):
    content: str


class OpenAIChatCompletionRequest(BaseModel):
    messages: list[dict]
    model: str | None = None
    stream: bool = True
