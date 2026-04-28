from __future__ import annotations

import asyncio
import json
import os
import pwd
import shutil
from urllib.parse import quote
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

from app.config import settings
from app.models import ChatSession
from app.store import store
from app.sub2api_client import sub2api_client


@dataclass(frozen=True)
class UserSandbox:
    root: Path
    workspace: Path
    home: Path
    guest_root: Path
    tmp: Path


class CodexRunner:
    system_binds = (
        Path("/bin"),
        Path("/usr"),
        Path("/lib"),
        Path("/lib64"),
        Path("/etc"),
        Path("/dev"),
        Path("/proc"),
        Path("/run/systemd/resolve"),
    )

    def sandbox_for_user(self, user_id: str) -> UserSandbox:
        user = store.get_user(user_id)
        if settings.codex_run_as_linux_user and user and user.linux_username:
            root = settings.linux_sandbox_root / user.linux_username
        else:
            root = settings.codex_workspace_root / user_id
        workspace = root / "workspace"
        home = root / "home"
        guest_root = root / ".guest-root"
        tmp = root / "tmp"
        workspace.mkdir(parents=True, exist_ok=True)
        (home / ".codex").mkdir(parents=True, exist_ok=True)
        guest_root.mkdir(parents=True, exist_ok=True)
        (guest_root / "home" / "codex").mkdir(parents=True, exist_ok=True)
        (guest_root / "tmp").mkdir(parents=True, exist_ok=True)
        (guest_root / "workspace").mkdir(parents=True, exist_ok=True)
        (guest_root / "opt" / "codex").mkdir(parents=True, exist_ok=True)
        tmp.mkdir(parents=True, exist_ok=True)
        return UserSandbox(root=root, workspace=workspace, home=home, guest_root=guest_root, tmp=tmp)

    def codex_executable(self) -> str:
        configured_exec = str(settings.codex_exec_bin).strip()
        if configured_exec and configured_exec != "." and Path(configured_exec).exists():
            return configured_exec
        configured_bin = str(settings.codex_bin).strip()
        if configured_bin:
            resolved = shutil.which(configured_bin) or configured_bin
            if Path(resolved).exists() or shutil.which(configured_bin):
                return resolved
        raise RuntimeError("Codex executable not found. Set CODEX_BIN or CODEX_EXEC_BIN in .env.")

    def can_use_proot(self) -> bool:
        return (
            settings.proot_bin.exists()
            and os.access(settings.proot_bin, os.X_OK)
            and (settings.proot_lib_dir / "libtalloc.so.2").exists()
        )

    def ensure_user_sandbox(self, user_id: str) -> UserSandbox:
        sandbox = self.sandbox_for_user(user_id)
        self.sync_runtime_home(sandbox)
        return sandbox

    def sync_runtime_home(self, sandbox: UserSandbox):
        runtime_codex_home = sandbox.home / ".codex"
        runtime_codex_home.mkdir(parents=True, exist_ok=True)

        if settings.agent_provider_mode == "sub2api":
            self.write_sub2api_runtime_home(sandbox)
            return

        if settings.codex_web_api_key:
            self.write_direct_runtime_home(runtime_codex_home)
            return

        host_codex_home = settings.codex_host_home / ".codex"
        auth_path = host_codex_home / "auth.json"
        if auth_path.exists():
            runtime_auth_path = runtime_codex_home / "auth.json"
            tmp_auth_path = runtime_auth_path.with_suffix(".tmp")
            shutil.copy2(auth_path, tmp_auth_path)
            tmp_auth_path.replace(runtime_auth_path)
            runtime_auth_path.chmod(0o660)

        config_path = host_codex_home / "config.toml"
        if config_path.exists():
            sanitized = self.sanitize_config(config_path.read_text(encoding="utf-8"))
            runtime_config_path = runtime_codex_home / "config.toml"
            self.replace_text(runtime_config_path, sanitized)
            runtime_config_path.chmod(0o660)

    def write_direct_runtime_home(self, runtime_codex_home: Path):
        config_lines = [
            f'model = "{settings.codex_model}"',
            'model_reasoning_effort = "high"',
            'approval_policy = "never"',
            'sandbox_mode = "danger-full-access"',
            'network_access = "enabled"',
            'disable_response_storage = true',
            "",
            "[notice]",
            "hide_full_access_warning = true",
            "hide_rate_limit_model_nudge = true",
            "",
        ]
        if settings.codex_web_base_url:
            config_lines = [
                'model_provider = "web-openai"',
                *config_lines,
                "[model_providers.web-openai]",
                'name = "web-openai"',
                f'base_url = "{self.responses_base_url(settings.codex_web_base_url)}"',
                'wire_api = "responses"',
                "requires_openai_auth = true",
                "",
            ]
        config_path = runtime_codex_home / "config.toml"
        self.replace_text(config_path, "\n".join(config_lines))
        config_path.chmod(0o660)

        auth_payload = {"OPENAI_API_KEY": settings.codex_web_api_key}
        auth_path = runtime_codex_home / "auth.json"
        self.replace_text(auth_path, json.dumps(auth_payload))
        auth_path.chmod(0o660)

    def write_sub2api_runtime_home(self, sandbox: UserSandbox):
        user = store.get_user(sandbox.root.name)
        if not user:
            raise RuntimeError("User not found while preparing sandbox")

        identity = sub2api_client.ensure_user_identity(user)
        runtime_codex_home = sandbox.home / ".codex"
        config_lines = [
            'model_provider = "sub2api"',
            f'model = "{settings.sub2api_model}"',
            'model_reasoning_effort = "high"',
            'network_access = "enabled"',
            'disable_response_storage = true',
            "",
            "[model_providers.sub2api]",
            'name = "sub2api"',
            f'base_url = "{settings.sub2api_base_url.rstrip("/")}/v1"',
            'wire_api = "responses"',
            "requires_openai_auth = true",
            "",
        ]
        config_path = runtime_codex_home / "config.toml"
        self.replace_text(config_path, "\n".join(config_lines))
        config_path.chmod(0o660)
        auth_payload = {"OPENAI_API_KEY": identity.api_key}
        auth_path = runtime_codex_home / "auth.json"
        self.replace_text(auth_path, json.dumps(auth_payload))
        auth_path.chmod(0o660)

    def responses_base_url(self, raw_url: str) -> str:
        base_url = raw_url.rstrip("/")
        if base_url.endswith("/v1"):
            return base_url
        return f"{base_url}/v1"

    def replace_text(self, path: Path, content: str):
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(content, encoding="utf-8")
        tmp_path.replace(path)

    def sanitize_config(self, raw: str) -> str:
        lines: list[str] = []
        skip_section = False

        for line in raw.splitlines():
            stripped = line.strip()
            if stripped.startswith("[projects."):
                skip_section = True
                continue
            if skip_section and stripped.startswith("[") and not stripped.startswith("[projects."):
                skip_section = False
            if skip_section:
                continue
            lines.append(line)

        return ("\n".join(lines).strip() + "\n") if lines else ""

    def build_command(self, chat: ChatSession, prompt: str) -> tuple[list[str], dict[str, str]]:
        self.validate_runtime_dependencies()
        sandbox = self.ensure_user_sandbox(chat.user_id)
        user = store.get_user(chat.user_id)
        linux_username = user.linux_username if user and settings.codex_run_as_linux_user else None
        codex_executable = self.codex_executable()
        if linux_username:
            self.validate_linux_user(linux_username)
            command = [
                codex_executable,
                "exec",
                "--skip-git-repo-check",
                "--ephemeral",
                "-C",
                str(sandbox.workspace),
                "--json",
                "--dangerously-bypass-approvals-and-sandbox",
            ]
        elif self.can_use_proot():
            command = [str(settings.proot_bin), "-r", str(sandbox.guest_root)]
            for host_path in self.system_binds:
                if host_path.exists():
                    command.extend(["-b", str(host_path)])
            command.extend(
                [
                    "-b",
                    f"{sandbox.workspace}:/workspace",
                    "-b",
                    f"{sandbox.home}:/home/codex",
                    "-b",
                    f"{sandbox.tmp}:/tmp",
                    "-b",
                    f"{Path(codex_executable).parent}:/opt/codex",
                    "-w",
                    "/workspace",
                    "/opt/codex/codex",
                    "exec",
                    "--skip-git-repo-check",
                    "--ephemeral",
                    "-C",
                    "/workspace",
                    "--json",
                    "--dangerously-bypass-approvals-and-sandbox",
                ]
            )
        else:
            command = [
                codex_executable,
                "exec",
                "--skip-git-repo-check",
                "--ephemeral",
                "-C",
                str(sandbox.workspace),
                "--json",
                "--dangerously-bypass-approvals-and-sandbox",
            ]
        model_name = settings.sub2api_model if settings.agent_provider_mode == "sub2api" else settings.codex_model
        if model_name:
            command.extend(["-m", model_name])
        if chat.thread_id:
            command.extend(["resume", chat.thread_id, prompt])
        else:
            command.append(prompt)
        env = os.environ.copy()
        env["HOME"] = str(sandbox.home) if linux_username or not self.can_use_proot() else "/home/codex"
        env["CODEX_HOME"] = str(Path(env["HOME"]) / ".codex")
        env["PATH"] = f"{Path(codex_executable).parent}:/usr/bin:/bin"
        env["TMPDIR"] = str(sandbox.tmp) if linux_username or not self.can_use_proot() else "/tmp"
        if self.can_use_proot():
            env["LD_LIBRARY_PATH"] = str(settings.proot_lib_dir)
        env.pop("CODEX_THREAD_ID", None)
        if linux_username:
            command = [
                "sudo",
                "-n",
                "-u",
                linux_username,
                f"HOME={env['HOME']}",
                f"CODEX_HOME={env['CODEX_HOME']}",
                f"PATH={env['PATH']}",
                f"TMPDIR={env['TMPDIR']}",
                f"LD_LIBRARY_PATH={env.get('LD_LIBRARY_PATH', '')}",
                *command,
            ]
        return command, env

    def validate_linux_user(self, linux_username: str):
        try:
            pwd.getpwnam(linux_username)
        except KeyError as exc:
            raise RuntimeError(
                f"Linux user {linux_username} does not exist. Run scripts/provision-linux-users.sh first."
            ) from exc

    def validate_runtime_dependencies(self):
        self.codex_executable()
        if settings.codex_run_as_linux_user:
            return
        if self.can_use_proot():
            return

    def generated_images(self, sandbox: UserSandbox) -> dict[str, Path]:
        images_root = sandbox.home / ".codex" / "generated_images"
        if not images_root.exists():
            return {}
        images: dict[str, Path] = {}
        for path in images_root.rglob("*"):
            if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
                images[str(path.relative_to(images_root))] = path
        return images

    def generated_image_markdown(self, user_id: str, image_keys: list[str]) -> str:
        lines = []
        for image_key in image_keys:
            encoded = "/".join(quote(part) for part in image_key.split("/"))
            lines.append(f"![Generated Image](/api/generated-images/{user_id}/{encoded})")
        return "\n\n".join(lines)

    async def stream_turn(self, chat: ChatSession, prompt: str) -> AsyncIterator[dict]:
        sandbox = self.sandbox_for_user(chat.user_id)
        images_before = set(self.generated_images(sandbox))
        command, env = self.build_command(chat, prompt)
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        final_text = ""
        thread_id = chat.thread_id
        codex_error = ""

        assert process.stdout is not None
        async for raw_line in process.stdout:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                yield {"type": "log", "message": line}
                continue

            event_type = event.get("type")
            if event_type == "error":
                codex_error = str(event.get("message") or codex_error)
                yield {"type": "log", "message": codex_error}
                continue

            if event_type == "turn.failed":
                error = event.get("error") or {}
                codex_error = str(error.get("message") or event.get("message") or codex_error)
                yield {"type": "log", "message": codex_error}
                continue

            if event_type == "thread.started":
                thread_id = event.get("thread_id") or thread_id
                yield {"type": "thread", "thread_id": thread_id}
                continue

            if event_type == "item.completed":
                item = event.get("item") or {}
                if item.get("type") == "agent_message":
                    text = item.get("text", "")
                    if text:
                        final_text = text
                        yield {"type": "assistant", "content": final_text}
                continue

            yield {"type": "event", "payload": event}

        stderr_text = ""
        if process.stderr is not None:
            stderr_bytes = await process.stderr.read()
            stderr_text = stderr_bytes.decode("utf-8", errors="replace").strip()

        return_code = await process.wait()
        if codex_error:
            raise RuntimeError(codex_error)
        if return_code != 0:
            raise RuntimeError(stderr_text or f"Codex exited with code {return_code}")
        images_after = self.generated_images(sandbox)
        new_image_keys = sorted(set(images_after) - images_before)
        if new_image_keys:
            image_markdown = self.generated_image_markdown(chat.user_id, new_image_keys)
            final_text = f"{final_text}\n\n{image_markdown}".strip()
            yield {"type": "assistant", "content": final_text}
        if not final_text:
            raise RuntimeError("Codex returned no assistant message")

        yield {
            "type": "done",
            "thread_id": thread_id,
            "content": final_text,
        }


codex_runner = CodexRunner()
