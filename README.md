# SpeakQuest

Read a script aloud, and SpeakQuest lines your words up against a reference
reading, marks the exact seconds where your pace, pauses, pitch, volume or
wording drift, shows the measurements, and gives you a drill for each one.

- **The transcript is the chart.** Each word is set in a variable font whose
  width, weight and baseline come from your measured rate, loudness and pitch;
  pauses are literal space; flaws get a red underline pattern and a code.
- **Scores are measured, not guessed.** Seven flaw rules and a versioned
  rubric (`rubric/v1.yaml`) produce deterministic scores. A language model
  only writes the coaching, from the findings, and a validator rejects any
  number or timestamp it invents.
- **Live demo (fixtures, clearly labelled):** https://speakquest-demo.vercel.app
- **Dataset (56 paired clips + labels):** https://drive.google.com/file/d/1J-ZSdX-YJne9chIGnnDjjnBblf33bygO/view?usp=sharing

Specification: [docs/system_design.md](docs/system_design.md) ·
Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) ·
Operations: [docs/OPERATIONS.md](docs/OPERATIONS.md) ·
Evaluation: [docs/EVALUATION.md](docs/EVALUATION.md) ·
Decisions: [docs/DECISIONS.md](docs/DECISIONS.md) ·
Status: [docs/FINAL_REPORT.md](docs/FINAL_REPORT.md)

## Quick start (local, no AWS)

Needs `uv`, Node 22, ffmpeg and (for the browser tests) Google Chrome.

```bash
make setup      # Python 3.12 venv from uv.lock + web dependencies
make models     # Vosk model + Piper voices into .models/
make dataset    # synthetic reference and practice takes
make local      # API + storage + workflow on http://localhost:8787
make web        # app on http://localhost:5173 (second terminal)
```

Record a take in the browser and it goes through the same handlers and
workflow steps that run in AWS: presigned upload, ffmpeg normalisation, word
timing (Vosk locally; Amazon Transcribe in the cloud), script diff, features,
findings, scores, coaching (Bedrock if AWS credentials are in your shell or
`.env`, otherwise template text), persistence, air time and stamps.

Only want to look at the interface? `npm --prefix web ci && npm --prefix web run dev`
with no `VITE_API_URL` serves the demo build.

## What's where

```
web/                         React 18 + TypeScript + Vite, On Air design system
services/worker/speakquest   analysis engine, contracts, storage adapters
services/api/speakquest_api  endpoints, workflow steps, repository, local runtime, seeding
services/explain/            Bedrock coaching, grounding validator, templates
eval/speakquest_eval         synthetic labelled dataset, metrics, harness
rubric/v1.yaml               thresholds, severity bands, penalties
data/                        scripts, annotations, manifest (audio is generated)
contracts/schema.json        JSON Schema generated from the Pydantic models
infra/                       Terraform: storage, data, registry, api, worker,
                             workflow, ai, observability, frontend
scripts/                     build, seed, smoke, e2e, verify-zero
```

## Commands

| | |
|---|---|
| `make check` | every lint, type check and test (Python, web, Terraform) |
| `make eval` | precision/recall, IoU and false positives per minute on dev and held-out data |
| `make e2e` | real Chrome with a fake microphone through the whole local system |
| `make smoke-worker` | the worker container image running as a Lambda against moto |
| `make plan` / `make up` / `make deploy` / `make seed` | AWS lifecycle (see OPERATIONS) |
| `make down` | `terraform destroy`, then `scripts/verify-zero.sh` |

## Status in one paragraph

The application, analysis pipeline, coaching, evaluation, Terraform and
deployment scripts are implemented and tested locally; the worker image builds
and runs as a Lambda in the emulator; Bedrock coaching is verified live; the
demo frontend is deployed to Vercel through Terraform. **The AWS backend is
not deployed**: an AWS Organizations policy on the provided account denies
Lambda, DynamoDB, Step Functions, ECR, Transcribe, API Gateway and S3 bucket
creation. Details, numbers and blockers: [docs/FINAL_REPORT.md](docs/FINAL_REPORT.md).

## Security

No AWS keys in the frontend, Git or Terraform; presigned URLs only, with type
and size signed; the bucket blocks public access and plain HTTP; one
least-privilege IAM role per function; recordings expire after 7 days.
`.env`, Terraform state, recordings and model files are gitignored.
