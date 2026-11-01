import numpy as np
import pytest

from app.adapters import interfaces as i
from app.adapters.fakes import (
    FakeAvatar,
    FakeGroq,
    FakeLipReader,
    FakeScribe,
    FakeTavusAPI,
    FakeTTS,
    VideoFileCamera,
)
from app.schemas import LipEvidence


def test_fakes_satisfy_interfaces():
    assert isinstance(FakeScribe(), i.SpeechToText)
    assert isinstance(FakeGroq(), i.LLMClient)
    assert isinstance(FakeTTS(), i.TextToSpeech)
    assert isinstance(FakeAvatar(), i.AvatarTransport)
    assert isinstance(FakeTavusAPI(), i.TavusREST)
    assert isinstance(FakeLipReader(), i.LipReader)
    assert isinstance(VideoFileCamera("x.mp4"), i.FrameSource)


def test_fake_scribe_scripted_then_empty():
    s = FakeScribe(["wa", "water"])
    assert [s.transcribe(b"\0\0", 16000).text for _ in range(3)] == ["wa", "water", ""]
    assert s.calls == [2, 2, 2]


def test_fake_groq_scripted_and_exhaustion():
    g = FakeGroq(['{"a":1}'])
    assert g.complete_json("sys", "u", temperature=0.2, max_tokens=300) == '{"a":1}'
    assert g.requests[0]["temperature"] == 0.2
    with pytest.raises(RuntimeError):
        g.complete_json("sys", "u", temperature=0.2, max_tokens=300)


def test_fake_tts_and_avatar_record_and_fail():
    t = FakeTTS()
    assert t.synthesize("hello there", "v") and t.spoken == ["hello there"]
    with pytest.raises(ConnectionError):
        FakeTTS(fail=True).synthesize("x", "v")
    assert FakeTTS(fail=True).spoken == []
    a, got = FakeAvatar(), []
    a.join("https://tavus.daily.co/c1", got.append)
    a.send({"event_type": "conversation.echo", "properties": {"modality": "text", "done": True}})
    assert got == [{"event_type": "conversation.replica.started_speaking"}]
    quiet = FakeAvatar(silent_modalities=("text",))
    quiet.join("u", got.append)
    quiet.send({"event_type": "conversation.echo", "properties": {"modality": "text"}})
    assert len(got) == 1 and len(quiet.echoes("text")) == 1
    with pytest.raises(ConnectionError):
        FakeAvatar(fail_join=True).join("u", got.append)


def test_fake_lip_reader_defaults_to_unavailable():
    r = FakeLipReader()
    assert r.available is False
    out = r.read([np.zeros((88, 88), np.uint8)] * 3)
    assert out.status == "unavailable" and out.text is None and out.frames == 3
    scripted = FakeLipReader(LipEvidence(status="ok", text="water", score=0.4), available=True)
    assert scripted.read([np.zeros((88, 88), np.uint8)]).text == "water"


def test_video_file_camera_loops(tmp_path):
    cv2 = pytest.importorskip("cv2")
    # Synthetic coloured frames only; no real media is ever written (R8).
    path = str(tmp_path / "synthetic.avi")
    w = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"MJPG"), 10, (64, 48))
    for k in range(3):
        w.write(np.full((48, 64, 3), k * 80, np.uint8))
    w.release()

    cam = VideoFileCamera(path)
    assert cam.open()
    frames = [cam.read() for _ in range(7)]  # more than the 3 frames in the file
    assert all(ok and f.shape == (48, 64, 3) for ok, f in frames)
    cam.close()
    assert cam.read() == (False, None)


def test_video_file_camera_missing_file():
    pytest.importorskip("cv2")
    assert VideoFileCamera("does_not_exist.avi").open() is False
