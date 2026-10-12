# Handoff — M2 Task 1: Scoring / Comparison Script

Unit `M2.1`, plan `plan/roadmap/02_M2_scoring-script.md`. Code commits: `02a2dc8` (scorer,
tests, plan corrections) and `2742299` (degenerate-face fix).

**Status: done.** All three exit criteria were run and hold (evidence below). The aggregate
score has some design choices that the owner should look at before M3 optimises against it
(see "Judgement calls"). For that reason this unit asks for a human check.

## What changed and why

| File | Change |
|---|---|
| `scripts/score_remesh.py` | New. It has the CLI from the plan (`--source --target --candidate --out`, plus `--samples` (default 100000), `--seed` (default 0) and a repeatable `--weight NAME=VALUE`). It appends one JSON line per invocation and prints every raw sub-metric for candidate and target next to the aggregate. It can also be imported: `Reference(source, target)` loads the source and scores the target once, then `.score(candidate)` returns the record and `append_jsonl(path, record)` writes it. M3 can use that instead of starting a process per trial. |
| `tests/test_score_remesh.py` | New. 13 `unittest` tests on synthetic meshes with known answers (see "Tests run"). |
| `plan/roadmap/02_M2_scoring-script.md` | A "Corrections from M2.1" note: trimesh/rtree, the 7th aggregate term, and how the exit criterion trial was produced. |
| `.gitignore` | `__pycache__`. |

### Places where the plan was wrong (corrected in the plan file)

1. **trimesh does not preserve quads.** `trimesh.load('quad-remeshed.obj', process=False)`
   gives 22,108 triangles for the 11,054 quads. So the script parses `v`/`f` records
   itself, keeping polygons intact. It handles `i`, `i/j`, `i//k` and negative indices, and
   rejects faces with fewer than 3 vertices and out-of-range indices.
2. **trimesh's nearest-point queries need `rtree`.** `mesh.nearest.on_surface` raises
   `ModuleNotFoundError: No module named 'rtree'`, and rtree is not in the plan's (and the
   check's) `pip install trimesh numpy scipy`.
   - `SurfaceDistance` replaces it with an exact query: a `scipy` `cKDTree` over triangle
     centroids, the 16 nearest triangles first, then a bound check.
   - Any untried triangle is at least `d(16th centroid) − r_max` away. Points where that
     does not settle the answer are checked against every triangle with its centroid
     within `best + r_max`.
   - Point-triangle distances use `trimesh.triangles.closest_point`.
   - It is exact: 0.0 max error against brute force on 200 on-surface and 200 off-surface
     points for both meshes, and in a unit test with huge triangles. A unit test fails if
     the bound is weakened.
3. **The exit criterion's "manual `InstantMeshes -v 11082 -p 4 -d` trial"** was produced
   through the C API, as the M1 handoff suggested. The GUI CLI does not configure under the
   toolbox's CMake 4.x, and M1 showed the C API with 1 thread is byte-identical to the CLI
   `-d -t 1`.

## Metric definitions (what the numbers mean)

1. **Counts:** `V` = number of `v` lines, `F` = number of `f` lines. The target values
   are read from the target file (11,082 / 11,054), not hard-coded. Deltas are given raw
   and as % of the target.
2. **Quad quality** (quads only; other arities go into the non-quad fraction):
   - Corner angle is `atan2(|a×b|, a·b)` of the 3D vectors to the previous and next
     vertex, so no planarity is assumed.
   - Per-face value = mean `|angle − 90°|` over its 4 corners. Reported: the mean and P90
     over faces, plus the worst single corner.
   - **Degenerate quads** are counted and **kept** in the angle statistics so that they
     are penalised. These are quads with a zero-length edge, or that visit a vertex twice,
     such as `[a v a b]`. A corner with a zero-length edge counts as 90° off.
   - Edge-length CV = std/mean over the unique undirected edges.
3. **Valence:**
   - Valence is the number of **distinct** incident faces per vertex.
   - A vertex is *interior* if each of its edges lies in exactly 2 distinct faces.
   - `pct_valence4_interior` and `mesh_valence_singularities` (interior, valence ≠ 4) are
     computed over interior vertices only, so boundary vertices are not counted as
     irregular.
   - Histograms are given for all referenced vertices and for interior ones only.
   - The JSON key, the printed label and a printed footnote all say that this is the
     realized-mesh count, **not** `compute_orientation_singularities`.
4. **Fidelity:**
   - Sample 100,000 area-uniform points on the (fan-triangulated) mesh with
     `trimesh.sample.sample_surface(seed=0)`.
   - Take the exact distance from each point to the source surface, divided by the
     source bounding-box diagonal (219.9231).
   - Reported: mean, RMS, P95 and max.
   - The target is scored with the same samples count and seed on every invocation.
     Same inputs give an identical record apart from the timestamp, which M3's
     "logged score = fresh score" exit criterion depends on.
