import pytest

from app.core.consent import ConsentRegistry
from app.core.errors import ConsentRequiredError
from app.schemas import CONSENT_PURPOSES


def test_registry_requires_each_purpose_separately():
    reg = ConsentRegistry()
    for p in CONSENT_PURPOSES:
        with pytest.raises(ConsentRequiredError):
            reg.require(p)
    reg.grant("camera")
    reg.require("camera")
    with pytest.raises(ConsentRequiredError):
        reg.require("microphone")


def test_revoke_notifies_listeners_once():
    reg = ConsentRegistry()
    seen: list[str] = []
    reg.on_revoke(seen.append)
    reg.revoke("avatar")  # never granted: no notification
    reg.grant("avatar")
    reg.revoke("avatar")
    assert seen == ["avatar"]
    assert not reg.has("avatar")


def test_unknown_purpose_is_an_error():
    with pytest.raises(ValueError):
        ConsentRegistry().grant("telemetry")


def test_consent_api_roundtrip(client):
    r = client.get("/consent")
    assert r.status_code == 200
    assert {c["purpose"]: c["granted"] for c in r.json()} == {p: False for p in CONSENT_PURPOSES}

    r = client.post("/consent", json={"purpose": "camera"})
    assert r.status_code == 200 and r.json()["granted"] is True

    granted = {c["purpose"] for c in client.get("/consent").json() if c["granted"]}
    assert granted == {"camera"}

    r = client.delete("/consent/camera")
    assert r.status_code == 200 and r.json()["granted"] is False


def test_consent_api_rejects_unknown_purpose_with_error_body(client):
    for r in (
        client.post("/consent", json={"purpose": "telemetry"}),
        client.delete("/consent/telemetry"),
    ):
        assert r.status_code == 422
        body = r.json()
        assert set(body) == {"error_code", "message", "recoverable"}
        assert body["error_code"] == "invalid_request"
