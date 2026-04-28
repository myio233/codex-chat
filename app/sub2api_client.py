from __future__ import annotations

import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from app.config import settings
from app.models import UserRecord
from app.store import store


@dataclass(frozen=True)
class Sub2APIIdentity:
    user_id: int
    email: str
    password: str
    api_key: str


class Sub2APIError(RuntimeError):
    pass


class Sub2APIClient:
    def __init__(self):
        self._admin_token: str | None = None
        self._admin_token_deadline = 0.0

    def enabled(self) -> bool:
        return settings.agent_provider_mode == "sub2api"

    def ensure_user_identity(self, user: UserRecord) -> Sub2APIIdentity:
        if not self.enabled():
            raise Sub2APIError("Sub2API integration is disabled")

        if not settings.sub2api_admin_email or not settings.sub2api_admin_password:
            raise Sub2APIError("SUB2API admin credentials are not configured")

        mapped_email = user.sub2api_email or self.build_internal_email(user.user_id)
        mapped_password = user.sub2api_password or self.generate_password()
        remote_user_id = user.sub2api_user_id

        if remote_user_id is None:
            remote_user = self.create_user(mapped_email, mapped_password)
            remote_user_id = int(remote_user["id"])
            user = store.set_user_sub2api_credentials(
                user.user_id,
                sub2api_user_id=remote_user_id,
                sub2api_email=mapped_email,
                sub2api_password=mapped_password,
            )

        self.sync_user_limits(user, remote_user_id)

        api_key = user.sub2api_api_key
        if not api_key:
            user_token = self.login(mapped_email, mapped_password)
            created_key = self.create_api_key(
                user_token,
                name=f"codex-chat-{user.user_id[:8]}",
            )
            api_key = created_key["key"]
            store.set_user_sub2api_credentials(user.user_id, sub2api_api_key=api_key)

        return Sub2APIIdentity(
            user_id=remote_user_id,
            email=mapped_email,
            password=mapped_password,
            api_key=api_key,
        )

    def build_internal_email(self, user_id: str) -> str:
        return f"codex-chat+{user_id}@{settings.sub2api_user_email_domain}"

    def generate_password(self) -> str:
        return f"CodexChat_{secrets.token_urlsafe(24)}"

    def sync_user_limits(self, user: UserRecord, remote_user_id: int):
        payload = {
            "status": "active" if user.enabled else "disabled",
            "concurrency": settings.sub2api_plus_concurrency if user.plan == "plus" else settings.sub2api_free_concurrency,
            "notes": f"codex-chat:{user.user_id}:{user.email}",
        }
        self.request(
            "PUT",
            f"/api/v1/admin/users/{remote_user_id}",
            payload=payload,
            token=self.admin_token(),
        )

    def admin_token(self) -> str:
        now = time.time()
        if self._admin_token and now < self._admin_token_deadline:
            return self._admin_token
        token = self.login(settings.sub2api_admin_email, settings.sub2api_admin_password)
        self._admin_token = token
        self._admin_token_deadline = now + 60 * 30
        return token

    def create_user(self, email: str, password: str) -> dict[str, Any]:
        response = self.request(
            "POST",
            "/api/v1/admin/users",
            payload={"email": email, "password": password},
            token=self.admin_token(),
        )
        return response["data"]

    def create_api_key(self, token: str, *, name: str) -> dict[str, Any]:
        response = self.request(
            "POST",
            "/api/v1/keys",
            payload={"name": name},
            token=token,
        )
        return response["data"]

    def login(self, email: str, password: str) -> str:
        response = self.request(
            "POST",
            "/api/v1/auth/login",
            payload={"email": email, "password": password},
        )
        return response["data"]["access_token"]

    def request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        payload: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        base_url = settings.sub2api_base_url.rstrip("/")
        url = f"{base_url}{path}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query, doseq=True)}"

        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        data = None
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        request = urllib.request.Request(url, method=method, data=data, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=settings.sub2api_timeout_seconds) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise Sub2APIError(f"Sub2API {method} {path} failed: {body or exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise Sub2APIError(f"Sub2API {method} {path} failed: {exc.reason}") from exc

        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:
            raise Sub2APIError(f"Sub2API {method} {path} returned invalid JSON") from exc

        if parsed.get("code") not in (0, "0", None):
            raise Sub2APIError(f"Sub2API {method} {path} failed: {parsed.get('message', 'unknown error')}")
        return parsed


sub2api_client = Sub2APIClient()
