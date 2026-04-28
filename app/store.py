from __future__ import annotations

import json
import secrets
import threading
import time
import uuid
from hashlib import pbkdf2_hmac
from pathlib import Path

from app.config import settings
from app.models import (
    AdminUpdateUserRequest,
    AppStateRecord,
    ChatMessage,
    ChatSession,
    RegisterRequest,
    SessionToken,
    UserRecord,
    UserView,
)


def _now() -> float:
    return time.time()


class JsonStore:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()
        if not self.path.exists():
            self._write_unlocked(AppStateRecord())
        self.ensure_admin_user()

    def _read_unlocked(self) -> AppStateRecord:
        if not self.path.exists():
            return AppStateRecord()
        return AppStateRecord.model_validate(json.loads(self.path.read_text(encoding="utf-8")))

    def _write_unlocked(self, payload: AppStateRecord):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(".tmp")
        tmp_path.write_text(payload.model_dump_json(indent=2), encoding="utf-8")
        tmp_path.replace(self.path)

    def hash_password(self, password: str) -> str:
        salt = secrets.token_bytes(16)
        digest = pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
        return f"{salt.hex()}:{digest.hex()}"

    def verify_password(self, password: str, encoded: str) -> bool:
        try:
            salt_hex, digest_hex = encoded.split(":", 1)
        except ValueError:
            return False
        salt = bytes.fromhex(salt_hex)
        digest = pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
        return secrets.compare_digest(digest.hex(), digest_hex)

    def ensure_admin_user(self):
        if not settings.admin_email or not settings.admin_password:
            return
        with self.lock:
            state = self._read_unlocked()
            now = _now()
            existing = next((user for user in state.users if user.email.lower() == settings.admin_email.lower()), None)
            if existing:
                existing.name = settings.admin_name
                existing.role = "admin"
                existing.plan = "plus"
                existing.enabled = True
                existing.updated_at = now
            else:
                assigned = {item.linux_username for item in state.users if item.linux_username}
                linux_username = next((item for item in self.linux_user_pool() if item not in assigned), None)
                state.users.append(
                    UserRecord(
                        user_id=uuid.uuid4().hex,
                        email=settings.admin_email.lower(),
                        name=settings.admin_name,
                        role="admin",
                        password_hash=self.hash_password(settings.admin_password),
                        plan="plus",
                        enabled=True,
                        linux_username=linux_username,
                        created_at=now,
                        updated_at=now,
                    )
                )
            self._write_unlocked(state)

    def _prune_tokens(self, state: AppStateRecord):
        now = _now()
        state.tokens = [token for token in state.tokens if token.expires_at > now]

    def authenticate_user(self, email: str, password: str) -> UserRecord | None:
        with self.lock:
            state = self._read_unlocked()
            user = next((item for item in state.users if item.email.lower() == email.lower()), None)
            if not user or not user.enabled:
                return None
            if not self.verify_password(password, user.password_hash):
                return None
            return user

    def create_user(self, payload: RegisterRequest) -> UserRecord:
        email = payload.email.strip().lower()
        name = payload.name.strip()
        password = payload.password.strip()
        if not name:
            raise ValueError("昵称不能为空")
        if len(password) < 8:
            raise ValueError("密码至少 8 位")
        with self.lock:
            state = self._read_unlocked()
            if any(item.email.lower() == email for item in state.users):
                raise ValueError("该邮箱已注册")
            now = _now()
            assigned = {item.linux_username for item in state.users if item.linux_username}
            linux_username = next((item for item in self.linux_user_pool() if item not in assigned), None)
            if not linux_username:
                raise ValueError("Linux 用户池已用完")
            user = UserRecord(
                user_id=uuid.uuid4().hex,
                email=email,
                name=name[:32],
                role="user",
                password_hash=self.hash_password(password),
                plan="free",
                enabled=True,
                linux_username=linux_username,
                created_at=now,
                updated_at=now,
            )
            state.users.append(user)
            self._write_unlocked(state)
            return user

    def issue_token(self, user_id: str) -> str:
        with self.lock:
            state = self._read_unlocked()
            self._prune_tokens(state)
            now = _now()
            token = secrets.token_urlsafe(32)
            state.tokens.append(
                SessionToken(
                    token=token,
                    user_id=user_id,
                    created_at=now,
                    expires_at=now + settings.session_ttl_seconds,
                )
            )
            self._write_unlocked(state)
            return token

    def get_user_by_token(self, token: str) -> UserRecord | None:
        with self.lock:
            state = self._read_unlocked()
            self._prune_tokens(state)
            session = next((item for item in state.tokens if item.token == token), None)
            if not session:
                self._write_unlocked(state)
                return None
            user = next((item for item in state.users if item.user_id == session.user_id and item.enabled), None)
            self._write_unlocked(state)
            return user

    def revoke_token(self, token: str):
        with self.lock:
            state = self._read_unlocked()
            state.tokens = [item for item in state.tokens if item.token != token]
            self._write_unlocked(state)

    def user_view(self, user: UserRecord) -> UserView:
        return UserView(
            user_id=user.user_id,
            email=user.email,
            name=user.name,
            role=user.role,
            plan=user.plan,
            enabled=user.enabled,
            linux_username=user.linux_username,
        )

    def linux_user_pool(self) -> list[str]:
        start = settings.linux_user_pool_start
        stop = start + settings.linux_user_pool_size
        return [f"{settings.linux_user_pool_prefix}{index:03d}" for index in range(start, stop)]

    def assign_linux_user(self, user_id: str) -> UserRecord:
        with self.lock:
            state = self._read_unlocked()
            user = next((item for item in state.users if item.user_id == user_id), None)
            if not user:
                raise ValueError("用户不存在")
            if user.linux_username:
                return user

            assigned = {item.linux_username for item in state.users if item.linux_username}
            linux_username = next((item for item in self.linux_user_pool() if item not in assigned), None)
            if not linux_username:
                raise ValueError("Linux 用户池已用完")

            user.linux_username = linux_username
            user.updated_at = _now()
            self._write_unlocked(state)
            return user

    def ensure_linux_users_for_existing_accounts(self) -> list[UserRecord]:
        updated: list[UserRecord] = []
        with self.lock:
            state = self._read_unlocked()
            assigned = {item.linux_username for item in state.users if item.linux_username}
            pool_iter = (item for item in self.linux_user_pool() if item not in assigned)
            changed = False
            for user in sorted(state.users, key=lambda item: item.created_at):
                if user.linux_username:
                    continue
                linux_username = next(pool_iter, None)
                if not linux_username:
                    break
                user.linux_username = linux_username
                user.updated_at = _now()
                updated.append(user)
                changed = True
            if changed:
                self._write_unlocked(state)
        return updated

    def list_chats_for_user(self, user_id: str) -> list[ChatSession]:
        with self.lock:
            state = self._read_unlocked()
            return sorted(
                [chat for chat in state.chats if chat.user_id == user_id],
                key=lambda item: item.updated_at,
                reverse=True,
            )

    def list_users(self) -> list[UserRecord]:
        with self.lock:
            state = self._read_unlocked()
            return sorted(state.users, key=lambda item: item.created_at, reverse=True)

    def get_user(self, user_id: str) -> UserRecord | None:
        with self.lock:
            state = self._read_unlocked()
            return next((item for item in state.users if item.user_id == user_id), None)

    def update_user(self, user_id: str, payload: AdminUpdateUserRequest) -> UserRecord:
        with self.lock:
            state = self._read_unlocked()
            user = next((item for item in state.users if item.user_id == user_id), None)
            if not user:
                raise ValueError("用户不存在")
            if payload.plan is not None:
                user.plan = payload.plan
            if payload.enabled is not None:
                user.enabled = payload.enabled
            user.updated_at = _now()
            self._write_unlocked(state)
            return user

    def set_user_sub2api_credentials(
        self,
        user_id: str,
        *,
        sub2api_user_id: int | None = None,
        sub2api_email: str | None = None,
        sub2api_password: str | None = None,
        sub2api_api_key: str | None = None,
    ) -> UserRecord:
        with self.lock:
            state = self._read_unlocked()
            user = next((item for item in state.users if item.user_id == user_id), None)
            if not user:
                raise ValueError("用户不存在")
            if sub2api_user_id is not None:
                user.sub2api_user_id = sub2api_user_id
            if sub2api_email is not None:
                user.sub2api_email = sub2api_email
            if sub2api_password is not None:
                user.sub2api_password = sub2api_password
            if sub2api_api_key is not None:
                user.sub2api_api_key = sub2api_api_key
            user.updated_at = _now()
            self._write_unlocked(state)
            return user

    def create_chat(self, user_id: str, title: str | None = None) -> ChatSession:
        with self.lock:
            state = self._read_unlocked()
            now = _now()
            chat = ChatSession(
                session_id=uuid.uuid4().hex,
                user_id=user_id,
                title=(title or "New chat").strip() or "New chat",
                created_at=now,
                updated_at=now,
            )
            state.chats.append(chat)
            self._write_unlocked(state)
            return chat

    def get_chat(self, user_id: str, session_id: str) -> ChatSession | None:
        with self.lock:
            state = self._read_unlocked()
            return next(
                (chat for chat in state.chats if chat.session_id == session_id and chat.user_id == user_id),
                None,
            )

    def save_chat(self, chat: ChatSession):
        with self.lock:
            state = self._read_unlocked()
            for index, existing in enumerate(state.chats):
                if existing.session_id == chat.session_id:
                    state.chats[index] = chat
                    break
            else:
                state.chats.append(chat)
            self._write_unlocked(state)

    def append_message(
        self,
        chat: ChatSession,
        *,
        role: str,
        content: str,
        status: str = "completed",
        error: str | None = None,
    ) -> ChatMessage:
        now = _now()
        message = ChatMessage(
            message_id=uuid.uuid4().hex,
            role=role,
            content=content,
            status=status,
            error=error,
            created_at=now,
        )
        chat.messages.append(message)
        chat.updated_at = now
        if role == "user" and (chat.title == "New chat" or not chat.title.strip()):
            chat.title = (content.strip().splitlines()[0][:48] or "New chat").strip()
        self.save_chat(chat)
        return message

    def update_message(
        self,
        chat: ChatSession,
        message_id: str,
        *,
        content: str | None = None,
        status: str | None = None,
        error: str | None = None,
    ) -> ChatMessage | None:
        for message in chat.messages:
            if message.message_id != message_id:
                continue
            if content is not None:
                message.content = content
            if status is not None:
                message.status = status
            if error is not None:
                message.error = error
            chat.updated_at = _now()
            self.save_chat(chat)
            return message
        return None


store = JsonStore(settings.storage_dir / "app-state.json")
