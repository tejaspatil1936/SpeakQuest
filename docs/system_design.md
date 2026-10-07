# SpeakQuest — System Design

**Multimodal AI Hackathon 2026 · Track C**
Version 1.0 · October 2026

> Compare a participant's speech with a reference, find the exact time ranges where delivery differs, show the measured evidence, and turn it into practice.

---

## 0. Decisions at a glance

| Area | Decision | Why |
|---|---|---|
| Frontend hosting | **Vercel** (React + TypeScript + Vite) | Fast deploys, preview URLs, free tier is enough for a hackathon |
| Infrastructure | **Terraform, 100% of resources** (AWS **and** the Vercel project) | One `apply` builds it, one `destroy` removes it |
| Cost target | **$0 after `make down`** | No always-on resources, no NAT, no KMS/Secrets Manager, every resource tagged and verifiable |
| Analysis runtime | **Lambda container image** (default) · Fargate (fallback, behind a flag) | No idle cost, no VPC, no multi-GB image pull per job |
| Word timing | **Amazon Transcribe word timestamps** on both recordings, then **text diff** against the script | Forced alignment breaks exactly where flaws happen (skips, repeats, fillers) |
| Scoring | **Deterministic Python rules, versioned** | Reproducible; the LLM never makes a number |
| Explanations | **Amazon Bedrock**, grounded on findings JSON, validated | Plain-language coaching that can't invent timestamps |
| Design | **Typography-led "On Air" system** — the transcript itself is the chart | Distinct, data-truthful, no generic AI look |

---

## 1. Architecture

```
                         ┌──────────────────────────────┐
  Browser  ─────────────▶│  Vercel  (React/TS/Vite)     │
     │                   └──────────────────────────────┘
     │ HTTPS (JSON)
     ▼
┌───────────────────────┐      presigned PUT      ┌──────────────────────┐
│ API Gateway (HTTP API)│ ◀──── upload URL ─────  │  S3  speakquest-audio│◀── browser uploads audio directly
└──────────┬────────────┘                         └──────────┬───────────┘
           │                                                 │
           ▼                                                 │
┌───────────────────────┐   StartExecution   ┌──────────────▼───────────────────────────────┐
│ Lambda  api-*         │ ─────────────────▶ │ Step Functions  analysis-workflow            │
│ (uploads, analyses,   │                    │                                              │
│  results, progress)   │                    │ 1 Normalize  → Lambda worker (ffmpeg)        │
└──────────┬────────────┘                    │ 2 Transcribe → aws-sdk:transcribe (poll)     │
           │                                 │ 3 Analyze    → Lambda worker (Python)        │
           ▼                                 │ 4 Explain    → Lambda explain → Bedrock      │
┌───────────────────────┐ ◀──── status ───── │ 5 Persist    → DynamoDB + S3 results         │
│ DynamoDB speakquest   │                    │   Catch      → mark FAILED + reason          │
└───────────────────────┘                    └──────────────────────────────────────────────┘

Ops: IAM (least privilege) · CloudWatch log groups (Terraform-owned, 3-day retention) · AWS Budgets alert
```

### Service list (final)

| Service | Role | Idle cost |
|---|---|---|
| Vercel | Hosts the frontend | $0 (Hobby) |
| API Gateway HTTP API | Public endpoints | $0 |
| Lambda (zip) | API handlers, explain step | $0 |
| Lambda (container) + ECR | Audio analysis worker | ECR storage only while it exists |
| Step Functions (Standard) | Orchestrates one analysis | $0 |
| S3 | Audio, transcripts, result JSON | Pennies while it exists |
| DynamoDB (on-demand) | Jobs, scores, XP, badges | $0 |
| Amazon Transcribe | Word-level timestamps | Pay per audio minute |
| Amazon Bedrock | Coaching text | Pay per token |
| CloudWatch Logs | Debugging | Pennies while it exists |
| IAM, AWS Budgets | Permissions, spend alerts | $0 |

**Removed from the original plan:** Amplify (replaced by Vercel), and ECS/Fargate as the default runtime (kept only as a fallback module).

