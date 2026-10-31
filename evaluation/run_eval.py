"""Evaluation harness (section 9): ablation R0 / A / A+ / B / C, plus optional WER, and a
measured-only report.

  R0  raw concatenated speech fragments shown as-is (baseline, no LLM)
  A   speech fragments + deterministic cleanup + partner context
  A+  A + profile terms + phrasebook
  B   A+ + gesture words
  C   B + lip hint (scenario `lip_ref`; simulated, no checkpoint is installed)

Groq calls are capped by --max-llm-calls and cached on disk by prompt hash
(evaluation/cache/, gitignored), so a rerun spends nothing. A scenario whose LLM call could
not be made is `not_run`. It is excluded from every rate and counted in the report, never
scored as a pass or a fail.

Usage:
  python evaluation/run_eval.py                       # test split, real Groq, no WER
  python evaluation/run_eval.py --wer --voice EXAVITQu4vr4xnSDxMaL
  python evaluation/run_eval.py --split tune --max-llm-calls 40
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import load_settings  # noqa: E402
from app.core.fragments import clean  # noqa: E402
from app.core.health import HealthRegistry  # noqa: E402
from app.schemas import DialogueTurn, EvidencePacket, Fragment, PhraseEntry  # noqa: E402
from app.services.fusion import FusionService, GroqLLM, LLMUnavailableError  # noqa: E402
from evaluation import metrics as M  # noqa: E402

CONFIGS = ["R0", "A", "A+", "B", "C"]
CACHE = ROOT / "evaluation" / "cache"


class BudgetExceeded(LLMUnavailableError):
    pass


class CachedLLM:
    """Wraps the real LLM: cache hit -> no call; miss -> call if budget remains."""

    def __init__(self, inner, budget: int) -> None:
        self.inner, self.budget = inner, budget
        self.calls = self.hits = self.refused = 0
        self.tripped: str | None = None
        self._asked: dict[str, int] = {}
        CACHE.mkdir(parents=True, exist_ok=True)

    def complete_json(self, system: str, user: str, *, temperature: float, max_tokens: int):
        base = f"{system}\n{user}\n{temperature}\n{max_tokens}"
        # the n-th ask of the same prompt is its own entry, so the spec's retry is a real retry
        nth = self._asked.get(base, 0)
        self._asked[base] = nth + 1
        key = hashlib.sha256(f"{base}\n#{nth}".encode()).hexdigest()
        path = CACHE / f"{key}.json"
        if path.is_file():
            self.hits += 1
            return json.loads(path.read_text(encoding="utf-8"))["raw"]
        if self.tripped:
            raise BudgetExceeded(f"not attempted after {self.tripped}")
        if self.calls >= self.budget:
            raise BudgetExceeded("eval LLM budget exhausted")
        try:
            raw = self.inner.complete_json(
                system, user, temperature=temperature, max_tokens=max_tokens
            )
        except LLMUnavailableError as exc:
            self.refused += 1
            self.tripped = str(exc)  # first refusal stops further calls this run
            raise
        self.calls += 1
        path.write_text(json.dumps({"raw": raw}, ensure_ascii=False), encoding="utf-8")
        return raw


def build_packet(sc: dict, config: str) -> EvidencePacket:
    frags: list[Fragment] = []
    t = 0

    def add(source, text, gap, conf=None):
        nonlocal t
        t += gap
        frags.append(
            Fragment(
                id=len(frags) + 1, ts_ms=t, gap_ms=gap, source=source, text=text, confidence=conf
            )
        )

    for f in sc["fragments"]:
        add("speech", f["text"], f["gap_ms"])
    if config in ("B", "C"):
        for g in sc["gesture_tokens"]:
            add("gesture", g["word"], 1200, g["score"])
    if config == "C" and sc.get("lip_ref"):
        add("lip", sc["lip_ref"], 900, None)
    flagged, cleaned = clean(frags)
    ctx = (
        [DialogueTurn(speaker="PARTNER", text=sc["partner_line"], ts_ms=0)]
        if sc["partner_line"]
        else []
    )
    personal = config in ("A+", "B", "C")
    return EvidencePacket(
        turn_id=sc["id"],
        speaker="PATIENT",
        ts_ms=t,
        language_pref=sc["language"],
        fragments=flagged,
        cleaned_fragments=cleaned,
        context=ctx,
        profile_terms=sc["profile_terms"] if personal else [],
        phrasebook_hits=[PhraseEntry(text=p, uses=1, last_used_ms=0) for p in sc["phrasebook"]]
        if personal
        else [],
    )


def evidence_text(p: EvidencePacket) -> str:
    parts = [f.text for f in p.fragments] + [c.text for c in p.context] + p.profile_terms
    parts += [h.text for h in p.phrasebook_hits]
    return " ".join(parts)


def judge(
    sc: dict,
    packet: EvidencePacket,
    cands: list[str],
    covers: list[list[int]],
    clarified: bool,
    fw: set[str],
) -> dict:
    allowed = {w.lower() for w in sc.get("allowed_additions", [])}
    target = sc["target_sentence"]

    def acc(c: str) -> bool:
        return (M.content_words(c, fw) - allowed) == (M.content_words(target, fw) - allowed)

    expected = sc["expected_clarification"]
    first_ok = bool(cands) and not expected and acc(cands[0])
    any_ok = not expected and any(acc(c) for c in cands)
    content_ids = {f.id for f in packet.fragments if "filler" not in f.flags}
    coverage = (
        len(set(covers[0]) & content_ids) / len(content_ids)
        if cands and content_ids and covers
        else None
    )
    ev = evidence_text(packet)
    unsupported = [M.unsupported_words(c, ev, fw) for c in cands]
    # simulated patient: one tap to pick an accepted candidate or to answer / reject;
    # otherwise edit (one edit, two taps for the two-step confirm)
    if expected:
        taps, edits = 1, 0
    elif any_ok:
        taps, edits = 1, 0
    else:
        taps, edits = (3, 1) if clarified else (2, 1)
    return {
        "first_accepted": first_ok,
        "any_accepted": any_ok,
        "clarified": clarified,
        "intent_ok": M.intent_correct(
            cands[0] if cands else None, clarified, expected, sc["intent_keywords"]
        ),
        "coverage": coverage,
        "n_candidates": len(cands),
        "n_unsupported": sum(1 for u in unsupported if u),
        "taps": taps,
        "edits": edits,
    }


def run_config(config: str, scenarios: list[dict], fusion: FusionService | None, fw):
    rows = []
    for sc in scenarios:
        packet = build_packet(sc, config)
        row = {
            "id": sc["id"],
            "language": sc["language"],
            "category": sc["category"],
            "expected_clarification": sc["expected_clarification"],
        }
        if config == "R0":
            raw = " ".join(f["text"] for f in sc["fragments"])
            cands = [raw] if raw.strip() else []
            covers = [[f.id for f in packet.fragments]] if cands else []
            row.update(judge(sc, packet, cands, covers, False, fw), status="ok", fusion_ms=None)
        else:
            t0 = time.perf_counter()
            result = fusion.reconstruct(packet)  # type: ignore[union-attr]
            ms = (time.perf_counter() - t0) * 1000
            errs = fusion.last_debug.get("errors", [])  # type: ignore[union-attr]
            content = [f for f in packet.fragments if "filler" not in f.flags]
            # any refusal makes the outcome unknown (e.g. invalid first output, refused retry)
            if content and any("unavailable" in e or "budget" in e for e in errs):
                row.update(status="not_run", reason=errs[-1])
                rows.append(row)
                continue
            cands = [c.text for c in result.candidates]
            covers = [c.covers for c in result.candidates]
            row.update(
                judge(sc, packet, cands, covers, result.clarification_required, fw),
                status="ok",
                fusion_ms=round(ms, 1) if content else None,
                first_candidate=cands[0] if cands else None,
                question=result.clarifying_question,
            )
        rows.append(row)
    return rows


def summarise(rows: list[dict]) -> dict:
    ok = [r for r in rows if r["status"] == "ok"]
    msg = [r for r in ok if not r["expected_clarification"]]
    neg = [r for r in ok if r["expected_clarification"]]
    by_lang = defaultdict(list)
    for r in ok:
        by_lang[r["language"]].append(r["intent_ok"])
    fus = [r["fusion_ms"] for r in ok if r.get("fusion_ms") is not None]
    cov = [r["coverage"] for r in msg if r.get("coverage") is not None]
    n_cand = sum(r["n_candidates"] for r in ok)
    rounds = [1 for r in ok if r["clarified"]]
    return {
        "n": len(rows),
        "evaluated": len(ok),
        "not_run": len(rows) - len(ok),
        "first_accept": M.rate(sum(r["first_accepted"] for r in msg), len(msg)),
        "any_accept": M.rate(sum(r["any_accepted"] for r in msg), len(msg)),
        "intent_acc": M.rate(sum(r["intent_ok"] for r in ok), len(ok)),
        "intent_acc_by_lang": {k: M.rate(sum(v), len(v)) for k, v in sorted(by_lang.items())},
        "coverage": M.mean(cov),
        "unsupported_rate": M.rate(sum(r["n_unsupported"] for r in ok), n_cand),
        "clarification_rate": M.rate(sum(r["clarified"] for r in ok), len(ok)),
        "clarify_when_expected": M.rate(sum(r["clarified"] for r in neg), len(neg)),
        "clarify_when_not_expected": M.rate(sum(r["clarified"] for r in msg), len(msg)),
        "clarify_rounds_mean": M.mean(rounds) if rounds else None,
        "effort_mean": M.mean([r["taps"] + r["edits"] for r in ok]),
        "fusion_p50": M.percentile(fus, 50),
        "fusion_p95": M.percentile(fus, 95),
        "fusion_n": len(fus),
    }


def run_wer(scenarios, settings, voice_id) -> dict:
    """Synthetic WER: ElevenLabs TTS (in memory) -> Scribe batch, raw output vs the text."""
    from app.services.scribe import ElevenLabsScribe
    from app.services.tts import ElevenLabsTTS

    tts, stt = (
        ElevenLabsTTS(settings.elevenlabs_api_key),
        ElevenLabsScribe(settings.elevenlabs_api_key),
    )
    items = []
    for sc in scenarios:
        if sc["target_sentence"]:
            items.append((sc["language"], sc["target_sentence"], sc["id"]))
        if sc["partner_line"]:
            items.append((sc["language"], sc["partner_line"], sc["id"] + ":partner"))
    out = []
    for lang, text, ref_id in items:
        t0 = time.perf_counter()
        pcm = tts.synthesize(text, voice_id, "pcm_16000")
        t_tts = (time.perf_counter() - t0) * 1000
        t0 = time.perf_counter()
        ev = stt.transcribe(pcm, 16000, None if lang == "mixed" else lang)
        t_stt = (time.perf_counter() - t0) * 1000
        del pcm  # audio never kept (R8)
        out.append(
            {
                "id": ref_id,
                "language": lang,
                "ref": text,
                "hyp": ev.text,
                "wer": round(M.wer(text, ev.text), 1),
                "tts_ms": round(t_tts),
                "scribe_ms": round(t_stt),
            }
        )
    by = defaultdict(list)
    for o in out:
        by[o["language"]].append((o["ref"], o["hyp"]))
    return {
        "items": out,
        "corpus_wer": M.corpus_wer((o["ref"], o["hyp"]) for o in out),
        "by_language": {k: M.corpus_wer(v) for k, v in sorted(by.items())},
        "scribe_p50": M.percentile([o["scribe_ms"] for o in out], 50),
        "scribe_p95": M.percentile([o["scribe_ms"] for o in out], 95),
        "tts_p50": M.percentile([o["tts_ms"] for o in out], 50),
        "tts_p95": M.percentile([o["tts_ms"] for o in out], 95),
    }


def fmt(v, pct=False, ms=False):
    if v is None:
        return "n/a"
    if pct:
        return f"{v * 100:.0f}%"
    if ms:
        return f"{v:.0f} ms"
    return f"{v:.2f}"


def write_report(path: Path, args, summaries, rows_by_cfg, wer_res, llm: CachedLLM | None):
    L = [
        "# PS-16 evaluation report",
        "",
        f"Generated by `evaluation/run_eval.py` on split **{args.split}**. Every number below "
        "was measured by this run. `n/a` means not measured, never zero.",
        "",
        "**Data:** all scenarios are synthetic (constructed text fragments; simulated atypical "
        "speech from `make_fragments.py`). Nothing here measures real impaired speech, which "
        "needs consented volunteer recordings.",
        "",
        "**Acceptance** is a deterministic proxy for a patient accepting a candidate: the "
        "candidate's content words equal the target's (function words ignored). No LLM judge "
        "is used.",
        "",
    ]
    if llm is not None:
        L += [
            f"LLM: `{args.model}` via Groq. Completed calls this run: {llm.calls}, cache "
            f"hits: {llm.hits}, refused: {llm.refused} (no further calls are attempted after "
            f"the first refusal), budget: {args.max_llm_calls}."
            + (f" Stopped by: {llm.tripped}." if llm.tripped else ""),
            "",
        ]
    L += [
        "## Reconstruction ablation",
        "",
        "| Config | Evaluated / n | Not run | First accept | Any accept | Intent acc | "
        "Coverage | Unsupported adds | Clarify rate | Clarify when expected | "
        "Clarify when not expected | Effort (taps+edits) | Fusion p50 / p95 |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for c in CONFIGS:
        s = summaries[c]
        L.append(
            f"| {c} | {s['evaluated']}/{s['n']} | {s['not_run']} | {fmt(s['first_accept'], 1)} | "
            f"{fmt(s['any_accept'], 1)} | {fmt(s['intent_acc'], 1)} | {fmt(s['coverage'], 1)} | "
            f"{fmt(s['unsupported_rate'], 1)} | {fmt(s['clarification_rate'], 1)} | "
            f"{fmt(s['clarify_when_expected'], 1)} | {fmt(s['clarify_when_not_expected'], 1)} | "
            f"{fmt(s['effort_mean'])} | "
            f"{fmt(s['fusion_p50'], ms=1)} / {fmt(s['fusion_p95'], ms=1)} (n={s['fusion_n']}) |"
        )
    L += ["", "Intent accuracy by language:", ""]
    for c in CONFIGS:
        by = summaries[c]["intent_acc_by_lang"]
        L.append(f"- {c}: " + (", ".join(f"{k} {fmt(v, 1)}" for k, v in by.items()) or "n/a"))
    not_run = [(c, r) for c in CONFIGS for r in rows_by_cfg[c] if r["status"] == "not_run"]
    if not_run:
        L += [
            "",
            f"Not run ({len(not_run)} scenario-configs): "
            + "; ".join(sorted({r["reason"] for _, r in not_run})),
        ]
    L += ["", "## Speech recognition (synthetic TTS speech)", ""]
    if wer_res is None:
        L.append("Not measured in this run (`--wer` not given).")
    else:
        L += [
            f"ElevenLabs Flash v2.5 voice `{args.voice}` -> Scribe `scribe_v2` batch, raw "
            "output, WER = (S+D+I)/N. This is clean synthetic speech, so it says nothing "
            "about atypical speech.",
            "",
            f"- Corpus WER: {fmt(wer_res['corpus_wer'])}% over {len(wer_res['items'])} utterances",
            "- By language: "
            + ", ".join(f"{k} {fmt(v)}%" for k, v in wer_res["by_language"].items()),
            f"- Scribe latency p50 / p95: {fmt(wer_res['scribe_p50'], ms=1)} / "
            f"{fmt(wer_res['scribe_p95'], ms=1)}",
            f"- TTS latency p50 / p95: {fmt(wer_res['tts_p50'], ms=1)} / "
            f"{fmt(wer_res['tts_p95'], ms=1)}",
            "",
            "Note: for code-mixed (romanised Hindi) references Scribe returns Devanagari "
            "script. Raw WER counts each script change as an error, so the `mixed` figure "
            "measures script mismatch as much as recognition (D-047).",
            "",
            "| id | lang | reference | Scribe output | WER % |",
            "|---|---|---|---|---|",
        ]
        for o in wer_res["items"]:
            L.append(f"| {o['id']} | {o['language']} | {o['ref']} | {o['hyp']} | {o['wer']} |")
    L += [
        "",
        "## End-to-end latency",
        "",
        "The harness does not run full turns. Stage latencies above are measured "
        "separately. A full measured turn is in `GET /metrics` when the server runs (D-034 "
        "defines `e2e_ms`). Avatar-tier latency: not measured (no live Tavus, D-044).",
        "",
        "## Not measured",
        "",
        "- Real impaired speech (no consented recordings).",
        "- Lip reading (no Auto-AVSR checkpoint, D-025); config C uses the scenario's "
        "`lip_ref` text as a simulated hint.",
        "- Avatar speech and verbatim fidelity (no live Tavus).",
        "- Clarification follow-up rounds (the harness scores the first response only).",
        "",
    ]
    path.write_text("\n".join(L), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="test", choices=["test", "tune", "all"])
    ap.add_argument("--max-llm-calls", type=int, default=80)
    ap.add_argument("--wer", action="store_true")
    ap.add_argument("--reuse-wer", action="store_true", help="take WER from results.json")
    ap.add_argument("--voice", default="EXAVITQu4vr4xnSDxMaL")  # premade (free plan), D-041
    ap.add_argument("--configs", default=",".join(CONFIGS))
    ap.add_argument("--out", default=str(ROOT / "evaluation" / "report.md"))
    args = ap.parse_args()
    settings = load_settings()
    args.model = settings.llm_model
    scenarios = json.loads((ROOT / "evaluation" / "scenarios.json").read_text(encoding="utf-8"))
    if args.split != "all":
        scenarios = [s for s in scenarios if s["split"] == args.split]
    fusion = FusionService(settings, HealthRegistry(settings))
    llm = CachedLLM(GroqLLM(settings.groq_api_key, settings.llm_model), args.max_llm_calls)
    fusion._llm = llm
    fw = fusion.function_words("hi")
    configs = [c for c in CONFIGS if c in args.configs.split(",")]
    rows_by_cfg = {c: [] for c in CONFIGS}
    for c in configs:
        rows_by_cfg[c] = run_config(c, scenarios, None if c == "R0" else fusion, fw)
        print(f"{c}: {summarise(rows_by_cfg[c])}")
    summaries = {c: summarise(rows_by_cfg[c]) for c in CONFIGS}
    wer_res = run_wer(scenarios, settings, args.voice) if args.wer else None
    prev = ROOT / "evaluation" / "results.json"
    if args.reuse_wer and wer_res is None and prev.is_file():
        wer_res = json.loads(prev.read_text(encoding="utf-8")).get("wer")
    (ROOT / "evaluation" / "results.json").write_text(
        json.dumps(
            {"split": args.split, "rows": rows_by_cfg, "summaries": summaries, "wer": wer_res},
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    write_report(Path(args.out), args, summaries, rows_by_cfg, wer_res, llm)
    print(f"report -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
