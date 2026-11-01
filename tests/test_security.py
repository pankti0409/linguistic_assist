import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api.ws import origin_allowed
from app.config import load_settings
from app.core.consent import ConsentRegistry
from app.main import create_app
from tests.conftest import WS_URL, fake_overrides


@pytest.mark.parametrize(
    "origin, ok",
    [
        (None, True),  # non-browser client
        ("http://localhost:5173", True),
        ("http://127.0.0.1:3000", True),
        ("https://evil.example", False),
        ("http://127.0.0.1.evil.example", False),
        ("http://localhost.evil.example", False),
        ("null", False),
    ],
)
def test_origin_rules(origin, ok):
    assert origin_allowed(origin, ()) is ok


def test_origin_allowlist_from_env():
    s = load_settings({"ALLOWED_ORIGINS": "https://app.example, https://b.example"})
    assert s.allowed_origins == ("https://app.example", "https://b.example")
    assert origin_allowed("https://b.example", s.allowed_origins)


def test_ws_refuses_foreign_origin(client):
    # TestClient reports a pre-accept close as 1008; uvicorn sends it as HTTP 403 on the wire.
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(WS_URL, headers={"origin": "https://evil.example"}):
            pass
    assert exc.value.code == 1008
    assert client.app.state.bus.subscriber_count == 0


def test_ws_accepts_loopback_origin(client):
    with client.websocket_connect(WS_URL, headers={"origin": "http://localhost:5173"}) as ws:
        client.app.state.bus.publish("error", {"x": 1})
        assert ws.receive_json()["data"] == {"x": 1}


def test_foreign_host_header_refused(settings):
    # DNS rebinding: attacker's name resolves to 127.0.0.1 but the Host header is theirs.
    with TestClient(
        create_app(settings, fake_overrides()), base_url="http://rebind.evil.example"
    ) as c:
        assert c.get("/health").status_code == 400
    with TestClient(create_app(settings, fake_overrides()), base_url="http://localhost:8765") as c:
        assert c.get("/health").status_code == 200


def test_revoke_still_notifies_after_a_listener_fails():
    reg = ConsentRegistry()
    seen: list[str] = []

    def broken(_: str) -> None:
        raise RuntimeError("service failed to stop")

    reg.on_revoke(broken)
    reg.on_revoke(seen.append)
    reg.grant("camera")
    reg.revoke("camera")
    assert seen == ["camera"] and not reg.has("camera")
