# Evaluation — split `heldout`, aligner `vosk`

Rubric 1.0.0 (digest `08d27bfce473`), match = same code and IoU ≥ 0.5. 12 flawed clips, 6 clean clips (1.14 min).

| Code | TP | FP | FN | Precision | Recall | Mean IoU |
|---|---:|---:|---:|---:|---:|---:|
| RUSH | 1 | 0 | 2 | 1.00 | 0.33 | 0.94 |
| DRAG | 2 | 1 | 1 | 0.67 | 0.67 | 0.88 |
| HESITATE | 2 | 0 | 0 | 1.00 | 1.00 | 0.95 |
| MONO | 3 | 0 | 0 | 1.00 | 1.00 | 0.97 |
| FADE | 3 | 1 | 0 | 0.75 | 1.00 | 0.91 |
| SKIP | 1 | 3 | 0 | 0.25 | 1.00 | 0.90 |
| FILLER | 2 | 2 | 1 | 0.50 | 0.67 | 0.91 |
| **all** | 14 | 7 | 4 | 0.67 | 0.78 | 0.93 |

**False positives on clean-vs-clean pairs:** 4 findings in 1.14 min = **3.51 per minute** (target < 1). By code: {'DRAG': 1, 'FILLER': 1, 'RUSH': 1, 'SKIP': 1}.

**Aligner boundary error** at known word edges: median 24.00 ms, p90 60.00 ms (n=1274).

<details><summary>Per-clip detail</summary>

| Clip | Labels | Found | TP/FP/FN |
|---|---|---|---|
| cabin-briefing__clean-amy | – | – | 0/0/0 |
| cabin-briefing__clean-ryan | – | SKIP@1.14-1.14 FILLER@1.89-2.25 | 0/2/0 |
| cabin-briefing__flawed-1 | RUSH@1.77-2.49 | SKIP@1.14-1.14 SKIP@2.52-2.56 FADE@3.78-4.11 | 0/3/1 |
| cabin-briefing__flawed-2 | MONO@6.38-9.07 FADE@10.79-11.56 | MONO@6.33-9.09 FADE@10.77-11.58 | 2/0/0 |
| cabin-briefing__flawed-3 | FILLER@8.78-9.25 | SKIP@1.14-1.14 FILLER@1.89-2.25 FILLER@8.76-9.30 | 1/2/0 |
| cabin-briefing__flawed-4 | HESITATE@3.48-4.81 DRAG@10.66-13.01 | HESITATE@3.52-4.78 DRAG@10.62-13.65 | 2/0/0 |
| the-toast__clean-amy | – | – | 0/0/0 |
| the-toast__clean-ryan | – | – | 0/0/0 |
| the-toast__flawed-1 | HESITATE@2.70-3.80 | HESITATE@2.72-3.78 | 1/0/0 |
| the-toast__flawed-2 | FILLER@4.95-5.37 MONO@11.24-14.02 | FILLER@4.92-5.37 FILLER@5.76-5.88 MONO@11.19-14.04 | 2/1/0 |
| the-toast__flawed-3 | FADE@9.54-10.04 | FADE@9.56-10.11 | 1/0/0 |
| the-toast__flawed-4 | RUSH@7.87-8.78 DRAG@11.48-13.59 | DRAG@11.43-13.59 | 1/0/1 |
| closing-argument__clean-amy | – | DRAG@4.26-4.89 RUSH@4.89-6.12 | 0/2/0 |
| closing-argument__clean-ryan | – | – | 0/0/0 |
| closing-argument__flawed-1 | DRAG@3.06-4.54 | – | 0/0/1 |
| closing-argument__flawed-2 | SKIP@1.63-1.63 FADE@4.57-5.32 | SKIP@1.65-1.65 DRAG@3.90-4.53 FADE@4.53-5.31 | 2/1/0 |
| closing-argument__flawed-3 | FILLER@7.11-7.48 | – | 0/0/1 |
| closing-argument__flawed-4 | RUSH@1.38-2.25 MONO@6.53-8.23 | RUSH@1.35-2.28 MONO@6.51-8.25 | 2/0/0 |

</details>
