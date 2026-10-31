"""TurnMachine (section 3): PARTNER and PATIENT turns, from capture to spoken message.

States: IDLE -> CAPTURING -> FUSING -> AWAITING_CONFIRM ->
        (SPEAKING -> IDLE | EDITING -> AWAITING_CONFIRM | REJECTED -> IDLE | CLARIFY -> CAPTURING)
A PARTNER turn goes CAPTURING -> IDLE (no fusion). If every output tier fails, SPEAKING
returns to AWAITING_CONFIRM so the patient can confirm again (D-036). Anything else is an
illegal transition (HTTP 409).

A PATIENT draft stays open across pauses. It closes on /turn/end, the __COMMIT__ gesture,
FRAGMENT_SILENCE_S without speech or fragments (only once it has a fragment), or
FRAGMENT_MAX_S.
"""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.config import Settings
from app.core.confirmation import ConfirmationRegistry
from app.core.consent import ConsentRegistry
from app.core.conversation import Conversation
from app.core.errors import AppError, IllegalTransitionError
from app.core.events import EventBus
from app.core.fragments import FragmentCollector, clean
from app.core.phrasebook import Phrasebook, ProfileTerms
from app.core.timing import Metrics, TurnTimer, now_ms
from app.schemas import EvidencePacket, Fragment, FusionResult, GestureWord, SpeechEvidence

log = logging.getLogger(__name__)

IDLE, CAPTURING, FUSING, AWAITING = "IDLE", "CAPTURING", "FUSING", "AWAITING_CONFIRM"
SPEAKING, EDITING, REJECTED, CLARIFY = "SPEAKING", "EDITING", "REJECTED", "CLARIFY"
TRANSITIONS: dict[str, set[str]] = {
    IDLE: {CAPTURING},
    CAPTURING: {FUSING, IDLE},
    FUSING: {AWAITING},
    AWAITING: {SPEAKING, EDITING, REJECTED, CLARIFY},
    EDITING: {AWAITING},
    SPEAKING: {IDLE, AWAITING},
    REJECTED: {IDLE},
    CLARIFY: {CAPTURING},
}
YES_NO = {"yes", "no"}
FALLBACK_PROMPT = "choose, edit or repeat"


class BadRequestError(AppError):
    status_code = 422
    error_code = "bad_request"
    recoverable = True


class OutputFailedError(AppError):
    status_code = 502
    error_code = "output_failed"
    recoverable = True


@dataclass
class Turn:
    id: str
    speaker: str
    modalities: list[str]
    language_pref: str
    state: str = IDLE
    collector: FragmentCollector = field(default_factory=FragmentCollector)
    timer: TurnTimer | None = None
    fragments: list[Fragment] = field(default_factory=list)  # flagged, after cleanup
    cleaned: list[str] = field(default_factory=list)
    result: FusionResult | None = None
    fallback: dict[str, str] | None = None
    clarify_rounds: int = 0
    clarifications: list[dict[str, str]] = field(default_factory=list)
    pending_edit: str | None = None
    final_text: str | None = None
    raw_transcripts: list[str] = field(default_factory=list)  # untouched Scribe output (WER)
    mouth_seen: bool = False
    closing: bool = False
    end_reason: str | None = None
    last_activity_ms: int = field(default_factory=now_ms)
    started_ms: int = field(default_factory=now_ms)
    spoken: dict[str, Any] | None = None

    def view(self) -> dict[str, Any]:
        items = self.fragments or self.collector.items()
        return {
            "turn_id": self.id,
            "speaker": self.speaker,
            "state": self.state,
            "modalities": self.modalities,
            "language_pref": self.language_pref,
            "fragments": [f.model_dump() for f in items],
            "cleaned_fragments": self.cleaned,
            "result": self.result.model_dump() if self.result else None,
            "fallback": self.fallback,
            "clarify_rounds": self.clarify_rounds,
            "pending_edit": self.pending_edit,
            "final_text": self.final_text,
            "raw_transcripts": self.raw_transcripts,
            "end_reason": self.end_reason,
            "spoken": self.spoken,
        }


