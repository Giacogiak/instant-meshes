# Milestone M5 — Locality-Aware Re-Ranking of the M3 Sweep

The owner opened M3/M4's chosen best mesh (`v2799_coff_s1`) and found serious problems in
high-curvature areas and broken geometry near some open boundaries, despite a good
aggregate score. `scripts/score_remesh.py`'s `aggregate()` reduces everything to 7 global,
equal-weighted scalars — it has no locality, and the chosen trial's score is ~70%
dominated by `edge_cv` (a uniform-vs-adaptive-spacing mismatch unrelated to curvature or
boundaries). This milestone builds a curvature/locality-aware metric and a
constraint-first re-ranking of the **137 trials M3 already logged**, with **zero new
`im_remesh` calls** — every trial's output `.obj` is still on disk in `tuning_runs/meshes/`
(gitignored but present), alongside `source.obj` and `quad-remeshed.obj`.

**Owner's decisions binding this milestone:**
- Scoring philosophy: **constraint-first** — hard gates reject visibly-broken meshes, then
  rank survivors by closeness to the Rhino target, not a blended 7-term average.
- Scope: **re-analyze the existing 137 trials only**. Do not sweep new parameters and do
  not call `im_remesh` at all in M5.1/M5.2.
- **No native/C-API changes.** `fill_holes` exposure and curvature-adaptive sizing are
  documented as future options only (see Task 3), not implemented here.

## Task 1 — Curvature/locality metric module (Milestone M5)

