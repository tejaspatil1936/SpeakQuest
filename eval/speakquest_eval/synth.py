"""Synthetic, labelled evaluation dataset (system design §5.5).

No licensed speech corpus with per-flaw time labels was available, so the
dataset is synthesised with Piper TTS. Every recording is assembled from
separately synthesised chunks, which makes the ground truth exact: a rushed
chunk, an inserted pause or filler, a faded tail or a flattened phrase sits
at a time range we placed ourselves.

Per script:
* ``reference``  – voice A, clean (the challenge's reference take)
* ``clean-<v>``  – voices B and C, clean (second readers, for false positives)
* ``flawed-<n>`` – voices B/C with 1–2 injected flaws each

Piper runs with noise disabled so synthesis is deterministic and the
committed annotations match regenerated audio (each annotation stores the
audio's SHA-256 to prove it).

Limitations (also in docs/EVALUATION.md): three synthetic US-English
voices, studio-clean signal, flaws produced by signal manipulation rather
than human performance.
"""

from __future__ import annotations

import hashlib
import json
import random
import wave
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from speakquest.challenges import CatalogueEntry, load_catalogue
from speakquest.contracts import FlawCode
from speakquest.tokens import normalize_word

GENERATOR_VERSION = "1"
REFERENCE_VOICE = "en_US-lessac-medium"
PARTICIPANT_VOICES = ("en_US-ryan-medium", "en_US-amy-medium")
PHRASE_GAP_S = {",": 0.32, ";": 0.4, ":": 0.4, ".": 0.55, "!": 0.55, "?": 0.55}
JOIN_GAP_S = 0.02

Audio = npt.NDArray[np.float32]


# --------------------------------------------------------------------------- script structure


@dataclass(frozen=True)
class SurfaceWord:
    text: str  # with punctuation, as written
    phrase: int
    first_token: int  # index of its first normalised token in the script
    n_tokens: int


def surface_words(script: str) -> list[SurfaceWord]:
    """Whitespace words with phrase index and token offsets (mirrors tokens.py)."""
    words: list[SurfaceWord] = []
    phrase, tok = 0, 0
    for raw in script.split():
        n = len(normalize_word(raw))
        words.append(SurfaceWord(text=raw, phrase=phrase, first_token=tok, n_tokens=n))
        tok += n
        if raw[-1] in PHRASE_GAP_S or raw.endswith("—"):
            phrase += 1
    return words


def phrases(words: Sequence[SurfaceWord]) -> list[list[int]]:
    out: dict[int, list[int]] = {}
    for i, w in enumerate(words):
        out.setdefault(w.phrase, []).append(i)
    return [out[k] for k in sorted(out)]


# --------------------------------------------------------------------------- synthesis


class Synth:
    def __init__(self, model_dir: Path):
        from piper import PiperVoice  # noqa: PLC0415 - optional extra

        self._voices: dict[str, Any] = {}
        self._loader = PiperVoice
        self.model_dir = model_dir

    def voice(self, name: str) -> Any:
        if name not in self._voices:
            path = self.model_dir / f"{name}.onnx"
            if not path.exists():
                raise FileNotFoundError(f"{path} missing; run `make models`")
            self._voices[name] = self._loader.load(str(path))
        return self._voices[name]

    def sample_rate(self, name: str) -> int:
        return int(self.voice(name).config.sample_rate)

    def say(self, voice: str, text: str, length_scale: float = 1.0) -> Audio:
        from piper import SynthesisConfig  # noqa: PLC0415

        cfg = SynthesisConfig(length_scale=length_scale, noise_scale=0.0, noise_w_scale=0.0)
        chunks = [c.audio_float_array for c in self.voice(voice).synthesize(text, syn_config=cfg)]
        return trim(np.concatenate(chunks).astype(np.float32), self.sample_rate(voice))


def trim(audio: Audio, sr: int, rel_db: float = -40.0, margin_s: float = 0.01) -> Audio:
    """Cut leading/trailing silence so chunk edges are word edges."""
    if audio.size == 0:
        return audio
    hop = max(1, int(sr * 0.005))
    n = len(audio) // hop
    rms = np.sqrt(np.mean(audio[: n * hop].reshape(n, hop) ** 2, axis=1) + 1e-12)
    db = 20 * np.log10(rms / (np.max(rms) + 1e-12))
    loud = np.nonzero(db > rel_db)[0]
    if loud.size == 0:
        return audio[:0]
    m = int(margin_s * sr)
    a = max(0, loud[0] * hop - m)
    b = min(len(audio), (loud[-1] + 1) * hop + m)
    return audio[a:b]


