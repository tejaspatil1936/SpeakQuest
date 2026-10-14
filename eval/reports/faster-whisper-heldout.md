# Evaluation — split `heldout`, aligner `faster-whisper`

Rubric 1.0.0 (digest `08d27bfce473`), match = same code and IoU ≥ 0.5. 12 flawed clips, 6 clean clips (1.14 min).

| Code | TP | FP | FN | Precision | Recall | Mean IoU |
|---|---:|---:|---:|---:|---:|---:|
| RUSH | 2 | 0 | 1 | 1.00 | 0.67 | 0.77 |
| DRAG | 3 | 2 | 0 | 0.60 | 1.00 | 0.70 |
| HESITATE | 2 | 0 | 0 | 1.00 | 1.00 | 0.57 |
| MONO | 2 | 0 | 1 | 1.00 | 0.67 | 0.83 |
| FADE | 0 | 3 | 3 | 0.00 | 0.00 | – |
| SKIP | 0 | 3 | 1 | 0.00 | 0.00 | – |
| FILLER | 0 | 2 | 3 | 0.00 | 0.00 | – |
| **all** | 9 | 10 | 9 | 0.47 | 0.50 | 0.71 |

**False positives on clean-vs-clean pairs:** 1 findings in 1.14 min = **0.88 per minute** (target < 1). By code: {'FILLER': 1}.

**Aligner boundary error** at known word edges: median 129.00 ms, p90 303.00 ms (n=1282).

<details><summary>Per-clip detail</summary>

| Clip | Labels | Found | TP/FP/FN |
|---|---|---|---|
| cabin-briefing__clean-amy | – | – | 0/0/0 |
| cabin-briefing__clean-ryan | – | – | 0/0/0 |
| cabin-briefing__flawed-1 | RUSH@1.77-2.49 | – | 0/0/1 |
| cabin-briefing__flawed-2 | MONO@6.38-9.07 FADE@10.79-11.56 | SKIP@1.30-1.30 MONO@6.16-8.90 FADE@10.52-11.22 | 1/2/1 |
| cabin-briefing__flawed-3 | FILLER@8.78-9.25 | – | 0/0/1 |
| cabin-briefing__flawed-4 | HESITATE@3.48-4.81 DRAG@10.66-13.01 | SKIP@1.30-1.30 HESITATE@4.10-4.78 DRAG@10.90-13.34 | 2/1/0 |
| the-toast__clean-amy | – | – | 0/0/0 |
| the-toast__clean-ryan | – | – | 0/0/0 |
| the-toast__flawed-1 | HESITATE@2.70-3.80 | HESITATE@2.72-3.42 | 1/0/0 |
| the-toast__flawed-2 | FILLER@4.95-5.37 MONO@11.24-14.02 | DRAG@4.46-6.12 | 0/1/2 |
| the-toast__flawed-3 | FADE@9.54-10.04 | FADE@9.34-9.84 | 0/1/1 |
| the-toast__flawed-4 | RUSH@7.87-8.78 DRAG@11.48-13.59 | RUSH@7.92-8.66 DRAG@11.10-12.98 | 2/0/0 |
| closing-argument__clean-amy | – | FILLER@6.64-6.84 | 0/1/0 |
| closing-argument__clean-ryan | – | – | 0/0/0 |
| closing-argument__flawed-1 | DRAG@3.06-4.54 | DRAG@3.26-4.88 | 1/0/0 |
| closing-argument__flawed-2 | SKIP@1.63-1.63 FADE@4.57-5.32 | SKIP@1.52-1.52 FADE@4.44-4.96 FILLER@6.28-6.48 | 0/3/2 |
| closing-argument__flawed-3 | FILLER@7.11-7.48 | DRAG@6.92-8.46 | 0/1/1 |
| closing-argument__flawed-4 | RUSH@1.38-2.25 MONO@6.53-8.23 | RUSH@1.44-2.08 FILLER@6.00-6.20 MONO@6.40-7.98 | 2/1/0 |

</details>