5. **Aggregate** = the weighted mean of 7 costs, each clamped to [0,1], where **0 is
   best**:
   - `count_v` = |ΔV|/V_t
   - `count_f` = |ΔF|/F_t
   - `angle` = mean angle deviation / 45°
   - `edge_cv` = the candidate's edge-length CV
   - `valence4` = |Δ%valence4| / 100
   - `fidelity` = |fid_mean_c − fid_mean_t| / fid_mean_t
   - `non_quad` = non-quad fraction
   - All weights are 1 by default. An undefined term (e.g. no quads at all) counts as 1.
   - The record also stores the terms, the weights, the sha256 of all three inputs and the
     library versions.
   - Every number in the record is checked to be finite before it is written. Undefined
     metrics are `null`.

## Exit criteria, one by one

Conditions for both runs:
- Fedora 44 toolbox `instant-meshes-build`, Python 3.14.8, numpy 2.5.4, scipy 1.18.1,
  trimesh 5.1.1, installed with `python3 -m pip install --user trimesh numpy scipy`, as
  the check does.
- `--samples 100000 --seed 0`.
- About 12 s wall time per invocation, including toolbox startup and scoring the target.
  The candidate's distance query is ~5 s of that.

### 1. Self-check (`--candidate quad-remeshed.obj`) — **met**

I ran the driver's exact `score-script` command (writing to `/tmp/score_selfcheck.jsonl`):
- exit 0, 0 lines matching `^(Traceback|Error)`, 1 JSON line written.

| metric | quad-remeshed.obj (= target) |
|---|---|
| V / F | 11082 / 11054 (ΔV = ΔF = 0) |
| angle dev mean / P90 / worst corner | 9.434° / 17.547° / 84.981° |
| degenerate quads | 0 |
| edge-length CV (mean edge 2.1426) | 0.5552 |
| non-quad fraction | 0.0000 |
| % valence 4 (interior) | 96.633 % (10,840 interior vertices) |
| mesh valence singularities | 365 (interior histogram 3:10, 4:10475, 5:350, 6:5) |
| boundary / non-manifold edges | 242 / 0 |
| **fidelity mean / RMS / P95 / max (÷ diag)** | **2.901e-4 / 4.366e-4 / 9.073e-4 / 4.429e-3** ← the fidelity baseline M3 chases |
| aggregate | **0.109257** (terms: angle 0.2096, edge_cv 0.5552, all others 0) |

### 2. Trial `-v 11082 -p 4 -d` — **met (via the C API)**

The trial was made with `/tmp/m2/make_trial.py`, a ctypes call to
`build-core/libinstantmeshes_core.so`:
- `im_set_thread_count(1)`;
- `rosy=4, posy=4, scale=-1, face_count=-1, vertex_count=11082, crease_angle=-1,
  extrinsic=1, align_to_boundaries=0, smooth_iter=2, knn_points=10, pure_quad=1,
  deterministic=1`.

Result: V=46322, F=41632, md5 `dde441c4…`, the same md5 M1 measured. Scored with the
default settings:

| metric | trial | target |
|---|---|---|
| V / F | 46322 / 41632 (ΔV +317.99 %, ΔF +276.62 %) | 11082 / 11054 |
| angle dev mean / P90 / worst corner | 3.768° / 9.560° / 90.000° | 9.434° / 17.547° / 84.981° |
| degenerate quads | 52 | 0 |
| edge-length CV (mean edge 0.9153) | 0.1706 | 0.5552 |
| non-quad fraction | 0.0000 | 0.0000 |
| % valence 4 (interior) | 99.043 % (36,788 interior) | 96.633 % |
| mesh valence singularities | 352 (interior histogram 2:108, 3:117, 4:36436, 5:124, 6:3) | 365 |
| boundary / non-manifold edges | 9512 / 52 | 242 / 0 |
| fidelity mean / RMS / P95 / max | 4.632e-5 / 1.607e-4 / 1.813e-4 / 6.771e-3 | 2.901e-4 / … |
| aggregate | **0.445545** (count_v 1, count_f 1, angle 0.0837, edge_cv 0.1706, valence4 0.0241, fidelity 0.8404, non_quad 0) | |

### 3. All sub-metrics sane and non-NaN in both runs — **met**

- I walked both JSON records: no `null` and no non-finite value. The script also enforces
  this on every run (`check_finite`, then `json.dumps(allow_nan=False)`).
- Sanity checks:
  - The self-check gives zero for every relative term, and identical candidate/target
    blocks.
  - The trial's V/F match the C API's `out_*_count`.
  - The angle and CV values are plausible for a denser, more uniform IM mesh.
  - Fidelity is ~0.03 % of the diagonal for the target; the brute-force check above is
    exact.

## Judgement calls the owner should look at (why `needsHumanCheck`)

1. **The 7th term, `non_quad`.** The plan's example formula has 6 terms, but its text says
   "weighted sum of *the above*", which includes the non-quad fraction. Without that term,
   a quad-dominant candidate would not be penalised for its triangles, because angles are
   measured on quads only. `--weight non_quad=0` (or `weights={'non_quad': 0}`) gives the
   exact 6-term formula.
