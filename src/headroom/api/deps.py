from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Request

from headroom.core.config import Settings


@lru_cache
def _settings() -> Settings:
    return Settings()


def get_settings() -> Settings:
    return _settings()


SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_repo(request: Request):
    return request.app.state.repo


def get_day_queue(request: Request):
    return request.app.state.day_queue


def get_night_queue(request: Request):
    return request.app.state.night_queue


def get_gates(request: Request) -> dict:
    return request.app.state.gates
