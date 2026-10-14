# SpeakQuest — final report

Date: 2026-10-15. Branch `main`, local only (the repository has no remote).

## 1. Executive summary

SpeakQuest is built end to end as specified, and works end to end **locally**.
A take recorded in a real browser runs through presigned upload, ffmpeg
normalisation, word timing, script diff, prosody features, seven flaw rules,
deterministic scoring, grounded Bedrock coaching, persistence, air time and
stamps, and plays back as the kinetic transcript with a hatched waveform. This
was verified in headless Chrome with a fake microphone (`make e2e`).

The AWS backend is fully written in Terraform and passes `terraform plan` (47
resources) against the target account, but **could not be deployed**: an AWS
Organizations service control policy on the provided account denies Lambda,
DynamoDB, Step Functions, ECR, Transcribe, API Gateway and S3 bucket creation.
The cloud code paths are tested against moto, and the worker container image
was run as a Lambda in the Runtime Interface Emulator. Bedrock coaching was
verified live. The frontend is deployed on Vercel through Terraform in demo
mode: **https://speakquest-demo.vercel.app**.

On the synthetic evaluation set, held-out detection reached precision 0.67 and
recall 0.78, but **3.51 false positives per minute on clean pairs, missing the
design's < 1/min target** (dev: 0.61/min).

## 2. Features

| Area | Feature | Status |
|---|---|---|
| Frontend | React 18 + TS + Vite, Tailwind tokens, On Air design (Paper/Booth, Archivo/Newsreader/Plex Mono, editorial grid, cue cards, stamps) | implemented, tested (unit + Chrome smoke 12 views), deployed (demo) |
| Frontend | Routes `/`, `/c/:id`, `/take/:analysisId`, `/me` | implemented, tested |
| Frontend | Recording: format detection, 3-2-1 count-in, live meter, tally button driven by level, script visible, `R` re-take | implemented, tested in Chrome with a fake microphone |
| Frontend | Upload progress + retry, analysis polling (1.5 s), loading/empty/error states | implemented, tested |
| Frontend | Kinetic transcript (wdth/wght/baseline/pause space/flaw patterns/skips/fillers), reference line, plain-text mode, SR text | implemented, tested |
| Frontend | WaveSurfer v7 waveform of real audio with hatched finding regions; Space/←/→ | implemented, tested (renders the uploaded recording in E2E) |
| Frontend | Zod contracts checked against the generated JSON Schema | implemented, tested |
| API | `GET /challenges`, `POST /uploads`, `POST /analyses`, `GET /analyses/{id}`, `GET /analyses/{id}/result`, `GET /me/progress` | implemented, tested (moto + local HTTP + browser) — AWS deploy **blocked** |
| API | Anonymous UUID sessions, session-scoped reads, validation, 10 MB cap, size+type-locked presigned PUT, 3 active takes/session, idempotent start, error envelope | implemented, tested |
| API | Stage throttling 10 rps / burst 20, CORS | implemented in Terraform (planned), local CORS tested — deploy **blocked** |
| Pipeline | ffmpeg normalisation; missing/empty/corrupt/unsupported/silent/quiet/short/long/large handling | implemented, tested (webm, ogg, m4a, mp3, wav) |
| Pipeline | Word timing: Amazon Transcribe (primary, parser + job adapter), Vosk, faster-whisper behind one interface | implemented, tested; Transcribe parsing tested on fixture JSON, live Transcribe **blocked** |
| Pipeline | Token normalisation, Needleman–Wunsch alignment, features, RUSH/DRAG/HESITATE/MONO/FADE/SKIP/FILLER, versioned rubric, deterministic scores | implemented, tested |
| Workflow | Step Functions definition (normalize, transcribe poll ≤ 40, analyze, explain, persist, MarkFailed), retries, timeouts | implemented, statically tested; deploy **blocked** |
| Workflow | Local runner with identical step order and failure semantics | implemented, tested |
| Coaching | Bedrock Converse adapter, validator (ids, numbers, timestamps, direction, spelled comparisons), one retry, template fallback | implemented, tested; **live Bedrock verified** (Nova 2 Lite) |
| Persistence | Result JSON, DynamoDB single table (+ SQLite local), take history, air time, five levels, six stamps | implemented, tested (moto + SQLite + E2E) |
| Evaluation | Labelled synthetic dataset (56 clips), IoU matching, per-class P/R, FP/min, boundary error, dev/held-out split | implemented, run, reported |
| Infra | Terraform modules storage, data, registry, api, worker, workflow, ai, observability, frontend | implemented, `fmt`/`validate`/`plan` pass; AWS apply **blocked**; Vercel module **deployed** |
| Infra | Worker image (Lambda Python 3.12, static ffmpeg) | implemented, built, run in Lambda emulator |
| Ops | `make up/deploy/seed/down`, `verify-zero.sh`, `purge-transcribe.sh` | implemented; teardown verified on real log groups + IAM role; `up` **blocked** at ECR |
| Ops | CI workflow, budget + alarms, 3-day log retention, tags | implemented (budget/alarms planned, not applied) |
| Not built | Fargate/WhisperX fallback runtime | not implemented (runtime test kept Lambda; see DECISIONS) |

## 3. Architecture and key decisions

See [ARCHITECTURE.md](ARCHITECTURE.md) and [DECISIONS.md](DECISIONS.md). In short:
one pure analysis pipeline shared by Lambda and local runtimes; every external
dependency behind an adapter (storage, repository, workflow starter, aligner,
model); speaker-relative features with per-speaker pitch normalisation; the
model only writes text and is validated; Nova 2 Lite as default coaching model
because Anthropic models are gated on this account; Vosk as the local timing
source because it measured 25 ms vs Whisper's 142.5 ms median boundary error.

