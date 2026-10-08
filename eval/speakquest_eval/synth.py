"""Synthetic, labelled evaluation dataset (system design §5.5).

No licensed speech corpus with per-flaw time labels was available, so the
dataset is synthesised with Piper TTS, with exact ground truth:

* Each phrase is synthesised whole, so prosody is natural. The phoneme
  sequence is built word by word and fed straight to the model, and the
  model's internal per-phoneme durations (exposed from the ONNX graph) give
  the exact start and end of every word.
* Flaws are applied *inside* that natural phrase at word boundaries:
  rushed/dragged spans are spliced in from a faster/slower rendering of the
  same phrase, pauses and fillers are inserted at a boundary, skipped words
  are cut out, faded tails get a gain ramp and monotone phrases are
  flattened with PSOLA.

Per script:
* ``reference``  – voice A, clean (the challenge's reference take)
* ``clean-<v>``  – voices B and C, clean (second readers, for false positives)
* ``flawed-<n>`` – voices B/C with 1–2 injected flaws each

Numbers are given to the voice in their spoken form ("eighteen eighty
nine"), the way a person reads them. Piper runs with noise disabled, so
synthesis is deterministic; each annotation stores the audio SHA-256.

Limitations (also in docs/EVALUATION.md): three synthetic US-English
voices, studio-clean signal, flaws produced by signal manipulation rather
than human performance.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import wave
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from speakquest.challenges import CatalogueEntry, load_catalogue
from speakquest.contracts import FlawCode
from speakquest.tokens import normalize_word

GENERATOR_VERSION = "2"
REFERENCE_VOICE = "en_US-lessac-medium"
PARTICIPANT_VOICES = ("en_US-ryan-medium", "en_US-amy-medium")
PHRASE_GAP_S = {",": 0.32, ";": 0.4, ":": 0.4, ".": 0.55, "!": 0.55, "?": 0.55}
EDGE_MARGIN_S = 0.01
XFADE_S = 0.006

Audio = npt.NDArray[np.float32]
Span = tuple[float, float]


# --------------------------------------------------------------------------- script structure


@dataclass(frozen=True)
class SurfaceWord:
    text: str  # with punctuation, as written
    phrase: int
    first_token: int  # index of its first normalised token in the script
    n_tokens: int

    @property
    def spoken(self) -> str:
        """What a reader says: digits spelled out the way the tokenizer expects."""
        bare = re.sub(r"^[^\w$£€]+|[^\w%]+$", "", self.text)
        if re.search(r"\d", bare):
            return " ".join(normalize_word(bare))
        return bare

    @property
    def last_token(self) -> int:
        return self.first_token + self.n_tokens - 1


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


@dataclass
class Rendered:
    """Audio plus the exact span of each surface word it contains."""

    audio: Audio
    spans: dict[int, Span]


class Synth:
    """Piper with per-phoneme durations exposed, driven by our own phonemes."""

    def __init__(self, model_dir: Path):
        from piper import PiperVoice  # noqa: PLC0415 - optional extra

        self._loader = PiperVoice
        self.model_dir = model_dir
        self._voices: dict[str, Any] = {}
        self._sessions: dict[str, Any] = {}

    def voice(self, name: str) -> Any:
        if name not in self._voices:
            path = self.model_dir / f"{name}.onnx"
            if not path.exists():
                raise FileNotFoundError(f"{path} missing; run `make models`")
            self._voices[name] = self._loader.load(str(path))
        return self._voices[name]

    def _session(self, name: str) -> Any:
        if name not in self._sessions:
            import onnx  # noqa: PLC0415
            import onnxruntime as ort  # noqa: PLC0415
            from onnx import TensorProto, helper  # noqa: PLC0415

            model = onnx.load(str(self.model_dir / f"{name}.onnx"))
            ceil = [n for n in model.graph.node if n.op_type == "Ceil"]
            if len(ceil) != 1:
                raise RuntimeError(f"{name}: cannot locate the duration node")
            model.graph.output.append(
                helper.make_tensor_value_info(ceil[0].output[0], TensorProto.FLOAT, None)
            )
            opts = ort.SessionOptions()
            opts.intra_op_num_threads = 2
            self._sessions[name] = ort.InferenceSession(
                model.SerializeToString(), opts, providers=["CPUExecutionProvider"]
            )
        return self._sessions[name]

    def sample_rate(self, name: str) -> int:
        return int(self.voice(name).config.sample_rate)

    def _word_phonemes(self, voice: Any, text: str) -> list[str]:
        sentences = voice.phonemize(text)
        flat = [p for s in sentences for p in s]
        # Drop punctuation the phonemiser echoes back; keep internal spaces
        # (a spelled-out number is several spoken words).
        flat = [p for p in flat if p not in ",.;:!?"]
        while flat and flat[-1] == " ":
            flat.pop()
        while flat and flat[0] == " ":
            flat.pop(0)
        return flat

    def phrase(
        self,
        voice_name: str,
        words: Sequence[tuple[int, str]],
        final: str = ".",
        length_scale: float = 1.0,
    ) -> Rendered:
        """Synthesise ``words`` (index, spoken text) as one utterance."""
        voice = self.voice(voice_name)
        id_map = voice.config.phoneme_id_map
        pad, bos, eos = id_map["_"][0], id_map["^"][0], id_map["$"][0]
        ids: list[int] = [bos, pad]
        owner: list[int | None] = [None, None]
        for n, (idx, text) in enumerate(words):
            for p in self._word_phonemes(voice, text):
                if p not in id_map:
                    continue
                ids += [id_map[p][0], pad]
                owner += [idx, idx]
            if n < len(words) - 1:
                ids += [id_map[" "][0], pad]
                owner += [None, None]
        if final and final in id_map:
            ids += [id_map[final][0], pad]
            owner += [None, None]
        ids.append(eos)
        owner.append(None)

        sess = self._session(voice_name)
        audio, durations = sess.run(
            None,
            {
                "input": np.array([ids], dtype=np.int64),
                "input_lengths": np.array([len(ids)], dtype=np.int64),
                "scales": np.array([0.0, length_scale, 0.0], dtype=np.float32),
            },
        )
        sr = self.sample_rate(voice_name)
        hop = int(voice.config.hop_length) if getattr(voice.config, "hop_length", None) else 256
        audio = np.asarray(audio, dtype=np.float32).reshape(-1)
        ends = np.cumsum(np.asarray(durations, dtype=np.float64).reshape(-1)) * hop / sr
        starts = np.concatenate([[0.0], ends[:-1]])
        spans: dict[int, Span] = {}
        for k, who in enumerate(owner):
            if who is None:
                continue
            s, e = spans.get(who, (starts[k], ends[k]))
            spans[who] = (min(s, starts[k]), max(e, ends[k]))
        first = min(s for s, _ in spans.values())
        last = max(e for _, e in spans.values())
        a = max(0, int((first - EDGE_MARGIN_S) * sr))
        b = min(len(audio), int((last + EDGE_MARGIN_S) * sr))
        shift = a / sr
        return Rendered(
            audio[a:b].copy(),
            {i: (round(s - shift, 4), round(e - shift, 4)) for i, (s, e) in spans.items()},
        )


# --------------------------------------------------------------------------- audio surgery


def _xfade_join(a: Audio, b: Audio, sr: int) -> Audio:
    n = min(int(XFADE_S * sr), len(a), len(b))
    if n == 0:
        return np.concatenate([a, b])
    ramp = np.linspace(0, 1, n, dtype=np.float32)
    mid = a[-n:] * (1 - ramp) + b[:n] * ramp
    return np.concatenate([a[:-n], mid, b[n:]]).astype(np.float32)


def cut(r: Rendered, start: float, end: float, sr: int) -> Rendered:
    """Keep [start, end) of a rendering (spans clipped and shifted)."""
    a, b = int(start * sr), int(end * sr)
    spans = {
        i: (s - a / sr, e - a / sr)
        for i, (s, e) in r.spans.items()
        if s >= start - 1e-6 and e <= end + 1e-6
    }
    return Rendered(r.audio[a:b].copy(), spans)


def concat(parts: Sequence[Rendered], sr: int, crossfade: bool = True) -> Rendered:
    audio = np.zeros(0, dtype=np.float32)
    spans: dict[int, Span] = {}
    for part in parts:
        offset = len(audio) / sr
        if crossfade and audio.size and part.audio.size:
            n = min(int(XFADE_S * sr), len(audio), len(part.audio))
            offset -= n / sr
            audio = _xfade_join(audio, part.audio, sr)
        else:
            audio = np.concatenate([audio, part.audio]).astype(np.float32)
        spans.update({i: (s + offset, e + offset) for i, (s, e) in part.spans.items()})
    return Rendered(audio, spans)


def silence(seconds: float, sr: int) -> Rendered:
    return Rendered(np.zeros(int(seconds * sr), dtype=np.float32), {})


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


def gain_ramp(audio: Audio, start: int, end: int, start_db: float, end_db: float) -> Audio:
    out = audio.copy()
    out[start:end] *= 10 ** (np.linspace(start_db, end_db, end - start) / 20)
    out[end:] *= 10 ** (end_db / 20)
    return out.astype(np.float32)


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


_MIN_WORDS: dict[str, int] = {
    "RUSH": 5,
    "DRAG": 5,
    "HESITATE": 3,
    "MONO": 4,
    "FADE": 3,
    "SKIP": 4,
    "FILLER": 3,
}


def _choose_phrase(
    rng: random.Random, phrase_words: list[list[int]], min_words: int, used: set[int]
) -> int | None:
    options = [i for i, ws in enumerate(phrase_words) if len(ws) >= min_words and i not in used]
    return rng.choice(options) if options else None


def _place(
    code: FlawCode, rng: random.Random, phrase_words: list[list[int]], used: set[int]
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
            round(rng.uniform(0.55, 0.68), 2)
            if code == "RUSH"
            else round(rng.uniform(1.55, 1.85), 2)
        )
        return Flaw(code, p, ws[start], ws[start + span - 1], {"length_scale": scale})
    if code == "HESITATE":
        k = rng.randint(1, len(ws) - 1)
        return Flaw(code, p, ws[k], ws[k], {"pause_s": round(rng.uniform(0.8, 1.4), 2)})
    if code == "MONO":
        return Flaw(code, p, ws[0], ws[-1], {"keep": round(rng.uniform(0.1, 0.25), 2)})
    if code == "FADE":
        return Flaw(code, p, ws[-2], ws[-1], {"start_db": -8.0, "end_db": -20.0})
    if code == "SKIP":
        n = rng.choice([1, 2])
        k = rng.randint(1, len(ws) - 1 - n)
        return Flaw(code, p, ws[k], ws[k + n - 1])
    k = rng.randint(1, len(ws) - 1)  # FILLER: inserted before word k
    return Flaw(
        code,
        p,
        ws[k],
        ws[k],
        {"filler": rng.choice(["um", "uh"]), "length_scale": round(rng.uniform(1.8, 2.6), 2)},
    )


ALL_CODES: tuple[FlawCode, ...] = ("RUSH", "DRAG", "HESITATE", "MONO", "FADE", "SKIP", "FILLER")


def plan_challenge(entry: CatalogueEntry, variants: int = 4) -> list[ClipPlan]:
    rng = random.Random(f"speakquest-{GENERATOR_VERSION}-{entry.id}")
    pw = phrases(surface_words(entry.script))
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
            placed = _place(code, rng, pw, used)
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


def _final_punct(word: SurfaceWord) -> str:
    return word.text[-1] if word.text[-1] in PHRASE_GAP_S else "."


def render_phrase(
    plan: ClipPlan, words: list[SurfaceWord], ws: list[int], flaw: Flaw | None, synth: Synth
) -> tuple[Rendered, list[tuple[FlawCode, float, float, Any]]]:
    """One phrase with its flaw applied; returns marks (code, start, end, span) in
    phrase-local time."""
    sr = synth.sample_rate(plan.voice)
    items = [(i, words[i].spoken) for i in ws]
    final = _final_punct(words[ws[-1]])
    natural = synth.phrase(plan.voice, items, final)
    if flaw is None:
        return natural, []
    sp = natural.spans
    tokens = (words[flaw.a].first_token, words[flaw.b].last_token)

    if flaw.code in ("RUSH", "DRAG"):
        alt = synth.phrase(plan.voice, items, final, float(flaw.params["length_scale"]))
        head = cut(natural, 0.0, sp[flaw.a][0], sr)
        middle = cut(alt, alt.spans[flaw.a][0], alt.spans[flaw.b][1], sr)
        after = [i for i in ws if i > flaw.b]
        tail_start = sp[after[0]][0] if after else sp[flaw.b][1]
        # Keep the natural gap that followed the span in the faster/slower take.
        gap_after = (alt.spans[after[0]][0] - alt.spans[flaw.b][1]) if after else 0.0
        middle = concat([middle, silence(max(0.0, gap_after), sr)], sr, crossfade=False)
        tail = cut(natural, tail_start, len(natural.audio) / sr, sr)
        out = concat([head, middle, tail], sr)
        return out, [(flaw.code, out.spans[flaw.a][0], out.spans[flaw.b][1], tokens)]

    if flaw.code == "HESITATE":
        k = flaw.a
        prev = ws[ws.index(k) - 1]
        boundary = (sp[prev][1] + sp[k][0]) / 2
        out = concat(
            [
                cut(natural, 0.0, boundary, sr),
                silence(float(flaw.params["pause_s"]), sr),
                cut(natural, boundary, len(natural.audio) / sr, sr),
            ],
            sr,
            crossfade=False,
        )
        return out, [
            (
                "HESITATE",
                out.spans[prev][1],
                out.spans[k][0],
                (words[prev].last_token, words[k].first_token),
            )
        ]

    if flaw.code == "MONO":
        flat = Rendered(flatten_pitch(natural.audio, sr, float(flaw.params["keep"])), dict(sp))
        return flat, [("MONO", sp[ws[0]][0], sp[ws[-1]][1], tokens)]

    if flaw.code == "FADE":
        a, b = int(sp[flaw.a][0] * sr), int(sp[flaw.b][1] * sr)
        faded = gain_ramp(
            natural.audio, a, b, float(flaw.params["start_db"]), float(flaw.params["end_db"])
        )
        return Rendered(faded, dict(sp)), [("FADE", sp[flaw.a][0], sp[flaw.b][1], tokens)]

    if flaw.code == "SKIP":
        after = [i for i in ws if i > flaw.b]
        out = concat(
            [
                cut(natural, 0.0, sp[flaw.a][0], sr),
                cut(natural, sp[after[0]][0], len(natural.audio) / sr, sr),
            ],
            sr,
        )
        prev = ws[ws.index(flaw.a) - 1]
        junction = (out.spans[prev][1] + out.spans[after[0]][0]) / 2
        return out, [("SKIP", junction, junction, tokens)]

    # FILLER: a drawn-out "um"/"uh" inserted before word a.
    filler = synth.phrase(
        plan.voice, [(-1, str(flaw.params["filler"]))], ",", float(flaw.params["length_scale"])
    )
    filler = Rendered(filler.audio, {})
    k = flaw.a
    prev = ws[ws.index(k) - 1]
    boundary = (sp[prev][1] + sp[k][0]) / 2
    head = cut(natural, 0.0, boundary, sr)
    start = len(head.audio) / sr + 0.12
    out = concat(
        [
            head,
            silence(0.12, sr),
            filler,
            silence(0.12, sr),
            cut(natural, boundary, len(natural.audio) / sr, sr),
        ],
        sr,
        crossfade=False,
    )
    return out, [
        ("FILLER", start + EDGE_MARGIN_S, start + len(filler.audio) / sr - EDGE_MARGIN_S, None)
    ]


def render(
    plan: ClipPlan, script: str, synth: Synth
) -> tuple[Audio, int, list[Label], list[dict[str, Any]]]:
    sr = synth.sample_rate(plan.voice)
    words = surface_words(script)
    pw = phrases(words)
    by_phrase = {f.phrase: f for f in plan.flaws}
    params = {f.phrase: f.params for f in plan.flaws}
    parts: list[Rendered] = [silence(0.35, sr)]
    labels: list[Label] = []
    for p, ws in enumerate(pw):
        if p > 0:
            parts.append(silence(PHRASE_GAP_S.get(words[pw[p - 1][-1]].text[-1], 0.32), sr))
        offset = sum(len(x.audio) for x in parts) / sr
        rendered, marks = render_phrase(plan, words, ws, by_phrase.get(p), synth)
        parts.append(rendered)
        for code, s, e, span in marks:
            labels.append(Label(code, round(offset + s, 3), round(offset + e, 3), span, params[p]))
    parts.append(silence(0.4, sr))
    whole = concat(parts, sr, crossfade=False)
    peak = float(np.max(np.abs(whole.audio))) or 1.0
    audio = (whole.audio / peak * 0.7).astype(np.float32)  # same headroom for every clip
    boundaries: list[dict[str, Any]] = []
    for i, (s, e) in sorted(whole.spans.items()):
        if i < 0:
            continue
        boundaries.append({"token": words[i].first_token, "edge": "start", "time": round(s, 3)})
        boundaries.append({"token": words[i].last_token, "edge": "end", "time": round(e, 3)})
    return audio, sr, labels, boundaries


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
                    "name": "piper-phoneme-splice",
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
                "boundaries": bounds,
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
