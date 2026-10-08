"""Real local aligners on real (synthesised) speech. Skipped without models."""

from __future__ import annotations

import os
import wave
from pathlib import Path

import numpy as np
import pytest

from speakquest.timing import VoskAligner, spoken_tokens

pytestmark = [pytest.mark.slow, pytest.mark.asr]
MODELS = Path(os.environ.get("SPEAKQUEST_MODEL_DIR", ".models"))
VOICE = MODELS / "piper" / "en_US-ryan-medium.onnx"
VOSK = MODELS / "vosk" / "vosk-model-small-en-us-0.15"


@pytest.fixture(scope="module")
def speech_wav(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if not VOICE.exists():
        pytest.skip("piper voice not downloaded (make models)")
    piper = pytest.importorskip("piper")
    voice = piper.PiperVoice.load(str(VOICE))
    audio = np.concatenate(
        [
            c.audio_float_array
            for c in voice.synthesize(
                "We ship the final build before the deadline, then we rest for a while."
            )
        ]
    )
    src_sr = voice.config.sample_rate
    # Resample to 16 kHz with linear interpolation (test-only; prod uses ffmpeg).
    n = int(len(audio) * 16000 / src_sr)
    audio16 = np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio)
    out = tmp_path_factory.mktemp("asr") / "speech.wav"
    with wave.open(str(out), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes((np.clip(audio16, -1, 1) * 32767).astype("<i2").tobytes())
    return out


def test_vosk_recovers_script_words_with_ordered_times(speech_wav: Path) -> None:
    if not VOSK.exists():
        pytest.skip("vosk model not downloaded (make models)")
    transcript = VoskAligner(str(VOSK)).transcribe(speech_wav, "en-US")
    norms = [t.norm for t in spoken_tokens(transcript)]
    expected = "we ship the final build before the deadline then we rest for a while".split()
    hits = sum(1 for w in expected if w in norms)
    assert hits >= len(expected) - 3
    starts = [w.start for w in transcript.words]
    assert starts == sorted(starts)
    assert transcript.aligner.startswith("vosk:")
