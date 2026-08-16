"""환경 설정. 값은 .env 또는 환경변수로 덮어쓸 수 있다 (AWS 배포 대비)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # 로컬은 SQLite, AWS로 옮길 때 postgresql+psycopg://... 로 바꾸면 된다.
    database_url: str = f"sqlite:///{(BASE_DIR / 'my_stock.db').as_posix()}"

    secret_key: str = "dev-only-change-me"
    session_max_age: int = 60 * 60 * 24 * 14  # 2주

    base_currency: str = "KRW"
    fx_pair: str = "USD/KRW"

    # 연휴로 시세가 비는 것을 대비한 조회 여유 기간 (기존 코드의 2일은 설·추석에 터졌다)
    quote_lookback_days: int = 10

    timezone: str = "Asia/Seoul"
    scheduler_enabled: bool = True
    scheduler_hour: int = 18  # KST 장 마감 후 일별 시세 수집


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