---

## 2. Request flow — one session

1. **Pick a challenge.** `GET /challenges` returns the cue card, the script and the reference audio URL. Reference recordings are pre-analysed once when the challenge is seeded.
2. **Record.** The browser's `MediaRecorder` produces webm/opus (Chrome, Firefox) or mp4/aac (Safari).
3. **Get an upload URL.** `POST /uploads` → Lambda returns an S3 presigned PUT (5-minute expiry, content-type and size locked).
4. **Upload.** The browser PUTs the file straight to S3. Audio never passes through Lambda.
5. **Start the analysis.** `POST /analyses` → Lambda writes `JOB#… status=QUEUED` to DynamoDB and starts the Step Functions execution.
6. **Workflow** (section 4) runs: normalize → transcribe → analyze → explain → persist.
7. **Poll.** The frontend polls `GET /analyses/{id}` every 1.5 s until it reports `DONE` or `FAILED`.
8. **Show results.** `GET /analyses/{id}/result` returns a presigned GET for the result JSON. The UI renders the kinetic transcript, the waveform, the findings and the score.
9. **Progress.** XP, badges and the takes history are updated in the same Persist step.

---

## 3. API

Base URL: the HTTP API invoke URL, exposed to Vercel as `VITE_API_URL`.

| Method | Path | Does |
|---|---|---|
| `GET` | `/challenges` | List challenges (script, difficulty, target flaw types) |
| `POST` | `/uploads` | `{challengeId, contentType, bytes}` → `{uploadUrl, key}` |
| `POST` | `/analyses` | `{challengeId, key}` → `{analysisId}` |
| `GET` | `/analyses/{id}` | `{status, stage, summary?, error?}` |
| `GET` | `/analyses/{id}/result` | `{resultUrl}` (presigned GET, 10 min) |
| `GET` | `/me/progress` | `{xp, level, badges[], takes[]}` |

**Identity:** anonymous. The browser creates a UUID on first visit and sends it in the `x-session-id` header. There are no accounts and no passwords, which leaves nothing to tear down in Cognito.
**Abuse limits:** HTTP API stage throttling (10 rps, burst 20), uploads capped at 10 MB and 3 minutes, and validation in the `POST /uploads` Lambda.
**CORS:** allow-origins = the Vercel production domain + `http://localhost:5173`. Preview deploys use a `VITE_API_URL` that points at the same API, and their origins are added through a Terraform variable when needed. The same origins go into the S3 bucket CORS rule, which is required for presigned PUTs from the browser.

---

## 4. Analysis workflow (Step Functions)

| State | Type | Detail |
|---|---|---|
| `Normalize` | Lambda (worker image) | ffmpeg → 16 kHz mono WAV in `work/`. The original is kept. Duration and loudness sanity checks run here. |
| `StartTranscribe` | `aws-sdk:transcribe:startTranscriptionJob` | Output goes to our bucket (`transcripts/`). Language is fixed per challenge. |
| `WaitTranscribe` / `CheckTranscribe` | Wait 5 s + `getTranscriptionJob` loop | Maximum 40 loops, then fail with `TRANSCRIBE_TIMEOUT`. |
| `Analyze` | Lambda (worker image) | Diff against the script, feature extraction, rubric scoring → `findings.json`. |
| `Explain` | Lambda (zip) → Bedrock | Grounded coaching text, validated (section 6). On failure, falls back to template text. |
| `Persist` | Lambda (zip) | Result JSON → S3. Summary, XP and badges → DynamoDB. |
| `Catch` (all states) | Lambda (zip) | `status=FAILED`, `error.code`, `error.stage` → DynamoDB. |

### Worker runtime

**Default: Lambda container image.**
- Contents: Python 3.12, numpy, scipy, librosa, praat-parselmouth, pydantic, plus a static ffmpeg binary. Roughly 600–800 MB, with no PyTorch.
- Settings: memory 3008 MB, timeout 300 s, ephemeral storage 2 GB.
- Why it's the default: no VPC, no idle cost, and the first-request cold start is a few seconds, which suits a live demo.

