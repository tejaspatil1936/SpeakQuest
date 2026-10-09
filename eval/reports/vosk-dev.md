# Evaluation — split `dev`, aligner `vosk`

Rubric 1.0.0 (digest `08d27bfce473`), match = same code and IoU ≥ 0.5. 20 flawed clips, 10 clean clips (1.64 min).

| Code | TP | FP | FN | Precision | Recall | Mean IoU |
|---|---:|---:|---:|---:|---:|---:|
| RUSH | 1 | 2 | 4 | 0.33 | 0.20 | 0.78 |
| DRAG | 3 | 1 | 1 | 0.75 | 0.75 | 0.70 |
| HESITATE | 4 | 0 | 0 | 1.00 | 1.00 | 0.95 |
| MONO | 5 | 1 | 0 | 0.83 | 1.00 | 0.96 |
| FADE | 5 | 0 | 0 | 1.00 | 1.00 | 0.89 |
| SKIP | 3 | 2 | 1 | 0.60 | 0.75 | 0.92 |
| FILLER | 2 | 2 | 1 | 0.50 | 0.67 | 0.93 |
| **all** | 23 | 8 | 7 | 0.74 | 0.77 | 0.89 |

**False positives on clean-vs-clean pairs:** 1 findings in 1.64 min = **0.61 per minute** (target < 1). By code: {'RUSH': 1}.

**Aligner boundary error** at known word edges: median 25.00 ms, p90 58.00 ms (n=1776).

<details><summary>Per-clip detail</summary>

| Clip | Labels | Found | TP/FP/FN |
|---|---|---|---|
| deadline__clean-amy | – | – | 0/0/0 |
| deadline__clean-ryan | – | – | 0/0/0 |
| deadline__flawed-1 | RUSH@2.68-3.10 | – | 0/0/1 |
| deadline__flawed-2 | SKIP@1.47-1.47 HESITATE@5.77-7.17 | SKIP@1.44-1.44 HESITATE@5.80-7.12 | 2/0/0 |
| deadline__flawed-3 | MONO@0.36-2.22 | MONO@0.30-2.25 | 1/0/0 |
| deadline__flawed-4 | FILLER@1.01-1.52 FADE@7.00-7.86 | DRAG@0.30-1.74 FILLER@0.99-1.53 FADE@6.96-7.89 | 2/1/0 |
| weather-desk__clean-amy | – | – | 0/0/0 |
| weather-desk__clean-ryan | – | – | 0/0/0 |
| weather-desk__flawed-1 | MONO@0.36-2.19 | MONO@0.30-2.28 | 1/0/0 |
| weather-desk__flawed-2 | FADE@2.36-2.89 HESITATE@10.70-11.78 | FADE@2.31-2.91 HESITATE@10.74-11.74 | 2/0/0 |
| weather-desk__flawed-3 | RUSH@7.18-8.12 | – | 0/0/1 |
| weather-desk__flawed-4 | SKIP@3.97-3.97 DRAG@6.03-8.12 | SKIP@3.96-3.99 FILLER@7.23-7.93 | 1/1/1 |
| station-ident__clean-amy | – | – | 0/0/0 |
| station-ident__clean-ryan | – | – | 0/0/0 |
| station-ident__flawed-1 | FILLER@0.66-1.15 | FILLER@0.66-1.20 | 1/0/0 |
| station-ident__flawed-2 | HESITATE@4.78-6.14 RUSH@8.85-9.41 | HESITATE@4.82-6.10 RUSH@8.94-9.45 | 2/0/0 |
| station-ident__flawed-3 | FADE@6.05-6.46 | FADE@6.03-6.54 | 1/0/0 |
| station-ident__flawed-4 | DRAG@0.56-2.33 MONO@6.51-10.02 | DRAG@0.33-3.18 FILLER@0.75-1.17 MONO@6.45-10.05 | 2/1/0 |
| product-pitch__clean-amy | – | – | 0/0/0 |
| product-pitch__clean-ryan | – | – | 0/0/0 |
| product-pitch__flawed-1 | DRAG@6.78-8.72 | DRAG@6.90-8.37 | 1/0/0 |
| product-pitch__flawed-2 | SKIP@1.89-1.89 MONO@8.66-11.07 | SKIP@1.71-1.71 MONO@8.64-11.10 | 1/1/1 |
| product-pitch__flawed-3 | FILLER@9.34-9.77 | – | 0/0/1 |
| product-pitch__flawed-4 | RUSH@1.92-2.73 FADE@5.56-6.46 | SKIP@2.43-2.43 MONO@4.14-6.48 FADE@5.52-6.48 | 1/2/1 |
| gallery-four__clean-amy | – | – | 0/0/0 |
| gallery-four__clean-ryan | – | RUSH@3.48-4.50 | 0/1/0 |
| gallery-four__flawed-1 | SKIP@3.29-3.29 | SKIP@3.27-3.30 RUSH@3.30-3.96 | 1/1/0 |
| gallery-four__flawed-2 | HESITATE@0.61-2.00 DRAG@10.87-13.62 | HESITATE@0.62-1.98 DRAG@10.26-14.04 | 2/0/0 |
| gallery-four__flawed-3 | RUSH@2.94-3.63 | RUSH@3.15-4.14 | 0/1/1 |
| gallery-four__flawed-4 | FADE@5.15-5.75 MONO@8.69-12.20 | FADE@5.10-5.76 MONO@8.64-12.24 | 2/0/0 |

</details>
