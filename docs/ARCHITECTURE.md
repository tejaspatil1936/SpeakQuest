# Architecture

SpeakQuest compares a participant's reading of a script with a reference
reading, finds the time ranges where delivery differs, shows the measured
evidence, and turns it into practice. This document describes what is built;
the specification it follows is [system_design.md](system_design.md).

## Components

```
web/                      React 18 + TS + Vite — Vercel
   │  HTTPS JSON (x-session-id)          presigned PUT/GET
   ▼                                     ▼
API Gateway HTTP API ──► Lambda  speakquest-<env>-api          S3 speakquest-<env>-<hex>
   (10 rps, burst 20)       │ StartExecution                    uploads/ work/ transcripts/
                            ▼                                   results/ references/
   Step Functions speakquest-<env>-analysis
     Normalize ──► Lambda worker (container: ffmpeg, numpy, scipy, parselmouth)
     StartTranscribe / Wait 5 s / GetTranscriptionJob (≤ 40 polls)
     Analyze ───► Lambda worker
     Explain ───► Lambda explain ──► Amazon Bedrock (Converse)   (failure tolerated)
     Persist ───► Lambda persist ──► S3 result.json + DynamoDB
     MarkFailed ► Lambda persist (status FAILED, code, stage)
   DynamoDB speakquest-<env> (single table, on-demand, TTL)
```

Every box above is Terraform (`infra/`), including the Vercel project.

## Code layout

| Path | What |
|---|---|
| `services/worker/speakquest/` | Analysis engine, contracts and shared adapters (no AWS required) |
| `services/api/speakquest_api/` | HTTP handlers, workflow steps, repository, Lambda entry points, local runtime, seeding |
| `services/explain/speakquest_explain/` | Bedrock coaching, grounding validator, template fallback |
| `eval/speakquest_eval/` | Synthetic labelled dataset generator, metrics, evaluation harness |
| `rubric/v1.yaml` | Every threshold, severity band and penalty |
| `data/scripts/challenges.yaml` | The eight scripts, cues and dev/held-out split |
| `data/annotations/` | Labelled flaw intervals and word boundaries for 56 clips |
| `contracts/schema.json` | JSON Schema generated from the Pydantic contracts |
| `web/` | Frontend (On Air design system) |
| `infra/` | Terraform root + 9 modules; `infra/frontend-demo/` deploys the demo build alone |

## The analysis pipeline (`services/worker/speakquest`)

| Module | Step |
|---|---|
| `normalize.py` | ffprobe → ffmpeg to 16 kHz mono 16-bit WAV; size, duration, silence and level checks with stable error codes |
| `timing.py` | `Aligner` protocol. Amazon Transcribe output parsing (primary), a Transcribe-job adapter (seeding), Vosk and faster-whisper (local), and a words.json replay. All yield the same `Transcript` |
| `tokens.py` | Lowercase, strip punctuation, spell out numbers (cardinals, years, ordinals, decimals, %, currency); phrase splitting; syllable estimate |
| `diff.py` | Needleman–Wunsch alignment of spoken tokens to script tokens (match/sub/ins/del), insertion classification (filler/repeat/insert), coverage |
| `features.py` | Energy-envelope pauses, loudness relative to the speaker's mean, Parselmouth F0 in semitones from the speaker's median, phrase pitch SD, untranscribed vocalisations, local rate vs the reference over the same script words |
| `findings.py` | RUSH, DRAG, HESITATE, MONO, FADE, SKIP, FILLER with evidence, severity and script span |
| `rubric.py` | Loads/validates the versioned rubric; deterministic 100-minus-penalties scoring |
| `pipeline.py` | Pure function: (audio, transcript, script, reference, rubric) → `AnalysisResult` |

The pipeline never sees vendor JSON and never calls a model. Identical inputs
and rubric produce byte-identical results (tested).

## Workflow and data flow

The API writes `ANALYSIS#<id>/META` (QUEUED) and a `TAKE#` item, then starts
an execution named after the analysis id (idempotent). Each step records its
stage. Step state is the execution input plus earlier results:

| Step | Reads | Writes |
|---|---|---|
| Normalize | `uploads/<sid>/<id>.<ext>` | `work/<id>/normalized.wav`, stage TRANSCRIBE |
| Transcribe states | `work/…/normalized.wav` | `transcripts/<id>.json` |
| Analyze | transcript, normalized WAV, `references/<cid>/features.json`, challenge item | `results/<id>/analysis.json` |
| Explain | analysis.json | `results/<id>/coaching.json` |
| Persist | analysis + coaching | `results/<id>/result.json`; analysis DONE + summary; take scores; profile air time + stamps (idempotent) |
| MarkFailed | Step Functions `{Error, Cause}` | analysis FAILED with code, message, stage, retryable |

`GET /analyses/{id}/result` returns presigned GETs for `result.json`, the
original upload and the reference audio.

## Local runtime

`speakquest-local` runs the same handlers and steps with `LocalStorage`
(a directory with HMAC-signed, expiring URLs checked like S3 presigned URLs),
`SqliteRepository` (the same single-table items) and `LocalWorkflow` (the
state machine's order and failure semantics, with Vosk in place of the
Transcribe states). See [OPERATIONS.md](OPERATIONS.md).

## Grounded coaching (`services/explain`)

The model receives only the findings JSON and the script. Its output must
parse as `{"items":[{finding_id, headline, why, drill}]}`, cover each finding
exactly once, contain no number absent from that finding's evidence (or the
script), no timestamps, no spelled-out derived comparisons, and no advice
that contradicts the finding's direction. One corrective retry, then template
text. Scores, findings, evidence and times never come from the model.

## Contracts

`speakquest/contracts.py` is the source of truth. `scripts/export_schemas.py`
writes `contracts/schema.json`; a test fails if it is stale; the web app's Zod
schemas are checked against it and against every fixture.

## Security

- One IAM role per function, scoped to exact ARNs and key prefixes (the API can
  sign PUTs only under `uploads/`); Step Functions may invoke only its three
  functions and Transcribe jobs named `speakquest-<env>-*`.
- Bucket: public access blocked, TLS-only policy, SSE-S3, CORS for the
  configured origins only; presigned PUTs sign Content-Type *and*
  Content-Length.
- Anonymous sessions are UUIDs; every read is scoped to the caller's session
  (another browser's analysis is a 404).
- No credentials in the frontend or the repository; Lambda config is non-secret
  environment variables; the Vercel token stays in the operator's shell.
- Recordings expire after 7 days; `make down` deletes everything.
