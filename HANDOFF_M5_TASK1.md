# Handoff — M5 Task 1: Curvature/locality metric module

Unit `M5.1`, plan `plan/roadmap/05_M5_locality-reranking.md`. Everything is in the commit
that adds this file.

**Status: done.** `scripts/mesh_locality.py` exists, runs on its own and reads only files
that are already on disk. It makes no `im_remesh` call, contains no `ctypes` and starts no
`subprocess`. It prints a `locality` block for M3/M4's chosen mesh `v2799_coff_s1` and for
the target. The scorer gained three backward-compatible flags; on the existing tests and
on the M2/M3 self-checks it still returns exactly what it returned before.

**First reading of `v2799_coff_s1`, not a verdict:**
- **Fit near high curvature.** In high-curvature regions, its p95 surface distance is
  **1.82×** the Rhino target's (3.075e-3 vs 1.692e-3 of the diagonal). The ratio stays
  between 1.44× and 1.82× under all nine D9 settings I tried.
- **Fit elsewhere.** In low-curvature regions it is much closer to the target: 1.26×
  (1.008e-3 vs 7.98e-4).
- **Boundary artifacts.** 32 of its 74 artifact boundary edges sit in high-curvature
  regions, which cover only 7.1% of its sampled surface. Unlike the fidelity ratio, this
  number depends heavily on D9 (see the D9 section). Owner's complaint #1 (problems at high
  curvature) is consistent with the numbers. Ranking the trials is M5.2's job.

## What changed and why

| File | Change |
|---|---|
| `scripts/mesh_locality.py` | New. Contains `SourceCurvature`, `locality()`, a `LocalityReference` convenience wrapper and a CLI. Details below. |
| `scripts/score_remesh.py` | `SurfaceDistance.__call__(points, return_triangle=False)` now tracks a parallel `best_tri` argmin in both passes. In the k-nearest pass it updates where `d < best`. In the chunked exhaustive fallback it sorts by (point, distance), takes the first entry per point and updates where that entry is `< best`. The distances are still computed by the same `np.minimum` / `np.minimum.at` calls. `quad_quality(mesh, return_detail=False)` returns `{'quad_faces', 'degenerate'}` as a second value. `valence(mesh, return_detail=False)` returns `{'not_interior', 'boundary_edges'}` (the `uE[mult == 1]` edge array) as a second value. With the defaults, all three return exactly what they returned before. |
| `scripts/tune_params.py` | `components(n_vertices, mesh, return_labels=False)`. With the flag it also returns the per-vertex labels; the count it returns is unchanged. **The plan did not ask for this.** It was needed because `components()` returned only a count, and `largest_boundary_component_edges` needs the labels. The plan says to reuse `components()` and not reimplement it, so I extended it, following the same pattern as the `score_remesh` flags. |
| `tests/test_mesh_locality.py` | New, 11 tests (listed under Tests run). |
| `plan/roadmap/05_M5_locality-reranking.md` | A status note after Task 1 with three corrections to the plan's text: `rtree`, `components()` and the weld. The criteria themselves are unchanged. |

### `mesh_locality.py` design

- **`SourceCurvature(source_trimesh, radius, pctl=10)`.**
  - Computes the trimesh mean and Gaussian curvature measures at every source vertex.
  - Flags the vertices whose |mean| is at or above the `(100 - pctl)` percentile.
  - A source triangle counts as high-curvature if **any** of its vertices is flagged.
  - Exposes `.mean`, `.gaussian`, `.high_vertex`, `.high_triangle`, `.threshold` and a
    JSON `.summary` (percentiles, counts, area fraction, connected patches, bbox).
  - It is built once; every candidate is then one indexing operation into
    `high_triangle`.
- **The curvature is computed on the welded source**, using `tune_params.weld()` with
  `WELD_TOL` (D6).
  - Why: `source.obj` is 40 components joined only by duplicated seam vertices. Without
    the weld, the folds across the seams contribute nothing to the measure (see the
    `test_seams_need_the_weld` test).
  - Measured on `source.obj` at r = 2.14: the unwelded |H| p90 is 2.41, against 3.64
    welded. Only **70%** of the welded high-curvature triangles are also flagged on the
    unwelded mesh.
  - Safety check: `welded_source_trimesh()` raises an error unless the weld collapses 0
    faces and leaves every triangle within `WELD_TOL` of the same-index triangle of
    `Reference.source_distance`. The weld keeps the face order, so triangle `i` is the
    same triangle in both meshes.
