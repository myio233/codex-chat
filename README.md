# Codex Chat

Codex Chat is an internal-first GPT-style web app backed by the Codex CLI. It
provides a browser chat UI, login-gated access, persistent chat history, and a
server-side bridge that can run Codex sessions for each user.

This repository contains the FastAPI backend, a lightweight static frontend, and
deployment templates.

## Features

- FastAPI backend with JSON API.
- Static browser chat UI served by the backend.
- Login-gated internal preview mode.
- Admin user management endpoints.
- Persistent users, tokens, and chat history in local JSON storage.
- Codex CLI bridge with resumable thread/session state.
- Optional per-user Linux sandbox provisioning.
- Optional Sub2API integration for user quota/concurrency management.
- Optional LLM Web API agent integration.
- Deployment templates for systemd and Nginx.

## Repository Layout

```text
.
├── app/
│   ├── config.py
│   ├── codex_runner.py
│   ├── llm_web_agent.py
│   ├── main.py
│   ├── models.py
│   ├── store.py
│   └── sub2api_client.py
├── frontend/
│   ├── index.html
│   ├── styles.css
│   └── app.js
├── deploy/
├── scripts/
├── .env.example
├── requirements.txt
└── run.py
```

Runtime directories are intentionally ignored:

- `.env`
- `storage/`
- `workspaces/`
- `tools/`
- `.playwright-mcp/`
- `test-results/`
- `nextchat/`

## Requirements

- Python 3.11+
- Codex CLI
- Optional: Nginx and systemd for production deployment

## Quick Start

Create and activate a virtual environment:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Create local configuration:

```bash
cp .env.example .env
```

Edit `.env` and set at least:

```text
ADMIN_EMAIL=admin@example.com
ADMIN_PASSWORD=change-me-now
CODEX_BIN=codex
CODEX_MODEL=
```

Start the app:

```bash
python run.py
```

Open:

```text
http://127.0.0.1:8787
```

## Configuration

Important settings:

```text
INTERNAL_ONLY=true
ALLOW_PUBLIC_SIGNUP=false
ADMIN_EMAIL=admin@example.com
ADMIN_PASSWORD=change-me-now
CODEX_BIN=codex
CODEX_WORKSPACE_ROOT=./workspaces
STORAGE_DIR=./storage
```

For a simple local demo, keep:

```text
CODEX_RUN_AS_LINUX_USER=false
```

For a multi-user server deployment, review `deploy/DEPLOY.md` and
`scripts/provision-linux-users.sh` before enabling per-user Linux sandboxes.

## API Surface

Common endpoints:

- `GET /api/config`
- `POST /api/auth/login`
- `POST /api/auth/logout`
- `GET /api/me`
- `GET /api/chat/sessions`
- `POST /api/chat/sessions`
- `GET /api/chat/sessions/{session_id}`
- `POST /api/chat/sessions/{session_id}/messages`
- `GET /api/admin/users`
- `PATCH /api/admin/users/{user_id}`

The frontend uses bearer tokens returned by `/api/auth/login`.

## Deployment

Production deployment templates live in `deploy/`:

- `deploy/codex-chat.service`
- `deploy/nginx.example.conf`

The deployment guide is in:

```text
deploy/DEPLOY.md
```

Before using the templates on another machine, replace hardcoded paths, service
users, and domains with your own values.

## Development Notes

The backend keeps the implementation intentionally small and file-based. This is
useful for internal previews, but a public deployment should replace JSON storage
with a real database, add stronger audit logging, and harden user isolation.