**Fallback: Fargate** (`var.worker_runtime = "fargate"`).
- When to use it: only if testing shows Transcribe timestamps are too coarse and WhisperX alignment is needed.
- Image: the WhisperX image (PyTorch + wav2vec2 weights baked in).
- Network: its own VPC with public subnets and `assign_public_ip = true`. **There is no NAT Gateway**, which would cost about $32/month even when idle.
- Running mode: for the demo, run it as a 1-task service so the image pull doesn't land on the critical path.

**Day-1 test that decides the runtime:** run Transcribe and WhisperX on 5 labelled clips and compare word boundaries.
- Median error under 40 ms → keep Lambda.
- Otherwise → switch the flag to Fargate.

---

## 5. Speech analysis pipeline

### 5.1 Word timing and script diff
1. Both the reference and the participant audio get Transcribe word timestamps. The reference is done once, at seed time.
2. Normalize the tokens: lowercase, strip punctuation, and spell out numbers in every script, because aligners cannot time digits.
3. Align the participant's word sequence to the script with Needleman–Wunsch (difflib is fine for a first pass).
   - **Insertions** → fillers or repetitions.
   - **Deletions** → skipped words.
   - **Matches** → used for prosody comparison.
4. Check early: some ASR models clean up "um/uh" and repetitions. Confirm that the flawed samples keep them. If they don't, add an energy-based disfluency detector on the gaps.

### 5.2 Features (interpretable only)

| Feature | Tool | Normalization |
|---|---|---|
| Word duration, local speech rate (syllables/s, 3-word window) | timestamps | Divide by the speaker's global rate ratio vs. the reference |
| Pause length and position | timestamps + RMS | Absolute ms |
| Pitch contour (F0) | parselmouth | **Semitones relative to the speaker's own median** |
| Pitch variability (st SD per phrase) | parselmouth | Per speaker |
| Loudness | RMS → dB | **Relative to the speaker's own mean** |

MFCCs and spectral features are **not used for scoring**. They mostly encode who the speaker is, so every comparison between different people would light up.

### 5.3 Flaw taxonomy (v1 rubric)

| Code | Flaw | Rule (initial thresholds, tune on dev set) |
|---|---|---|
| `RUSH` | Rushed section | Local rate > 1.35× reference over ≥ 3 matched words |
| `DRAG` | Dragged section | Local rate < 0.7× reference over ≥ 3 matched words |
| `HESITATE` | Long hesitation | Pause > 600 ms where the reference has < 250 ms |
| `MONO` | Monotone | Phrase pitch SD < 50% of the reference phrase |
| `FADE` | Trailing off | Last 2 words of a phrase > 6 dB below the speaker's mean |
| `SKIP` | Skipped words | Deletion in the script diff |
| `FILLER` | Filler or repeat | Insertion in the script diff |

Each finding has the following shape:

```json
{
  "id": "f3",
  "code": "HESITATE",
  "start": 12.41, "end": 13.38,
  "words": ["before", "the", "deadline"],
  "evidence": {"pause_ms": 970, "reference_pause_ms": 140},
  "severity": 2,
  "rubric_version": "1.0.0"
}
```

### 5.4 Scoring
- Five dimensions, each 0–100: **Pace, Pauses, Pitch, Volume, Accuracy** (skips + fillers).
- Each dimension's score = 100 − the sum of severity-weighted penalties, floored at 0. The weights live in `rubric/v1.yaml`.
- Every result stores `rubric_version`, `worker_image_digest`, `transcribe_language` and the Bedrock `model_id`. The same input always gives the same score.

### 5.5 Evaluation (what we show the judges)
- **Dataset:** 6–10 scripts × (1 clean reference + 1 second clean reader + 3–5 flawed variants), with every flaw interval labelled in `data/annotations/*.json`.
- **Detection:** per flaw type, precision and recall, where a match means timestamp IoU ≥ 0.5.
- **False-positive rate:** flags per minute on the clean-vs-clean pairs. Target < 1 per minute.
- **Split:** tune thresholds on the dev scripts and report on the held-out scripts only.
- **Limitations section:** state the speaker count, the accents covered, the recording conditions, and the cases where Transcribe timing fails.

