"""Interpretable prosody features (system design §5.2).

Everything here is speaker-relative or reference-relative so two different
voices can be compared:

* local speech rate → ratio of the reference's time for the *same script
  words* to this take's time, normalised by the global ratio (clamped);
* pauses → silent runs found in the RMS envelope around word boundaries,
  in absolute milliseconds;
* pitch → semitones from the speaker's own median F0 (Parselmouth);
* loudness → word RMS in dB relative to the speaker's own mean.

MFCCs/spectral features are deliberately absent: they encode *who* is
speaking, so cross-speaker comparisons would flag everything.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from speakquest.contracts import (
    AlignOp,
    Pause,
    PhraseStat,
    ScriptInfo,
    TakeAnalysis,
    Vocalization,
    WordKind,
    WordMeasure,
)
from speakquest.diff import InsertKind
from speakquest.normalize import FloatArray, frame_rms
from speakquest.rubric import FeatureConfig
from speakquest.timing import SpokenToken
from speakquest.tokens import syllables

_EPS = 1e-10


# --------------------------------------------------------------------------- signal tracks


@dataclass(frozen=True)
class Tracks:
    """Frame-level envelopes shared by every measurement."""

    frame_s: float
    db: npt.NDArray[np.float64]  # RMS level per frame, dBFS
    silent: npt.NDArray[np.bool_]
    pitch_times: npt.NDArray[np.float64]
    pitch_hz: npt.NDArray[np.float64]  # 0 where unvoiced
    speech_db: float

    def frames(self, start: float, end: float) -> slice:
        a = max(0, math.floor(start / self.frame_s))
        b = min(len(self.db), math.ceil(end / self.frame_s))
        return slice(a, max(a, b))

    def voiced_in(self, start: float, end: float) -> npt.NDArray[np.float64]:
        mask = (self.pitch_times >= start) & (self.pitch_times < end) & (self.pitch_hz > 0)
        return self.pitch_hz[mask]


def extract_pitch(
    samples: FloatArray, sr: int, floor_hz: float, ceiling_hz: float, time_step: float = 0.01
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    import parselmouth  # noqa: PLC0415 - heavy import kept out of module import time

    if samples.size < int(sr * 3 / floor_hz) + 1:
        return np.zeros(0), np.zeros(0)
    snd = parselmouth.Sound(samples.astype(np.float64), sampling_frequency=sr)
    pitch = snd.to_pitch_ac(time_step=time_step, pitch_floor=floor_hz, pitch_ceiling=ceiling_hz)
    hz = np.nan_to_num(np.asarray(pitch.selected_array["frequency"], dtype=np.float64))
    times = np.asarray(pitch.xs(), dtype=np.float64)
    return times, hz


def build_tracks(samples: FloatArray, sr: int, cfg: FeatureConfig) -> Tracks:
    rms = frame_rms(samples, sr, cfg.frame_ms).astype(np.float64)
    db = 20.0 * np.log10(np.maximum(rms, _EPS))
    if db.size:
        top = np.sort(rms)[int(rms.size * 0.7) :]
        speech_db = float(20 * np.log10(max(float(np.sqrt(np.mean(top**2))), _EPS)))
    else:
        speech_db = -120.0
    silent = db < speech_db + cfg.silence_rel_db
    times, hz = extract_pitch(samples, sr, cfg.pitch_floor_hz, cfg.pitch_ceiling_hz)
    return Tracks(
        frame_s=cfg.frame_ms / 1000,
        db=db,
        silent=silent,
        pitch_times=times,
        pitch_hz=hz,
        speech_db=speech_db,
    )


# --------------------------------------------------------------------------- helpers


def _longest_run(mask: npt.NDArray[np.bool_]) -> tuple[int, int]:
    """(start, length) of the longest run of True; (0, 0) if none."""
    best = (0, 0)
    start = None
    for i, v in enumerate(np.append(mask, False)):
        if v and start is None:
            start = i
        elif not v and start is not None:
            if i - start > best[1]:
                best = (start, i - start)
            start = None
    return best


def _runs(mask: npt.NDArray[np.bool_]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    start = None
    for i, v in enumerate(np.append(mask, False)):
        if v and start is None:
            start = i
        elif not v and start is not None:
            out.append((start, i))
            start = None
    return out


def _mean_db(db: npt.NDArray[np.float64]) -> float | None:
    if db.size == 0:
        return None
    return float(10 * np.log10(np.mean(10 ** (db / 10)) + _EPS))


def robust_sd(values: npt.NDArray[np.float64]) -> float:
    """SD after trimming the outer 5 % (octave errors and creaky frames)."""
    if values.size < 3:
        return 0.0
    lo, hi = np.percentile(values, [5, 95])
    kept = values[(values >= lo) & (values <= hi)]
    return float(np.std(kept)) if kept.size >= 3 else float(np.std(values))


def _r(x: float | None, nd: int = 2) -> float | None:
    return None if x is None or not math.isfinite(x) else round(float(x), nd)


# --------------------------------------------------------------------------- per-take measurement


def _pause_between(
    tracks: Tracks, prev: SpokenToken, nxt: SpokenToken, min_pause_ms: int
) -> tuple[float, float] | None:
    """Longest silent run between the midpoints of two neighbouring words.

    Aligners place boundaries loosely (often stretching a word over the
    following silence), so the pause is measured from the energy envelope,
    searching between word midpoints, rather than trusting the ASR gap.
    """
    lo = (prev.start + prev.end) / 2
    hi = (nxt.start + nxt.end) / 2
    if hi <= lo:
        return None
    sl = tracks.frames(lo, hi)
    start, length = _longest_run(tracks.silent[sl])
    ms = length * tracks.frame_s * 1000
    if ms < min_pause_ms:
        return None
    s = (sl.start + start) * tracks.frame_s
    return s, s + length * tracks.frame_s


def word_kinds(
    ops: Sequence[AlignOp], inserts: dict[int, InsertKind], n_tokens: int
) -> tuple[list[WordKind], list[int | None]]:
    kinds: list[WordKind] = ["insert"] * n_tokens
    script_idx: list[int | None] = [None] * n_tokens
    for op in ops:
        if op.take_index is None:
            continue
        if op.op in ("match", "sub"):
            kinds[op.take_index] = "match" if op.op == "match" else "sub"
            script_idx[op.take_index] = op.script_index
        else:
            kinds[op.take_index] = inserts.get(op.take_index, "insert")
    return kinds, script_idx


def measure(
    samples: FloatArray,
    sr: int,
    tokens: Sequence[SpokenToken],
    ops: Sequence[AlignOp],
    inserts: dict[int, InsertKind],
    script: ScriptInfo,
    cfg: FeatureConfig,
    tracks: Tracks | None = None,
) -> TakeAnalysis:
    """Measure one recording (take or reference) against its alignment."""
    tracks = tracks or build_tracks(samples, sr, cfg)
    duration = len(samples) / sr if sr else 0.0
    kinds, script_idx = word_kinds(ops, inserts, len(tokens))

    # Pauses before each word.
    pauses: list[Pause] = []
    pause_before = [0] * len(tokens)
    for k in range(1, len(tokens)):
        span = _pause_between(tracks, tokens[k - 1], tokens[k], cfg.min_pause_ms)
        if span:
            ms = round((span[1] - span[0]) * 1000)
            pause_before[k] = ms
            pauses.append(
                Pause(start=round(span[0], 3), end=round(span[1], 3), ms=ms, before_word=k)
            )

    # Loudness relative to the speaker's mean (non-silent frames of words only).
    word_db: list[float | None] = []
    for tok in tokens:
        sl = tracks.frames(tok.start, tok.end)
        frames = tracks.db[sl][~tracks.silent[sl]]
        word_db.append(_mean_db(frames))
    known = [
        d for d, kd in zip(word_db, kinds, strict=True) if d is not None and kd in ("match", "sub")
    ]
    mean_db = float(np.mean(known)) if known else None

    # Pitch relative to the speaker's median.
    voiced_all = tracks.pitch_hz[tracks.pitch_hz > 0]
    median_hz = float(np.median(voiced_all)) if voiced_all.size else None

    def semitones(hz: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
        assert median_hz is not None
        return 12.0 * np.log2(hz / median_hz)

    words: list[WordMeasure] = []
    for k, tok in enumerate(tokens):
        voiced = tracks.voiced_in(tok.start, tok.end)
        pitch_st = float(np.median(semitones(voiced))) if voiced.size and median_hz else None
        level = word_db[k]
        rel_db = level - mean_db if level is not None and mean_db is not None else None
        words.append(
            WordMeasure(
                index=k,
                text=tok.text,
                norm=tok.norm,
                start=tok.start,
                end=tok.end,
                kind=kinds[k],
                script_index=script_idx[k],
                syllables=syllables(tok.norm),
                loudness_db=_r(rel_db, 1),
                pitch_st=_r(pitch_st, 2),
                pause_before_ms=pause_before[k],
            )
        )

    # Phrase spans and pitch variability.
    phrases: list[PhraseStat] = []
    by_phrase: dict[int, list[WordMeasure]] = {}
    for w in words:
        if w.script_index is not None:
            by_phrase.setdefault(script.tokens[w.script_index].phrase, []).append(w)
    for phrase, members in sorted(by_phrase.items()):
        start, end = members[0].start, members[-1].end
        voiced = tracks.voiced_in(start, end)
        sd = robust_sd(semitones(voiced)) if voiced.size and median_hz else None
        phrases.append(
            PhraseStat(
                phrase=phrase,
                start=start,
                end=end,
                pitch_sd_st=_r(sd, 2),
                voiced_frames=int(voiced.size),
            )
        )

    vocal = find_vocalizations(tracks, tokens, cfg)

    matched = [w for w in words if w.kind in ("match", "sub")]
    total_syll = sum(w.syllables for w in matched)
    talk_time = articulation_time(matched, pauses, min_pause_ms=cfg.rate_pause_ms)
    return TakeAnalysis(
        duration_s=round(duration, 3),
        words=words,
        pauses=pauses,
        phrases=phrases,
        vocalizations=vocal,
        syllables_per_s=round(total_syll / talk_time, 3) if talk_time > 0 else 0.0,
        pitch_median_hz=_r(median_hz, 1),
        loudness_mean_db=_r(tracks.speech_db, 1),
    )


def find_vocalizations(
    tracks: Tracks, tokens: Sequence[SpokenToken], cfg: FeatureConfig
) -> list[Vocalization]:
    """Voiced sound between words that the aligner did not transcribe.

    Some recognisers drop "um"/"uh". A run of non-silent, mostly voiced
    frames that is fenced by silence on both sides inside an inter-word gap
    is reported so FILLER detection does not depend on the recogniser's
    verbatim-ness (system design §5.1 step 4).
    """
    out: list[Vocalization] = []
    fence = max(1, int(0.06 / tracks.frame_s))
    for k in range(1, len(tokens)):
        lo, hi = tokens[k - 1].end, tokens[k].start
        if (hi - lo) * 1000 < cfg.vocalization_min_ms:
            continue
        sl = tracks.frames(lo, hi)
        sil = tracks.silent[sl]
        for a, b in _runs(~sil):
            if a < fence or b > len(sil) - fence:
                continue  # touches a word boundary: probably part of that word
            if not (sil[a - fence : a].all() and sil[b : b + fence].all()):
                continue
            s = (sl.start + a) * tracks.frame_s
            e = (sl.start + b) * tracks.frame_s
            ms = round((e - s) * 1000)
            if not cfg.vocalization_min_ms <= ms <= cfg.vocalization_max_ms:
                continue
            frames_in = (tracks.pitch_times >= s) & (tracks.pitch_times < e)
            if frames_in.sum() == 0:
                continue
            voiced_ratio = float((tracks.pitch_hz[frames_in] > 0).mean())
            if voiced_ratio >= cfg.vocalization_min_voiced_ratio:
                out.append(Vocalization(start=round(s, 3), end=round(e, 3), ms=ms))
    return out


def articulation_time(
    words: Sequence[WordMeasure],
    pauses: Sequence[Pause],
    exclude: Sequence[WordMeasure] = (),
    min_pause_ms: int = 0,
) -> float:
    """Span from first to last word, minus pauses and excluded words inside it.

    Only pauses of at least ``min_pause_ms`` are removed: shorter silences are
    stop closures and micro-gaps that lengthen with slow speech and belong to
    the speaking time.
    """
    if not words:
        return 0.0
    start, end = words[0].start, words[-1].end
    t = end - start
    for p in pauses:
        if p.ms >= min_pause_ms:
            t -= max(0.0, min(p.end, end) - max(p.start, start))
    for w in exclude:
        if start < w.start and w.end < end:
            t -= w.end - w.start
    return max(t, 0.0)


# --------------------------------------------------------------------------- take vs reference


def _by_script(analysis: TakeAnalysis) -> dict[int, WordMeasure]:
    return {w.script_index: w for w in analysis.words if w.script_index is not None}


def span_time(
    analysis: TakeAnalysis,
    script_ids: Sequence[int],
    index: dict[int, WordMeasure],
    min_pause_ms: int,
) -> float:
    """Speaking time for a run of script words (pauses and insertions removed)."""
    first, last = index[script_ids[0]], index[script_ids[-1]]
    inserted = [
        w for w in analysis.words if w.script_index is None and first.start < w.start < last.end
    ]
    span = [first, last]
    return articulation_time(span, analysis.pauses, inserted, min_pause_ms)


def common_runs(take: TakeAnalysis, ref: TakeAnalysis) -> list[list[int]]:
    """Runs of consecutive script indices matched in both recordings."""
    shared = sorted(set(_by_script(take)) & set(_by_script(ref)))
    runs: list[list[int]] = []
    for j in shared:
        if runs and runs[-1][-1] == j - 1:
            runs[-1].append(j)
        else:
            runs.append([j])
    return runs


def compare_rates(take: TakeAnalysis, ref: TakeAnalysis, cfg: FeatureConfig) -> TakeAnalysis:
    """Fill ``rate_ratio`` on matched take words and ``rate_ratio_global``.

    Ratio = reference time / take time for the same window of script words,
    so 1.4 means "40 % faster than the reference". Windows never straddle a
    skipped word (the reference would include time the take does not).
    """
    t_idx, r_idx = _by_script(take), _by_script(ref)
    runs = common_runs(take, ref)
    shared = [j for run in runs for j in run]
    if not shared:
        return take

    gap = cfg.rate_pause_ms
    half = cfg.rate_window_words // 2
    raw: dict[int, float] = {}
    for run in runs:
        if len(run) < 2:
            continue
        for p in range(len(run)):
            a = max(0, p - half)
            b = min(len(run), a + cfg.rate_window_words)
            a = max(0, b - cfg.rate_window_words)
            window = run[a:b]
            tt = span_time(take, window, t_idx, gap)
            rt = span_time(ref, window, r_idx, gap)
            if tt > 0.02 and rt > 0.02:
                raw[run[p]] = rt / tt

    # The speaker's typical pace relative to the reference: the median window
    # ratio, so a rushed or dragged stretch does not shift it.
    if raw:
        global_ratio = float(np.median(list(raw.values())))
    else:
        t_total = sum(span_time(take, run, t_idx, gap) for run in runs)
        r_total = sum(span_time(ref, run, r_idx, gap) for run in runs)
        global_ratio = r_total / t_total if t_total > 0 else 1.0
    lo, hi = cfg.global_rate_normalization
    norm = min(max(global_ratio, lo), hi)
    ratios = {j: r / norm for j, r in raw.items()}

    updated = [
        w.model_copy(update={"rate_ratio": round(ratios[w.script_index], 3)})
        if w.script_index is not None and w.script_index in ratios
        else w
        for w in take.words
    ]
    return take.model_copy(update={"words": updated, "rate_ratio_global": round(global_ratio, 3)})