Add a new module, **`scripts/mesh_locality.py`**, that builds on `score_remesh.py`'s
existing `Reference`/`SurfaceDistance`/`PolyMesh` machinery rather than forking it
(`scripts/tune_params.py`'s `import score_remesh` is the pattern to copy).

- **`SourceCurvature(source_trimesh, radius)`**: per-source-vertex curvature via
  `trimesh.curvature.discrete_mean_curvature_measure`/`discrete_gaussian_curvature_measure`
  (confirmed importable in `trimesh==5.1.1`, signature `(mesh, points, radius)`). Build
  **once** per `Reference` and reuse across every trial, the same "build once, reuse per
  candidate" shape `SurfaceDistance` already has. Anchor `radius` to the target's own mean
  edge length (`quad_quality()['edge_length_mean']` on `quad-remeshed.obj`, already logged
  in every trial row) rather than inventing a new constant. Flag the top-`PCTL`% of
  `|mean curvature|` source vertices as "high-curvature" — **this percentile, and the
  radius choice, are judgment calls (D9)**: pick a reasonable starting value (e.g. top
  10%), but print the full curvature distribution and the resulting high-curvature region's
  size/extent in the handoff so the owner can sanity-check the cutoff, rather than treating
  your first choice as final.
- **`locality(mesh, source_distance, source_curvature, diag, samples, seed)`**: resamples
  the candidate exactly as `fidelity()` does, but needs each sample's nearest *source*
  triangle (not just its distance) to classify high/low curvature. Add this to
  `SurfaceDistance.__call__` via a new optional `return_triangle=False` flag — this needs
  **new** argmin bookkeeping (a parallel `best_tri` array alongside the existing `best`
  distance array, updated in both the k-nearest pass and the chunked exhaustive-fallback
  pass); it is not already tracked. Similarly add optional `return_detail=False` to
  `quad_quality()` (exposing the already-computed `degenerate` face mask) and `valence()`
  (exposing the already-computed `not_interior` vertex mask). All three additions must be
  backward compatible: every existing call site (M2's and M3's scripts and tests) is
  unaffected by the default `False`, and the existing test suite must stay green unchanged.
- Output shape mirrors `fidelity()`'s `{mean, rms, p95, max, samples}`, split into
  `high_curv_fidelity` / `low_curv_fidelity`. Also report `boundary_edges_near_high_curv`,
  `boundary_components` and `largest_boundary_component_edges` (boundary-edge connected
  components — reuse `tune_params.components()` directly, do not reimplement it), and
  `degenerate_quads_near_high_curv`.
- **Scoping note**: every M3 trial remeshed the *welded* source (0 boundary edges, 1
  component — confirmed in every trial's logged `weld` block). So a trial's output boundary
  edges are necessarily extraction artifacts, not reflections of a real opening. The useful
  signal is "are artifact boundaries concentrated in high-curvature regions" (a direct test
  of the `align_to_boundaries=0` / reprojection-window theory), **not** "does the boundary
  count approach the target's 242" — no welded-source output can meaningfully approach that
  number, so do not build a gate or report around that comparison.
- **No `ctypes`, no `subprocess`, no `build-core` dependency** — this module must never
  re-mesh. `grep -L ctypes scripts/mesh_locality.py` (i.e. confirming no match) is part of
  the exit criterion.

### Naming convention for this unit

New module at `scripts/mesh_locality.py`. New tests at `tests/test_mesh_locality.py`,
following `tests/test_score_remesh.py`'s synthetic-grid-helper pattern — include at least
one synthetic mesh with a known curvature split (e.g. a bent strip: flat half + sharply
creased half) so the high/low-curvature split can be checked against a known-correct
answer, not just "it runs."

**Decided (giacomo forcina, 2026-10-13), resolving D9:** keep the validated defaults —
`radius_scale = 1.0` (the target's own mean edge length, 2.1426) and `pctl = 10`. The
owner characterized what they saw as "dents that make the shape jagged, in respect to the
original curve" — local, small-scale irregularity relative to the intended smooth surface,
rather than clearly one of "tight sharp creases" or "broad rounded fillets." Since the
measured fidelity-ratio finding (1.44–1.82× the target in high-curvature regions) holds
across every radius/percentile combination M5.1 tried, and nothing in this description
argues for a smaller (0.5×) or larger (2×) radius over the validated 1×/10% default, M5.2
should use `radius_scale=1.0, pctl=10` and carry the owner's description forward as
qualitative context for whoever visually inspects the eventual top-ranked mesh.

**Status after M5.1 (2026-10-13):** `scripts/mesh_locality.py` and its tests are in place
(evidence and D9 data in `HANDOFF_M5_TASK1.md`). Three corrections to the text above,
measured in the toolbox: (1) `discrete_mean_curvature_measure` is importable but needs the
optional `rtree` package at call time (`mesh.face_adjacency_tree`), which is not installed;
the module passes it an rtree-free stand-in built on `cKDTree` (tested against an exhaustive
candidate set), so trimesh's formula is still the one used. (2) `tune_params.components()`
returned only a count, so `largest_boundary_component_edges` could not be had from it; it
gained the same kind of backward-compatible `return_labels=False` flag as the
`score_remesh` functions. (3) Curvature must be computed on the **welded** source: on the
raw `source.obj` the 40 components' seams carry no face adjacency and their folds vanish
from the measure. The weld keeps every face in order, so triangle indices still match
`Reference`'s `SurfaceDistance`.

## Task 2 — Constraint-first re-ranking of the 137 existing trials (Milestone M5)

Add **`scripts/rank_trials.py`**, which:

1. Reads `tuning_results.jsonl` (full params + full candidate/target sub-metrics for all
   137 trials) and locates each trial's output mesh under `tuning_runs/meshes/`.
2. **Verifies each on-disk mesh's sha256 still matches the logged value** before using it —
   if `tuning_runs/` has been regenerated or partially cleaned since M3, a stale mesh must
   not silently corrupt the re-rank. Report (don't silently skip) any mismatch or missing
   file.
3. Builds one shared `score_remesh.Reference` plus one `mesh_locality.SourceCurvature`
   (Task 1), and recomputes `locality()` for every trial, including for `quad-remeshed.obj`
   itself (to get the target's own `high_curv_fidelity`, needed for gate G3 below).
4. Applies three gates, independent of overall score:
   - **G1 — no degenerate quads**: `quad_quality.degenerate_quads == 0` (already logged;
     near-universal pass rate per M3's handoff — kept as a safety net, not expected to
     reject much).
   - **G2 — no large contiguous boundary hole**: `largest_boundary_component_edges <= N`.
     Do **not** gate on raw `boundary_edges` near the target's 242 — the welded-source
     scoping note above shows that doesn't discriminate among the 137 trials (they range
     0–264, all under even a loose "2x target" ceiling). **`N` is a judgment call (D10)**:
     propose starting at the 95th percentile of the 137 trials' own
     `largest_boundary_component_edges` distribution, but say plainly in the handoff that
     this is circular (it can only ever reject the worst ~5%) and name 2–3 trials it
     rejects so the owner can eyeball whether the cut looks sensible.
   - **G3 — curvature-region fidelity bounded relative to target**:
     `high_curv_fidelity.p95 <= k * target_high_curv_fidelity.p95`, consistent with the
     existing "match Rhino, don't minimize to zero" philosophy from M2's D4. **`k` is a
     judgment call (D11)**: print the full distribution of `high_curv_fidelity.p95` across
     the 137 trials relative to the target's value before picking a starting `k` (e.g. 2x),
     so the owner can see the spread that choice is being made against.
5. Among gate-passing trials, ranks by `high_curv_fidelity.p95` scored relative-to-target
   (reuse `aggregate()`'s existing `ratio()` helper — don't reimplement it), tie broken by
   the existing global `fidelity.mean` ratio. **The exact ranking formula (p95 vs. mean vs.
   a blend of high/low-curvature buckets) is a judgment call (D12)** — state the choice and
   reasoning plainly; this is the direct implementation of "closeness to the Rhino target
   surface as primary objective."
6. Writes **`tuning_runs/rank_results.jsonl`** — one row per trial: `name`, `params`,
   `gates: {G1, G2, G3}`, `passed`, the full `locality` record, and `rank` (null if it
   didn't pass). Prints a summary report in the style of `tune_params.py --report`.

### Exit criteria for Task 1 + Task 2

- `scripts/mesh_locality.py` run standalone (e.g.
  `--source source.obj --target quad-remeshed.obj --candidate tuning_runs/meshes/v2799_coff_s1.obj`)
  prints a `locality` block with the `{mean, rms, p95, max, samples}` shape for both
  curvature buckets, plus the boundary/degenerate-quad locality fields — using only
  already-on-disk files, no `im_remesh` call.
- `scripts/rank_trials.py` re-ranks all 137 existing trials and writes
  `tuning_runs/rank_results.jsonl`, with **zero new `im_remesh` calls** (no `import ctypes`
  anywhere in either new script).
- The report **explicitly states `v2799_coff_s1`'s new gate pass/fail status and rank**
  (the sanity check against the M3/D8 pick), and **the new #1 trial's name, params, and why
  it beat `v2799_coff_s1`** — or explicitly confirms no change, which is itself a useful
  finding.
- `python3 -m unittest discover -s tests -p 'test_*.py'` stays green (the existing 20 tests,
  unchanged) plus the new `test_mesh_locality.py`/`test_rank_trials.py`.
- **This milestone does not conclude that the new top trial is "fixed."** Set
  `needsHumanCheck` and name the new top trial's mesh path
  (`tuning_runs/meshes/<name>.obj`) explicitly in the handoff for the owner to open in a
  viewer — do not repeat M3's "nobody looked at the mesh" gap. Also report D9–D12's chosen
  defaults and the data that should inform the owner's review of each, exactly as M3's
  handoff did for D7/D8.

### Toolchain note for this unit

Same `instant-meshes-build` toolbox as M2/M3 (Python + `trimesh`/`numpy`/`scipy`, already
installed there). No C/C++ build and no `.NET` SDK are needed — `build-core` is not touched.

## Task 3 — *(deferred, not started until the owner reviews Task 2's findings)* `align_to_boundaries` × `extrinsic` re-sweep (Milestone M5)

**This task is explicitly deferred and awaiting a decision** — do not start it as part of
this milestone's automatic run. It is scoped here only so it can be triggered later as its
own unit, conditional on what Task 2's re-ranking shows (**D13**): if G3/high-curvature
fidelity turns out uncorrelated with `align_to_boundaries`, there may be nothing to gain
from sweeping it; if the new ranking surfaces a cluster of trials all failing G2
specifically, that is the signal to actually run this.

If and when triggered: sweep `align_to_boundaries` ∈ {0, 1} × `extrinsic` ∈ {0, 1} (4 new
trials) at the new best `vertex_count`/`crease_angle`/`smooth_iter` from Task 2, reusing
`tune_params.py`'s `run_trial()`/`trial_params()`/`trial_name()` with minimal extension
(sweep two more previously-fixed fields; encode them in the trial name, e.g.
`_a{0,1}_e{0,1}`), logged into the same `tuning_results.jsonl` under a new `stage` value
(e.g. `'stage3_boundary'`). Re-rank the 4 new rows through Task 2's `rank_trials.py` against
the same gates. **No native-code change** (`fill_holes` exposure, curvature-adaptive sizing)
is in scope even if this task is triggered — those stay future options only.

## Exit criteria

- Task 1 and Task 2's criteria above, both met with zero new `im_remesh` calls.
- Task 3 remains unstarted, with no `M5.3` unit added to `plan/run.manifest.json`, unless
  and until the owner explicitly triggers it after reviewing Task 2's findings.
