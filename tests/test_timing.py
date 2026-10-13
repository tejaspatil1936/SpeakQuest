from __future__ import annotations

import json
from pathlib import Path

import pytest

from speakquest.contracts import TimedWord, Transcript
from speakquest.errors import AnalysisError
from speakquest.timing import (
    TranscribeFileAligner,
    WordsFileAligner,
    get_aligner,
    parse_transcribe_json,
    spoken_tokens,
)

FIXTURE = Path(__file__).parent / "fixtures" / "transcribe_sample.json"


def test_parse_transcribe_drops_punctuation_and_keeps_fillers() -> None:
    t = parse_transcribe_json(json.loads(FIXTURE.read_text()))
    assert [w.text for w in t.words] == ["Before", "the", "um", "deadline", "in", "2026"]
    assert t.words[2].start == 0.90
    assert t.words[2].confidence == pytest.approx(0.87)
    assert t.aligner == "amazon-transcribe"


def test_failed_or_malformed_transcribe_documents() -> None:
    with pytest.raises(AnalysisError) as e:
        parse_transcribe_json({"status": "FAILED", "results": {}})
    assert e.value.code == "TRANSCRIBE_FAILED"
    with pytest.raises(AnalysisError):
        parse_transcribe_json({"results": None})


def test_spoken_tokens_expand_numbers_evenly() -> None:
    toks = spoken_tokens(parse_transcribe_json(json.loads(FIXTURE.read_text())))
    assert [t.norm for t in toks][-3:] == ["twenty", "twenty", "six"]
    assert toks[-3].start == 2.05 and toks[-1].end == 2.95
    assert toks[-2].start == pytest.approx(2.35)
    assert {t.source_word for t in toks[-3:]} == {5}


def test_spoken_tokens_clamp_overlaps() -> None:
    t = Transcript(
        aligner="x",
        language="en-US",
        words=[
            TimedWord(text="a", start=0.0, end=0.5),
            TimedWord(text="b", start=0.4, end=0.8),
        ],
    )
    toks = spoken_tokens(t)
    assert toks[1].start == 0.5


def test_file_aligners_round_trip(tmp_path: Path) -> None:
    t = TranscribeFileAligner(FIXTURE).transcribe(Path("unused.wav"), "en-US")
    words = tmp_path / "words.json"
    words.write_text(t.model_dump_json())
    assert WordsFileAligner(words).transcribe(Path("x"), "en-US") == t
    assert get_aligner("words-file", words_path=words).name == "words-file"
    with pytest.raises(ValueError):
        get_aligner("nope")


def test_transcribe_job_aligner_polls_until_complete(tmp_path: Path) -> None:
    import json as _json

    from speakquest.timing import TranscribeJobAligner

    wav = tmp_path / "ref.wav"
    wav.write_bytes(b"RIFF....fake")

    class S3:
        def __init__(self) -> None:
            self.objects: dict[str, bytes] = {}

        def upload_file(self, src: str, bucket: str, key: str) -> None:
            self.objects[key] = Path(src).read_bytes()

        def get_object(self, Bucket: str, Key: str) -> dict:  # noqa: N803 - boto3 names
            class Body:
                def __init__(self, data: bytes) -> None:
                    self.data = data

                def read(self) -> bytes:
                    return self.data

            return {"Body": Body(self.objects[Key])}

    class Transcribe:
        def __init__(self, s3: S3, statuses: list[str]) -> None:
            self.s3, self.statuses, self.started = s3, statuses, {}

        def start_transcription_job(self, **kw: object) -> None:
            self.started = kw
            self.s3.objects[str(kw["OutputKey"])] = FIXTURE.read_bytes()

        def get_transcription_job(self, TranscriptionJobName: str) -> dict:  # noqa: N803
            return {"TranscriptionJob": {"TranscriptionJobStatus": self.statuses.pop(0)}}

    s3 = S3()
    tr = Transcribe(s3, ["QUEUED", "IN_PROGRESS", "COMPLETED"])
    aligner = TranscribeJobAligner("bucket", "speakquest-dev", s3=s3, transcribe=tr, poll_s=0)
    out = aligner.transcribe(wav, "en-US")
    assert [w.text for w in out.words][:2] == ["Before", "the"]
    assert str(tr.started["Media"]["MediaFileUri"]).startswith("s3://bucket/work/seed/")  # type: ignore[index]
    assert _json.dumps(tr.started["LanguageCode"]) == '"en-US"'

    stuck = Transcribe(s3, ["IN_PROGRESS"] * 3)
    with pytest.raises(AnalysisError) as e:
        TranscribeJobAligner(
            "bucket", "p", s3=s3, transcribe=stuck, poll_s=0, max_polls=3
        ).transcribe(wav, "en-US")
    assert e.value.code == "TRANSCRIBE_TIMEOUT"
    failed = Transcribe(s3, ["FAILED"])
    with pytest.raises(AnalysisError) as e:
        TranscribeJobAligner("bucket", "p", s3=s3, transcribe=failed, poll_s=0).transcribe(
            wav, "en-US"
        )
    assert e.value.code == "TRANSCRIBE_FAILED"