class TurnMachine:
    def __init__(
        self,
        settings: Settings,
        bus: EventBus,
        consent: ConsentRegistry,
        conversation: Conversation,
        phrasebook: Phrasebook,
        profile: ProfileTerms,
        fusion,
        scribe,
        speech_out,
        confirmations: ConfirmationRegistry,
        metrics: Metrics,
        lip=None,
        gesture=None,
        face=None,
        watchdog_s: float = 0.2,
    ) -> None:
        self._s = settings
        self._bus = bus
        self._consent = consent
        self.conversation = conversation
        self.phrasebook = phrasebook
        self.profile = profile
        self.fusion = fusion
        self.scribe = scribe
        self.speech_out = speech_out
        self.confirmations = confirmations
        self.metrics = metrics
        self.lip = lip
        self.gesture = gesture
        self.face = face
        self._lock = threading.RLock()
        self._turn: Turn | None = None
        self._replaying = False
        if gesture is not None:
            gesture.subscribe_words(self._on_gesture_word)
        self._stop = threading.Event()
        self._watchdog_s = watchdog_s
        self._watch = threading.Thread(target=self._watchdog, name="turn-watchdog", daemon=True)
        self._watch.start()

    # --- state helpers ---------------------------------------------------

    def current(self) -> Turn | None:
        with self._lock:
            return self._turn

    def state(self) -> str:
        with self._lock:
            return self._turn.state if self._turn else IDLE

    def _go(self, turn: Turn, new: str) -> None:
        if new not in TRANSITIONS[turn.state]:
            raise IllegalTransitionError(f"{turn.state} -> {new} is not allowed")
        turn.state = new
        self._bus.publish("turn.state", {"turn_id": turn.id, "speaker": turn.speaker, "state": new})

    def _require(self, turn_id: str | None, *states: str) -> Turn:
        t = self._turn
        if t is None or t.state == IDLE:
            raise IllegalTransitionError("no active turn")
        if turn_id is not None and turn_id != t.id:
            raise IllegalTransitionError(f"turn {turn_id} is not the active turn")
        if states and t.state not in states:
            raise IllegalTransitionError(f"turn is {t.state}, expected {' or '.join(states)}")
        return t

    # --- start / end -----------------------------------------------------

    def start(self, speaker: str, modalities: list[str], language_pref: str = "en") -> Turn:
        mods = list(dict.fromkeys(modalities or ["speech"]))
        with self._lock:
            if self._turn is not None and self._turn.state != IDLE:
                raise IllegalTransitionError(f"a turn is already {self._turn.state}")
            if speaker == "PARTNER":
                mods = ["speech"]  # partner turns are mic only
            # consent before any state change (R3)
            if "speech" in mods:
                self._consent.require("microphone")
            if {"gesture", "lip"} & set(mods):
                self._consent.require("camera")
            turn = Turn(
                id=uuid.uuid4().hex[:12],
                speaker=speaker,
                modalities=mods,
                language_pref=language_pref,
            )
            turn.timer = TurnTimer(turn.id, speaker)
            if self.speech_out is not None and hasattr(self.speech_out, "interrupt"):
                self.speech_out.interrupt()  # a new turn stops any avatar speech
            if "speech" in mods:
                self.scribe.start(speaker, language_pref, self._on_speech_final)
            if "lip" in mods and self.lip is not None:
                self.lip.start_capture()
            self._turn = turn
            self._go(turn, CAPTURING)
            return turn

    def end(self, turn_id: str | None = None, reason: str = "api") -> Turn:
        with self._lock:
            turn = self._require(turn_id, CAPTURING)
            if turn.closing:
                raise IllegalTransitionError("turn is already closing")
            turn.closing = True
            turn.end_reason = reason
            turn.timer.mark("end")  # type: ignore[union-attr]
        # slow work outside the lock: wait for the last transcriptions and the lip read
        if "speech" in turn.modalities:
            self.scribe.stop()
        turn.timer.mark("scribe_done")  # type: ignore[union-attr]
        lip_ev = None
        if "lip" in turn.modalities and self.lip is not None:
            try:
                lip_ev = self.lip.stop_capture().result(timeout=60)
            except Exception:
                log.exception("lip read failed")
            turn.timer.mark("lip_done")  # type: ignore[union-attr]
        if turn.speaker == "PARTNER":
            with self._lock:
                text = " ".join(t for t in turn.raw_transcripts if t.strip())
                turn.final_text = text
                self.conversation.add("PARTNER", text)
                self._go(turn, IDLE)
                self.metrics.record(turn.timer)  # type: ignore[arg-type]
                return turn
        if lip_ev is not None and lip_ev.status == "ok" and lip_ev.text:
            self._add_fragment(turn, "lip", lip_ev.text, confidence=lip_ev.score)
        with self._lock:
            self._go(turn, FUSING)
        self._fuse(turn)
        return turn

    # --- fusion -----------------------------------------------------------

    def _packet(self, turn: Turn) -> EvidencePacket:
        flagged, cleaned = clean(turn.collector.items())
        turn.fragments, turn.cleaned = flagged, cleaned
        return EvidencePacket(
            turn_id=turn.id,
            speaker="PATIENT",
            ts_ms=now_ms(),
            language_pref=turn.language_pref,
            fragments=flagged,
            cleaned_fragments=cleaned,
            mouth_activity=turn.mouth_seen,
            context=self.conversation.recent(),
            profile_terms=self.profile.for_packet(),
            phrasebook_hits=self.phrasebook.search(cleaned, self._s.phrasebook_topk),
            clarifications=turn.clarifications,
        )

    def _fuse(self, turn: Turn) -> None:
        packet = self._packet(turn)
        turn.timer.mark("fusion_start")  # type: ignore[union-attr]
        result = self.fusion.reconstruct(packet)
        turn.timer.marks["fusion_done"] = now_ms()  # type: ignore[union-attr]
        fallback = None
        capped = turn.clarify_rounds >= self._s.max_clarify_rounds
        if result.clarification_required and (capped or not result.clarifying_question):
            if not result.candidates or capped:
                # no more questions: show the cleaned fragments as plain text (section 8.6 F)
                # the patient's own content, without their yes/no answers
                _, content = clean(
                    [f for f in turn.collector.items() if "answer_to_question" not in f.flags]
                )
                fallback = {"text": " ".join(content), "prompt": FALLBACK_PROMPT}
                result = result.model_copy(update={"clarifying_question": None})
        with self._lock:
            turn.result, turn.fallback = result, fallback
            self._go(turn, AWAITING)
            turn.timer.mark("candidates")  # type: ignore[union-attr]
        self._bus.publish(
            "fusion.candidates",
            {
                "turn_id": turn.id,
                "result": result.model_dump(),
                "fallback": fallback,
                "fragments": [f.model_dump() for f in turn.fragments],
                "cleaned": turn.cleaned,
            },
        )
        if result.clarification_required and result.clarifying_question:
            self._bus.publish(
                "fusion.question",
                {
                    "turn_id": turn.id,
                    "question": result.clarifying_question,
                    "round": turn.clarify_rounds + 1,
                    "answer_with": ["Thumb_Up", "Thumb_Down"],
                },
            )

    # --- patient decisions ---------------------------------------------------

    def confirm(
        self, turn_id: str, choice_index: int | None = None, edited_text: str | None = None
    ) -> dict[str, Any]:
        with self._lock:
            turn = self._require(turn_id, AWAITING)
            timer = turn.timer
            timer.counters["taps"] += 1  # type: ignore[union-attr]
            edited = False
            if edited_text is not None:
                text = " ".join(edited_text.split())
                if not text:
                    raise BadRequestError("edited_text is empty")
                if turn.pending_edit != text:
                    # first submission: show the final text back before speaking (8.7)
                    self._go(turn, EDITING)
                    turn.pending_edit = text
                    timer.counters["edits"] += 1  # type: ignore[union-attr]
                    self._go(turn, AWAITING)
                    return {
                        "turn_id": turn.id,
                        "state": AWAITING,
                        "final_text": text,
                        "confirm_required": True,
                    }
                edited = True
            elif choice_index is not None:
                cands = turn.result.candidates if turn.result else []
                if not 0 <= choice_index < len(cands):
                    raise BadRequestError(f"choice_index {choice_index} out of range")
                text = cands[choice_index].text
            else:
                raise BadRequestError("give choice_index or edited_text")
            cid = self.confirmations.issue(turn.id, text)
            turn.final_text = text
            timer.mark("confirmed")  # type: ignore[union-attr]
            self._bus.publish(
                "confirm.issued", {"turn_id": turn.id, "confirmation_id": cid, "text": text}
            )
            self._go(turn, SPEAKING)
        try:
            spoken = self.speech_out.speak(cid, timer)
        except Exception as exc:
            with self._lock:
                self._go(turn, AWAITING)
            raise OutputFailedError(f"message was not spoken: {exc}") from exc
        with self._lock:
            turn.spoken = spoken
            self.conversation.add("PATIENT", text)
            self.phrasebook.add(text, edited=edited)
            self._go(turn, IDLE)
            self.metrics.record(timer)  # type: ignore[arg-type]
            self.metrics.bump("messages_spoken")
        return {"turn_id": turn.id, "state": IDLE, "final_text": text, "spoken": spoken}

    def replay(self) -> dict[str, Any]:
        """Say the last spoken PATIENT message again (D-057).

        The text is the one the patient already confirmed, taken from the finished turn and
        never from the request. It still goes through a fresh one-time confirmation ID (R2).
        It is not added to the context or phrasebook a second time.
        """
        with self._lock:
            turn = self._turn
            if turn is None or turn.state != IDLE or turn.speaker != "PATIENT":
                raise IllegalTransitionError("nothing to replay while a turn is open")
            if not turn.spoken or not turn.final_text:
                raise IllegalTransitionError("no spoken message to replay")
            if self._replaying:
                raise IllegalTransitionError("already replaying")
            self._replaying = True
            text = turn.final_text
            cid = self.confirmations.issue(turn.id, text)
            self._bus.publish(
                "confirm.issued",
                {"turn_id": turn.id, "confirmation_id": cid, "text": text, "replay": True},
            )
        try:
            spoken = self.speech_out.speak(cid, None)
        except Exception as exc:
            raise OutputFailedError(f"message was not spoken: {exc}") from exc
        finally:
            with self._lock:
                self._replaying = False
        self.metrics.bump("replays")
        return {"turn_id": turn.id, "state": IDLE, "final_text": text, "spoken": spoken}

    def reject(self, turn_id: str | None = None) -> Turn:
        with self._lock:
            turn = self._require(turn_id, AWAITING)
            turn.timer.counters["taps"] += 1  # type: ignore[union-attr]
            self._go(turn, REJECTED)  # rejected candidates are never stored (8.6 C)
            if self.speech_out is not None and hasattr(self.speech_out, "interrupt"):
                self.speech_out.interrupt()
            self._go(turn, IDLE)
            self.metrics.record(turn.timer)  # type: ignore[arg-type]
            self.metrics.bump("turns_rejected")
            return turn

    def clarify(self, answer: str, turn_id: str | None = None, source: str = "gesture") -> Turn:
        answer = " ".join((answer or "").split())
        if not answer:
            raise BadRequestError("answer is empty")
        with self._lock:
            turn = self._require(turn_id, AWAITING)
            r = turn.result
            if r is None or not r.clarification_required or not r.clarifying_question:
                raise IllegalTransitionError("there is no open clarifying question")
            if turn.clarify_rounds >= self._s.max_clarify_rounds:
                raise IllegalTransitionError("clarification rounds exhausted")
            turn.timer.counters["taps"] += 1  # type: ignore[union-attr]
            self._go(turn, CLARIFY)
            turn.clarifications.append({"question": r.clarifying_question, "answer": answer})
            turn.clarify_rounds += 1
            turn.timer.counters["clarify_rounds"] = turn.clarify_rounds  # type: ignore[union-attr]
            self._add_fragment(turn, source, answer, flags=["answer_to_question"])
            self._go(turn, CAPTURING)
            self._go(turn, FUSING)
        self._fuse(turn)
        return turn

    # --- evidence in -------------------------------------------------------------

    def _add_fragment(self, turn, source, text, *, ts_ms=None, confidence=None, flags=None):
        frag = turn.collector.add(source, text, ts_ms=ts_ms, confidence=confidence, flags=flags)
        if source != "speech":  # speech sets it from the utterance end in _on_speech_final
            turn.last_activity_ms = now_ms()
        self._bus.publish("fragment.added", {"turn_id": turn.id, "fragment": frag.model_dump()})
        flagged, cleaned = clean(turn.collector.items())
        self._bus.publish(
            "draft.updated",
            {
                "turn_id": turn.id,
                "fragments": [f.model_dump() for f in flagged],
                "cleaned": cleaned,
            },
        )
        return frag

    def _on_speech_final(self, ev: SpeechEvidence, seg) -> None:
        from app.services.scribe import is_low_confidence

        with self._lock:
            turn = self._turn
            if turn is None or turn.state != CAPTURING:
                return
            turn.raw_transcripts.append(ev.text)
            if not ev.text.strip():
                return  # empty finals (noise) carry no content (D-032) and keep the clock running
            # silence counts from when the person stopped talking, not from when the
            # transcript arrived ~1 s later (D-057)
            end = getattr(seg, "end_ms", None) or now_ms()
            turn.last_activity_ms = max(turn.last_activity_ms, min(end, now_ms()))
            if turn.speaker != "PATIENT":
                return  # partner text joins at end
            flags = ["low_confidence"] if is_low_confidence(ev) else []
            self._add_fragment(
                turn,
                "speech",
                ev.text,
                ts_ms=getattr(seg, "start_ms", None),
                confidence=ev.confidence,
                flags=flags,
            )

    def _on_gesture_word(self, gw: GestureWord) -> None:
        turn = self._turn
        if turn is None or turn.speaker != "PATIENT":
            return
        if turn.state == CAPTURING and not turn.closing:
            if gw.word == "__COMMIT__":
                threading.Thread(
                    target=self._safe, args=(self.end, turn.id, "commit"), daemon=True
                ).start()
            elif gw.word == "__CLEAR__":
                with self._lock:
                    turn.collector.clear()
                    turn.last_activity_ms = now_ms()
                self._bus.publish(
                    "draft.updated", {"turn_id": turn.id, "fragments": [], "cleaned": []}
                )
            elif "gesture" in turn.modalities and not gw.word.startswith("__"):
                with self._lock:
                    self._add_fragment(turn, "gesture", gw.word, confidence=gw.score)
        elif turn.state == AWAITING and gw.word in YES_NO:
            r = turn.result
            # the UI asks the question only when there is no candidate to offer (D-058)
            if r and r.clarification_required and r.clarifying_question and not r.candidates:
                threading.Thread(
                    target=self._safe, args=(self.clarify, gw.word, turn.id), daemon=True
                ).start()

    def _safe(self, fn, *args) -> None:
        try:
            fn(*args)
        except AppError as exc:
            log.info("ignored %s: %s", type(exc).__name__, exc.message)
        except Exception:
            log.exception("turn action failed")

    # --- watchdog ----------------------------------------------------------------

    def _watchdog(self) -> None:
        while not self._stop.wait(self._watchdog_s):
            try:
                self._tick()
            except Exception:
                log.exception("watchdog tick failed")

    def _tick(self) -> None:
        with self._lock:
            turn = self._turn
            if turn is None or turn.state != CAPTURING or turn.closing:
                return
            if self.face is not None and self.face.mouth_activity:
                turn.mouth_seen = True
            now = now_ms()
            reason = None
            if turn.speaker == "PATIENT":
                silent = now - turn.last_activity_ms >= self._s.fragment_silence_s * 1000
                # an utterance being spoken or transcribed holds the draft open without
                # restarting the clock; background noise alone no longer resets it (D-057)
                talking = "speech" in turn.modalities and getattr(self.scribe, "busy", False)
                if len(turn.collector) > 0 and silent and not talking:
                    reason = "silence"
                elif now - turn.started_ms >= self._s.fragment_max_s * 1000:
                    reason = "max_duration"
            elif now - turn.started_ms >= self._s.turn_max_s * 1000:
                reason = "max_duration"
        if reason:
            threading.Thread(
                target=self._safe, args=(self.end, turn.id, reason), daemon=True
            ).start()

    def shutdown(self) -> None:
        self._stop.set()
        t = self._turn
        if t is not None and t.state == CAPTURING and self.scribe.active:
            self.scribe.stop(timeout_s=1)
