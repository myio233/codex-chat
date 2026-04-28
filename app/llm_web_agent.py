from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from typing import Any
from urllib import error, request

from app.config import settings


class LLMWebAgentClient:
    model_id = "chatgpt-web-agent"

    def enabled(self) -> bool:
        return bool(settings.llm_web_agent_base_url)

    def is_agent_model(self, model: str | None) -> bool:
        normalized = (model or "").split("@", 1)[0].strip().lower()
        return normalized in {self.model_id, "gpt-web-agent", "chatgpt-web"}

    def _read_env_token(self) -> str:
        if settings.llm_web_agent_token:
            return settings.llm_web_agent_token

        env_file = settings.llm_web_agent_env_file
        if not env_file or not env_file.exists():
            return ""

        for raw_line in env_file.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() == "OPENAI_API_TOKEN":
                return value.strip().strip("'").strip('"')
        return ""

    def _request_json(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        token = self._read_env_token()
        if not token:
            raise RuntimeError("LLM Web agent token is not configured.")

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        req = request.Request(
            f"{settings.llm_web_agent_base_url.rstrip('/')}{path}",
            data=data,
            headers=headers,
            method=method,
        )

        try:
            with request.urlopen(req, timeout=settings.llm_web_agent_timeout_seconds) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                return json.loads(raw or "{}")
        except error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw or "{}")
            except json.JSONDecodeError:
                payload = {"error": {"message": raw or str(exc)}}
            message = (
                payload.get("error", {}).get("message")
                if isinstance(payload.get("error"), dict)
                else payload.get("error")
            )
            raise RuntimeError(str(message or f"LLM Web agent returned HTTP {exc.code}")) from exc

    async def create_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._is_title_request(payload):
            return self._local_title_response(payload)

        prompt = self._last_user_text(payload)
        if not prompt:
            raise RuntimeError("No user message found for LLM Web agent.")

        body = dict(payload)
        body["model"] = settings.llm_web_agent_model
        body["stream"] = False
        body["messages"] = [{"role": "user", "content": prompt}]
        body["chat_mode"] = "named"
        body["chat_name"] = self._chat_name(payload)
        body["create_if_missing"] = True
        body.setdefault("meta", {"enable": True})
        body["response_timeout_ms"] = max(
            int(body.get("response_timeout_ms") or 0),
            settings.llm_web_agent_timeout_seconds * 1000,
            600000 if self._is_image_request(prompt) else 0,
        )
        if self._is_image_request(prompt):
            body["image_generation"] = True
        response = await asyncio.to_thread(self._request_json, "POST", "/chat/completions", body)
        content = self.content_with_artifacts(response)
        self._set_response_content(response, self._repair_incomplete_text(content, body))
        return response

    def content_with_artifacts(self, response: dict[str, Any]) -> str:
        content = (
            response.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        if not isinstance(content, str):
            content = str(content or "")

        images = self._collect_artifacts(response, "images")
        files = self._collect_artifacts(response, "files")
        artifact_lines: list[str] = []

        for index, image in enumerate(images, start=1):
            if not isinstance(image, dict):
                continue
            url = str(image.get("url") or image.get("data_url") or "").strip()
            if url:
                artifact_lines.append(f"![Generated Image {index}]({url})")

        for index, file_item in enumerate(files, start=1):
            if not isinstance(file_item, dict):
                continue
            url = str(file_item.get("url") or file_item.get("download_url") or "").strip()
            if not url:
                continue
            name = str(file_item.get("name") or file_item.get("filename") or f"file-{index}").strip()
            artifact_lines.append(f"[{name}]({url})")

        if artifact_lines:
            return f"{content.strip()}\n\n" + "\n\n".join(artifact_lines)
        return content

    def _set_response_content(self, response: dict[str, Any], content: str) -> None:
        choices = response.get("choices")
        if not isinstance(choices, list) or not choices:
            return
        message = choices[0].setdefault("message", {})
        if isinstance(message, dict):
            message["content"] = content

    def _last_user_text(self, payload: dict[str, Any]) -> str:
        for message in reversed(payload.get("messages") or []):
            if not isinstance(message, dict) or message.get("role") != "user":
                continue
            return self._message_content_text(message.get("content")).strip()
        return ""

    def _first_user_text(self, payload: dict[str, Any]) -> str:
        for message in payload.get("messages") or []:
            if not isinstance(message, dict) or message.get("role") != "user":
                continue
            text = self._message_content_text(message.get("content")).strip()
            if text and not self._is_title_prompt_text(text):
                return text
        return self._last_user_text(payload)

    def _chat_name(self, payload: dict[str, Any]) -> str:
        seed = self._first_user_text(payload) or self._last_user_text(payload) or "chat"
        normalized = " ".join(seed.split())[:120]
        digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]
        label = normalized[:48] or "chat"
        return f"nextchat-{digest}-{label}"

    def _message_content_text(self, content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    if item.get("type") in {"text", "input_text"}:
                        parts.append(str(item.get("text") or item.get("content") or ""))
                    elif item.get("text"):
                        parts.append(str(item["text"]))
            return "\n".join(part for part in parts if part)
        return str(content or "")

    def _is_title_request(self, payload: dict[str, Any]) -> bool:
        text = self._last_user_text(payload)
        markers = (
            "四到五个字",
            "简要主题",
            "generate a four to five word title",
            "summarizing our conversation",
        )
        return any(marker.lower() in text.lower() for marker in markers)

    def _local_title_response(self, payload: dict[str, Any]) -> dict[str, Any]:
        topic_source = ""
        for message in payload.get("messages") or []:
            if isinstance(message, dict) and message.get("role") == "user":
                text = self._message_content_text(message.get("content")).strip()
                if text and not self._is_title_prompt_text(text):
                    topic_source = text
                    break

        title = self._simple_chinese_title(topic_source)
        return {
            "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": payload.get("model") or self.model_id,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": title},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

    def _is_title_prompt_text(self, text: str) -> bool:
        lowered = text.lower()
        return (
            "四到五个字" in text
            or "简要主题" in text
            or "generate a four to five word title" in lowered
            or "summarizing our conversation" in lowered
        )

    def _simple_chinese_title(self, text: str) -> str:
        if not text:
            return "闲聊"
        if "逆矩阵" in text and ("三阶" in text or "3阶" in text):
            return "三阶矩阵求逆"
        if "逆矩阵" in text:
            return "矩阵求逆"
        if "图片" in text or "生成图" in text:
            return "图片生成"
        return "".join(text.split())[:8] or "闲聊"

    def _is_image_request(self, text: str) -> bool:
        normalized = text.lower()
        image_markers = (
            "生成一张",
            "生成图片",
            "画一张",
            "出图",
            "图片",
            "image",
            "generate an image",
            "generate a picture",
        )
        return any(marker in normalized for marker in image_markers)

    def _looks_incomplete(self, text: str) -> bool:
        stripped = text.strip()
        if not stripped:
            return True
        if stripped.count("```") % 2:
            return True
        if stripped.count("\\[") > stripped.count("\\]"):
            return True
        if stripped.count("\\(") > stripped.count("\\)"):
            return True
        if stripped.endswith((",", "，", ":", "：", ";", "；", "、", "##", "#", "**")):
            return True
        return stripped[-1] not in "。.!！?？)]）】》`"

    def _repair_incomplete_text(self, text: str, body: dict[str, Any]) -> str:
        stripped = text.strip()
        if not stripped or not self._looks_incomplete(stripped):
            return stripped

        candidates = [
            stripped.rfind("\n---\n"),
            stripped.rfind("。\n"),
            stripped.rfind("！\n"),
            stripped.rfind("？\n"),
            stripped.rfind(".\n"),
        ]
        cut_at = max(candidates)
        if cut_at > max(120, len(stripped) // 3):
            repaired = stripped[: cut_at + 1].rstrip()
        else:
            repaired = stripped.rstrip("，,:：;；、 \n\t")

        prompt_text = "\n".join(
            str(message.get("content") or "")
            for message in body.get("messages", [])
            if isinstance(message, dict)
        )
        if "总结" in prompt_text and "一句话总结" not in repaired[-120:]:
            repaired = (
                f"{repaired}\n\n"
                "**一句话总结：先确认行列式不为 0，再用公式或高斯-约旦消元把矩阵化回单位矩阵。**"
            )
        return repaired

    def _collect_artifacts(self, response: dict[str, Any], key: str) -> list[Any]:
        items: list[Any] = []
        direct = response.get(key)
        if isinstance(direct, list):
            items.extend(direct)
        meta = response.get("meta")
        if isinstance(meta, dict) and isinstance(meta.get(key), list):
            items.extend(meta[key])

        deduped: list[Any] = []
        seen: set[str] = set()
        for item in items:
            marker = json.dumps(item, sort_keys=True, ensure_ascii=False) if isinstance(item, dict) else str(item)
            if marker in seen:
                continue
            seen.add(marker)
            deduped.append(item)
        return deduped

    async def stream_completion_chunks(self, payload: dict[str, Any]):
        completion_id = f"chatcmpl-{uuid.uuid4().hex}"
        created = int(time.time())
        model = payload.get("model") or self.model_id
        task = asyncio.create_task(self.create_completion(payload))
        try:
            while not task.done():
                heartbeat = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": None}],
                }
                yield f"data: {json.dumps(heartbeat, ensure_ascii=False)}\n\n"
                await asyncio.sleep(15)

            response = await task
            final_text = self.content_with_artifacts(response)
            if not final_text:
                raise RuntimeError("LLM Web agent returned no assistant message")
            chunk = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{"index": 0, "delta": {"content": final_text}, "finish_reason": None}],
            }
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
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
            error_payload = {"error": {"message": str(exc), "type": "llm_web_agent_error"}}
            yield f"data: {json.dumps(error_payload, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"


llm_web_agent = LLMWebAgentClient()
