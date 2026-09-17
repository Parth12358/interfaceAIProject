"""Centralized runtime configuration.

Single source of truth for env-derived settings. Nothing here decides *behavior*
during replay (that lives in the artifact); this is process/infra config only.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # dotenv optional at runtime
    pass


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class LLMConfig:
    api_key: str | None
    base_url: str
    model: str


@dataclass(frozen=True)
class Config:
    llm: LLMConfig
    target_app_url: str
    target_app_port: int
    inject_timeout: bool
    surface: str
    chrome_debug_port: int
    viewport: tuple[int, int]


def load() -> Config:
    return Config(
        llm=LLMConfig(
            api_key=os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY"),
            base_url=os.environ.get("LLM_BASE_URL", "https://api.deepseek.com"),
            model=os.environ.get("LLM_MODEL", "deepseek-flash"),
        ),
        target_app_url=os.environ.get("TARGET_APP_URL", "http://127.0.0.1:5000/"),
        target_app_port=_int("TARGET_APP_PORT", 5000),
        inject_timeout=os.environ.get("CORESERV_INJECT_TIMEOUT", "0") == "1",
        surface=os.environ.get("SURFACE", "cdp"),
        chrome_debug_port=_int("CHROME_REMOTE_DEBUG_PORT", 9222),
        viewport=(_int("VIEWPORT_W", 1280), _int("VIEWPORT_H", 800)),
    )
