# Handoff — M3 Task 1: Parameter Tuning Harness

Unit `M3.1`, plan `plan/roadmap/03_M3_tuning-harness.md`. The code commit is `31658ab` (harness
and tests). The sweep log, the plan corrections and this handoff are in the commit that adds
this file.

**Status: done.** All three exit criteria were run and hold (evidence below). This unit asks
for a human check because of the findings in "What the owner should look at": one aggregate
term dominates the score, and nobody has looked at the best mesh.

## Result

**Best parameter set** (stage 2, trial `v2663_c45_s1`, aggregate **0.142816**, where 0 is best):

```
vertex_count=2663  crease_angle=45  smooth_iter=1
rosy=4 posy=4 pure_quad=1 deterministic=1 scale=-1 face_count=-1
extrinsic=1 align_to_boundaries=0 knn_points=10      (1 TBB thread, welded source)
```

| metric | best trial | target `quad-remeshed.obj` |
|---|---|---|
| V / F | 10938 / 11008 (ΔV −1.30 %, ΔF −0.42 %) | 11082 / 11054 |
| angle dev mean / P90 / worst corner | 8.306° / 17.970° / 89.996° | 9.434° / 17.547° / 84.981° |
| degenerate quads / non-quad faces | 0 / 0 | 0 / 0 |
| edge-length CV | 0.1675 | 0.5552 |
| % valence 4 (interior) | 91.85 % | 96.63 % |
| mesh valence singularities | 887 (interior histogram 2:6, 3:309, 4:10001, 5:476, 6:87, 7:7, 8:2) | 365 |
| boundary / non-manifold edges | 52 / 0 | 242 / 0 |
| fidelity mean / RMS / P95 / max (÷ diag) | 3.24e-4 / 6.78e-4 / 1.44e-3 / 9.00e-3 | 2.90e-4 / 4.37e-4 / 9.07e-4 / 4.43e-3 |
| aggregate terms | count_v 0.0130, count_f 0.0042, angle 0.1195, **edge_cv 0.6982**, valence4 0.0478, fidelity 0.1170, non_quad 0 | (0) |

