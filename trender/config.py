"""Konfiguracja aplikacji wczytywana ze zmiennych środowiskowych / pliku .env."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    demo_mode: Literal["auto", "on", "off"] = "auto"

    allegro_client_id: str = ""
    allegro_client_secret: str = ""
    allegro_sandbox: bool = False

    ebay_client_id: str = ""
    ebay_client_secret: str = ""
    ebay_marketplace: str = "EBAY_DE"

    etsy_api_key: str = ""
    etsy_shared_secret: str = ""

    olx_enabled: bool = True

    serpapi_key: str = ""
    pytrends_enabled: bool = True
    trends_geo: str = "PL"

    thingiverse_token: str = ""
    cults3d_username: str = ""
    cults3d_api_key: str = ""
    myminifactory_api_key: str = ""
    printables_enabled: bool = True

    db_path: str = "data/trender.db"
    refresh_interval_hours: float = 24
    market_cache_hours: float = 6
    host: str = "127.0.0.1"
    port: int = 8000


@lru_cache
def get_settings() -> Settings:
    return Settings()
