import pytest

from app.adapters.fakes import FakeMic, FakeScribe, silence, tone
from app.config import load_settings
from app.core.consent import ConsentRegistry
from app.core.errors import ConsentRequiredError
from app.core.health import HealthRegistry
from app.schemas import SpeechEvidence
from app.services.scribe import ScribeService, Segmenter, is_low_confidence
from tests.test_camera import Recorder


def test_segmenter_cuts_at_pauses_and_drops_blips():
    seg = Segmenter(silence_ms=700)
    audio = (
        silence(600) + tone(500) + silence(900) + tone(80) + silence(900) + tone(700) + silence(800)
    )
    segs, voiced = seg.feed(audio, t_ms=0)
    segs += seg.flush()
    assert voiced
    assert len(segs) == 2  # the 80 ms blip is shorter than min_ms
    assert all(400 <= s.end_ms - s.start_ms <= 2000 for s in segs)
    assert segs[0].end_ms < segs[1].start_ms


def test_short_pause_does_not_split():
    seg = Segmenter(silence_ms=700)
    segs, _ = seg.feed(silence(300) + tone(400) + silence(300) + tone(400) + silence(900), t_ms=0)
    assert len(segs) == 1


def test_flush_returns_open_utterance():
    seg = Segmenter()
    segs, _ = seg.feed(silence(300) + tone(600), t_ms=0)
    assert segs == [] and seg.in_speech
    assert len(seg.flush()) == 1


def _svc(transcripts, audio, granted=True):
    s = load_settings({})
    consent = ConsentRegistry()
    if granted:
        consent.grant("microphone")
    mic = FakeMic(audio)
    bus = Recorder()
    svc = ScribeService(s, bus, HealthRegistry(s), consent, FakeScribe(transcripts), lambda: mic)
    return svc, mic, bus


def test_service_transcribes_each_utterance_in_order():
    audio = silence(400) + tone(500) + silence(900) + tone(500) + silence(900) + tone(500)
    svc, mic, bus = _svc(["wa", "water", "cold"], audio)
    finals = []
    svc.start("PATIENT", "en", lambda ev, seg: finals.append((ev.text, seg.start_ms)))
    mic.wait_done()
    results = svc.stop()
    assert [r.text for r in results] == ["wa", "water", "cold"]
    assert [t for t, _ in finals] == ["wa", "water", "cold"]
    starts = [s for _, s in finals]
    assert starts == sorted(starts)
    assert [e["speaker"] for e in bus.of("speech.final")] == ["PATIENT"] * 3


def test_microphone_requires_consent():
    svc, _, _ = _svc([], b"", granted=False)
    with pytest.raises(ConsentRequiredError):
        svc.start("PATIENT", "en", lambda *a: None)


def test_transcriber_failure_is_soft():
    class Broken:
        def transcribe(self, *a, **k):
            raise ConnectionError("no network")

    s = load_settings({})
    consent = ConsentRegistry()
    consent.grant("microphone")
    mic = FakeMic(silence(300) + tone(500) + silence(900))
    health, bus = HealthRegistry(s), Recorder()
    svc = ScribeService(s, bus, health, consent, Broken(), lambda: mic)
    svc.start("PARTNER", "en", lambda *a: None)
    mic.wait_done()
    assert svc.stop() == []
    assert health.get("scribe").status == "unavailable" and bus.of("error")


def test_low_confidence_rule():
    assert is_low_confidence(SpeechEvidence(text="", is_final=True))
    assert is_low_confidence(SpeechEvidence(text="ab", is_final=True))
    assert is_low_confidence(SpeechEvidence(text="water", is_final=True, confidence=0.2))
    assert not is_low_confidence(SpeechEvidence(text="water", is_final=True, confidence=0.9))
    assert not is_low_confidence(SpeechEvidence(text="water", is_final=True))