For comparison, M2's trial (`vertex_count=11082` on the unwelded source) scored 0.4455
under the old absolute scorer. On the welded source, M1's anchor `vertex_count=2770, smooth_iter=2,
crease off` already scores 0.149879. Most of the improvement comes from welding and from
anchoring `vertex_count` correctly; the sweep itself only gained another ~0.007.

**Sensitivity.** Main-effect ranges are the spread of the per-level mean score. "At best
others" means the other two parameters are held at the stage's best values.

| parameter | stage 1 (45 trials) | stage 2 (100 grid points; 9 were already logged by stage 1, so 91 new trials) | reading |
|---|---|---|---|
| `smooth_iter` | 0.0995 / 0.1253 | 0.0976 / 0.1258 | **most sensitive.** `0` is always bad (+0.08–0.13), and 1, 2 and 4 are within ~0.008 of each other |
| `vertex_count` | 0.0830 / 0.0993 | 0.0133 / 0.0280 | strong over the ±27 % stage-1 range, only through `count_v`/`count_f`; flat within ±5 % |
| `crease_angle` | 0.0275 / 0.0426 | 0.0666 / 0.0972 | 20° and 30° hurt; off, 45° and 60° are equivalent (means 0.1865 / 0.1862 / 0.1863) |

Per level (mean score):
- Stage 2 `crease_angle`: off 0.1865, 20° 0.2528, 30° 0.2200, 45° 0.1862, 60° 0.1863.
- Stage 2 `smooth_iter`: 0 → 0.2799, 1 → 0.1823, 2 → 0.1840, 4 → 0.1861.
- Stage 1 `vertex_count`: 1972 → 0.2860, 2341 → 0.2462, **2731 → 0.2030**, 3081 → 0.2346,
  3450 → 0.2773.

**The response is rugged at the optimum.** The score does not change smoothly with
`vertex_count`:
- The `c45_s1` line over `vertex_count` 2594 / 2663 / 2731 / 2799 / 2868 gives
  0.1708 / **0.1428** / 0.1473 / 0.1520 / 0.1602.
- The `coff_s1` line gives 0.1640 / 0.1575 / 0.1545 / **0.1461** / 0.1558.
- Neighbouring trials differ by 0.005–0.03, which is more than the gap between the best
  few parameter sets. Treat the top ~10 trials (0.1428–0.1535, every one with `smooth_iter ≥ 1`
  and crease off/45/60) as equally good. The exact winner is partly luck in the
  extraction.

## What changed and why

| File | Change |
|---|---|
| `scripts/tune_params.py` | New. It welds the source, calls `im_remesh` via ctypes in single-threaded `spawn` worker processes (4 by default), scores each trial with `score_remesh.Reference` (one per worker), and appends one JSON line per trial from the parent process. Modes: `--smoke-test`, `--stage anchor\|1\|2`, `--report`, `--verify-best`. Trials already in the log (same params, same welded-source sha256, same samples/seed) are skipped, so a stage can be resumed. If `build-core/libinstantmeshes_core.so` is missing, it builds it with M1's exact cmake invocation. `im_remesh`'s progress output goes to `tuning_runs/meshes/<trial>.log`, through an fd-level redirect. |
| `tests/test_tune_params.py` | New. 7 tests: welding a split square, the tolerance boundary, transitive clusters, a collapsed face being dropped, the OBJ round trip, the ctypes struct layout against `capi.h` (sizeof 48 and field offsets), the param/key/name bookkeeping, and best-row selection. |
| `tuning_results.jsonl` | **The M3 deliverable.** 137 rows (1 anchor + 45 stage 1 + 91 stage 2), 655 KB. Each row holds the full `im_remesh_params`, the welded input's path and sha256, the remesh rc/V/F/seconds, the output's sha256, the full M2 score record (every raw sub-metric for candidate and target, the terms and the aggregate), the weld stats and the score settings. The top-level `aggregate` is a convenience copy. |
| `plan/roadmap/03_M3_tuning-harness.md` | "Corrections from M3.1": what the D6 boundary numbers compare, the calibrated anchor, and why stage 2 is a grid. |
| `.gitignore` | `tuning_runs` (welded source, 137 output meshes, logs, the smoke log). |

### Weld (D6): tolerance and justification

- Vertex pairs within distance r in `source.obj` (scipy `cKDTree.query_pairs`):
  - **10,287 for every r from 0 (exact) through 1e-4**;
  - 10,307 at 1e-3, 10,485 at 1e-2 and 12,874 at 1e-1.
  - Every pair up to 1e-4 is between two boundary vertices.
- So the seam duplicates are exactly coincident, and there is a clean plateau up to 1e-4.
  **Chosen tolerance: 1e-5** world units (the bbox diagonal is 219.92), in the middle of the
  plateau.
  - At 1e-3 the weld would already collapse 10 triangles (measured); at 1e-5 it collapses 0.
- Merging is transitive (connected components of the pair graph). 9,146 clusters of 2–4
  vertices each merge into their lowest-index member, and vertex order is kept.
- I did not use trimesh `merge_vertices(digits_vertex=5)`: it rounds to a grid, so two
  coincident-within-tolerance points can still fall on opposite sides of a rounding boundary,
  and it would not report collapses. The `cKDTree` weld is exact about the tolerance.
- Welded source (`tuning_runs/source_welded.obj`, sha256 `b63990bc…`): it is rebuilt on
  every run in ~3 s, so it cannot go stale. Every row records its sha256.

| | `source.obj` | welded |
|---|---|---|
| V / F | 97,400 / 175,566 | 87,691 / 175,566 |
| boundary edges | 20,392 | **0** |
| non-manifold edges | 0 | 0 |
| connected components | 40 | **1** |

Scoring still uses the original `source.obj` and `quad-remeshed.obj`, as D6 requires.

## Exit criteria, one by one

Conditions for every number in this file:
- Fedora 44 toolbox `instant-meshes-build`, Python 3.14.8, numpy 2.5.4, scipy 1.18.1,
  trimesh 5.1.1, `build-core/libinstantmeshes_core.so` from M1 (unchanged).
- 8-core host, 7 GB RAM, `--workers 4`.
- Each worker runs with `im_set_thread_count(1)`; `--samples 100000 --seed 0`.
- Per trial: remesh 2–5 s and scoring 9–13 s (4 workers in parallel). Stage 1 took 3 min 4 s;
  stage 2 took ~6 min.

### 1. `source.obj` welded before the sweep; boundary edges measured — **met**

- **The welded source mesh itself has 0 boundary edges**, against 20,392 unwelded. That is
  |0 − 242| = 242 from the target, against 9,270 for the 9,512.
- The plan's "9,512" is the boundary count of the *remesh output* of the unwelded source,
  not of the source itself (see the plan correction). So I also measured the like-for-like
  remesh. I ran M1/M2's exact trial params (`vertex_count=11082, smooth_iter=2`, crease off,
  1 thread) on both inputs:

| input | output V / F | boundary edges | non-manifold edges | degenerate quads |
|---|---|---|---|---|
| unwelded `source.obj` | 46322 / 41632 (= M2's numbers) | **9,512** | 52 | 52 |
| welded | 44500 / 44592 | **0** | 0 | 0 |

- Across all 137 sweep outputs (welded): 0–264 boundary edges, at most 1 non-manifold edge
  and at most 1 degenerate quad. The best trial has 52 and 0; the anchor has 46.
- Welding removed the defects that M2 blamed on the seams.

### 2. Best set re-run standalone; logged score = fresh scorer invocation — **met**

`tune_params.py --verify-best`:
- It re-welds the source and checks that its sha256 matches the logged input.
- It runs `im_remesh` with the best params in a **fresh Python process**, to a temp file.
- It then runs the **`score_remesh.py` CLI** as a separate process on that file and compares.

Output:

```
best logged: v2663_c45_s1 score 0.1428156265610388 (stage stage2)
output V/F         identical
output sha256      identical
aggregate score    identical
aggregate terms    identical
candidate metrics  identical      (counts, quad_quality, valence, fidelity blocks)
fresh score 0.1428156265610388, logged score 0.1428156265610388
```

Exit 0, 19 s. The comparison is exact float equality, not a tolerance.

### 3. `scripts/tune_params.py --smoke-test` runs one trial end-to-end and exits 0 — **met**

`toolbox run -c instant-meshes-build python3 scripts/tune_params.py --smoke-test`:
- exit 0, 28.7 s wall;
- built nothing, because the library already existed;
- welded the source;
- ran one `im_remesh` call: `vertex_count=300`, crease off, `smooth_iter=0` → V=766, F=618;
- scored it: aggregate 0.646105;
- appended one row to `tuning_runs/smoke_results.jsonl`, which it deletes first so that it
  always holds exactly one row.

There are no lines matching the check's fail pattern
`^(CMake Error|error:|FAILED|Traceback)`: `im_remesh`'s own output goes to the trial's
`.log`. I did not run the driver's full `tuning-sweep` command verbatim (its `dnf`/`cmake`
steps). Its last step is exactly the command above.

## What the owner should look at (why `needsHumanCheck`)

1. **`edge_cv` is ~70 % of the best score, and no parameter moves it.**
   - The term ranges only 0.663–0.748 over all 137 logged trials. In the best trial it is
     0.698/7 = 0.0997 of the 0.1428.
   - Instant Meshes makes uniform edges (CV ≈ 0.17); Rhino's remesh is size-adaptive
     (CV 0.555). This is D4 working as designed. But with this setup the floor for any IM
     result is ≈ 0.095, and the swept parameters only fight over the remaining ~0.05.
   - Getting adaptivity would need something outside this sweep's parameter space, such as
     a non-uniform scale or density field. If that is not a goal, `--weight edge_cv=0`
     would let the other terms decide. Changing weights does **not** need re-meshing: every
     row has all raw metrics, so the log can be re-aggregated offline.
2. **The best trial's blind spots (D5):**
   - It has 887 valence singularities vs. the target's 365 (91.9 % vs. 96.6 % valence-4).
     The `valence4` term only sees the 4.8-point % difference, so this costs 0.048.
   - Its fidelity tail is 2× the target's (max 9.0e-3 vs. 4.4e-3; P95 1.44e-3 vs. 9.1e-4),
     while its mean is close (+11.7 %).
   - The search did **not** exploit degenerate quads (0) or non-manifold edges (0).
   - Boundary edges are 52 vs. 242. The welded source is closed, so the target's 242 are
     Rhino-side holes, not something IM should reproduce.
3. **Nobody has looked at the best mesh.**
   - `tuning_runs/meshes/v2663_c45_s1.obj` (regenerate with `--verify-best`, or re-run
     stage 2) should get the plan's optional qualitative spot-check. In particular, check
     whether a 45° crease threshold puts creases where the part has real edges.
   - The ruggedness above makes the runner-up `v2799_coff_s1` (0.1461, no creases) an
     equally defensible pick.

## What I got wrong on the way

- Before I measured, I read D6's "should land near the target's 242, not 9,512" as being
  about the welded *source*. The welded source has 0 boundary edges, because it is closed.
  The 9,512 is a remesh-output number, so I added the like-for-like remesh measurement and
  corrected the plan text rather than report a number that answers a different question.
- The stage-1 grid point 2731 (the calibrated centre) scored *worse* (0.1511 with crease 45,
  0.1553 with crease off) than the uncalibrated anchor 2770 (0.1499). Taking "calibrated
  = better" for granted would have been wrong. That was the first sign of the ruggedness
  described above. Stage 2's ±5 % grid around 2731 covered 2770's neighbourhood anyway.
- The smoke trial's scoring took 14 s for a 766-vertex mesh (vs. ~5 s for an 11k one). Its
  large triangles push more samples into the distance query's ball-search fallback (M2's
  open item 2). This does not matter for the check, but don't assume "small mesh = fast
  score".

## Open

1. The owner's call on `edge_cv` weighting (above). If it changes, re-aggregate
   `tuning_results.jsonl` offline from the stored metrics and re-pick the best. The harness
   does not need to re-mesh.
2. `align_to_boundaries` and `extrinsic` were not swept: they are fixed at the CLI defaults,
   as the plan specifies. The welded source has no boundaries, so `align_to_boundaries`
   should be inert now.
3. Stage 2 is a grid, not `scipy.optimize`: the response is non-smooth and partly integer
   (see the plan correction). A finer `vertex_count` scan around 2663 would most likely find
   another lucky point. It would not find a real improvement.
4. M2's open items still stand: no source→candidate (reverse) fidelity, and the
   distance-query speed.

## Tests run

- `toolbox run -c instant-meshes-build python3 -m unittest discover -s tests -p 'test_*.py'`
  (from the repo root): **20/20 OK** (13 existing `test_score_remesh` tests, unchanged, plus
  7 new ones).
- `--smoke-test`, `--stage anchor`, `--stage 1`, `--stage 2`, `--report` and `--verify-best`
  were all run as described above; all exited 0.
- `ctest` in `build-core` was not re-run: no native code or CMake file changed in this unit.

## For the next unit (M4, C# P/Invoke demo)

- If the demo wants "good" defaults for this part, use the best set above:
  `vertex_count=2663, crease_angle=45, smooth_iter=1, rosy=posy=4, pure_quad=1,
  deterministic=1`.
- **Weld the input first.** Without welding, every setting produces seam holes. The weld
  is a 1e-5 exact-coincidence merge, `tune_params.weld()`.
- `vertex_count` must be ~¼ of the wanted output V in pure-quad mode.
- Reproducible output needs `im_set_thread_count(1)` before the first `im_remesh` in the
  process. `deterministic=1` alone is not enough (M1).
- The ctypes layout in `tune_params.py` (`ImRemeshParams`: 10 int + 2 float in header
  order, 48 bytes) is the same layout the C# `[StructLayout(LayoutKind.Sequential)]` struct
  needs.