---

## 6. Bedrock grounding contract

- **Input:** the `findings[]` JSON plus the challenge script. No raw audio.
- **Output schema:** `{"items":[{"finding_id":"f3","headline":"…","why":"…","drill":"…"}]}`.
- **Validator:**
  - Every `finding_id` must exist in the input.
  - Any number in the text must appear in that finding's evidence.
  - No timestamps may appear in the text, because the UI renders them from the findings.
  - On failure: retry once, then fall back to template text.
- **Model:** `var.bedrock_model_id` (a small, fast model). Check model access in the deployment region on day one.
- **Prompt voice:** direct, specific, second person, one drill per finding, no praise padding.

---

## 7. Data

### DynamoDB — single table `speakquest` (on-demand, PITR off, deletion protection off)

| PK | SK | Attributes |
|---|---|---|
| `SESSION#<uuid>` | `PROFILE` | xp, level, badges[], created_at |
| `SESSION#<uuid>` | `TAKE#<ts>#<analysisId>` | challengeId, scores{}, status |
| `ANALYSIS#<id>` | `META` | status, stage, sessionId, keys{}, error, ttl |
| `CHALLENGE#<id>` | `META` | script, difficulty, flaw_targets[], reference_key |

TTL on `ANALYSIS#*` is 14 days.

### S3 — bucket `speakquest-<env>-<suffix>` (SSE-S3, public access blocked, `force_destroy = true`)

```
references/<challengeId>/audio.wav | words.json | features.json
uploads/<sessionId>/<analysisId>.<ext>      lifecycle: expire 7 days
work/<analysisId>/normalized.wav            lifecycle: expire 1 day
transcripts/<analysisId>.json               lifecycle: expire 7 days
results/<analysisId>/result.json
```

---

## 8. Infrastructure as code — the zero-bill contract

### 8.1 Rules
1. **Terraform owns everything.** Nothing is created in the console. The Vercel project is a Terraform resource too (`vercel/vercel` provider).
2. **Every resource carries tags** through provider `default_tags`: `project=speakquest`, `env`, `owner`.
3. **Destroy never gets blocked by data:**
   - S3 `force_destroy = true`
   - ECR `force_delete = true`
   - DynamoDB `deletion_protection_enabled = false`
4. **No orphaned logs.** Every Lambda, state machine and (fallback) ECS log group is created by Terraform with `retention_in_days = 3`, before the function first runs. Otherwise AWS auto-creates log groups that survive `destroy`.
5. **No services with deletion windows or idle fees:**
   - No KMS customer-managed keys (7–30 day pending deletion, monthly fee)
   - No Secrets Manager (7-day minimum deletion, monthly fee)
   - No NAT Gateway, no Elastic IPs, no RDS, no OpenSearch
   - Config goes in Lambda env vars. Only the Vercel token is secret, and it lives in your shell environment.
6. **No default-VPC dependencies.** The fallback Fargate module brings its own VPC, which is destroyed with it.

### 8.2 Layout

```
infra/
  main.tf  providers.tf  variables.tf  outputs.tf  versions.tf
  modules/
    storage/        # S3 bucket, CORS, lifecycle
    data/           # DynamoDB
    registry/       # ECR (force_delete)
    api/            # HTTP API, routes, api Lambdas, log groups
    worker/         # Lambda container OR Fargate (var.worker_runtime)
    workflow/       # Step Functions + log group
    ai/             # IAM policies for Transcribe + Bedrock
    observability/  # Budget + alarm
    frontend/       # vercel_project + env vars (VITE_API_URL)
```

