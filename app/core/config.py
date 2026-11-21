"""全局配置：全部来自环境变量 / .env，禁止在代码里写死密钥。"""

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # 应用
    app_env: str = "local"
    log_level: str = "INFO"
    app_host: str = "127.0.0.1"
    app_port: int = 8420

    # 数据库：本地 SQLite，生产 Neon Postgres
    database_url: str = "sqlite+aiosqlite:///./data/zhiwei.db"

    # Telegram
    telegram_bot_token: str = ""
    telegram_user_id: int | None = None
    telegram_webhook_secret: str = ""
    telegram_webhook_url: str = ""
    # 国内直连 Telegram 不通时填本地代理，例如 http://127.0.0.1:7897
    telegram_proxy: str = ""
    bot_mode: str = "polling"  # polling | webhook

    # 模型
    llm_provider: str = "ollama"  # ollama | gemini | openrouter
    llm_fallback_provider: str = ""
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3:8b"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    openrouter_api_key: str = ""
    openrouter_model: str = ""
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-chat"
    deepseek_base_url: str = "https://api.deepseek.com"

    # 人格
    ai_name: str = "知微"
    user_name: str = "木川"

    # 只读 HTTP 接口的访问令牌（不设则关闭这些接口）
    admin_api_token: str = ""

    # 记忆
    memory_auto_save: bool = True

    @field_validator("telegram_user_id", mode="before")
    @classmethod
    def _blank_to_none(cls, v: object) -> object:
        """`.env` 里留空（TELEGRAM_USER_ID=）时视为未配置，而不是解析失败。"""
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        return v

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    def public_dict(self) -> dict:
        """给 /health、日志用的脱敏快照：绝不包含任何密钥。"""
        return {
            "app_env": self.app_env,
            "database": "sqlite" if self.is_sqlite else "postgres",
            "llm_provider": self.llm_provider,
            "llm_fallback": self.llm_fallback_provider or None,
            "bot_mode": self.bot_mode,
            "ai_name": self.ai_name,
            "user_name": self.user_name,
            "telegram_configured": bool(self.telegram_bot_token),
            "owner_bound": self.telegram_user_id is not None,
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
