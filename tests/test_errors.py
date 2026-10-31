from fastapi import APIRouter

from app.core.errors import ConsentRequiredError, IllegalTransitionError


def test_app_errors_render_spec_body(client):
    router = APIRouter()

    @router.get("/_boom/consent")
    def _c():
        raise ConsentRequiredError("camera")

    @router.get("/_boom/409")
    def _t():
        raise IllegalTransitionError("IDLE -> SPEAKING")

    @router.get("/_boom/crash")
    def _x():
        raise KeyError("secret-detail")

    client.app.include_router(router)

    r = client.get("/_boom/consent")
    assert r.status_code == 403
    assert r.json() == {
        "error_code": "consent_required",
        "message": "consent for 'camera' has not been recorded; POST /consent first",
        "recoverable": True,
    }
    r = client.get("/_boom/409")
    assert r.status_code == 409 and r.json()["error_code"] == "illegal_transition"


def test_unhandled_error_hides_details(settings):
    from fastapi.testclient import TestClient

    from app.main import create_app

    app = create_app(settings)

    @app.get("/_boom")
    def _x():
        raise KeyError("secret-detail")

    with TestClient(app, base_url="http://127.0.0.1", raise_server_exceptions=False) as c:
        r = c.get("/_boom")
    assert r.status_code == 500
    assert r.json() == {"error_code": "internal_error", "message": "KeyError", "recoverable": False}


def test_unknown_route_uses_error_body(client):
    r = client.get("/nope")
    assert r.status_code == 404 and r.json()["error_code"] == "http_404"
