# Execution log

Autonomous build of SpeakQuest from `docs/system_design.md`, 2026-10-15
(times are local, single session). Newest last.

## Phase 0 — Reconnaissance

- Repository: only `system_design.md` and `.env`; not a Git repository. Initialised
  `main`, moved the design to `docs/`.
- Tools present: Python 3.14 (3.12 installed through uv), Node 22, npm 9, Docker 29,
  ffmpeg 8, AWS CLI 2.31, Vercel CLI (logged in), Google Chrome 143. Terraform
  missing → installed 1.16.6 to `~/.local/bin` after verifying the SHA-256.
- Machine: 8 cores, ~1 GB free RAM of 7.7 GB, 14 GB free disk, no GPU.
- `.env` holds `AWSKEY1`/`AWSKEY2` (access key id / secret). Caller: IAM user with
  AdministratorAccess in us-east-1.
- **Blocker found:** an AWS Organizations SCP explicitly denies Lambda, DynamoDB,
  Step Functions, ECR, Transcribe, API Gateway, ECS, Polly, SNS and
  `tag:GetResources` in all probed regions (later also S3 CreateBucket). Allowed:
  IAM, CloudWatch Logs, Budgets, Cost Explorer, Bedrock.
- Bedrock: `us.anthropic.claude-haiku-4-5` answered once, then all Anthropic models
  returned "use case details have not been submitted"; Amazon Nova models work.
- Decision: build the full AWS design (tested against moto), plus a faithful local
  runtime that runs the same handlers and steps, with local word timing.

## Phase 1–2 — Foundation and analysis engine

- Packaging (uv.lock), contracts + JSON Schema export with drift test, error codes,
  JSON logs, rubric v1 + deterministic scorer, token normalisation, Needleman–Wunsch
  diff, ffmpeg normalisation with all audio failure modes, aligner interface
  (Transcribe parser primary), features, findings, pipeline.
- Synthetic-signal tests inject each flaw with a known magnitude: all seven rules,
  combinations, determinism, script mismatch, no speech.
- Local aligners measured: Whisper base.en dropped an inserted filler and smeared
  timing; Vosk ran in ~1 s / 200 MB with tight boundaries → Vosk default.

## Phase 5 (evaluation, done early) — dataset and tuning

- Synthetic dataset with Piper TTS; v1 (chunked) distorted flaws and espeak read
  1889 as a cardinal (also found a real tokenizer bug: `1889,`).
- v2 exposes VITS phoneme durations from the ONNX graph → exact word labels,
  in-context flaws; v3 calibrates flaw magnitudes to achieved values.
- Dev tuning: P/R/FP-per-min 0.39/0.73/8.47 → 0.74/0.77/0.61 (per-speaker pitch
  normalisation, pause handling in rate, hysteresis, filler renderings).
- Held-out, evaluated once: P 0.67, R 0.78, **FP 3.51/min (target < 1 missed)**.
- Aligner comparison: Vosk 25 ms median boundary error vs Whisper 142.5 ms.

## Phase 3 — Frontend (parallel worktree, merged by rebase)

- 17 commits: Vite/React/TS strict, Zod contracts checked against the JSON Schema,
  HTTP + isolated demo adapters, recording with count-in/meter/tally/R, upload with
  progress and retry, processing/failure/playback, kinetic transcript, hatched
  waveform, director's notes, `/me` air time, levels and stamps, accessibility,
  Chrome smoke test at 1280/375 px in both themes.

## Phase 4 — API, workflow, coaching

- Storage (S3 + signed local), repository (DynamoDB + SQLite, one contract suite),
  six endpoints with session scoping, limits and idempotency, workflow steps,
  Lambda entry points (zip ones never import numpy), local runner/server, seeding.
- Explain: validator, templates, Bedrock Converse with one retry; live Bedrock test
  passes with Nova 2 Lite. Live output exposed two validator gaps (wrong direction,
  "three times lower") → both now rejected.

## Phase 6 — Infrastructure

- Terraform root + 9 modules; `fmt`/`validate` pass; `plan` against the real account
  succeeds (47 resources, all taggable ones tagged).
- Worker image builds (static ffmpeg pinned by SHA-256, deps by hash) and runs as a
  Lambda under the Runtime Interface Emulator against moto (normalize + analyze).
- Disposable real apply: S3 bucket creation denied by SCP; created 4 log groups +
  1 IAM role in workspace `sqtest`, confirmed 3-day retention and tags, destroyed,
  `verify-zero.sh` clean for all permitted checks (exit 3: 7 checks SCP-blocked).
- Makefile (`up/deploy/seed/down` …), CI workflow, verify-zero, purge script.

## Phase 7 — End-to-end verification

- HTTP E2E (pytest) against the local server with real audio and Vosk.
- **Browser E2E** (`make e2e`): headless Chrome with a fake microphone records via
  MediaRecorder, uploads, analyses and plays back. It found a real bug (local CORS
  preflight lacked PUT), fixed. Passing for two clips; flaw codes match labels.
- Vercel demo deployed through Terraform (`infra/frontend-demo`); found and fixed a
  path-prefix bug in the frontend module. https://speakquest-demo.vercel.app serves
  the app, deep links, fixtures and audio.

## Phase 8 — Release readiness

- Docs: README, ARCHITECTURE, OPERATIONS, EVALUATION, DECISIONS, this log,
  FINAL_REPORT.
- Fresh clone: `make setup-py`, `make test-fast`, web tests/build and contract check
  pass; full pytest 202 passed / 8 skipped (models, dataset, live AWS).
- Secrets sweep of tracked files and full history: no keys, tokens, account ids,
  state or recordings.

## Next action

Run the AWS deployment (`make up`) on an account without the SCP restrictions, then
compare Amazon Transcribe boundaries with the dataset labels (`speakquest-eval run
--aligner` with a Transcribe-backed aligner) and re-check the held-out false
positive rate on human recordings.
