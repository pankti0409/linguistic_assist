from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, load_settings
from app.main import create_app

BASE_URL = "http://127.0.0.1"  # TrustedHostMiddleware refuses Starlette's default "testserver"
# websocket_connect() ignores base_url and joins onto ws://testserver, so pass an absolute URL.
WS_URL = "ws://127.0.0.1/ws"


@pytest.fixture
def settings() -> Settings:
    # Never read the developer's real .env in tests.
    return load_settings({"SIMULATE": "1"})


@pytest.fixture
def client(settings: Settings):
    with TestClient(create_app(settings), base_url=BASE_URL) as c:
        yield c
