from app.config import load_settings
from app.core.health import SERVICES, HealthRegistry


def test_health_lists_every_service_with_a_status(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert set(body["services"]) == {"camera", "face", "gesture", "lip", "scribe", "tts", "avatar"}
    for name, svc in body["services"].items():
        assert svc["status"] in {"ok", "degraded", "unavailable"}, name
    assert body["avatar_mode"] in {"full", "echo"}
    assert body["simulate"] is True
    assert any("Hindi" in s for s in body["limits"]["lip"])


def test_idle_services_are_unavailable_not_ok(client):
    # Nothing runs before consent; the fake lip reader is unavailable too.
    services = client.get("/health").json()["services"]
    assert all(s["status"] == "unavailable" for s in services.values())
    for name in ("camera", "face", "gesture"):
        assert services[name]["detail"].startswith("not built yet") or services[name]["detail"] in {
            "stopped"
        }


def test_health_never_exposes_secrets(tmp_path):
    secret = "sk_this_must_not_leak"
    reg = HealthRegistry(load_settings({"ELEVENLABS_API_KEY": secret, "VOICE_ID": "v"}))
    dumped = reg.snapshot().model_dump_json()
    assert secret not in dumped
    assert reg.get("scribe").configured is True and reg.get("tts").configured is True


def test_lip_configured_only_when_checkpoint_exists(tmp_path):
    ckpt = tmp_path / "vsr.pth"
    reg = HealthRegistry(load_settings({"LIP_CHECKPOINT": str(ckpt)}))
    assert reg.get("lip").configured is False
    ckpt.write_bytes(b"x")
    assert HealthRegistry(load_settings({"LIP_CHECKPOINT": str(ckpt)})).get("lip").configured
    off = HealthRegistry(load_settings({"LIP_CHECKPOINT": str(ckpt), "LIP_ENABLED": "0"}))
    assert off.get("lip").configured is False


def test_service_can_report_its_own_status():
    reg = HealthRegistry(load_settings({}))
    reg.set("camera", "ok", "index 0", backend="fake")
    cam = reg.get("camera")
    assert (cam.status, cam.backend) == ("ok", "fake")
    assert set(reg.snapshot().services) == set(SERVICES)
