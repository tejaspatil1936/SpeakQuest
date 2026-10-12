# SpeakQuest web

React 18 + TypeScript + Vite front end for SpeakQuest, built to the **On Air**
design system (system design §9–10). Deployed on Vercel with this directory as
the project root.

## Run it

```bash
npm ci
cp .env.example .env.local   # optional
npm run dev                  # http://localhost:5173
```

| Variable | Meaning |
|---|---|
| `VITE_API_URL` | Base URL of the SpeakQuest HTTP API (API Gateway invoke URL, or the local server). |
| `VITE_DEMO` | `1` forces demo mode even when `VITE_API_URL` is set. |

Only these two `VITE_*` variables exist; they are public by design. No AWS
credentials or secrets belong in the browser build.

### Demo mode

With `VITE_API_URL` unset (or `VITE_DEMO=1`) the app uses `src/api/demo.ts`,
which serves only `public/fixtures/`: result JSON produced by the **real**
pipeline on synthetic TTS takes (`scripts/make_demo_fixtures.py` at the repo
root), their Opus audio and the challenge list. A persistent banner says so. In
demo mode you can still open the mic and record, but your take is never uploaded
or analysed; "sending" shows a pre-analysed fixture for that script, labelled as
such. The HTTP adapter (`src/api/http.ts`) never imports the demo adapter.

## Checks

```bash
npm run typecheck   # tsc, strict
npm run lint        # ESLint: typescript-eslint, react-hooks, jsx-a11y
npm test            # Vitest + Testing Library (contract, API client, upload retry,
                    # transcript model, recorder support, pages)
npm run build       # production build to dist/
npm run smoke       # needs a build: drives system Chrome over CDP at 1280/375 px
                    # and Paper theme, fails on missing content or horizontal
                    # overflow, writes screenshots to smoke-output/
```

`tests/contract.test.ts` compares every Zod schema in `src/api/schema.ts` with
`../contracts/schema.json` (generated from the Pydantic models) — keys and
required-ness — and parses every fixture, so backend/frontend drift fails CI.

## Layout

```
src/api/        schema.ts (Zod contracts) · http.ts · upload.ts (presigned PUT, retry)
                demo.ts (fixtures only) · session.ts (anonymous x-session-id)
src/lib/        transcript.ts (kinetic transcript model) · copy.ts (director's voice)
                recorder.ts (format detection, meter) · levels.ts · phrases.ts · theme.ts
src/hooks/      useRecorder (mic → meter → 3-2-1 → MediaRecorder) · useSendTake
src/components/ KineticTranscript · Waveform (WaveSurfer v7 + regions) · Findings
                ScoreSlate · Booth (tally button, level meter) · CueCard · Processing
src/pages/      ChallengeIndex (/) · CuePage (/c/:id) · TakePage (/take/:id) · MePage (/me)
```

## How the transcript encodes measurements

| Measurement | Type |
|---|---|
| Local rate vs reference (`rate_ratio`) | Archivo `wdth`: 100 − (r − 1)·90, clamped 62–125 |
| Loudness vs your mean (`loudness_db`) | Archivo `wght`: 450 + dB·45, clamped 100–900 |
| Pitch vs your median (`pitch_st`) | baseline shift −st·0.025 em, clamped ±0.15 em |
| Pause before word (`pause_before_ms` ≥ 150) | literal space, 1.6 em per second (max 6 em), mono label |
| Finding | red underline, one pattern per code, plus mono code tag |
| Skipped script word | struck through in grey |
| Filler / inserted word | Newsreader italic, grey |

Keyboard: `Space` play/pause, `←`/`→` step findings, `R` re-take; every word
is a button that seeks the audio. A plain-text transcript toggle is provided.