2. **`angle` and `edge_cv` are absolute, not relative to the target**, as in the plan's
   formula. The target itself costs 0.2096 + 0.5552, so the target's own score is 0.109,
   not 0.
   - Its edge-length CV is high (0.555): Rhino's remesh is size-adaptive.
   - So a uniform IM mesh beats the target on `edge_cv` (the trial: 0.17). M3 will be
     pushed toward uniformity, not toward Rhino's adaptivity.
   - If "match the target" is the intent, `|CV_c − CV_t| / CV_t` would be the alternative.
     That is a one-line change in `aggregate()`.
3. **`fidelity` penalises being *closer* to the source than the target**, as the plan
   specifies ("≈ target, not → 0"). The 4× denser trial is 6× closer and pays 0.84 for it.
   That is correct per the plan, but it is worth knowing when reading M3 results.
4. **Defects that are reported but not in the aggregate:**
   - degenerate quads (52 in the trial);
   - boundary and non-manifold edges (9512 / 52 vs. 242 / 0);
   - the fidelity tail (max is worse than the target: 6.8e-3 vs. 4.4e-3).
   - One-sided fidelity (candidate → source) is what the plan asks for. Source → candidate,
     which would catch dropped regions, is **not** computed.

## What I got wrong on the way

- My first version counted incident face *occurrences* per vertex and edge. Instant
  Meshes' pure-quad output contains `[a v a b]` faces (52 in the trial, probably from
  subdividing the irregular faces). They made `v` look like an interior vertex of
  valence 1, so the trial showed interior vertices of valence 1 and 2.
  - Fixed in `2742299`: valence and edge multiplicity count distinct faces, and these
    faces are reported as degenerate.
  - Two new tests cover it; both fail on the old code.
  - The trial's singularity count went from 370 to 352.
  - The remaining 108 interior valence-2 vertices are genuine doublets (two quads sharing
    two consecutive edges).
- My first `.gitignore` edit appended `__pycache__` to `build-core`, which had no trailing
  newline, so the line became `build-core__pycache__` and un-ignored `build-core/`. I
  caught it before the handoff and amended the (unpushed) commit.
- In one unit test I first expected the wrong valence histogram; the code was right.

## Open

1. **Source → candidate fidelity** (the reverse direction, Hausdorff-style) is not
   implemented. It would cost about another 5 s per candidate with `SurfaceDistance` on
   the candidate.
2. **The distance query** falls back to the ball search for ~99 % of points: `r_max` = 2.13
   is about 4× the median triangle radius of 0.48. It is still exact and takes ~5 s per
   100k samples. If M3 needs it faster, the options are fewer `--samples`, or splitting
   off the few large triangles into their own tree.
3. **The aggregate design questions** above (relative vs. absolute `angle`/`edge_cv`, the
   `non_quad` term).

## Tests run

- `toolbox run -c instant-meshes-build python3 -m unittest discover -s tests -p 'test_*.py'`
  (from the repo root): **13/13 OK**, 0.36 s. The tests cover:
  - OBJ parsing (plain, `//`, negative indices; quads kept);
  - grid / rhombus / non-planar quad angles and CV;
  - degenerate quads;
  - non-quad fraction;
  - grid valence (boundary handled);
  - a cube (8 valence-3 singularities);
  - a face that revisits a vertex;
  - exact distance vs. brute force with huge triangles;
  - an offset plane giving exact fidelity;
  - end-to-end CLI: self-check terms are 0, one JSONL line per invocation, hand-computed
    terms and aggregate, `--weight`;
  - determinism across `Reference` instances;
  - the non-finite guard.
- The driver's `score-script` check command, verbatim: exit 0, no fail-pattern lines.
- `ctest` in `build-core` (no native code changed): 1/1 passed, 4.4 s.

## For the next units

- **M3:**
  - `import score_remesh` (add `scripts/` to `sys.path`), build one
    `Reference('source.obj', 'quad-remeshed.obj')` per process (~6 s), then call
    `ref.score(path)` per trial (~5–6 s) and `append_jsonl(...)`.
  - Records hold the candidate's sha256. The score is deterministic for the same file,
    samples and seed, so M3's "logged = fresh" check should compare `aggregate.score`
    exactly.
- **The pure-quad size anchor** is confirmed: `vertex_count = 11082` gives 46k V, so the
  count terms saturate at 1 and give **no gradient** until V is within 100 % of the
  target. Anchor near ~2,770 as the M3 plan's M1 note says.
- **Finding:**
  - `source.obj` is **40 connected components with unwelded seams**: 20,017 boundary
    vertices, 10,287 exactly coincident (< 1e-6) boundary vertex pairs.
  - Instant Meshes treats those seams as open boundaries. That is very likely why the
    trial has 9,512 boundary edges against the target's 242, and why it has the
    degenerate/non-manifold faces.
  - Welding the source before remeshing (e.g. `trimesh` `merge_vertices`) may matter more
    than any swept parameter. `align_to_boundaries` is also relevant.
  - Not done here, since this is not M2's scope.
