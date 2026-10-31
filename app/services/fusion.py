"""FusionService (section 8.6 D-E): fragments -> 2-3 candidate sentences, or a yes/no question.

Only the EvidencePacket (text and derived features) is sent to Groq, never media (R4). The
LLM output is validated (schema, 2-3 rule, coverage) with one retry. The post-validator then
drops any candidate that adds a word not traceable to the evidence or the function-word
allowlist (R10). Added words are computed here, not taken on trust from the LLM.
"""

from __future__ import annotations

import json
import logging

from pydantic import ValidationError

from app.config import ROOT, Settings
from app.core.fragments import tokens
from app.core.health import HealthRegistry
from app.schemas import Candidate, EvidencePacket, FusionResult, coverage_errors

log = logging.getLogger(__name__)

PROMPTS = ROOT / "prompts"
TEMPERATURE = 0.2
MAX_TOKENS = 300  # spec cap on output tokens (D-033)

# Groq strict structured output: every property required, every object closed (Groq docs).
FUSION_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "intent",
        "candidates",
        "unexplained_fragment_ids",
        "clarifying_question",
        "clarification_required",
        "reasoning_summary",
    ],
    "properties": {
        "intent": {"type": "string"},
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["text", "covers", "added_words"],
                "properties": {
                    "text": {"type": "string"},
                    "covers": {"type": "array", "items": {"type": "integer"}},
                    "added_words": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "unexplained_fragment_ids": {"type": "array", "items": {"type": "integer"}},
        "clarifying_question": {"type": ["string", "null"]},
        "clarification_required": {"type": "boolean"},
        "reasoning_summary": {"type": "string"},
    },
}


def load_function_words(lang: str) -> set[str]:
    words: set[str] = set()
    for code in {"en", lang if lang in ("en", "hi") else "hi"}:
        path = PROMPTS / f"function_words_{code}.txt"
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                words.update(tokens(line) or [line.lower()])
    return words


class GroqLLM:
    """LLMClient over Groq chat completions with strict json_schema output (groq SDK 1.7)."""

    def __init__(self, api_key: str, model: str) -> None:
        from groq import Groq

        self._client = Groq(api_key=api_key)
        self.model = model

    def complete_json(self, system: str, user: str, *, temperature: float, max_tokens: int) -> str:
        res = self._client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=temperature,
            max_completion_tokens=max_tokens,
            reasoning_effort="low",
            include_reasoning=False,
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "fusion_result", "strict": True, "schema": FUSION_SCHEMA},
            },
        )
        return res.choices[0].message.content or ""


def packet_json(packet: EvidencePacket) -> str:
    """The exact user message: the packet only, compact, no media (R4)."""
    d = packet.model_dump()
    d["fragments"] = [
        {k: f[k] for k in ("id", "source", "text", "gap_ms", "confidence", "flags")}
        for f in d["fragments"]
    ]
    for t in d["context"]:
        t.pop("ts_ms", None)
    for p in d["phrasebook_hits"]:
        p.pop("last_used_ms", None)
    return json.dumps(d, ensure_ascii=False, separators=(",", ":"))


def clarification(reason: str, question: str | None = None, ids: list[int] | None = None):
    return FusionResult(
        intent="unclear",
        candidates=[],
        unexplained_fragment_ids=ids or [],
        clarifying_question=question,
        clarification_required=True,
        reasoning_summary=reason[:200],
    )


def evidence_vocabulary(packet: EvidencePacket) -> tuple[set[str], set[str]]:
    """(fragment tokens, all traceable tokens: fragments, context, profile, phrasebook)."""
    frag = {t for f in packet.fragments for t in tokens(f.text)}
    frag |= {t for c in packet.cleaned_fragments for t in tokens(c)}
    other = {t for c in packet.context for t in tokens(c.text)}
    other |= {t for term in packet.profile_terms for t in tokens(term)}
    other |= {t for p in packet.phrasebook_hits for t in tokens(p.text)}
    for c in packet.clarifications:
        other |= set(tokens(c.get("question", "")))
    return frag, frag | other


