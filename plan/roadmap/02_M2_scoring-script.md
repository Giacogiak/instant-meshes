# Milestone M2 — Scoring / Comparison Script

## Task 1 — Scoring / Comparison Script (Milestone M2)

Standalone, independent of M1 — runs directly against CLI-produced `.obj` files, so tuning can start before the native library exists.

- **Stack**: Python + `trimesh` + `numpy` + `scipy` (none currently installed in this environment — add a `pip install trimesh numpy scipy` setup step). `trimesh` handles `.obj` loading (quads preserved), surface sampling, and nearest-point queries without hand-rolled half-edge structures.
- **Script**: `scripts/score_remesh.py --source source.obj --target quad-remeshed.obj --candidate trial.obj --out results.jsonl`, appending one JSON line per invocation.
- **Metrics** (all reported individually, never collapsed to only the aggregate):
  1. **Count delta**: `ΔV`, `ΔF` vs. `quad-remeshed.obj`'s 11,082/11,054, raw and as % of target.
  2. **Quad quality**: per-face interior-angle deviation from 90° (mean + 90th percentile, computed from 3D corner vectors — don't assume planarity), edge-length coefficient of variation, and non-quad face fraction (should be 0 when `pure_quad=true`).
  3. **Valence distribution**: vertex valence histogram (counts of incident faces per vertex) for both candidate and target; report `% valence==4` and singularity count (valence≠4 interior vertices). Keep this clearly separate from the native pipeline's own `compute_orientation_singularities` count (an orientation-field pre-extraction count, not a realized-mesh valence count) — don't conflate the two numbers in reports.
  4. **Fidelity to `source.obj`**: sample points on the candidate's surface, compute nearest-surface distance back to `source.obj` (mean, RMS, 95th-percentile/max, normalized by source bounding-box diagonal). Compute the same for `quad-remeshed.obj` once, as the fidelity bar to match — the goal is `fidelity(candidate) ≈ fidelity(quad-remeshed)`, not `fidelity(candidate) → 0`.
- **Aggregate score**: weighted sum of the above, normalized to `[0,1]` per sub-metric, **starting with equal weights** (per the user's decision) — e.g. `score = mean(ΔV%, ΔF%, mean_angle_dev/45°, edge_length_CV, |%valence4_delta|, |fidelity_delta|/fidelity_target)`. Always print raw sub-metrics alongside the aggregate.
- **First run to perform once this script exists**: score `quad-remeshed.obj` itself against `source.obj` (treating Rhino's own output as the "candidate") to establish the fidelity baseline that Instant Meshes trials are chasing in metric 4.

> **Corrections from M2.1 (measured, see `HANDOFF_M2_TASK1.md`):**
> - **`trimesh` does not preserve quads.** `trimesh.load('quad-remeshed.obj', process=False)` returns 22,108 triangles for 11,054 quads. The script parses `v`/`f` records itself (polygons intact) and uses `trimesh` for area-uniform sampling and point-triangle closest points only.
> - **`trimesh`'s nearest-point queries need `rtree`**, which is not in `pip install trimesh numpy scipy` (`ModuleNotFoundError: No module named 'rtree'`). Nearest-surface distance is done with a `scipy` `cKDTree` over triangle centroids plus an exact bound check. It matches brute force exactly (0.0 error).
> - **Aggregate:** non-quad fraction is included as a 7th equal-weight term ("weighted sum of *the above*"). `--weight non_quad=0` reproduces the 6-term example formula exactly. Each term is clamped to `[0,1]`; 0 = best.
> - **Exit criterion 2's trial** was produced through the C API (`im_remesh`, 1 thread), because the GUI CLI does not configure under the toolbox's CMake 4.x. M1 showed this is byte-identical to `InstantMeshes -d -t 1`.

**Decided (giacomo forcina, 2026-10-12), resolving the M2.1 handoff's "Judgement calls":**
- **D3 — `non_quad` term:** keep it as a 7th equal-weight term by default (the implemented behavior). `--weight non_quad=0` remains available to reproduce the plan's literal 6-term example.
- **D4 — `angle`/`edge_cv` scoring:** changed from absolute cost to relative-to-target (`|x_candidate - x_target| / x_target`), consistent with the fidelity term's existing "match Rhino's result, not minimize toward zero" philosophy. Implemented in `aggregate()`; fixed a related edge case the change exposed (`ratio()` returning `None`→worst-cost when the target's own value is exactly 0, e.g. a perfectly regular test mesh, even when the candidate matches it exactly) — both now correctly score 0 in that case.
- **D5 — unscored defects** (degenerate quads, boundary/non-manifold edge mismatch, fidelity max tail): left as reported-only diagnostics, not folded into the aggregate, until M3's Stage-1 sweep shows whether the search actually exploits that blind spot.
- **D6 — source mesh welding:** `source.obj`'s 40 disconnected components with unwelded seams (10,287 near-coincident boundary-vertex pairs) are suspected to dominate the trial's boundary/degenerate-face defects more than any swept parameter. M3 must weld the source before sweeping — see `plan/roadmap/03_M3_tuning-harness.md`.

### Toolchain note for this unit

System `pip` is not installed and this environment has no preexisting Python virtualenv with `trimesh`/`numpy`/`scipy`. Install and run inside the `instant-meshes-build` toolbox container (see plan-run prompt notes) so `pip install` has a reliable base (`python3-pip` via `dnf`) without needing host `sudo`.

## Exit criteria

- Run `scripts/score_remesh.py` on `quad-remeshed.obj` vs. `source.obj` (self-check, i.e. `--candidate quad-remeshed.obj`).
- Run on a quick manual `InstantMeshes -v 11082 -p 4 -d` trial.
- Confirm all sub-metrics print sane, non-NaN values in both runs.