def flatten_pitch(audio: Audio, sr: int, keep: float) -> Audio:
    """Compress the F0 contour towards its median (PSOLA resynthesis)."""
    import parselmouth  # noqa: PLC0415
    from parselmouth.praat import call  # noqa: PLC0415

    snd = parselmouth.Sound(audio.astype(np.float64), sampling_frequency=sr)
    manip = call(snd, "To Manipulation", 0.01, 75, 400)
    pitch = snd.to_pitch_ac(time_step=0.01, pitch_floor=75, pitch_ceiling=400)
    median = call(pitch, "Get quantile", 0, 0, 0.5, "Hertz")
    tier = call(manip, "Extract pitch tier")
    call(tier, "Formula", f"{median} + (self - {median}) * {keep}")
    call([tier, manip], "Replace pitch tier")
    out = call(manip, "Get resynthesis (overlap-add)")
    res = np.asarray(out.values[0], dtype=np.float32)
    return res[: len(audio)] if res.size >= len(audio) else np.pad(res, (0, len(audio) - res.size))


def gain_ramp(audio: Audio, start_db: float, end_db: float) -> Audio:
    ramp = np.linspace(start_db, end_db, audio.size)
    return (audio * 10 ** (ramp / 20)).astype(np.float32)


# --------------------------------------------------------------------------- flaw plans


@dataclass
class Flaw:
    code: FlawCode
    phrase: int
    a: int = 0  # surface-word range [a, b] inside the script (inclusive)
    b: int = 0
    params: dict[str, float | str] = field(default_factory=dict)


@dataclass
class ClipPlan:
    clip_id: str
    challenge_id: str
    role: str
    voice: str
    split: str
    flaws: list[Flaw]


def _choose_phrase(
    rng: random.Random, phrase_words: list[list[int]], min_words: int, used: set[int]
) -> int | None:
    options = [i for i, ws in enumerate(phrase_words) if len(ws) >= min_words and i not in used]
    return rng.choice(options) if options else None


_MIN_WORDS: dict[str, int] = {
    "RUSH": 5,
    "DRAG": 5,
    "HESITATE": 3,
    "MONO": 4,
    "FADE": 3,
    "SKIP": 4,
    "FILLER": 3,
}


def _place(
    code: FlawCode,
    rng: random.Random,
    words: list[SurfaceWord],
    phrase_words: list[list[int]],
    used: set[int],
) -> Flaw | None:
    p = _choose_phrase(rng, phrase_words, _MIN_WORDS[code], used)
    if p is None:
        return None
    used.add(p)
    ws = phrase_words[p]
    if code in ("RUSH", "DRAG"):
        span = min(len(ws) - 1, rng.choice([4, 5]))
        start = rng.randint(0, len(ws) - span)
        scale = (
            round(rng.uniform(0.52, 0.62), 2) if code == "RUSH" else round(rng.uniform(1.6, 1.9), 2)
        )
        return Flaw(code, p, ws[start], ws[start + span - 1], {"length_scale": scale})
    if code == "HESITATE":
        k = rng.randint(1, len(ws) - 1)
        return Flaw(code, p, ws[k], ws[k], {"pause_s": round(rng.uniform(0.9, 1.5), 2)})
    if code == "MONO":
        return Flaw(code, p, ws[0], ws[-1], {"keep": round(rng.uniform(0.1, 0.25), 2)})
    if code == "FADE":
        return Flaw(code, p, ws[-2], ws[-1], {"start_db": -8.0, "end_db": -20.0})
    if code == "SKIP":
        n = rng.choice([1, 2])
        k = rng.randint(1, len(ws) - 1 - n)
        return Flaw(code, p, ws[k], ws[k + n - 1])
    k = rng.randint(1, len(ws) - 1)  # FILLER: inserted before word k
    return Flaw(code, p, ws[k], ws[k], {"filler": rng.choice(["Um,", "Uh,", "Umm,"])})


ALL_CODES: tuple[FlawCode, ...] = ("RUSH", "DRAG", "HESITATE", "MONO", "FADE", "SKIP", "FILLER")


