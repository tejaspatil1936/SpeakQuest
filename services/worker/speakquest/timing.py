"""Word timing: aligner adapters and time-span helpers.

Amazon Transcribe is the primary timestamp source. In the cloud the
transcription job runs as its own Step Functions state, so the Analyze step
only *parses* Transcribe's JSON (:func:`parse_transcribe_json`). Other
aligners implement :class:`Aligner` and produce the same :class:`Transcript`,
so the rest of the pipeline cannot tell them apart and an alternative (the
local faster-whisper adapter, or WhisperX) can be evaluated without touching
diff, features, findings or scoring.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Protocol

from speakquest.contracts import TimedWord, Transcript
from speakquest.errors import AnalysisError
from speakquest.normalize import load_wav
from speakquest.tokens import normalize_word


class Aligner(Protocol):
    name: str

    def transcribe(self, wav: Path, language: str) -> Transcript: ...


# --------------------------------------------------------------------------- Amazon Transcribe


def parse_transcribe_json(doc: dict[str, Any], language: str = "en-US") -> Transcript:
    """Convert an Amazon Transcribe output document into a :class:`Transcript`.

    Punctuation items carry no timestamps and are dropped; each pronunciation
    item keeps its top alternative.
    """
    status = doc.get("status")
    if status not in (None, "COMPLETED"):
        raise AnalysisError("TRANSCRIBE_FAILED", f"job status {status}", stage="TRANSCRIBE")
    try:
        items = doc["results"]["items"]
    except (KeyError, TypeError) as exc:
        raise AnalysisError(
            "TRANSCRIBE_FAILED", "malformed transcript", stage="TRANSCRIBE"
        ) from exc
    words: list[TimedWord] = []
    for item in items:
        if item.get("type") != "pronunciation":
            continue
        alt = (item.get("alternatives") or [{}])[0]
        content = str(alt.get("content", "")).strip()
        if not content or "start_time" not in item:
            continue
        conf = alt.get("confidence")
        words.append(
            TimedWord(
                text=content,
                start=float(item["start_time"]),
                end=float(item["end_time"]),
                confidence=min(1.0, max(0.0, float(conf))) if conf not in (None, "") else None,
            )
        )
    return Transcript(aligner="amazon-transcribe", language=language, words=words)


@dataclass
class TranscribeFileAligner:
    """Reads a Transcribe output JSON that the workflow already produced."""

    transcript_path: Path
    name: str = "amazon-transcribe"

    def transcribe(self, wav: Path, language: str) -> Transcript:
        doc = json.loads(self.transcript_path.read_text())
        return parse_transcribe_json(doc, language)


class TranscribeJobAligner:
    """Runs a real Amazon Transcribe job (used when seeding references).

    In the analysis workflow the job is started and polled by Step Functions
    states instead; this adapter does the same from Python so reference
    takes get the same timestamps as participants' takes.
    """

    name = "amazon-transcribe"

    def __init__(
        self,
        bucket: str,
        job_prefix: str,
        region: str | None = None,
        poll_s: float = 5.0,
        max_polls: int = 40,
        s3: Any = None,
        transcribe: Any = None,
    ):
        import boto3  # noqa: PLC0415

        self.bucket = bucket
        self.job_prefix = job_prefix
        self.poll_s = poll_s
        self.max_polls = max_polls
        self.s3: Any = s3 or boto3.client("s3", region_name=region)
        self.transcribe_client: Any = transcribe or boto3.client("transcribe", region_name=region)

    def transcribe(self, wav: Path, language: str) -> Transcript:
        import hashlib  # noqa: PLC0415
        import time  # noqa: PLC0415

        digest = hashlib.sha256(wav.read_bytes()).hexdigest()[:12]
        job = f"{self.job_prefix}-{digest}-{int(time.time())}"
        media_key = f"work/seed/{job}.wav"
        output_key = f"transcripts/seed/{job}.json"
        self.s3.upload_file(str(wav), self.bucket, media_key)
        self.transcribe_client.start_transcription_job(
            TranscriptionJobName=job,
            LanguageCode=language,
            MediaFormat="wav",
            Media={"MediaFileUri": f"s3://{self.bucket}/{media_key}"},
            OutputBucketName=self.bucket,
            OutputKey=output_key,
        )
        for _ in range(self.max_polls):
            status = self.transcribe_client.get_transcription_job(TranscriptionJobName=job)[
                "TranscriptionJob"
            ]["TranscriptionJobStatus"]
            if status == "COMPLETED":
                body = self.s3.get_object(Bucket=self.bucket, Key=output_key)["Body"].read()
                return parse_transcribe_json(json.loads(body), language)
            if status == "FAILED":
                raise AnalysisError("TRANSCRIBE_FAILED", job, stage="TRANSCRIBE")
            time.sleep(self.poll_s)
        raise AnalysisError("TRANSCRIBE_TIMEOUT", job, stage="TRANSCRIBE")


# --------------------------------------------------------------------------- fixtures


@dataclass
class WordsFileAligner:
    """Replays a saved :class:`Transcript` (``words.json``) — used for seeded
    references and deterministic tests."""

    words_path: Path
    name: str = "words-file"

    def transcribe(self, wav: Path, language: str) -> Transcript:
        return Transcript.model_validate_json(self.words_path.read_text())


# --------------------------------------------------------------------------- faster-whisper

# Whisper tends to "clean up" disfluencies. A verbatim-style prompt makes it
# keep fillers (system design §5.1 step 4). The script is deliberately *not*
# used as a prompt: that would make the recogniser hallucinate skipped words.
_VERBATIM_PROMPT = "Umm, let me think like, hmm... Okay, uh, here's what I'm, like, thinking."


WHISPER_SR = 16000


class FasterWhisperAligner:
    """Local CPU aligner (CTranslate2 Whisper with DTW word timestamps).

    Used when Amazon Transcribe is not reachable, and as the comparison
    aligner in the evaluation harness.
    """

    _models: ClassVar[dict[str, Any]] = {}
    _lock: ClassVar[threading.Lock] = threading.Lock()

    def __init__(self, model: str | None = None, compute_type: str = "int8"):
        self.model_name = model or os.environ.get("SPEAKQUEST_WHISPER_MODEL", "base.en")
        self.compute_type = compute_type
        self.name = f"faster-whisper:{self.model_name}"

    def _model(self) -> Any:
        with self._lock:
            if self.model_name not in self._models:
                try:
                    from faster_whisper import WhisperModel  # noqa: PLC0415 - optional extra
                except ImportError as exc:  # pragma: no cover - depends on extras
                    raise AnalysisError(
                        "INTERNAL",
                        "faster-whisper not installed (uv sync --extra asr)",
                        stage="TRANSCRIBE",
                    ) from exc
                cache = os.environ.get("SPEAKQUEST_MODEL_DIR", str(Path(".models").resolve()))
                self._models[self.model_name] = WhisperModel(
                    self.model_name,
                    device="cpu",
                    compute_type=self.compute_type,
                    download_root=cache,
                    cpu_threads=min(4, os.cpu_count() or 1),
                )
            return self._models[self.model_name]

    def transcribe(self, wav: Path, language: str) -> Transcript:
        lang = language.split("-", maxsplit=1)[0]
        # Decode with our own loader: the pipeline always hands over the
        # normalised 16 kHz WAV, and this sidesteps faster-whisper's PyAV path.
        samples, sr = load_wav(wav)
        if sr != WHISPER_SR:
            raise AnalysisError(
                "INTERNAL", f"aligner needs {WHISPER_SR} Hz audio, got {sr}", stage="TRANSCRIBE"
            )
        try:
            segments, _info = self._model().transcribe(
                samples,
                language=lang,
                word_timestamps=True,
                beam_size=5,
                temperature=0.0,
                condition_on_previous_text=False,
                initial_prompt=_VERBATIM_PROMPT,
                vad_filter=False,
            )
            words = [
                TimedWord(
                    text=w.word.strip(),
                    start=round(max(0.0, w.start), 3),
                    end=round(max(w.start, w.end), 3),
                    confidence=round(min(1.0, max(0.0, w.probability)), 4),
                )
                for seg in segments
                for w in (seg.words or [])
                if w.word.strip()
            ]
        except AnalysisError:
            raise
        except Exception as exc:
            raise AnalysisError("TRANSCRIBE_FAILED", str(exc)[:300], stage="TRANSCRIBE") from exc
        return Transcript(aligner=self.name, language=language, words=words)


# --------------------------------------------------------------------------- Vosk (Kaldi)


class VoskAligner:
    """Local CPU aligner using a Kaldi model through Vosk.

    HMM decoding places word boundaries on the acoustics, which in our
    measurements is far tighter than Whisper's attention-based timestamps
    (see docs/EVALUATION.md), and it runs in ~200 MB of RAM. This is the
    default stand-in for Amazon Transcribe when Transcribe is unavailable.
    """

    _models: ClassVar[dict[str, Any]] = {}
    _lock: ClassVar[threading.Lock] = threading.Lock()

    def __init__(self, model_path: str | None = None):
        default = (
            Path(os.environ.get("SPEAKQUEST_MODEL_DIR", ".models"))
            / "vosk"
            / ("vosk-model-small-en-us-0.15")
        )
        self.model_path = model_path or os.environ.get("SPEAKQUEST_VOSK_MODEL", str(default))
        self.name = f"vosk:{Path(self.model_path).name}"

    def _model(self) -> Any:
        with self._lock:
            if self.model_path not in self._models:
                try:
                    import vosk  # noqa: PLC0415 - optional extra
                except ImportError as exc:  # pragma: no cover - depends on extras
                    raise AnalysisError(
                        "INTERNAL", "vosk not installed (uv sync --extra asr)", stage="TRANSCRIBE"
                    ) from exc
                if not Path(self.model_path).is_dir():
                    raise AnalysisError(
                        "INTERNAL",
                        f"vosk model missing at {self.model_path} (run `make models`)",
                        stage="TRANSCRIBE",
                    )
                vosk.SetLogLevel(-1)
                self._models[self.model_path] = vosk.Model(self.model_path)
            return self._models[self.model_path]

    def transcribe(self, wav: Path, language: str) -> Transcript:
        import vosk  # noqa: PLC0415 - optional extra

        samples, sr = load_wav(wav)
        pcm = (samples * 32767).clip(-32768, 32767).astype("<i2").tobytes()
        try:
            rec = vosk.KaldiRecognizer(self._model(), sr)
            rec.SetWords(True)
            results: list[dict[str, Any]] = []
            step = sr // 2 * 2  # half a second of 16-bit samples
            for i in range(0, len(pcm), step):
                if rec.AcceptWaveform(pcm[i : i + step]):
                    results.append(json.loads(rec.Result()))
            results.append(json.loads(rec.FinalResult()))
        except AnalysisError:
            raise
        except Exception as exc:
            raise AnalysisError("TRANSCRIBE_FAILED", str(exc)[:300], stage="TRANSCRIBE") from exc
        words = [
            TimedWord(
                text=str(w["word"]),
                start=round(float(w["start"]), 3),
                end=round(float(w["end"]), 3),
                confidence=round(min(1.0, max(0.0, float(w.get("conf", 1.0)))), 4),
            )
            for r in results
            for w in r.get("result", [])
            if str(w.get("word", "")).strip()
        ]
        return Transcript(aligner=self.name, language=language, words=words)


def get_aligner(name: str, **kwargs: Any) -> Aligner:
    if name == "vosk":
        return VoskAligner(**kwargs)
    if name in ("faster-whisper", "whisper"):
        return FasterWhisperAligner(**kwargs)
    if name == "transcribe-file":
        return TranscribeFileAligner(**kwargs)
    if name == "words-file":
        return WordsFileAligner(**kwargs)
    raise ValueError(f"unknown aligner {name!r}")


# --------------------------------------------------------------------------- spoken tokens


@dataclass(frozen=True)
class SpokenToken:
    """A normalised token with timing. One recognised word can expand into
    several tokens ("2026" → twenty twenty six); its span is split evenly."""

    norm: str
    text: str
    start: float
    end: float
    confidence: float | None
    source_word: int


def spoken_tokens(transcript: Transcript) -> list[SpokenToken]:
    out: list[SpokenToken] = []
    for idx, word in enumerate(transcript.words):
        norms = normalize_word(word.text)
        if not norms:
            continue
        step = (word.end - word.start) / len(norms)
        for k, norm in enumerate(norms):
            out.append(
                SpokenToken(
                    norm=norm,
                    text=word.text if len(norms) == 1 else norm,
                    start=round(word.start + k * step, 3),
                    end=round(word.start + (k + 1) * step, 3),
                    confidence=word.confidence,
                    source_word=idx,
                )
            )
    # Aligners occasionally emit overlapping spans; clamp to keep time monotonic.
    fixed: list[SpokenToken] = []
    for raw in out:
        tok = raw
        if fixed and tok.start < fixed[-1].end:
            start = fixed[-1].end
            tok = SpokenToken(
                tok.norm, tok.text, start, max(start, tok.end), tok.confidence, tok.source_word
            )
        fixed.append(tok)
    return fixed