- **`rtree`.** `trimesh.curvature.discrete_mean_curvature_measure` reads
  `mesh.face_adjacency_tree`, which needs `rtree`, and `rtree` is not installed. M2's
  scorer avoids `rtree` for the same reason. So `mean_curvature_measure()` passes trimesh a
  small object with the same attributes, plus a `cKDTree` stand-in:
  - The stand-in's `intersection_v(mins, maxs)` returns every segment whose midpoint is
    within (ball radius + half the segment's length) of the query point. That is a
    superset of the segments that can meet the ball.
  - Trimesh then computes each candidate's exact length inside the ball, so extra
    candidates contribute 0.
  - The computation runs in chunks of 5,000 points to bound memory.
  - A test checks the result against an exhaustive candidate list at three radii
    (atol 1e-12).
  - The Gaussian measure needs no `rtree`, so it is trimesh's own function, called
    unchanged.
- **`locality(mesh, source_distance, source_curvature, diag, samples, seed)`.**
  - It draws the same points `fidelity()` draws (same sampler, count and seed). Each
    point is high or low curvature according to its nearest source triangle.
  - Output keys:
    - `high_curv_fidelity` and `low_curv_fidelity`, each shaped
      `{samples, mean, rms, p95, max}` (all `None` with `samples: 0` if a bucket is empty)
    - `high_curv_sample_fraction`
    - `boundary_edges`, `boundary_edges_near_high_curv`, `boundary_components`,
      `largest_boundary_component_edges`
    - `degenerate_quads`, `degenerate_quads_near_high_curv`
    - `samples`
  - "Near high curvature" uses the same rule as the samples: the nearest source triangle
    to an edge's midpoint or a quad's centroid is a high-curvature triangle.
  - Boundary components come from `tune_params.components(..., return_labels=True)`,
    called on a `PolyMesh` whose "faces" are the boundary edges.
  - **`high_curv_sample_fraction` is the baseline** for reading the boundary and degenerate
    counts. If boundary edges were spread like the surface, about that fraction of them
    would be "near". The plan's scoping note says the useful signal is how concentrated
    they are, not how many there are compared with the target's 242. I did not build
    anything around the 242.
- **`LocalityReference(source, target, samples, seed, pctl, radius_scale, reference=None)`.**
  - Builds or reuses a `score_remesh.Reference` and sets
    `radius = radius_scale × target edge_length_mean` (2.1426 for `quad-remeshed.obj`).
  - Computes the target's own locality once.
  - `.record(path)` returns the JSON record (`check_finite`'d).
  - M5.2 should pass its own `Reference` as `reference=`, so the source and the target are
    loaded only once.

## Exit criteria

The plan has one `## Exit criteria` for all of M5, plus a block for Task 1 and Task 2
together. This unit covers Task 1's part of them. **The phase's criteria are not met** (see
Still open).

- **Standalone run prints a locality block of the right shape — met.** Command:
  `toolbox run -c instant-meshes-build python3 scripts/mesh_locality.py --source source.obj
  --target quad-remeshed.obj --candidate tuning_runs/meshes/v2799_coff_s1.obj`. It exits
  with rc 0 after about 33 s wall time. The output, under the conditions given below:

  ```
  curvature: radius 2.1426, top 10% |mean curvature measure| >= 3.644
    high-curvature: 8770 / 87691 vertices, 19728 / 175566 triangles, 10.26% of the area, 29 connected patches
  locality                                  candidate         target
  high_curv_fidelity.samples                     7094           9478
  high_curv_fidelity.mean                   1.058e-03      6.201e-04
  high_curv_fidelity.rms                    1.444e-03      8.183e-04
  high_curv_fidelity.p95                    3.075e-03      1.692e-03
  high_curv_fidelity.max                    6.381e-03      3.748e-03
  low_curv_fidelity.samples                     92906          90522
  low_curv_fidelity.mean                    2.426e-04      2.556e-04
  low_curv_fidelity.rms                     4.867e-04      3.748e-04
  low_curv_fidelity.p95                     1.008e-03      7.979e-04
  low_curv_fidelity.max                     7.909e-03      4.429e-03
  high_curv_sample_fraction                    0.0709         0.0948
  boundary_edges                                   74            242
  boundary_edges_near_high_curv                    32             20
  boundary_components                               4             17
  largest_boundary_component_edges                 22             26
  degenerate_quads                                  0              0
  degenerate_quads_near_high_curv                   0              0
  ```

  The 74 boundary edges match the `valence.boundary_edges` that M3 logged for this trial.
  A second, independent build gave the same p95 (3.0752748339850145e-3), so the output is
  deterministic.
- **No `ctypes` in the new script — met for `mesh_locality.py`.**
  `grep -c ctypes scripts/mesh_locality.py` prints `0`, and the file contains no
  `subprocess` and does not use `build-core`. **One caveat:** `import tune_params`, which
  the plan asks for, imports `ctypes` into the process. The text-level grep criterion still
  holds, and the native library is never loaded: only `tune_params.load_core()` loads it,
  and nothing here calls that.
- **Test suite — met for Task 1.**
  `python3 -m unittest discover -s tests -p 'test_*.py'` reports **Ran 31 tests, OK**:
  the 20 existing tests, unchanged, plus 11 new ones. `test_rank_trials.py` belongs to
  M5.2.
- **Still open for M5.2:** `rank_trials.py`, `rank_results.jsonl`, the
  `v2799_coff_s1` / new-#1 statement, the `needsHumanCheck` mesh path, D10–D12, and the
  phase-level "Task 3 unstarted" bullet. That bullet is true now: I did not touch the
  manifest or Task 3.

**Conditions for every number:**
- Fedora 44 toolbox `instant-meshes-build`; Python 3.14.8, numpy 2.5.4, scipy 1.18.1,
  trimesh 5.1.1, no `rtree`.
- `source.obj` sha256 `3e2e44ee…` (welded in memory to 87,691 V / 175,566 F, 0
  collapsed); `quad-remeshed.obj` as committed.
- `--samples 100000 --seed 0` (the defaults, the same as M3); default `--pctl 10`,
  `--radius-scale 1`.

## D9: percentile and radius — data for the owner

**Defaults chosen:** `pctl = 10` and `radius = 1.0 ×` the target's mean edge length
(2.1426). These are starting values, not conclusions.

**Source |mean curvature measure| distribution** (welded, r = 2.1426, 87,691 vertices).
The measure is ½ Σ (edge length inside the ball × dihedral angle), so it has length
units. For a reference point, a straight 90° crease through the ball's centre gives
r·π/2 ≈ 3.37.

| p0 | p1 | p5 | p10 | p25 | p50 | p75 | p90 | p95 | p99 | p100 |
|---|---|---|---|---|---|---|---|---|---|---|
| 9.1e-6 | 0.0135 | 0.067 | 0.126 | 0.271 | 0.772 | 2.374 | **3.644** | 5.275 | 6.203 | 6.472 |

The Gaussian measure (sum of vertex defects in the ball) is mostly ≤ 0: p1 −2.47, p50
−0.014, p99 +0.51. The model is dominated by saddle-like and cylindrical regions (fillets),
not caps.

The top-10% region:
- 8,770 vertices, 19,728 of 175,566 triangles, **10.26% of the source area**.
- **29 connected patches**, with bbox [−67.6, −38.9, −39.9] → [118.9, 37.8, 47.9]. That
  spans nearly the whole model, so the region is a set of creases and fillets spread over
  the part, not one localized zone.
- The distribution has a long flat top (p75 2.37 → p99 6.20). Above about p75, most
  vertices sit on a real fold, so moving the cutoff between 5% and 25% changes which folds
  are counted more than whether a fold is counted at all.

**Sensitivity**, on `v2799_coff_s1` (cand) and `quad-remeshed.obj` (tgt). "hi" is the
high-curvature bucket. "bnd near hi" is boundary edges near high curvature / all boundary
edges, with the bucket's sample fraction in parentheses as the baseline:

| radius × edge | pctl | area | cand hi p95 | tgt hi p95 | ratio | cand lo p95 | tgt lo p95 | cand bnd near hi | tgt bnd near hi |
|---|---|---|---|---|---|---|---|---|---|
| 0.5 (1.07) | 5 | 4.2% | 3.07e-3 | 1.93e-3 | 1.59 | 1.29e-3 | 8.15e-4 | 3/74 (0.009) | 90/242 (0.033) |
| 0.5 | 10 | 10.2% | 2.68e-3 | 1.68e-3 | 1.59 | 1.04e-3 | 7.71e-4 | 11/74 (0.066) | 182/242 (0.092) |
| 0.5 | 20 | 24.6% | 2.16e-3 | 1.40e-3 | 1.54 | 6.44e-4 | 5.80e-4 | 28/74 (0.210) | 228/242 (0.233) |
| 1.0 (2.14) | 5 | 4.3% | 3.15e-3 | 1.82e-3 | 1.73 | 1.27e-3 | 8.27e-4 | 20/74 (0.012) | 0/242 (0.035) |
| **1.0** | **10** | 10.3% | 3.08e-3 | 1.69e-3 | **1.82** | 1.01e-3 | 7.98e-4 | **32/74 (0.071)** | 20/242 (0.095) |
| 1.0 | 20 | 25.0% | 2.43e-3 | 1.34e-3 | 1.80 | 7.29e-4 | 6.84e-4 | 35/74 (0.223) | 64/242 (0.242) |
| 2.0 (4.29) | 5 | 8.3% | 2.34e-3 | 1.63e-3 | 1.44 | 1.15e-3 | 8.51e-4 | 0/74 (0.071) | 0/242 (0.079) |
| 2.0 | 10 | 12.9% | 2.67e-3 | 1.59e-3 | 1.68 | 1.05e-3 | 7.95e-4 | 20/74 (0.100) | 0/242 (0.122) |
| 2.0 | 20 | 25.9% | 2.40e-3 | 1.34e-3 | 1.79 | 7.62e-4 | 7.34e-4 | 37/74 (0.235) | 4/242 (0.252) |

What this shows:
1. **The fidelity finding is robust.** `v2799_coff_s1`'s high-curvature p95 is 1.44–1.82×
   the target's in every setting, and higher than its low-curvature ratio (1.04–1.58×) in
   every row (only barely in the 0.5×/5% row: 1.59 vs 1.58). G3 (M5.2) should therefore discriminate whatever D9 ends up being.
2. **The boundary-concentration finding is fragile.**
   - At 1×/10%, 43% of the artifact boundary edges sit on 7% of the surface, about 6×
     enrichment.
   - At 0.5×/5% it is 3 of 74, and at 2×/5% it is 0 of 74.
   - So the artifact holes lie next to the strongest folds (radius scale 1, top 5–10%),
     but not on the sharpest few percent at a smaller or larger radius.
   - Before anyone quotes this number as support for the `align_to_boundaries=0` theory,
     the owner should look at where the 4 boundary loops actually are.
3. **The target's own 242 real boundary edges swing from 0 to 228 "near high curvature"**
   as the radius changes. Its openings have rims that look highly curved at a small radius
   and smooth at a large one. This is one more reason not to compare candidate and target
   boundary counts.

**What I'd suggest the owner check for D9:** open the source with the 29 patches coloured
(`SourceCurvature(...).high_triangle` over the welded source), or simply look at whether
the regions they found broken are inside them. If the broken areas are tight creases, a
smaller radius (0.5×) isolates them better. If they are broad fillets, 1× or 2× is better.

## What I got wrong on the way

- I first planned to compute curvature directly on the `PolyMesh` loaded from
  `source.obj`, as the plan literally describes ("per-source-vertex"). Checking trimesh's
  formula, I found it sums only over face-adjacency edges, so `source.obj`'s seams would
  have been invisible. I switched to the welded mesh and added both the index-match safety
  check and a test showing the difference.
- The plan says the trimesh function is "confirmed importable", and it is, but calling it
  raises `ModuleNotFoundError: rtree`. I verified this before writing any code, which is
  why the stand-in exists.
- My first bent-strip test asserted |H| > 0 for every vertex at x ≥ 10. The strip's last
  column (x = 20) is a straight end with no fold, so |H| = 0 there. I also asserted
  exactly 0 on flat or seam vertices, but `arccos` rounding leaves about 5e-9, and plate
  distances come out around 1e-15. I fixed the tests' expectations, not the code: each of
  these was a wrong expectation, and each fix is commented in the test.
- My first sensitivity script ran under `python3 -I`, which also drops the toolbox's
  user-site numpy. I re-ran it without `-I`; it was my own script in `/tmp/m51`.

## Still open

1. **D9 is the owner's decision.** The defaults are 10% and 1×; the data is above.
2. **The `rank-trials` check will fail on this unit.** This diff touches
   `scripts/mesh_locality.py`, so the manifest's diff rule adds the `rank-trials` check.
   That check runs `scripts/rank_trials.py`, which is M5.2's file and does not exist yet.
   I did not add a stub, because that would fake Task 2. This is an ordering issue in the
   manifest, which belongs to the owner, not a defect in this unit. The check should pass
   once M5.2 lands.
3. `import tune_params` brings `ctypes` into the process (see the exit criteria section).
   If the owner wants "no ctypes" to hold at runtime rather than only in the file's text,
   `components()` and `weld()` would have to move to a module that does not import
   `ctypes`. That would be a refactor of M3's file, which I did not do.
4. M3's open item "nobody has looked at the D8 mesh" stands. This unit only measures; it
   makes no visual claim.

## Tests run

- `toolbox run -c instant-meshes-build python3 -m unittest discover -s tests -p
  'test_*.py'` → **Ran 31 tests, OK**. The 11 new tests:
  - SurfaceDistance argmin against brute force, on the existing huge-triangle fixture that
    exercises the fallback pass.
  - The default return is unchanged.
  - `return_detail` on `quad_quality` and `valence`; `return_labels` on `components`.
  - The rtree-free measure against exhaustive candidates.
  - Bent strip (flat half + 45° zigzag half): the known split, |H| = 0 on the flat side,
    the top 40% all on the creased side, one patch.
  - The seam test: unwelded loses the fold, welded keeps it.
  - Two plates over the strip: the exact high/low sample counts, low max = 0,
    0 < high ≤ 0.25·cos 45°, 54 boundary edges of which 28 near high, 2 components,
    largest 28.
  - Degenerate quads, one per half: 2 total, 1 near high.
  - A closed box gives 0 boundary.
  - The CLI end to end, run twice: identical records, and the source is welded on the way.
- The driver's `score-script` check, run by hand:
  `score_remesh.py --candidate quad-remeshed.obj` → aggregate 0.000000, rc 0.
- The driver's `tuning-sweep` check, last step: `tune_params.py --smoke-test` →
  `v300_coff_s0 V=766 F=618 aggregate 0.646105`, the same as M3's handoff, with sha
  `8805c2ce…` as in M4.2. `build-core/` was already built and I did not rebuild it.
- The D9 sensitivity script `/tmp/m51/sens.py` (table above), about 3 min, and a timing
  script `/tmp/m51/t.py`. These are throwaway files, not committed.

## For the next unit (M5.2, `rank_trials.py`)

- Build it as `score_remesh.Reference(source, target)`, then
  `mesh_locality.LocalityReference(source, target, reference=ref)`, then
  `lref.locality(score_remesh.load_obj(path))` per trial. `lref.target` is the target's
  locality, and `lref.target['high_curv_fidelity']['p95']` is G3's denominator
  (1.692e-3 at the defaults).
- **Timing:**
  - Building the reference plus the curvature takes about 26 s (reference 5.7 s, weld
    3.4 s, curvature 9.4 s, target locality about 6 s).
  - Each trial then takes **about 6.5 s**, measured on two trials. 137 trials in series is
    about **15 min**.
  - The `rank-trials` check's timeout is 30 min, so a serial loop fits, but not with much
    room. A `multiprocessing` pool needs care: a fork-start pool would inherit the built
    reference, and a spawn pool would rebuild it in every worker.
  - Memory per process is modest. The curvature runs in chunks; the largest arrays are
    about 100k samples × 16 nearest triangles.
- `largest_boundary_component_edges` for `v2799_coff_s1` is 22 (4 components) and for the
  target 26 (17 components). Both numbers come from this module, not from M3's log, which
  never recorded components.
- Pass `pctl` and `radius_scale` through to the CLI rather than hard-coding them, so the
  owner's D9 answer is a flag change.