def plan_challenge(entry: CatalogueEntry, variants: int = 4) -> list[ClipPlan]:
    rng = random.Random(f"speakquest-{GENERATOR_VERSION}-{entry.id}")
    words = surface_words(entry.script)
    pw = phrases(words)
    plans = [
        ClipPlan(f"{entry.id}__reference", entry.id, "reference", REFERENCE_VOICE, entry.split, [])
    ]
    plans += [
        ClipPlan(f"{entry.id}__clean-{v.split('-')[1]}", entry.id, "clean", v, entry.split, [])
        for v in PARTICIPANT_VOICES
    ]
    # Cycle through the challenge's targets first, then the remaining codes,
    # so every code shows up in both splits.
    others = [c for c in ALL_CODES if c not in entry.flaw_targets]
    rng.shuffle(others)
    queue = [*entry.flaw_targets, *others]
    qi = 0
    for n in range(1, variants + 1):
        used: set[int] = set()
        flaws: list[Flaw] = []
        want = 1 if n % 2 else 2
        attempts = 0
        while len(flaws) < want and attempts < len(ALL_CODES) * 2:
            code = queue[qi % len(queue)]
            qi += 1
            attempts += 1
            if any(f.code == code for f in flaws):
                continue
            placed = _place(code, rng, words, pw, used)
            if placed:
                flaws.append(placed)
        voice = PARTICIPANT_VOICES[(n - 1) % len(PARTICIPANT_VOICES)]
        plans.append(
            ClipPlan(
                f"{entry.id}__flawed-{n}",
                entry.id,
                "flawed",
                voice,
                entry.split,
                sorted(flaws, key=lambda f: f.a),
            )
        )
    return plans


# --------------------------------------------------------------------------- rendering


@dataclass
class Label:
    code: FlawCode
    start: float
    end: float
    script_span: tuple[int, int] | None
    params: dict[str, float | str]


@dataclass
class Boundary:
    """A word edge whose time is known exactly (a chunk edge)."""

    token: int
    edge: str  # "start" | "end"
    time: float


def _text(words: Sequence[SurfaceWord], idx: Iterable[int]) -> str:
    return " ".join(words[i].text for i in idx)