### 8.3 State
- **Default:** local state (`terraform.tfstate`), **gitignored**. Only one person runs `apply`/`destroy`.
- **If several people deploy:** an S3 backend with `use_lockfile = true` (Terraform ≥ 1.10, so no DynamoDB lock table is needed), in a separate `infra/bootstrap` stack. Destroy that stack last.
- **Back up local state.** Losing it means losing the ability to destroy cleanly. The verification script (8.5) is the safety net.

### 8.4 Commands

```make
make up       # tf apply -target=module.registry → docker build/push worker → tf apply (all) → seed references
make deploy   # rebuild + push worker image, update Lambda image digest
make seed     # upload reference audio, pre-compute reference words/features
make down     # tf destroy -auto-approve → scripts/verify-zero.sh
```

### 8.5 `scripts/verify-zero.sh` (runs automatically after destroy)

```bash
#!/usr/bin/env bash
set -euo pipefail
REGION=${AWS_REGION:-us-east-1}
echo "Tagged resources still present:"
aws resourcegroupstaggingapi get-resources --region "$REGION" \
  --tag-filters Key=project,Values=speakquest \
  --query 'ResourceTagMappingList[].ResourceARN' --output text
echo "Leftover log groups:"
aws logs describe-log-groups --region "$REGION" \
  --log-group-name-prefix /aws/lambda/speakquest --query 'logGroups[].logGroupName' --output text
aws logs describe-log-groups --region "$REGION" \
  --log-group-name-prefix /aws/vendedlogs/states/speakquest --query 'logGroups[].logGroupName' --output text
echo "Leftover ECR repos:"
aws ecr describe-repositories --region "$REGION" \
  --query "repositories[?starts_with(repositoryName,'speakquest')].repositoryName" --output text
echo "Done. Empty output above = nothing left to bill."
```

The tagging API can show just-deleted resources for a few minutes, so re-run it if anything appears.

### 8.6 What "$0" means, honestly
- **After `make down`:** no resource exists, so nothing accrues.
- **While running:** you pay for usage — Transcribe minutes, Bedrock tokens, Lambda and Step Functions beyond free tier, and S3/ECR/log storage. For a hackathon this is small. The AWS Budget sends an alert at $5 and $15. **An alert is not a cap.**
- **Check 24–48 h after destroy:** Cost Explorer should show $0/day, after the final partial-day charges.
- **Vercel:** the Hobby plan is free and for non-commercial use. `terraform destroy` deletes the project.
- **Transcribe job records:** they stay listed in the console until they expire, at no cost. Delete them anyway with `scripts/purge-transcribe.sh` if you want a clean console.

### 8.7 Destroy gotchas checklist
- [ ] Every log group is declared in Terraform before first invocation
- [ ] S3 `force_destroy`, ECR `force_delete` set
- [ ] No manually created resources (run verify-zero before the demo too)
- [ ] Budget lives in Terraform (it gets destroyed as well)
- [ ] Fallback Fargate: no NAT, the VPC is inside the module
- [ ] Bedrock model invocation logging is **off** (otherwise it writes to an S3/log destination)

---

## 9. Frontend

**Stack:** React 18 + TypeScript + Vite · Tailwind (custom tokens only — no default palette) · WaveSurfer.js v7 (regions plugin) · Motion for transitions · TanStack Query for polling · Zod for API types shared with the Pydantic schemas (generated from JSON Schema).

**Routes**

| Route | Screen |
|---|---|
| `/` | Front page — the challenge index |
| `/c/:id` | Cue card → record → upload |
| `/take/:analysisId` | Processing, then the results ("the playback") |
| `/me` | Takes history, air time, stamps |

**Recording UX:**
- A 3-2-1 count-in.
- A live input level meter, so users see when they're too quiet before they record.
- The script is visible while recording.
- Re-take is one keystroke (`R`).
- Upload progress is shown, and failures can be retried.

---

## 10. Design system — "On Air"

### 10.1 Concept
The app is a **recording studio and a printed score**. The user does takes, not "attempts". The results page reads like a marked-up script a voice director handed back. The **transcript is the visualization**: words are set in a variable font whose shape is driven by the measured data. The typography is the evidence, not decoration.

