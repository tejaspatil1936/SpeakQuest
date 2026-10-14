# Evaluation

Everything here was produced by `make eval` (`speakquest-eval run`) on
2026-10-15 with rubric **1.0.0**. Full per-clip reports are in
[`eval/reports/`](../eval/reports). Nothing in this document was estimated or
typed in by hand.

## Dataset

No licensed recordings with per-flaw time labels were available, so the
dataset is **synthetic** (`speakquest-eval generate`,
`eval/speakquest_eval/synth.py`):

- **8 scripts** (`data/scripts/challenges.yaml`) × 7 clips = **56 clips,
  9.8 minutes**: 1 reference (voice *lessac*), 2 clean second readers (*ryan*,
  *amy*), 4 flawed variants (ryan/amy) with 1–2 injected flaws each.
- Voices: three Piper VITS voices, US English, studio-clean, 22.05 kHz.
- **Exact labels.** Each phrase is synthesised whole (natural prosody). The
  generator exposes the model's per-phoneme durations from the ONNX graph, so
  every word's start and end is known; flaws are applied inside the natural
  phrase at word boundaries:

  | Flaw | How it is injected | Magnitude |
  |---|---|---|
  | RUSH | span spliced from a faster rendering of the same phrase | 1.45–1.8× (achieved, iterated to within 3 %) |
  | DRAG | span spliced from a slower rendering | 0.55–0.68× |
  | HESITATE | silence inserted at a word boundary | 0.8–1.4 s |
  | MONO | phrase F0 compressed towards its median (PSOLA) | 10–25 % of the contour kept |
  | FADE | gain ramp over the phrase's last two words | −8 → −20 dB |
  | SKIP | 1–2 words cut out | — |
  | FILLER | "um"/"erm" inserted between words | 0.30–0.55 s |

- Labels: `data/annotations/<clip>.json` (flaw intervals, script spans, every
  word edge, audio SHA-256). Synthesis is deterministic (noise disabled), so
  regenerated audio matches the committed annotations.
- **Split:** thresholds were tuned on the 5 **dev** scripts (20 flawed + 10
  clean clips); results are reported on the 3 **held-out** scripts (12 flawed
  + 6 clean clips), which were evaluated once with the frozen rubric.

Flaw counts — dev: RUSH 5, DRAG 4, HESITATE 4, MONO 5, FADE 5, SKIP 4,
FILLER 3; held-out: RUSH 3, DRAG 3, HESITATE 2, MONO 3, FADE 3, SKIP 1,
FILLER 3.

## Method

- Each clip runs through the production pipeline: ffmpeg normalisation →
  aligner → script diff → features → rules, against the challenge's
  reference processed the same way.
- **Match:** same flaw code and timestamp IoU ≥ 0.5, one-to-one, greedy by IoU.
  SKIP labels are points in time, so SKIP intervals are padded to 0.3 s on
  both sides before IoU.
- **False-positive rate:** findings per minute on the clean second-reader
  clips compared with the reference.
- **Aligner timing:** absolute error of each recognised word's start/end
  against the labelled word edges.

## Results — Vosk aligner (the local default)

| Split | Precision | Recall | Mean IoU | FP / min (clean) | Boundary error median / p90 |
|---|---:|---:|---:|---:|---:|
| dev (tuning) | 0.74 | 0.77 | 0.89 | 0.61 | 25 / 58 ms (n = 1,776) |
| **held-out** | **0.67** | **0.78** | **0.93** | **3.51** | **24 / 60 ms (n = 1,274)** |

Held-out per code (precision / recall): RUSH 1.00 / 0.33, DRAG 0.67 / 0.67,
HESITATE 1.00 / 1.00, MONO 1.00 / 1.00, FADE 0.75 / 1.00, SKIP 0.25 / 1.00,
FILLER 0.50 / 0.67.

**The held-out false-positive rate (3.51/min) misses the design's target of
< 1/min.** It comes from 4 findings (one each of DRAG, FILLER, RUSH, SKIP) in
1.14 clean minutes, so the estimate is coarse, but it is the measured
number. On dev the rate was 0.61/min.

## Tuning history (dev split only)

| Change | Dev P / R / FP-per-min |
|---|---|
| Initial thresholds from the design, chunk-synthesised dataset | 0.39 / 0.73 / 8.47 |
| Dataset v2: in-context synthesis with exact word labels, spoken numbers | 0.50 / 0.70 / 6.11 |
| Per-speaker pitch normalisation; ≥250 ms pauses only excluded from rate; calibrated flaw magnitudes | 0.78 / 0.70 / 0.61 |
| Hysteresis + whole-stretch re-measurement for RUSH/DRAG; recogniser renderings of "um" as fillers | 0.74 / 0.77 / 0.61 |

Each threshold change is commented in `rubric/v1.yaml`. The design's MONO
threshold moved from 0.50 to 0.40 after per-speaker normalisation.

## Aligner comparison (the design's runtime test)

The design's day-one test compares Transcribe with WhisperX word boundaries on
labelled clips: median error < 40 ms keeps the Lambda runtime. Amazon
Transcribe is blocked for this account by an organisation policy and WhisperX
(PyTorch + wav2vec2) does not fit this machine, so the same test was run on
the two local aligners, over every labelled word edge:

| Aligner | Boundary median (dev / held-out) | p90 | Held-out P / R | Held-out FP/min |
|---|---:|---:|---:|---:|
| **Vosk** small-en-us 0.15 (Kaldi) | **25 / 24 ms** | 58 / 60 ms | 0.67 / 0.78 | 3.51 |
| faster-whisper base.en | 142.5 / 129 ms | 300 / 303 ms | 0.47 / 0.50 | 0.88 |

Vosk is well under the 40 ms bar; Whisper is not, and it drops fillers
(FILLER recall 0.00) — the failure the design anticipated. Whisper's lower
false-positive rate comes with half the recall. **Amazon Transcribe itself was
not measured** (see the blockers in [FINAL_REPORT.md](FINAL_REPORT.md)).

## Limitations

- **Speakers:** three synthetic voices (one reference, two participants), all
  US English. No human speech, no accents beyond the voices' own, no
  children's or elderly voices.
- **Recording conditions:** studio-clean synthetic audio; no room noise,
  microphones, compression artefacts or background speech. The browser E2E run
  passes the same audio through Chrome's capture and Opus encoding, which is
  the only lossy path tested.
- **Flaws are manipulated, not performed.** A splice from a faster rendering is
  not how a nervous speaker rushes; real flaws co-occur and blur together.
- **Small held-out set:** 18 flawed labels and 1.14 clean minutes. One finding
  more or less moves FP/min by 0.9.
- **Where timing fails:** fast stretches are where the recogniser drops or
  merges short words; on held-out data that produced SKIP false positives
  inside rushed spans. Fillers are often recognised as "oh"/"of" rather than
  "um", which is why recogniser renderings count as fillers.
- **Not evaluated:** Amazon Transcribe timestamps, the Bedrock coaching text
  beyond its validator, and real users' recordings.
