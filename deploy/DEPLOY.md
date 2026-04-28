# Codex Chat Deployment

This guide shows a simple single-service deployment behind Nginx. It assumes the
project is installed at `/opt/codex-chat` and runs as the `codex-chat` Linux
user. Adjust paths, user names, and domains for your server.

## 1. Prepare The App

```bash
sudo mkdir -p /opt/codex-chat
sudo chown -R codex-chat:codex-chat /opt/codex-chat
cd /opt/codex-chat

python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and set:

```text
APP_HOST=127.0.0.1
APP_PORT=8787
SITE_URL=https://chat.example.com
ADMIN_EMAIL=admin@example.com
ADMIN_PASSWORD=replace-with-a-strong-password
CODEX_BIN=codex
CODEX_RUN_AS_LINUX_USER=false
```

## 2. Install systemd Service

```bash
sudo cp deploy/codex-chat.service /etc/systemd/system/codex-chat.service
sudo systemctl daemon-reload
sudo systemctl enable --now codex-chat.service
sudo systemctl status codex-chat.service --no-pager
```

## 3. Install Nginx Site

Replace `chat.example.com` in `deploy/nginx.example.conf` with your domain,
then install it:

```bash
sudo cp deploy/nginx.example.conf /etc/nginx/sites-available/codex-chat
sudo ln -s /etc/nginx/sites-available/codex-chat /etc/nginx/sites-enabled/codex-chat
sudo nginx -t
sudo systemctl reload nginx
```

## 4. Add TLS

```bash
sudo certbot --nginx -d chat.example.com
```

## 5. Optional Linux User Sandboxes

For multi-user isolation, review the provisioning script before running it:

```bash
sudo scripts/provision-linux-users.sh
```

Then set:

```text
CODEX_RUN_AS_LINUX_USER=true
LINUX_SANDBOX_ROOT=/var/lib/codex-chat/sandboxes
```

## Security Checklist

- Keep `.env` out of Git.
- Use a strong admin password.
- Keep `INTERNAL_ONLY=true` for private deployments.
- Do not expose public signup until user isolation and rate limits are reviewed.
- Back up `storage/` if you need to preserve chat history.
