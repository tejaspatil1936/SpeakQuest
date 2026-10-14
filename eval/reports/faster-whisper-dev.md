# Evaluation — split `dev`, aligner `faster-whisper`

Rubric 1.0.0 (digest `08d27bfce473`), match = same code and IoU ≥ 0.5. 20 flawed clips, 10 clean clips (1.64 min).

| Code | TP | FP | FN | Precision | Recall | Mean IoU |
|---|---:|---:|---:|---:|---:|---:|
| RUSH | 0 | 2 | 5 | 0.00 | 0.00 | – |
| DRAG | 3 | 5 | 1 | 0.38 | 0.75 | 0.75 |
| HESITATE | 3 | 0 | 1 | 1.00 | 0.75 | 0.62 |
| MONO | 4 | 0 | 1 | 1.00 | 0.80 | 0.83 |
| FADE | 2 | 3 | 3 | 0.40 | 0.40 | 0.65 |
| SKIP | 0 | 10 | 4 | 0.00 | 0.00 | – |
| FILLER | 0 | 1 | 3 | 0.00 | 0.00 | – |
| **all** | 12 | 21 | 18 | 0.36 | 0.40 | 0.73 |

**False positives on clean-vs-clean pairs:** 4 findings in 1.64 min = **2.45 per minute** (target < 1). By code: {'RUSH': 2, 'SKIP': 2}.

**Aligner boundary error** at known word edges: median 142.50 ms, p90 300.00 ms (n=1776).

<details><summary>Per-clip detail</summary>

| Clip | Labels | Found | TP/FP/FN |
|---|---|---|---|
| deadline__clean-amy | – | – | 0/0/0 |
| deadline__clean-ryan | – | – | 0/0/0 |
| deadline__flawed-1 | RUSH@2.68-3.10 | – | 0/0/1 |
| deadline__flawed-2 | SKIP@1.47-1.47 HESITATE@5.77-7.17 | SKIP@1.28-1.28 HESITATE@5.80-6.56 | 1/1/1 |
| deadline__flawed-3 | MONO@0.36-2.22 | MONO@0.00-1.96 | 1/0/0 |
| deadline__flawed-4 | FILLER@1.01-1.52 FADE@7.00-7.86 | DRAG@0.00-1.70 FILLER@0.92-1.16 FADE@6.90-7.56 | 1/2/1 |
| weather-desk__clean-amy | – | – | 0/0/0 |
| weather-desk__clean-ryan | – | RUSH@4.58-5.20 | 0/1/0 |
| weather-desk__flawed-1 | MONO@0.36-2.19 | MONO@0.00-2.14 | 1/0/0 |
| weather-desk__flawed-2 | FADE@2.36-2.89 HESITATE@10.70-11.78 | FADE@2.00-2.76 | 0/1/2 |
| weather-desk__flawed-3 | RUSH@7.18-8.12 | RUSH@4.58-5.20 | 0/1/1 |
| weather-desk__flawed-4 | SKIP@3.97-3.97 DRAG@6.03-8.12 | SKIP@3.72-3.72 DRAG@5.78-8.54 | 1/1/1 |
| station-ident__clean-amy | – | SKIP@2.66-2.66 | 0/1/0 |
| station-ident__clean-ryan | – | SKIP@1.70-1.70 | 0/1/0 |
| station-ident__flawed-1 | FILLER@0.66-1.15 | DRAG@0.48-1.80 SKIP@2.46-2.46 | 0/2/1 |
| station-ident__flawed-2 | HESITATE@4.78-6.14 RUSH@8.85-9.41 | SKIP@2.66-2.66 HESITATE@4.82-5.62 | 1/1/1 |
| station-ident__flawed-3 | FADE@6.05-6.46 | SKIP@1.70-1.70 FADE@5.94-6.42 | 1/1/0 |
| station-ident__flawed-4 | DRAG@0.56-2.33 MONO@6.51-10.02 | DRAG@0.00-9.86 SKIP@3.42-3.42 | 0/2/2 |
| product-pitch__clean-amy | – | – | 0/0/0 |
| product-pitch__clean-ryan | – | – | 0/0/0 |
| product-pitch__flawed-1 | DRAG@6.78-8.72 | DRAG@6.82-8.50 | 1/0/0 |
| product-pitch__flawed-2 | SKIP@1.89-1.89 MONO@8.66-11.07 | SKIP@1.38-1.38 SKIP@2.12-2.12 MONO@8.66-10.72 | 1/2/1 |
| product-pitch__flawed-3 | FILLER@9.34-9.77 | DRAG@8.96-10.96 | 0/1/1 |
| product-pitch__flawed-4 | RUSH@1.92-2.73 FADE@5.56-6.46 | SKIP@2.22-2.22 FADE@5.40-6.02 | 0/2/2 |
| gallery-four__clean-amy | – | – | 0/0/0 |
| gallery-four__clean-ryan | – | RUSH@3.66-5.02 | 0/1/0 |
| gallery-four__flawed-1 | SKIP@3.29-3.29 | SKIP@3.10-3.10 | 0/1/1 |
| gallery-four__flawed-2 | HESITATE@0.61-2.00 DRAG@10.87-13.62 | DRAG@0.00-14.58 HESITATE@0.86-1.86 DRAG@10.12-14.58 | 2/1/0 |
| gallery-four__flawed-3 | RUSH@2.94-3.63 | RUSH@3.04-4.66 | 0/1/1 |
| gallery-four__flawed-4 | FADE@5.15-5.75 MONO@8.69-12.20 | FADE@4.92-5.52 MONO@8.58-12.08 | 1/1/1 |

</details>
