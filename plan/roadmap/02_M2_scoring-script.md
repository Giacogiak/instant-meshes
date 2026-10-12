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

### Toolchain note for this unit

System `pip` is not installed and this environment has no preexisting Python virtualenv with `trimesh`/`numpy`/`scipy`. Install and run inside the `instant-meshes-build` toolbox container (see plan-run prompt notes) so `pip install` has a reliable base (`python3-pip` via `dnf`) without needing host `sudo`.

## Exit criteria

- Run `scripts/score_remesh.py` on `quad-remeshed.obj` vs. `source.obj` (self-check, i.e. `--candidate quad-remeshed.obj`).
- Run on a quick manual `InstantMeshes -v 11082 -p 4 -d` trial.
- Confirm all sub-metrics print sane, non-NaN values in both runs.