## 4. Commands

```bash
make setup models dataset   # dependencies, models, synthetic data
make check                  # all lint, type checks, tests, build, terraform validate
make eval                   # detection metrics → eval/reports/
make local / make web       # run the system locally
make e2e                    # real Chrome + fake mic through the local system
make smoke-worker           # worker image as a Lambda against moto
make plan / up / deploy / seed / down / verify-zero
```

## 5. Test results

**Passed (run in this session):**

| Suite | Result |
|---|---|
| `make check` (ruff, format, mypy, contracts, pytest, ESLint, tsc, Vitest, build, terraform) | exit 0 |
| pytest (models + dataset present) | 205 passed, 5 skipped (live AWS opt-ins) |
| pytest in a fresh clone (no models/dataset) | 202 passed, 8 skipped (models, dataset, live AWS) |
| Vitest | 89 passed (5 files) |
| Web smoke (Chrome, demo build, 4 routes × 1280/375/paper) | 12/12 |
| Browser E2E `make e2e` (fake mic → local API → workflow → playback) | PASS for `deadline__flawed-2` (SKIP, HESITATE) and `deadline__flawed-4` (FILLER, FADE; plus a DRAG false positive) |
| Worker image in Lambda RIE against moto | PASS (normalize 1.1 s, analyze 0.2 s) |
| Live Bedrock coaching test (`SPEAKQUEST_LIVE_AWS=1`) | PASS (Nova 2 Lite) |
| `terraform validate`, `fmt -check`; `terraform plan` vs real account | pass; 47 to add |
| Real AWS apply/destroy of permitted resources (4 log groups, 1 IAM role) + verify-zero | created, tagged, 3-day retention confirmed, destroyed; verify-zero exit 3 (clean, 7 checks SCP-blocked) |
| Vercel Terraform apply + HTTP checks + Chrome render | pass |

**Failed / below target:** held-out false-positive rate 3.51/min vs < 1/min target.

**Not executed:** live S3 checks (`tests/test_live_s3.py`; bucket creation
denied), any Lambda/Step Functions/DynamoDB/API Gateway/Transcribe call against
AWS, `make up` beyond its first step, CI on GitHub (nothing pushed), microphone
recording in a non-headless browser with a human voice.

Evaluation (Vosk, rubric 1.0.0; details in [EVALUATION.md](EVALUATION.md)):

| Split | Precision | Recall | Mean IoU | FP/min | Boundary median |
|---|---:|---:|---:|---:|---:|
| dev | 0.74 | 0.77 | 0.89 | 0.61 | 25 ms |
| held-out | 0.67 | 0.78 | 0.93 | 3.51 | 24 ms |

## 6. AWS deployment status

**Not deployed. No AWS endpoint exists.** `make up` fails at its first step
(ECR `CreateRepository` is denied by the SCP), and a disposable `apply` of the
storage module was refused at `s3:CreateBucket` with *"explicit deny in a
service control policy"*. Verified working on the account: IAM role creation,
CloudWatch log groups, Bedrock (Nova models), Budgets/Cost Explorer reads.
Nothing created during testing remains (destroyed and verified).

## 7. Vercel deployment

Deployed through Terraform (`infra/frontend-demo`, state local and gitignored):
**https://speakquest-demo.vercel.app** — demo build with a persistent banner
stating that results are pre-analysed synthetic TTS takes and recordings are
not analysed. Remove with
`VERCEL_API_TOKEN=… terraform -chdir=infra/frontend-demo destroy`.

## 8. Cost and teardown

Current spend from this work: Bedrock tokens for coaching tests (a few dozen
small requests) and nothing else on AWS; Vercel Hobby is free. Cost drivers once
deployed and the teardown procedure are in [OPERATIONS.md](OPERATIONS.md):
`make down` then `scripts/verify-zero.sh` (exit 0 only when every check ran and
found nothing). Budgets alert at $5 and $15; they do not cap spending.

## 9. Known bugs, limitations and blockers

- **Blocker:** SCP denies the core AWS services (above). Needs an account or OU
  without those denies.
- **Blocker:** Anthropic models on Bedrock require the account owner's use-case
  form; Nova 2 Lite is used instead.
- Held-out FP rate misses target; RUSH recall is low (0.20 dev / 0.33 held-out):
  natural pacing differences between voices and recogniser errors in fast speech.
- Evaluation is synthetic (three TTS voices, clean audio, manipulated flaws);
  Amazon Transcribe timing and WhisperX were not measured.
- `verify-zero.sh` cannot prove zero on this account (exit 3) because the tag API
  and several list APIs are denied.
- The Vercel production domain is derived from the project name for CORS; if the
  name is taken, set `allowed_origins` to the assigned domain.
- Headless E2E uses Chrome's fake capture device; a human voice through a real
  microphone has not been tested here.

## 10. Git

- Branch `main`, **74 local commits** including this report. A parallel
  worktree branch (`feat/web`, 17 commits) was rebased onto `main` and deleted.
- The repository has **no remote configured**; no `git push` or any other
  remote-writing command was run. Working tree clean after the final commit.

## 11. Next most valuable tasks

1. Deploy to an account without the SCP: `make up`, then run the live S3 checks
   and a browser take against the real API.
2. Measure Amazon Transcribe boundaries on the dataset (wire
   `TranscribeJobAligner` into `speakquest-eval`) and redo the runtime decision.
3. Collect a small set of human recordings (several speakers and rooms) with
   flaw labels; re-tune on dev and re-check the FP rate.
4. Reduce RUSH misses and SKIP false positives in fast speech (e.g. use the
   aligner's confidence to suppress deletions inside rushed spans).
5. Submit the Bedrock Anthropic use-case form if a Claude model is preferred and
   compare coaching quality.