### 10.2 Type

| Role | Font | Use |
|---|---|---|
| Display | **Archivo** (variable: `wght` 100–900, `wdth` 62–125) | Huge headlines, scores, the kinetic transcript |
| Voice | **Newsreader** (italic, optical sizes) | Coaching notes, the "director's" voice |
| Data | **IBM Plex Mono** (tabular numerals) | Timestamps, measurements, labels |

**Scale (fluid, `clamp`):**

| Token | Size | Use |
|---|---|---|
| `--t-mega` | `clamp(6rem, 18vw, 16rem)` | Score number |
| `--t-xl` | `clamp(3rem, 8vw, 7rem)` | Page titles |
| `--t-l` | `clamp(1.75rem, 3.5vw, 2.75rem)` | Kinetic transcript |
| `--t-body` | `1.125rem` | Body text |
| `--t-label` | `0.75rem` | Mono labels, uppercase, `letter-spacing: 0.08em` |

**Headline treatment:**
- Archivo at `wdth 62` for tall condensed headings and `wdth 125` for wide stamps.
- Tight leading (0.88) on display sizes.
- Headlines are allowed to bleed off the grid edge on wide screens.

### 10.3 The kinetic transcript (signature element)
Each word in the user's take is rendered with properties computed from its measurements:

| Measurement | Typographic property |
|---|---|
| Local rate vs. reference | `font-variation-settings: "wdth"` — rushed words are **condensed**, dragged words are **expanded** |
| Relative loudness | `"wght"` — loud is heavy, fading is hairline |
| Pitch (semitones from median) | Baseline shift, ±0.15em max |
| Pause | Literal horizontal space proportional to its length, with a thin mono `0.97s` label |
| Flaw | Red underline in a distinct pattern per flaw type plus a mono code tag (`HESITATE`) — never colour alone |
| Skipped word | The script word shown struck through, in grey |
| Filler | Inserted in Newsreader italic, grey |

Clicking any word seeks the waveform. The reference take renders the same way above it in ink at 40% opacity, so the two lines read like a score and its performance.

### 10.4 Colour

| Token | Light ("Paper") | Dark ("Booth") | Meaning |
|---|---|---|---|
| `--paper` | `#F1ECE2` | `#0F0F0D` | Background |
| `--ink` | `#121212` | `#EDE8DE` | Text, reference |
| `--ink-2` | `#6B665E` | `#8C877E` | Secondary text |
| `--tally` | `#E1342A` | `#FF4A3D` | Flaws, record state — **only** |
| `--rule` | `#121212` | `#EDE8DE` | 1–2 px rules |

These are the only colours. Red appears only when something is recording or something is wrong, so it always means something.

### 10.5 Layout and components
- **Grid:** a 12-column editorial grid with visible 1 px rules between sections, as in print. Asymmetric splits (8/4, 7/5) instead of centred stacks.
- **Score page:** the score number at `--t-mega`, left-aligned and cropped by the viewport. The five dimension scores sit beside it as a mono "slate" table, not as progress rings.
- **Cue cards:** challenges are presented as index cards, with the script set large, a mono difficulty tag and a corner punch-hole detail. Shown in a scrolling list, **not** a 3-column grid of identical cards.
- **Record button:** a large circular tally light that pulses with the actual input level, not a looping animation.
- **Waveform:** ink on paper, flaw regions as red hatching, a playhead as a 2 px rule.
- **Progress:**
  - XP is shown as **Air time** (minutes recorded).
  - Levels are **Rehearsal → Read-through → Dress → Opening night → Headliner**.
  - Badges are **typographic stamps** (rotated, wide Archivo, double rule border). No trophy icons.
- **Motion:** used only to reveal data. Words settle into their measured widths when results load (400 ms, ease-out, staggered). `prefers-reduced-motion` gets static output.

### 10.6 Copy voice
Direct, specific, like a voice director. Examples:
- "You rushed 'before the deadline' — 1.4× the reference pace."
- "Take 3. Pauses fixed. Pitch still flat in line two."

