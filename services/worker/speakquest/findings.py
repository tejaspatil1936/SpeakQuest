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
    ScriptInfo,
    TakeAnalysis,
    WordMeasure,
)
from speakquest.features import articulation_time, common_runs
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

    for code, key, direction in (
        ("RUSH", "rate_ratio_above", "above"),
        ("DRAG", "rate_ratio_below", "below"),
    ):
        rule = rubric.rule(code)  # type: ignore[arg-type]
        thr = float(rule[key])
        min_words = int(rule["min_words"])
        for run in common_runs(take, ref):
            current: list[int] = []
            for j in [*run, None]:
                ratio = t_idx[j].rate_ratio if j is not None else None
                hit = ratio is not None and (ratio > thr if direction == "above" else ratio < thr)
                if hit and j is not None:
                    current.append(j)
                    continue
                if len(current) >= min_words:
                    tw = [t_idx[k] for k in current]
                    rw = [r_idx[k] for k in current]
                    ratios = [w.rate_ratio for w in tw if w.rate_ratio is not None]
                    mean_ratio = sum(ratios) / len(ratios)
                    syl = sum(w.syllables for w in tw)
                    t_time = articulation_time(tw, take.pauses)
                    r_time = articulation_time(rw, ref.pauses)
                    out.append(
                        _Draft(
                            code=code,  # type: ignore[arg-type]
                            start=tw[0].start,
                            end=tw[-1].end,
                            words=[_display(script, k) for k in current],
                            evidence={
                                "rate_ratio": _r(mean_ratio),
                                "syllables_per_s": _r(syl / t_time, 1) if t_time else 0.0,
                                "reference_syllables_per_s": _r(syl / r_time, 1) if r_time else 0.0,
                            },
                            severity=rubric.severity(code, mean_ratio, direction),  # type: ignore[arg-type]
                            script_span=(current[0], current[-1]),
                            take_words=[w.index for w in tw],
                        )
                    )
                current = []

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
    rule = rubric.rule("MONO")
    ref_phrases = {p.phrase: p for p in ref.phrases}
    out: list[_Draft] = []
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
        ratio = p.pitch_sd_st / rp.pitch_sd_st
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
                    "pitch_sd_st": _r(p.pitch_sd_st, 1),
                    "reference_pitch_sd_st": _r(rp.pitch_sd_st, 1),
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
