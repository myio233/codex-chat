from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_DIR = Path(__file__).resolve().parent
ROOT_DIR = APP_DIR.parent
ENV_FILE = ROOT_DIR / ".env"

if ENV_FILE.exists():
    load_dotenv(ENV_FILE, override=True)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(ENV_FILE), extra="ignore")

    app_host: str = Field(default="127.0.0.1", alias="APP_HOST")
    app_port: int = Field(default=8787, alias="APP_PORT")
    app_origin: str = Field(default="*", alias="APP_ORIGIN")
    app_title: str = Field(default="Codex Chat", alias="APP_TITLE")
    site_url: str = Field(default="http://127.0.0.1:8787", alias="SITE_URL")

    internal_only: bool = Field(default=True, alias="INTERNAL_ONLY")
    allow_public_signup: bool = Field(default=False, alias="ALLOW_PUBLIC_SIGNUP")
    admin_email: str = Field(default="", alias="ADMIN_EMAIL")
    admin_password: str = Field(default="", alias="ADMIN_PASSWORD")
    admin_name: str = Field(default="Admin", alias="ADMIN_NAME")
    session_ttl_seconds: int = Field(default=60 * 60 * 24 * 30, alias="SESSION_TTL_SECONDS")

    codex_bin: str = Field(default="codex", alias="CODEX_BIN")
    codex_exec_bin: Path = Field(
        default=Path(""),
        alias="CODEX_EXEC_BIN",
    )
    agent_provider_mode: str = Field(default="host", alias="AGENT_PROVIDER_MODE")
    codex_workspace_root: Path = Field(default=ROOT_DIR / "workspaces", alias="CODEX_WORKSPACE_ROOT")
    linux_user_pool_prefix: str = Field(default="codexweb", alias="LINUX_USER_POOL_PREFIX")
    linux_user_pool_start: int = Field(default=1, alias="LINUX_USER_POOL_START")
    linux_user_pool_size: int = Field(default=100, alias="LINUX_USER_POOL_SIZE")
    linux_sandbox_root: Path = Field(default=Path("/var/lib/codex-chat/sandboxes"), alias="LINUX_SANDBOX_ROOT")
    codex_run_as_linux_user: bool = Field(default=False, alias="CODEX_RUN_AS_LINUX_USER")
    codex_model: str = Field(default="", alias="CODEX_MODEL")
    codex_web_api_key: str = Field(default="", alias="CODEX_WEB_API_KEY")
    codex_web_base_url: str = Field(default="", alias="CODEX_WEB_BASE_URL")
    codex_allow_dangerous: bool = Field(default=False, alias="CODEX_ALLOW_DANGEROUS")
    codex_host_home: Path = Field(default=Path.home(), alias="CODEX_HOST_HOME")
    proot_bin: Path = Field(default=Path(""), alias="PROOT_BIN")
    proot_lib_dir: Path = Field(default=Path(""), alias="PROOT_LIB_DIR")
    sub2api_base_url: str = Field(default="http://127.0.0.1:8080", alias="SUB2API_BASE_URL")
    sub2api_admin_email: str = Field(default="", alias="SUB2API_ADMIN_EMAIL")
    sub2api_admin_password: str = Field(default="", alias="SUB2API_ADMIN_PASSWORD")
    sub2api_model: str = Field(default="gpt-5.4", alias="SUB2API_MODEL")
    sub2api_plus_concurrency: int = Field(default=5, alias="SUB2API_PLUS_CONCURRENCY")
    sub2api_free_concurrency: int = Field(default=0, alias="SUB2API_FREE_CONCURRENCY")
    sub2api_user_email_domain: str = Field(default="sub2api.local", alias="SUB2API_USER_EMAIL_DOMAIN")
    sub2api_timeout_seconds: int = Field(default=20, alias="SUB2API_TIMEOUT_SECONDS")

    llm_web_agent_base_url: str = Field(default="", alias="LLM_WEB_AGENT_BASE_URL")
    llm_web_agent_token: str = Field(default="", alias="LLM_WEB_AGENT_TOKEN")
    llm_web_agent_env_file: Path = Field(default=Path(""), alias="LLM_WEB_AGENT_ENV_FILE")
    llm_web_agent_model: str = Field(default="gpt-5-3", alias="LLM_WEB_AGENT_MODEL")
    llm_web_agent_timeout_seconds: int = Field(default=300, alias="LLM_WEB_AGENT_TIMEOUT_SECONDS")

    storage_dir: Path = Field(default=ROOT_DIR / "storage", alias="STORAGE_DIR")
    frontend_dir: Path = ROOT_DIR / "frontend"


settings = Settings()
settings.storage_dir.mkdir(parents=True, exist_ok=True)
settings.codex_workspace_root.mkdir(parents=True, exist_ok=True)
