from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from speakquest.errors import AnalysisError
from speakquest.normalize import frame_rms, load_wav, normalize, probe, speech_level_dbfs
from speakquest.rubric import load_rubric
from tests.audio_helpers import silence, tone, transcode, write_wav

pytestmark = pytest.mark.slow
LIMITS = load_rubric().audio


def _speechy(seconds: float = 3.0, amp: float = 0.3) -> np.ndarray:
    return np.concatenate([silence(0.2), tone(seconds, amp=amp), silence(0.2)])


def test_wav_round_trip_to_16k_mono(tmp_path: Path) -> None:
    src = write_wav(tmp_path / "in.wav", _speechy(), sr=16000)
    stereo44 = transcode(src, tmp_path / "in44.wav", "-ac", "2", "-ar", "44100")
    out = normalize(stereo44, tmp_path / "out.wav", LIMITS)
    samples, sr = load_wav(out.path)
    assert sr == 16000
    assert out.duration_s == pytest.approx(3.4, abs=0.02)
    assert len(samples) == pytest.approx(3.4 * 16000, abs=400)
    # RMS of the voiced section sits a few dB under its peak.
    assert out.peak_dbfs - 8 < out.speech_dbfs < out.peak_dbfs
    assert out.clipped_ratio == 0


@pytest.mark.parametrize(
    ("ext", "args"),
    [
        ("webm", ["-c:a", "libopus"]),
        ("ogg", ["-c:a", "libopus"]),
        ("m4a", ["-c:a", "aac"]),
        ("mp3", []),
    ],
)
def test_browser_formats_decode(tmp_path: Path, ext: str, args: list[str]) -> None:
    src = write_wav(tmp_path / "in.wav", _speechy())
    enc = transcode(src, tmp_path / f"take.{ext}", *args)
    out = normalize(enc, tmp_path / "out.wav", LIMITS)
    assert out.duration_s == pytest.approx(3.4, abs=0.1)
    assert probe(enc).channels == 1


def test_missing_and_empty_uploads(tmp_path: Path) -> None:
    with pytest.raises(AnalysisError) as e:
        normalize(tmp_path / "nope.webm", tmp_path / "o.wav", LIMITS)
    assert e.value.code == "AUDIO_MISSING"
    empty = tmp_path / "empty.webm"
    empty.write_bytes(b"")
    with pytest.raises(AnalysisError) as e:
        normalize(empty, tmp_path / "o.wav", LIMITS)
    assert e.value.code == "AUDIO_MISSING"


def test_malformed_and_non_audio_files(tmp_path: Path) -> None:
    junk = tmp_path / "junk.webm"
    junk.write_bytes(np.random.default_rng(1).bytes(4096))
    with pytest.raises(AnalysisError) as e:
        normalize(junk, tmp_path / "o.wav", LIMITS)
    assert e.value.code in {"AUDIO_UNSUPPORTED", "AUDIO_CORRUPT"}
    text = tmp_path / "notes.wav"
    text.write_text("this is not audio\n" * 50)
    with pytest.raises(AnalysisError) as e:
        normalize(text, tmp_path / "o.wav", LIMITS)
    assert e.value.code in {"AUDIO_UNSUPPORTED", "AUDIO_CORRUPT"}
    assert e.value.stage == "NORMALIZE"


def test_video_without_audio_is_unsupported(tmp_path: Path) -> None:
    import subprocess

    vid = tmp_path / "v.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=32x32:d=1",
            str(vid),
        ],
        check=True,
        timeout=60,
    )
    with pytest.raises(AnalysisError) as e:
        normalize(vid, tmp_path / "o.wav", LIMITS)
    assert e.value.code == "AUDIO_UNSUPPORTED"


def test_silent_quiet_short_long_large(tmp_path: Path) -> None:
    cases = {
        "AUDIO_SILENT": silence(3.0),
        "AUDIO_TOO_QUIET": _speechy(amp=0.002),
        "AUDIO_TOO_SHORT": tone(0.8),
        "AUDIO_TOO_LONG": tone(LIMITS.max_duration_s + 2, amp=0.2),
    }
    for code, samples in cases.items():
        src = write_wav(tmp_path / f"{code}.wav", samples)
        with pytest.raises(AnalysisError) as e:
            normalize(src, tmp_path / "o.wav", LIMITS)
        assert e.value.code == code
    src = write_wav(tmp_path / "big.wav", _speechy())
    tiny = LIMITS.model_copy(update={"max_bytes": 1000})
    with pytest.raises(AnalysisError) as e:
        normalize(src, tmp_path / "o.wav", tiny)
    assert e.value.code == "AUDIO_TOO_LARGE"


def test_frame_rms_and_speech_level() -> None:
    sig = tone(1.0, amp=0.5)
    rms = frame_rms(sig, 16000, 20)
    assert rms.shape == (50,)
    assert speech_level_dbfs(silence(1.0), 16000) < -100
    assert frame_rms(np.zeros(10, dtype=np.float32), 16000, 20).size == 0
