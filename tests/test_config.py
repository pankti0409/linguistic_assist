import pytest

from app.config import BIND_HOST, load_settings


def test_defaults_match_spec_table():
    s = load_settings({})
    assert (s.camera_fps, s.camera_size, s.vision_fps) == (30, (640, 480), 15)
    assert (s.gesture_min_score, s.gesture_stable_frames) == (0.7, 8)
    assert (s.lip_buffer_s, s.lip_min_frames, s.lip_max_yaw_deg) == (4, 8, 25)
    assert s.context_turns == 6
    assert (s.fragment_silence_s, s.fragment_max_s) == (6, 45)
    assert (s.phrasebook_topk, s.max_clarify_rounds) == (5, 2)
    assert (s.confirm_ttl_s, s.turn_max_s) == (120, 20)
    assert s.llm_model == "openai/gpt-oss-120b"
    assert s.debug_save_clips is False


def test_env_overrides_and_inline_comments():
    s = load_settings(
        {"CAMERA_SIZE": "320x240", "FRAGMENT_SILENCE_S": "8", "TAVUS_PIPELINE_MODE": "echo   # x"}
    )
    assert s.camera_size == (320, 240)
    assert s.fragment_silence_s == 8
    assert s.tavus_pipeline_mode == "echo"


def test_microphone_device_env_supports_name_or_index():
    name = "MacBook Air Microphone"
    assert load_settings({"MIC_DEVICE": name}).mic_device == name
    assert load_settings({"MIC_DEVICE": "2"}).mic_device == "2"
    assert load_settings({}).mic_device == ""


def test_debug_save_clips_refused():
    with pytest.raises(ValueError, match="R8"):
        load_settings({"DEBUG_SAVE_CLIPS": "true"})


def test_bad_pipeline_mode_refused():
    with pytest.raises(ValueError):
        load_settings({"TAVUS_PIPELINE_MODE": "chatty"})


def test_bind_host_is_loopback():
    assert BIND_HOST == "127.0.0.1"
