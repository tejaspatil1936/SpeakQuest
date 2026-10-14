# Operations

## Prerequisites

| Tool | Version used | Needed for |
|---|---|---|
| uv | 0.11 | Python 3.12 environment (`uv` downloads Python itself) |
| Node.js / npm | 22 / 9+ | web app |
| ffmpeg / ffprobe | any recent | audio normalisation (local) |
| Terraform | ≥ 1.10 (tested 1.16.6) | infrastructure |
| Docker | 24+ | worker image |
| AWS CLI v2 | 2.31 | deploy, seed, verify-zero |
| Google Chrome | any recent | browser smoke and E2E tests |

## Local development (no AWS needed)

```bash
make setup          # uv sync (all extras) + npm ci
make models         # Vosk model + three Piper voices into .models/ (~230 MB)
make dataset        # 56 synthetic clips + annotations (data/audio is gitignored)
make local          # seeds .local/ on first run, serves http://localhost:8787
make web            # in another terminal: http://localhost:5173
```

`make local` coaches with Bedrock if AWS credentials are available in the
shell or `.env`, otherwise with the deterministic template. Data lives in
`.local/` (SQLite + a directory standing in for the bucket); delete it to
start over.

The web app without any backend: `npm --prefix web run dev` with
`VITE_API_URL` unset runs the clearly labelled demo build.

## Checks

| Command | What it runs |
|---|---|
| `make check` | ruff, mypy, contract drift, pytest, ESLint, tsc, Vitest, production build, Terraform fmt + validate |
| `make test-fast` | Python tests that do not touch audio |
| `make eval` | detection evaluation on dev and held-out splits → `eval/reports/` |
| `make e2e` | headless Chrome with a fake microphone → local API → workflow → playback |
| `make smoke-worker` | builds the worker image and runs it as a Lambda (RIE) against moto |
| `npm --prefix web run smoke` | demo build at 1280/375 px in both themes, screenshots in `web/smoke-output/` |
| `SPEAKQUEST_LIVE_AWS=1 pytest -m live_aws` | live Bedrock coaching; live bucket checks need `SPEAKQUEST_LIVE_BUCKET` |

## Deploying to AWS

1. Credentials: an AWS profile, or `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`
   in the shell or `.env` (`scripts/with-aws-env.sh` loads them; values are
   never printed).
2. `cp infra/terraform.tfvars.example infra/terraform.tfvars` and set `owner`,
   `alert_email`, `env`.
3. Check Bedrock model access in the region for `bedrock_model_id`
   (default `us.amazon.nova-2-lite-v1:0`).
4. `make plan` — review.
5. `make up` — applies `module.registry`, builds and pushes the worker image
   (digest saved to `infra/.worker-digest`), applies everything pinned to that
   digest, then `make seed` uploads and pre-analyses the reference takes with
   Amazon Transcribe (`SEED_ALIGNER=vosk make seed` to use the local aligner).
   `AUTO_APPROVE=1` skips Terraform's prompts.
6. Point the web app at `terraform output api_url` (`VITE_API_URL`), or set
   `enable_frontend = true` with `VERCEL_API_TOKEN` in the shell to let
   Terraform create and deploy the Vercel project.

`make deploy` rebuilds the worker image and rolls only the worker Lambda.

State is local (`infra/terraform.tfstate`, gitignored). **Back it up**: losing
it means destroying by hand; `scripts/verify-zero.sh` is the safety net. For
several operators use an S3 backend with `use_lockfile = true` in a separate
bootstrap stack.

### Demo frontend only

```bash
export VERCEL_API_TOKEN=...      # from your shell, never a file in the repo
terraform -chdir=infra/frontend-demo init
terraform -chdir=infra/frontend-demo apply
terraform -chdir=infra/frontend-demo destroy   # removes the project
```

## Teardown

```bash
make down          # terraform destroy, then scripts/verify-zero.sh
```

`verify-zero.sh` checks the tagging API and every service by name prefix
(log groups, ECR, S3, DynamoDB, Lambda, Step Functions, HTTP APIs, IAM roles,
SNS, alarms, budgets). Exit 0 = verified empty; 1 = leftovers (re-run after a
few minutes; the tagging API lags deletes); 3 = nothing found but some checks
were not permitted, so zero is **not** proven. `PREFIX=speakquest-<env>`
narrows it to one environment. `scripts/purge-transcribe.sh` deletes
Transcribe job records (free, just tidy).

Check Cost Explorer 24–48 h after a destroy for $0/day.

## Cost

| While running | Driver |
|---|---|
| Amazon Transcribe | per audio minute of each take and reference (the largest item) |
| Bedrock | ~1–2 k tokens per analysed take with findings |
| Lambda | worker: 3008 MB × a few seconds per take; others negligible |
| Step Functions Standard | ~12–50 state transitions per take (poll loop) |
| S3, ECR, CloudWatch Logs | storage while it exists (recordings expire in 7 days, logs in 3) |
| API Gateway, DynamoDB on-demand | per request; idle cost $0 |

No NAT gateway, RDS, OpenSearch, KMS customer keys, Secrets Manager or
always-on compute. The AWS Budget emails at $5 and $15 actual spend and on a
forecast overrun — **an alert is not a cap**. Vercel Hobby is free for
non-commercial use.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Take fails with `AUDIO_SILENT` / `AUDIO_TOO_QUIET` | microphone muted or far away; the booth's meter shows the level before recording |
| `SCRIPT_MISMATCH` | less than 35 % of the script recognised — wrong script, or very noisy audio |
| `TRANSCRIBE_TIMEOUT` | the job did not finish in 40 × 5 s; check Transcribe quotas |
| `REFERENCE_NOT_READY` (409) | run `make seed` |
| Coaching says "template" | no Bedrock access for `bedrock_model_id`; see `coaching.rejections` in the result |
| Upload stays at 0 % locally | the app's origin is not in `SPEAKQUEST_ALLOWED_ORIGINS` (local) or `allowed_origins` (Terraform) |
| `vosk model missing` | `make models` |
| `terraform plan` asks for a Vercel token | only when `enable_frontend = true`; export `VERCEL_API_TOKEN` |
| Logs | CloudWatch: `/aws/lambda/speakquest-<env>-*`, `/aws/vendedlogs/states/speakquest-<env>-analysis`; every line is JSON with `event` and `analysis_id` |