def post_validate(
    result: FusionResult, packet: EvidencePacket, function_words: set[str]
) -> tuple[FusionResult, list[dict]]:
    """R10: drop candidates with unsupported additions; recompute added_words in code."""
    frag_vocab, vocab = evidence_vocabulary(packet)
    kept: list[Candidate] = []
    dropped: list[dict] = []
    for c in result.candidates:
        toks = tokens(c.text)
        unsupported = [t for t in toks if t not in vocab and t not in function_words]
        if unsupported or not toks:
            dropped.append({"text": c.text, "unsupported": unsupported})
            continue
        added: list[str] = []
        for t in toks:
            if t not in frag_vocab and t not in added:
                added.append(t)
        kept.append(c.model_copy(update={"added_words": added}))
    update: dict = {"candidates": kept}
    if not kept and result.candidates:
        return (
            clarification(
                "every candidate added unsupported words",
                ids=[f.id for f in packet.fragments if "filler" not in f.flags],
            ),
            dropped,
        )
    if len(kept) == 1 and not result.clarification_required:
        update["clarification_required"] = True
        update["clarifying_question"] = (
            result.clarifying_question or f'Did you mean: "{kept[0].text}"?'
        )
    return result.model_copy(update=update), dropped


def lip_only(packet: EvidencePacket) -> bool:
    content = [f for f in packet.fragments if "filler" not in f.flags]
    return bool(content) and all(f.source == "lip" for f in content)


class FusionService:
    def __init__(self, settings: Settings, health: HealthRegistry, llm=None) -> None:
        self._s = settings
        self._health = health
        self._llm = llm
        self._backend = "fake" if llm is not None else "real"
        self.system_prompt = (PROMPTS / "fusion_system.md").read_text(encoding="utf-8")
        self._fw: dict[str, set[str]] = {}
        self.last_debug: dict = {}

    def _client(self):
        if self._llm is None:
            if not self._s.groq_api_key:
                raise RuntimeError("GROQ_API_KEY not set")
            self._llm = GroqLLM(self._s.groq_api_key, self._s.llm_model)
        return self._llm

    def function_words(self, lang: str) -> set[str]:
        if lang not in self._fw:
            self._fw[lang] = load_function_words(lang)
        return self._fw[lang]

    def reconstruct(self, packet: EvidencePacket) -> FusionResult:
        content = [f for f in packet.fragments if "filler" not in f.flags]
        if not content:
            return clarification("no content fragments", None)
        user = packet_json(packet)
        result: FusionResult | None = None
        errors: list[str] = []
        for _attempt in range(2):  # first try plus one retry (section 8.6 D)
            try:
                raw = self._client().complete_json(
                    self.system_prompt, user, temperature=TEMPERATURE, max_tokens=MAX_TOKENS
                )
            except Exception as exc:
                log.warning("fusion LLM call failed: %s", type(exc).__name__)
                errors.append(f"llm call failed: {type(exc).__name__}")
                continue
            try:
                candidate = FusionResult.model_validate_json(raw)
                cov = coverage_errors(candidate, packet.fragments)
                if cov:
                    raise ValueError("; ".join(cov))
                result = candidate
                break
            except (ValidationError, ValueError) as exc:
                errors.append(f"invalid output: {str(exc)[:160]}")
        self.last_debug = {"errors": errors, "dropped": []}
        if result is None:
            return clarification(
                "reconstruction failed validation twice; please repeat",
                None,
                [f.id for f in content],
            )
        result, dropped = post_validate(result, packet, self.function_words(packet.language_pref))
        self.last_debug["dropped"] = dropped
        if lip_only(packet) and not result.clarification_required:
            q = result.clarifying_question
            if not q and result.candidates:
                q = f'Did you mean: "{result.candidates[0].text}"?'
            result = result.model_copy(
                update={"clarification_required": True, "clarifying_question": q}
            )
        return result