def render(
    plan: ClipPlan, script: str, synth: Synth
) -> tuple[Audio, int, list[Label], list[Boundary]]:
    sr = synth.sample_rate(plan.voice)
    words = surface_words(script)
    pw = phrases(words)
    by_phrase = {f.phrase: f for f in plan.flaws}
    audio: list[Audio] = [np.zeros(int(0.35 * sr), dtype=np.float32)]
    t = 0.35
    labels: list[Label] = []
    bounds: list[Boundary] = []

    def emit(chunk: Audio, idx: list[int] | None) -> tuple[float, float]:
        nonlocal t
        start = t
        audio.append(chunk)
        t += len(chunk) / sr
        if idx:
            first, last = words[idx[0]], words[idx[-1]]
            bounds.append(Boundary(first.first_token, "start", round(start, 3)))
            bounds.append(Boundary(last.first_token + last.n_tokens - 1, "end", round(t, 3)))
        return start, t

    def gap(seconds: float) -> tuple[float, float]:
        nonlocal t
        start = t
        audio.append(np.zeros(int(seconds * sr), dtype=np.float32))
        t += int(seconds * sr) / sr
        return start, t

    def tokens_of(a: int, b: int) -> tuple[int, int]:
        return words[a].first_token, words[b].first_token + words[b].n_tokens - 1

    for p, ws in enumerate(pw):
        if p > 0:
            gap(PHRASE_GAP_S.get(words[pw[p - 1][-1]].text[-1], 0.32))
        flaw = by_phrase.get(p)
        if flaw is None:
            emit(synth.say(plan.voice, _text(words, ws)), ws)
            continue
        pre = [i for i in ws if i < flaw.a]
        mid = [i for i in ws if flaw.a <= i <= flaw.b]
        post = [i for i in ws if i > flaw.b]
        span = tokens_of(flaw.a, flaw.b)
        if flaw.code in ("RUSH", "DRAG"):
            if pre:
                emit(synth.say(plan.voice, _text(words, pre)), pre)
                gap(JOIN_GAP_S)
            s, e = emit(
                synth.say(plan.voice, _text(words, mid), float(flaw.params["length_scale"])), mid
            )
            labels.append(Label(flaw.code, s, e, span, flaw.params))
            if post:
                gap(JOIN_GAP_S)
                emit(synth.say(plan.voice, _text(words, post)), post)
        elif flaw.code == "HESITATE":
            before = [i for i in ws if i < flaw.a]
            after = [i for i in ws if i >= flaw.a]
            emit(synth.say(plan.voice, _text(words, before)), before)
            s, e = gap(float(flaw.params["pause_s"]))
            prev_tok = words[before[-1]].first_token + words[before[-1]].n_tokens - 1
            labels.append(
                Label("HESITATE", s, e, (prev_tok, words[after[0]].first_token), flaw.params)
            )
            emit(synth.say(plan.voice, _text(words, after)), after)
        elif flaw.code == "MONO":
            chunk = synth.say(plan.voice, _text(words, ws))
            s, e = emit(flatten_pitch(chunk, sr, float(flaw.params["keep"])), ws)
            labels.append(Label("MONO", s, e, tokens_of(ws[0], ws[-1]), flaw.params))
        elif flaw.code == "FADE":
            head = [i for i in ws if i < flaw.a]
            emit(synth.say(plan.voice, _text(words, head)), head)
            gap(JOIN_GAP_S)
            tail = synth.say(plan.voice, _text(words, mid))
            s, e = emit(
                gain_ramp(tail, float(flaw.params["start_db"]), float(flaw.params["end_db"])), mid
            )
            labels.append(Label("FADE", s, e, span, flaw.params))
        elif flaw.code == "SKIP":
            emit(synth.say(plan.voice, _text(words, pre)), pre)
            s, e = gap(JOIN_GAP_S)
            labels.append(Label("SKIP", s, e, span, {"skipped": _text(words, mid)}))
            emit(synth.say(plan.voice, _text(words, post)), post)
        elif flaw.code == "FILLER":
            before = [i for i in ws if i < flaw.a]
            after = [i for i in ws if i >= flaw.a]
            emit(synth.say(plan.voice, _text(words, before)), before)
            gap(0.15)
            s, e = emit(synth.say(plan.voice, str(flaw.params["filler"])), None)
            labels.append(Label("FILLER", s, e, None, flaw.params))
            gap(0.15)
            emit(synth.say(plan.voice, _text(words, after)), after)
    gap(0.4)
    out = np.concatenate(audio).astype(np.float32)
    peak = float(np.max(np.abs(out))) or 1.0
    out = (out / peak * 0.7).astype(np.float32)  # same headroom for every clip
    for lab in labels:
        lab.start, lab.end = round(lab.start, 3), round(lab.end, 3)
    return out, sr, labels, bounds


def write_wav(path: Path, audio: Audio, sr: int) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm)
    return hashlib.sha256(pcm).hexdigest()


def generate(
    out_audio: Path, out_annotations: Path, model_dir: Path, only: Sequence[str] = ()
) -> list[dict[str, Any]]:
    synth = Synth(model_dir)
    rows: list[dict[str, Any]] = []
    for entry in load_catalogue():
        if only and entry.id not in only:
            continue
        for plan in plan_challenge(entry):
            audio, sr, labels, bounds = render(plan, entry.script, synth)
            wav = out_audio / f"{plan.clip_id}.wav"
            digest = write_wav(wav, audio, sr)
            annotation = {
                "clip_id": plan.clip_id,
                "challenge_id": plan.challenge_id,
                "role": plan.role,
                "voice": plan.voice,
                "split": plan.split,
                "sample_rate": sr,
                "duration_s": round(len(audio) / sr, 3),
                "audio_sha256": digest,
                "generator": {
                    "name": "piper-chunked",
                    "version": GENERATOR_VERSION,
                    "noise_scale": 0.0,
                    "noise_w_scale": 0.0,
                },
                "flaws": [
                    {
                        **asdict(lab),
                        "script_span": list(lab.script_span) if lab.script_span else None,
                    }
                    for lab in labels
                ],
                "boundaries": [asdict(b) for b in bounds],
            }
            out_annotations.mkdir(parents=True, exist_ok=True)
            (out_annotations / f"{plan.clip_id}.json").write_text(
                json.dumps(annotation, indent=2) + "\n"
            )
            rows.append(
                {
                    "clip_id": plan.clip_id,
                    "challenge_id": plan.challenge_id,
                    "role": plan.role,
                    "voice": plan.voice,
                    "split": plan.split,
                    "duration_s": annotation["duration_s"],
                    "flaws": "+".join(lab.code for lab in labels),
                }
            )
    return rows