Never: "Unlock your potential", "Great job! 🎉", "Let's dive in".

### 10.7 Anti-slop rules (enforced in review)

| Not allowed | Instead |
|---|---|
| Purple/blue gradients, glows, glassmorphism, blurred blobs | Flat paper and ink, rules, hatching |
| Inter / Roboto / system-ui as the visible face | Archivo / Newsreader / Plex Mono |
| Emoji in UI, icon on every heading | Typography and mono labels carry hierarchy |
| Three identical feature cards, centred hero + CTA | Editorial asymmetric grid |
| `rounded-2xl` + soft shadow on everything | Square corners, 1–2 px rules; radius only on the record button and cue-card corners |
| Progress rings, confetti, trophies | Slate tables, stamps, air time |
| Default shadcn/ui styling | Components restyled from tokens, or built in-house |
| Generic copy | Specific, measured, second-person |
| Decorative stock illustration | The user's own speech, set as type |

**Review gate:** every screen is checked against this table before it merges.

### 10.8 Accessibility
- **Contrast:** WCAG AA on both themes. `--tally` on `--paper` is used for large or underlined elements only.
- **Flaws:** colour + pattern + text code.
- **Kinetic transcript:** has a plain-text mode toggle, and screen readers get "word, 0.97 second pause, hesitation flag".
- **Keyboard:**
  - Space plays/pauses.
  - ← and → step between findings.
  - R re-takes.
  - Every interactive word is a button.
- **Captions:** reference audio has synced captions.

---

## 11. Security
- IAM is one role per function, scoped to exact ARNs and prefixes. For example, the api Lambda can `s3:PutObject` only to `uploads/*` (to sign upload URLs) and `GetObject` only from `results/*`.
- No AWS keys in the frontend or in Git. The Vercel token and the AWS credentials stay in your local shell.
- Bucket public access is fully blocked. All browser access goes through presigned URLs with short expiry.
- Uploads are validated: content type, size, duration, with an ffmpeg probe before analysis.
- Voice recordings auto-expire after 7 days. `make down` deletes everything.
- Add `.gitignore` entries for `*.tfstate*`, `.terraform/`, `.env*`.

---

## 12. Repository layout

```
speakquest/
  web/                  # React + TS + Vite (Vercel root dir)
  services/
    api/                # Python Lambda handlers (zip)
    worker/             # Dockerfile, analysis package, ffmpeg
      speakquest/
        normalize.py  timing.py  diff.py  features.py  rubric.py  findings.py
    explain/            # Bedrock call + validator
  rubric/v1.yaml
  data/
    scripts/  annotations/  manifest.csv     # audio itself stays out of Git (LFS or S3 seed)
  eval/                 # precision/recall, IoU, false-positive report
  infra/                # Terraform (section 8)
  scripts/verify-zero.sh  purge-transcribe.sh
  Makefile
  docs/system_design.md
```

---

## 13. Build order

| # | Deliverable | Done when |
|---|---|---|
| 1 | Local pipeline: two recordings → timing, diff, features | Prints findings for one pair |
| 2 | Dataset + annotations; Transcribe vs. WhisperX timing test | Runtime decision made (section 4) |
| 3 | Rubric v1 + eval harness | Precision/recall and FP/min reported on held-out scripts |
| 4 | Frontend: kinetic transcript + waveform on a static result JSON | Results page matches section 10 |
| 5 | Terraform: storage, data, api, registry, worker, workflow | `make up` → full analysis in the cloud |
| 6 | Explain step + validator | Coaching text with zero invented numbers |
| 7 | Vercel via Terraform, recording flow, progress/stamps | End-to-end on the production URL |
| 8 | `make down` + verify-zero rehearsal | Clean destroy proven **before** demo day |

---

## 14. Open items
- Team size and hackathon length, which decide how much of step 7 fits.
- Bedrock model choice and region (confirm model access on day one).
- Language and accents in scope for v1 (assume English, `en-US`).
- Whether the judges want a public URL after the event. If so, delay `make down` until judging closes.
