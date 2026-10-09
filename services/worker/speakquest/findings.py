"""Turn measurements into findings (system design §5.3).

A finding is a time range, the words it covers, the measured evidence and a
severity. The rules are deliberately simple comparisons against the
reference so each one can be explained with its own numbers.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from speakquest.contracts import (
    FLAW_CODES,
    AlignOp,
    EvidenceValue,
    Finding,
    FlawCode,
    PhraseStat,
    ScriptInfo,
    TakeAnalysis,
    WordMeasure,
)
from speakquest.features import common_runs, span_time
from speakquest.rubric import Rubric


@dataclass
class _Draft:
    code: FlawCode
    start: float
    end: float
    words: list[str]
    evidence: dict[str, EvidenceValue]
    severity: int
    script_span: tuple[int, int] | None = None
    take_words: list[int] = field(default_factory=list)


def _r(x: float, nd: int = 2) -> float:
    return round(float(x), nd)


def _display(script: ScriptInfo, j: int) -> str:
    return script.tokens[j].norm


# --------------------------------------------------------------------------- pace


def _pace(
    take: TakeAnalysis, ref: TakeAnalysis, script: ScriptInfo, rubric: Rubric
) -> list[_Draft]:
    out: list[_Draft] = []
    t_idx = {w.script_index: w for w in take.words if w.script_index is not None}
    r_idx = {w.script_index: w for w in ref.words if w.script_index is not None}
    lo, hi = rubric.features.global_rate_normalization
    g_raw = take.rate_ratio_global if take.rate_ratio_global is not None else 1.0
    norm = min(max(g_raw, lo), hi)

    for code, key, direction in (
        ("RUSH", "rate_ratio_above", "above"),
        ("DRAG", "rate_ratio_below", "below"),
    ):
        rule = rubric.rule(code)  # type: ignore[arg-type]
        thr = float(rule[key])
        low = float(rule["extend_above" if direction == "above" else "extend_below"])
        min_words = int(rule["min_words"])
        gap = rubric.features.rate_pause_ms

        def beyond(value: float | None, limit: float, up: bool = direction == "above") -> bool:
            return value is not None and (value > limit if up else value < limit)

        # Hysteresis: a stretch starts where windowed ratios pass a looser
        # bound and must contain at least one word past the real threshold.
        # The stretch is then re-measured as a whole (reference time / take
        # time for exactly those words), which undoes the window's blurring
        # at the stretch edges, and only that number is compared with the rule.
        for run in common_runs(take, ref):
            vals = [t_idx[j].rate_ratio for j in run]
            i = 0
            while i < len(run):
                if not beyond(vals[i], low):
                    i += 1
                    continue
                j = i
                while j < len(run) and beyond(vals[j], low):
                    j += 1
                seg = run[i:j]
                i = j
                if len(seg) < min_words or not any(beyond(v, thr) for v in vals[i - len(seg) : i]):
                    continue
                t_time = span_time(take, seg, t_idx, gap)
                r_time = span_time(ref, seg, r_idx, gap)
                if t_time <= 0 or r_time <= 0:
                    continue
                seg_ratio = (r_time / t_time) / norm
                if not beyond(seg_ratio, thr):
                    continue
                tw = [t_idx[k] for k in seg]
                syl = sum(w.syllables for w in tw)
                out.append(
                    _Draft(
                        code=code,  # type: ignore[arg-type]
                        start=tw[0].start,
                        end=tw[-1].end,
                        words=[_display(script, k) for k in seg],
                        evidence={
                            "rate_ratio": _r(seg_ratio),
                            "syllables_per_s": _r(syl / t_time, 1),
                            "reference_syllables_per_s": _r(syl / r_time, 1),
                        },
                        severity=rubric.severity(code, seg_ratio, direction),  # type: ignore[arg-type]
                        script_span=(seg[0], seg[-1]),
                        take_words=[w.index for w in tw],
                    )
                )

    # A take that is rushed or dragged *throughout* is absorbed by the clamped
    # global normalisation only up to the clamp; beyond the rule threshold it
    # is reported once, over the whole take.
    g = take.rate_ratio_global
    matched = [w for w in take.words if w.script_index is not None]
    if g is not None and matched:
        for code, key, direction in (
            ("RUSH", "rate_ratio_above", "above"),
            ("DRAG", "rate_ratio_below", "below"),
        ):
            thr = float(rubric.rule(code)[key])  # type: ignore[arg-type]
            if (direction == "above" and g > thr) or (direction == "below" and g < thr):
                out.append(
                    _Draft(
                        code=code,  # type: ignore[arg-type]
                        start=matched[0].start,
                        end=matched[-1].end,
                        words=[],
                        evidence={"rate_ratio": _r(g), "scope": "whole take"},
                        severity=rubric.severity(code, g, direction),  # type: ignore[arg-type]
                        script_span=(matched[0].script_index or 0, matched[-1].script_index or 0),
                    )
                )
    return out


# --------------------------------------------------------------------------- pauses


def _hesitations(
    take: TakeAnalysis, ref: TakeAnalysis, script: ScriptInfo, rubric: Rubric
) -> list[_Draft]:
    rule = rubric.rule("HESITATE")
    above, ref_below = float(rule["pause_ms_above"]), float(rule["reference_pause_ms_below"])
    r_idx = {w.script_index: w for w in ref.words if w.script_index is not None}
    pauses = {p.before_word: p for p in take.pauses}
    out: list[_Draft] = []
    words = take.words
    for k, w in enumerate(words):
        p = pauses.get(k)
        if p is None or p.ms <= above:
            continue
        prev_matched = next((x for x in reversed(words[:k]) if x.script_index is not None), None)
        next_matched = next((x for x in words[k:] if x.script_index is not None), None)
        if prev_matched is None or next_matched is None:
            continue  # leading or trailing silence is not a hesitation
        assert prev_matched.script_index is not None and next_matched.script_index is not None
        lo, hi = prev_matched.script_index + 1, next_matched.script_index
        ref_pause = max(
            (r_idx[j].pause_before_ms for j in range(lo, hi + 1) if j in r_idx), default=0
        )
        if ref_pause >= ref_below:
            continue  # the reference breathes here too: it's the script's phrasing
        out.append(
            _Draft(
                code="HESITATE",
                start=p.start,
                end=p.end,
                words=[
                    _display(script, prev_matched.script_index),
                    _display(script, next_matched.script_index),
                ],
                evidence={"pause_ms": p.ms, "reference_pause_ms": ref_pause},
                severity=rubric.severity("HESITATE", p.ms, "above"),
                script_span=(prev_matched.script_index, next_matched.script_index),
                take_words=[w.index],
            )
        )
    return out


# --------------------------------------------------------------------------- pitch & volume


def _phrase_words(take: TakeAnalysis, phrase: int, script: ScriptInfo) -> list[WordMeasure]:
    return [
        w
        for w in take.words
        if w.script_index is not None and script.tokens[w.script_index].phrase == phrase
    ]


def _monotone(
    take: TakeAnalysis, ref: TakeAnalysis, script: ScriptInfo, rubric: Rubric
) -> list[_Draft]:
    """Phrase pitch variability against the reference, per speaker.

    Voices differ in how much they move pitch at all, so each phrase's SD
    ratio is divided by the speaker's *median* phrase ratio (floored, so a
    take that is flat throughout still surfaces) before the threshold.
    """
    rule = rubric.rule("MONO")
    ref_phrases = {p.phrase: p for p in ref.phrases}
    eligible: list[tuple[PhraseStat, PhraseStat, list[WordMeasure], float]] = []
    for p in take.phrases:
        rp = ref_phrases.get(p.phrase)
        members = _phrase_words(take, p.phrase, script)
        if (
            rp is None
            or p.pitch_sd_st is None
            or rp.pitch_sd_st is None
            or len(members) < int(rule["min_phrase_words"])
            or rp.pitch_sd_st < float(rule["min_reference_sd_st"])
            or p.voiced_frames < int(rule["min_voiced_frames"])
        ):
            continue
        eligible.append((p, rp, members, p.pitch_sd_st / rp.pitch_sd_st))
    if not eligible:
        return []
    ratios = sorted(r for *_, r in eligible)
    speaker = (
        ratios[len(ratios) // 2]
        if len(ratios) % 2
        else (ratios[len(ratios) // 2 - 1] + ratios[len(ratios) // 2]) / 2
    )
    norm = min(max(speaker, float(rule["speaker_normalization_floor"])), 1.0)
    out: list[_Draft] = []
    if speaker < float(rule["whole_take_below"]):
        first, last = eligible[0][2], eligible[-1][2]
        out.append(
            _Draft(
                code="MONO",
                start=first[0].start,
                end=last[-1].end,
                words=[],
                evidence={"ratio": _r(speaker), "scope": "whole take"},
                severity=rubric.severity("MONO", speaker, "below"),
                script_span=(first[0].script_index or 0, last[-1].script_index or 0),
            )
        )
        return out
    for p, rp, members, raw in eligible:
        ratio = raw / norm
        if ratio >= float(rule["sd_ratio_below"]):
            continue
        out.append(
            _Draft(
                code="MONO",
                start=p.start,
                end=p.end,
                words=[
                    _display(script, w.script_index) for w in members if w.script_index is not None
                ],
                evidence={
                    "pitch_sd_st": _r(p.pitch_sd_st or 0.0, 1),
                    "reference_pitch_sd_st": _r(rp.pitch_sd_st or 0.0, 1),
                    "ratio": _r(ratio),
                },
                severity=rubric.severity("MONO", ratio, "below"),
                script_span=(members[0].script_index or 0, members[-1].script_index or 0),
                take_words=[w.index for w in members],
            )
        )
    return out


def _fades(
    take: TakeAnalysis, ref: TakeAnalysis, script: ScriptInfo, rubric: Rubric
) -> list[_Draft]:
    rule = rubric.rule("FADE")
    n = int(rule["last_words"])
    out: list[_Draft] = []
    for phrase in range(script.phrase_count):
        tail = [w for w in _phrase_words(take, phrase, script) if w.loudness_db is not None][-n:]
        if len(tail) < n:
            continue
        drop = -sum(w.loudness_db or 0.0 for w in tail) / n
        if drop < float(rule["db_below_mean"]):
            continue
        ref_tail = [
            w
            for w in _phrase_words(ref, phrase, script)
            if w.script_index in {t.script_index for t in tail} and w.loudness_db is not None
        ]
        ref_drop = (
            (-sum(w.loudness_db or 0.0 for w in ref_tail) / len(ref_tail)) if ref_tail else 0.0
        )
        if drop - ref_drop < float(rule["reference_margin_db"]):
            continue
        out.append(
            _Draft(
                code="FADE",
                start=tail[0].start,
                end=tail[-1].end,
                words=[
                    _display(script, w.script_index) for w in tail if w.script_index is not None
                ],
                evidence={"drop_db": _r(drop, 1), "reference_drop_db": _r(ref_drop, 1)},
                severity=rubric.severity("FADE", drop, "above"),
                script_span=(tail[0].script_index or 0, tail[-1].script_index or 0),
                take_words=[w.index for w in tail],
            )
        )
    return out


# --------------------------------------------------------------------------- accuracy


def _script_diff(
    take: TakeAnalysis,
    script: ScriptInfo,
    ops: Sequence[AlignOp],
    rubric: Rubric,
    confidences: dict[int, float],
) -> list[_Draft]:
    out: list[_Draft] = []
    words = take.words
    filler_rule = rubric.rule("FILLER")
    other_conf = float(filler_rule["other_insert_min_confidence"])

    def time_before(pos: int) -> float:
        for op in reversed(ops[:pos]):
            if op.take_index is not None:
                return words[op.take_index].end
        return words[0].start if words else 0.0

    def time_after(pos: int) -> float:
        for op in ops[pos:]:
            if op.take_index is not None:
                return words[op.take_index].start
        return words[-1].end if words else 0.0

    i = 0
    while i < len(ops):
        op = ops[i]
        if op.op == "del":
            j = i
            while j < len(ops) and ops[j].op == "del":
                j += 1
            run = [o.script_index for o in ops[i:j] if o.script_index is not None]
            start, end = time_before(i), time_after(j)
            out.append(
                _Draft(
                    code="SKIP",
                    start=min(start, end),
                    end=max(start, end),
                    words=[_display(script, s) for s in run],
                    evidence={"skipped_words": len(run)},
                    severity=rubric.severity("SKIP", len(run), "above"),
                    script_span=(run[0], run[-1]),
                )
            )
            i = j
            continue
        if op.op == "ins":
            j = i
            while j < len(ops) and ops[j].op == "ins":
                j += 1
            members = [words[o.take_index] for o in ops[i:j] if o.take_index is not None]
            kept = [
                w
                for w in members
                if w.kind in ("filler", "repeat") or confidences.get(w.index, 0.0) >= other_conf
            ]
            if kept:
                kinds = sorted({w.kind for w in kept})
                out.append(
                    _Draft(
                        code="FILLER",
                        start=kept[0].start,
                        end=kept[-1].end,
                        words=[w.norm for w in kept],
                        evidence={"count": len(kept), "kind": "+".join(kinds)},
                        severity=rubric.severity("FILLER", len(kept), "above"),
                        take_words=[w.index for w in kept],
                    )
                )
            i = j
            continue
        i += 1

    # Untranscribed vocalisations ("um" the recogniser cleaned up).
    inserted = [w for w in words if w.script_index is None]
    for v in take.vocalizations:
        if any(w.start < v.end and v.start < w.end for w in inserted):
            continue
        out.append(
            _Draft(
                code="FILLER",
                start=v.start,
                end=v.end,
                words=[],
                evidence={"vocalization_ms": v.ms, "kind": "vocalization"},
                severity=1,
            )
        )
    return out


# --------------------------------------------------------------------------- entry point


def detect(
    take: TakeAnalysis,
    ref: TakeAnalysis,
    script: ScriptInfo,
    ops: Sequence[AlignOp],
    rubric: Rubric,
    confidences: dict[int, float] | None = None,
) -> tuple[list[Finding], TakeAnalysis]:
    """Run every rule; return findings (ids f1…fn in time order) and the take
    with ``finding_ids`` attached to the words each finding covers."""
    drafts = [
        *_pace(take, ref, script, rubric),
        *_hesitations(take, ref, script, rubric),
        *_monotone(take, ref, script, rubric),
        *_fades(take, ref, script, rubric),
        *_script_diff(take, script, ops, rubric, confidences or {}),
    ]
    order = {c: i for i, c in enumerate(FLAW_CODES)}
    drafts.sort(key=lambda d: (round(d.start, 3), round(d.end, 3), order[d.code]))
    findings: list[Finding] = []
    attach: dict[int, list[str]] = {}
    for n, d in enumerate(drafts, start=1):
        fid = f"f{n}"
        findings.append(
            Finding(
                id=fid,
                code=d.code,
                dimension=rubric.dimensions[d.code],
                start=round(d.start, 3),
                end=round(d.end, 3),
                words=d.words,
                evidence=d.evidence,
                severity=d.severity,
                rubric_version=rubric.version,
                script_span=d.script_span,
            )
        )
        for k in d.take_words:
            attach.setdefault(k, []).append(fid)
    words = [w.model_copy(update={"finding_ids": attach.get(w.index, [])}) for w in take.words]
    return findings, take.model_copy(update={"words": words})
