# Engineering decisions

Decisions taken while implementing [system_design.md](system_design.md), with
the evidence behind them. Deviations from the design are marked **Deviation**.

## Account constraints found on day one

Probed 2026-10-15 with the project's credentials (IAM user with
AdministratorAccess, us-east-1). An AWS Organizations service control policy
**explicitly denies**, in every region tried: Lambda, DynamoDB, Step
Functions, ECR, Transcribe, API Gateway, ECS, Polly, SNS and
`tag:GetResources`, and also **S3 CreateBucket** (found when a disposable
apply was attempted). IAM, CloudWatch Logs, Budgets, Cost Explorer and Bedrock
are allowed. Everything below that says "local stand-in" exists because of
this; the AWS code paths are still implemented and tested against moto.

## Timing: Transcribe primary, local aligners behind the same interface

- The Analyze step only parses Transcribe JSON (`parse_transcribe_json`); the
  job runs as Step Functions states, as designed.
- `Aligner` protocol implementations: Transcribe (job adapter used for
  seeding), Vosk, faster-whisper, words.json replay.
- **Local default: Vosk.** Measured on every labelled word edge: 25 ms median
  (Vosk) vs 142.5 ms (Whisper base.en); Whisper also dropped fillers. See
  [EVALUATION.md](EVALUATION.md#aligner-comparison-the-designs-runtime-test).
- **WhisperX was not run**: it needs PyTorch and wav2vec2 weights; this machine
  had ~1 GB of free RAM and no GPU. Not claimed as benchmarked.

## Worker runtime: Lambda container only

The design's runtime test (median boundary error < 40 ms → keep Lambda) passed
with the local aligner, so the Fargate/WhisperX fallback was **not built**.
`var.worker_runtime` accepts only `"lambda"` and its validation message says
why. **Deviation** (fallback module omitted).

## Signal processing without librosa

numpy/scipy + Parselmouth cover RMS envelopes and F0. librosa (and numba)
would add ~150 MB and cold-start time for nothing used. **Deviation** (design
lists librosa in the image).

## Speaker-relative measurement

- **Rate:** reference time / take time for the *same script words*, windows
  never cross a skipped word, divided by the speaker's global ratio (median of
  windows) clamped to [0.85, 1.18]. A take rushed *throughout* beyond the rule
  threshold gets one whole-take finding instead of disappearing into the
  normalisation.
- **Pauses:** measured from the RMS envelope between word midpoints, because
  recognisers stretch words over silence. Only pauses ≥ 250 ms are excluded
  from speaking time; shorter silences stretch with slow speech and removing
  them hid dragging (dev evidence).
- **Pitch variability:** "per speaker" as the design's feature table says:
  phrase SD ratio divided by the speaker's median ratio (floor 0.30). Without
  it a naturally flatter voice was flagged MONO on every phrase.

## Script diff

Integer-cost Needleman–Wunsch. Fillers are priced so they never substitute
for a script word. Substitutions are treated as matched positions for prosody
and not flagged (recogniser noise); coverage counts only exact and near
matches, so reading a different text is rejected (`SCRIPT_MISMATCH`).
Recogniser renderings of hesitation sounds ("oh", "ah", …) count as fillers.
Untranscribed voiced bursts fenced by silence become FILLER findings.

## Coaching model: Amazon Nova 2 Lite via Converse

Anthropic models on Bedrock answered once, then returned *"Model use case
details have not been submitted for this account"*. Submitting that form is an
account-level declaration for the owner, so it was not done. Nova 2 Lite,
Nova Lite and Nova Pro all passed the validator on the fixtures; Nova 2 Lite
wrote the most accurate notes (Nova Lite and Nova Pro both told a speaker who
dragged to "slow down"). The adapter uses the Converse API, so `var.bedrock_model_id` can name
any text model. **Deviation** from the implied Claude default.

Validator additions beyond the design (all prompted by real model output):
direction contradictions (DRAG → "slow down") and spelled-out derived
comparisons ("three times lower") are rejected.

## Data model

- Challenges live under `pk = CATALOGUE`, `sk = CHALLENGE#<id>` so listing is
  one Query. **Deviation** from `CHALLENGE#<id> / META`.
- One API Lambda routes all six endpoints (one role, least privilege); the
  worker image serves Normalize and Analyze (`{"step": …}`); Persist and
  MarkFailed share the persist function.
- Presigned PUTs sign Content-Length as well as Content-Type ("size locked").
- `GET /analyses/{id}/result` also returns `audioUrl` and `referenceAudioUrl`
  so the playback screen can draw the waveform. **Addition.**

## Budget scope

The budget is account-wide: a project-tag filter needs the cost-allocation tag
activated in Billing (up to 24 h) and an inactive filter silently reports $0.

## Synthetic evaluation data

Piper TTS with exposed phoneme durations gives exact word-level labels and
deterministic audio. Limitations are listed in
[EVALUATION.md](EVALUATION.md#limitations).

## Frontend on Vercel without the backend

The AWS stack cannot be created here, so `infra/frontend-demo/` deploys the
web app built in demo mode (clearly bannered fixtures) with the same Terraform
module the full stack uses.
