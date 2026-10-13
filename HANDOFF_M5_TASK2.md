# Handoff — M5 Task 2: Constraint-first re-ranking of the 137 existing trials

Unit `M5.2`, plan `plan/roadmap/05_M5_locality-reranking.md`. Everything is in the commit
that adds this file.

**Status: done, and a human check is needed.** `scripts/rank_trials.py` has re-ranked all 137
trials that M3 logged. It made no `im_remesh` call. Every mesh's sha256 matched the log.
It wrote `tuning_runs/rank_results.jsonl`. The new #1 is a mesh nobody has opened yet, and
it wins partly because it has more vertices (see "The count caveat"). This milestone does
**not** conclude that the mesh is fixed.

## Result

| | M3/D8 pick `v2799_coff_s1` | **new #1 `v3450_c45_s2`** | target |
|---|---|---|---|
| gates G1 / G2 / G3 | pass / pass / pass | pass / pass / pass | — |
| **new rank** (of 87 that pass) | **#69** | **#1** | — |
| M3 aggregate (rank of 137) | 0.146129 (#2) | 0.238218 (#81) | 0 |
| params `vertex_count / crease_angle / smooth_iter` | 2799 / off / 1 | **3450 / 45 / 2** | — |
| V / F (ΔV) | 11355 / 11415 (+2.5%) | **13975 / 14066 (+26.1%)** | 11082 / 11054 |
| high_curv p95 (÷ diag) and ratio to target | 3.075e-3 (1.817×) | **2.093e-3 (1.237×)** | 1.692e-3 |
| high_curv mean / max | 1.058e-3 / 6.38e-3 | 8.89e-4 / 6.42e-3 | 6.20e-4 / 3.75e-3 |
| low_curv p95 (ratio) | 1.008e-3 (1.26×) | 8.31e-4 (1.04×) | 7.98e-4 |
| global fidelity mean (as M3 logged it) | 3.00e-4 | 2.65e-4 | 2.90e-4 |
| boundary edges (near high curvature) / components / largest | 74 (32) / 4 / 22 | **0 / 0 / 0** | 242 (20) / 17 / 26 |
| degenerate quads | 0 | 0 | 0 |

**Mesh for the owner to open: `tuning_runs/meshes/v3450_c45_s2.obj`**, sha256
`39ac0ca26d61…` (it matches the log). Open it next to `source.obj` and
`tuning_runs/meshes/v2799_coff_s1.obj`. The owner described the problem as "dents that make
the shape jagged, in respect to the original curve". Look for that in the high-curvature
regions, and also look at the open boundaries.

**Why `v3450_c45_s2` beat `v2799_coff_s1`:**
1. **`smooth_iter` 2 instead of 1.** This is the largest effect in the data. Mean
   high-curvature p95 ratio per level: s0 2.339, s1 1.903, **s2 1.534**, s4 1.610. G3
   rejects 36 of the 37 `smooth_iter=0` trials. `smooth_iter=1`, D8's value, is the
   second-worst level.
2. **`vertex_count` 3450, which gives 26% more vertices than the target.** This is the
   top of the swept range. Mean ratio per level falls steadily as the count rises, from
   2.228 at 1972 to 1.600 at 3450. A denser mesh simply follows the surface more closely.
   That is why this is a caveat, not a finding.
3. **No artifact boundary at all.** Only 3 trials have none, all of them `v3450_c45_*`.
   `v2799_coff_s1` has 74 boundary edges, 32 of them next to high curvature.

It wins on both curvature buckets, not only on the one used for ranking.

### The count caveat, and the alternative closest to D8

The ranking the plan specifies controls nothing about vertex count. 5 of the top 6 have
+7% to +26% more vertices than the target. **Among the 49 passing trials within ±5% of the
target's V:**

| new rank | trial | ΔV | hi-p95 ratio | lo-p95 (ratio) | bnd edges | M3 aggregate |
|---|---|---|---|---|---|---|
| #7 | v2799_c20_s2 | +3.1% | 1.390 | 2.27e-3 (2.85×) | 52 | 0.2437 (#89) |
| #8 | v2799_c20_s4 | +3.1% | 1.404 | 2.25e-3 (2.82×) | 52 | 0.2465 (#91) |
| #9 | v2731_c20_s4 | +1.6% | 1.407 | 2.23e-3 (2.79×) | 70 | 0.2346 (#76) |
| **#13** | **v2799_coff_s2** | **+2.5%** | **1.424** | **9.71e-4 (1.22×)** | 74 | **0.1497 (#5)** |
| #15 | v2731_c20_s2 | +1.6% | 1.430 | 2.23e-3 (2.79×) | 70 | 0.2343 (#74) |

The `crease_angle=20` trials buy their high-curvature fit with low-curvature regions 2.8×
worse than the target. That is the D12 problem below. **`v2799_coff_s2`** keeps D8's
parameters except `smooth_iter` 1 → 2:
- Same V/F as D8 (+2.5%).
- High-curvature p95 1.82× → **1.42×**; low-curvature p95 1.26× → 1.22×.
- M3 aggregate #5.
- It is the best trial within the count band under the `worst_bucket` ranking (rank 7
  there overall, behind five +6–26% trials and `v2868_c45_s2` at +5.9%).

If the owner wants a trial at the target's density, this is the obvious second mesh to open:
`tuning_runs/meshes/v2799_coff_s2.obj`.

## What changed and why

| File | Change |
|---|---|
| `scripts/rank_trials.py` | New. A CLI with no required arguments; the defaults point at `tuning_results.jsonl`, `tuning_runs/meshes/` and `tuning_runs/rank_results.jsonl`. It does steps 1–6 of the plan (details below). No `ctypes`, no `subprocess`, no `im_remesh`. |
| `scripts/score_remesh.py` | `ratio()` was moved out of `aggregate()` to module level, with the same body, and `aggregate()` calls it. **The plan says to reuse `aggregate()`'s `ratio()` helper, but it was a closure and could not be imported.** Moving it changes no result: the score self-check gives 0.000000 and the 20 original tests pass unchanged. |
| `tests/test_rank_trials.py` | New, 9 tests (see "Tests run"). It reuses `test_mesh_locality`'s bent-strip fixtures. |
| `plan/roadmap/05_M5_locality-reranking.md` | A status note after Task 2: the `ratio()` correction and the count caveat. The criteria are unchanged. |

### `rank_trials.py` design

1. **Inputs.** It reads every row of the log with `remesh.rc == 0` (all 137) and refuses
   duplicate names. Each mesh is found **by its file name under `--mesh-dir`**, not by the
   absolute path in the log, so the tree can be moved.
2. **Verification.** Each mesh gets a status of `ok`, `missing` or `sha256 mismatch`.
   - A mesh that is not `ok` is printed as `NOT VERIFIED <name>: <status>`.
   - It stays in the output with `locality`/`gates`/`rank` set to null.
   - It makes the **exit status 1**, so a stale tree cannot pass unnoticed.
   - Separately, the degenerate-quad count recomputed from the mesh must equal the logged
     one, or the script raises an error.
3. **Locality.** It builds one `score_remesh.Reference` and one
   `mesh_locality.LocalityReference`, whose target locality gives G3's denominator. Trials
   then run on a **fork** pool (`--workers`, default 4), so each worker inherits the built
   reference instead of rebuilding it. `samples`/`seed` come from the log's
   `score_settings`, and the script refuses a log that mixes settings.
4. **Gates.** All limits are inclusive (`<=`):
   - G1: `degenerate_quads == 0`.
   - G2: `largest_boundary_component_edges <= N`. N comes from `--g2-max`, or by default
     the `--g2-pctl` (95) percentile of the verified trials.
   - G3: `high_curv p95 <= k × target`, with k from `--g3-k` (2).
5. **Rank.** `rank_key` stores `score_remesh.ratio()` of the high- and low-curvature p95
   and of the global `fidelity.mean`, each against the target, plus
   `worst_bucket = max(high, low)`. `--rank-by high_p95` (the default) or `worst_bucket`
   picks the primary key. Ties are broken by the fidelity-mean ratio, then by name.
6. **Output.** One row per trial, rewritten on every run (through a temporary file and
   `os.replace`). Fields:
   - `name`, `stage`, `params`
   - `mesh {path, sha256, status}`
   - `aggregate`, `aggregate_rank`, `dV_pct`, `fidelity_mean`
   - `gates {G1, G2, G3}`, `passed`, the full `locality`, `rank_key`, `rank`
   - `settings`: pctl, radius, samples, seed, source/target sha256 and every gate limit,
     so each row is self-describing.

   The report prints the following, in the style of `tune_params --report`:
   - the verification summary
   - the trials each gate rejects
   - D10's and D11's distributions and histograms
   - the passing top 10
   - the top 5 under the other D12 key
   - the top 5 within ±5% of the target's V
   - Spearman correlation with the M3 aggregate
   - each parameter's main effect
   - `--compare`'s (default `v2799_coff_s1`) gate status and rank
   - the new #1 with its mesh path, and a metric-by-metric comparison of the two

## Exit criteria

The plan has one `## Exit criteria` for the whole of M5, plus a block for Task 1 and
Task 2 together. This unit reaches the Task 2 part of that block:

- **`mesh_locality.py` standalone run — met by M5.1.** This unit did not touch it.
- **`rank_trials.py` re-ranks all 137 and writes `tuning_runs/rank_results.jsonl` with
  zero new `im_remesh` calls — met.**
  - Command: `toolbox run -c instant-meshes-build python3 scripts/rank_trials.py`, which
    is exactly the driver's `rank-trials` check. rc 0, 137 of 137 verified, 137 rows
    written.
  - `grep -c "ctypes\|subprocess\|im_remesh\|load_core" scripts/rank_trials.py` prints 0.
    M5.1's caveat still applies: importing `tune_params`, for its paths and `read_log`,
    pulls `ctypes` into the process, but nothing loads the library.
  - The file is in `tuning_runs/`, which is gitignored, so it is **not committed**.
    Rerunning the command reproduces it, and the numbers in this handoff were identical
    on both full runs.
- **The report states `v2799_coff_s1`'s gate status and rank, and the new #1's name,
  params and why it won — met.** Both are in the Result section above, and the script
  prints both.
- **Unit tests — met.** `python3 -m unittest discover -s tests -p 'test_*.py'` → **Ran
  40 tests, OK**: the 20 original tests unchanged, M5.1's 11, and the 9 new ones.
- **`needsHumanCheck` and a named mesh path — met.** The mesh is
  `tuning_runs/meshes/v3450_c45_s2.obj`, plus `v2799_coff_s2.obj` as the
  count-matched alternative.
- **Phase-level bullet "Task 3 remains unstarted, no M5.3 added": still true.** I did not
  touch the manifest or Task 3. This bullet stays open until the owner decides D13.
- **Not met by any unit, by design:** the owner's visual review, and decisions D9–D12.
  D9 was decided before this unit.

**Conditions for every number:**
- Fedora 44 toolbox `instant-meshes-build`; Python 3.14.8, numpy 2.5.4, scipy 1.18.1,
  trimesh 5.1.1, no `rtree`.
- `source.obj` welded in memory, as in M5.1; `quad-remeshed.obj` as committed.
- `samples 100000, seed 0`, from the log; `pctl 10`, `radius_scale 1.0` (radius 2.1426),
  as decided for D9.
- G2 N = 44 (the trials' p95), G3 k = 2, `--rank-by high_p95`.

**Timing:**
- Building the reference and the curvature takes 26 s. The 137 trials then take **478 s**
  (first run, with the unit tests running alongside) and **630 s** (second run, alone, on
  a busier desktop), using 4 forked workers. The wall time was 8.5 and 11 min, against
  the check's 30-minute timeout.
- Each worker shows about 150% CPU, because numpy/scipy use threads inside each worker.
  On 8 logical CPUs, 4 workers therefore oversubscribe the machine somewhat. Worker RSS
  peaks at about 0.4–0.85 GB, and the machine (7.5 GB) dipped into swap.
- If the check ever comes close to its timeout, `--workers 2` is the first thing to try.
  I did not tune this.

## D10–D12: the defaults chosen and the data behind them

### D10 — G2 limit N on `largest_boundary_component_edges`: **N = 44** (p95 of the trials)

```
distribution: p0=0, p5=16, p10=16, p25=16, p50=22, p75=28, p90=34.8, p95=44, p100=92
histogram (edges:trials): 0:3 16:38 20:22 22:8 24:15 25:4 28:18 30:8 32:3 34:4 36:4 44:4 54:3 92:3
```

- **This rule is circular.** A percentile of the trials themselves can only ever reject
  the worst ~5%.
- Here it rejects 6 trials, which all have `crease_angle=45` at the two lowest vertex
  counts:
  - `v1972_c45_s{0,2,4}`: largest hole 92 edges, 264 boundary edges in total.
  - `v2341_c45_s{0,2,4}`: largest hole 54 edges, 114 in total.
- The cut falls in a real gap in the data (44 → 54 → 92), so it is a natural break and
  not an arbitrary cut. For scale, the target's own largest opening is 26 edges, but those
  are real openings and not comparable (see the M5.1 scoping note).
- Suggested for the owner: look at `v2341_c45_s2.obj`'s 54-edge hole. If even that looks
  acceptable, raise N; if holes of 28–36 edges already look broken, lower it.
- Lowering N to 28 would reject 23 more trials. It does not change the #1, which has 0.
- G2 does nothing for the #1 or for D8's pick.

### D11 — G3 multiplier k: **k = 2** (limit 3.385e-3)

```
high_curv p95 / target p95 over 137 trials:
  p0=1.237, p5=1.401, p10=1.428, p25=1.537, p50=1.743, p75=2.086, p90=2.382, p95=2.601, p100=2.933
histogram: [1.2,1.3):2 [1.3,1.4):5 [1.4,1.5):17 [1.5,1.6):26 [1.6,1.7):15 [1.7,1.8):7
           [1.8,1.9):8 [1.9,2.0):14 [2.0,2.1):10 [2.1,2.2):8 [2.2,2.3):6 [2.3,2.4):7
           [2.4,2.5):4 [2.5,2.6):1 [2.6,2.7):4 [2.7,2.8):1 [2.8,2.9):1 [2.9,3.0):1
```

- **No trial reaches the target.** The best is 1.237×. So the two-sided `ratio()`
  behaves exactly like "lower is better" on this data, and the concern from M2's D4 (that
  a trial could be penalized for being better than the target) never applies.
- k = 2 rejects **43** trials, 36 of them with `smooth_iter=0`. The distribution is
  bimodal, with modes around 1.5–1.6 and 1.9–2.1, and k = 2 cuts between them.
- k = 1.5 would keep only 23 trials and **reject D8's pick** (1.817×). k = 1.8 would keep
  68 and also reject it.
- The ranking already orders by this same metric, so k only decides what counts as
  "visibly broken". That is a visual judgement for the owner: where between 1.24×
  (`v3450_c45_s2`) and 1.82× (`v2799_coff_s1`) do the dents become unacceptable?

### D12 — rank formula: **`high_p95`** (the high-curvature p95 ratio), tie broken by the fidelity-mean ratio

- **Why `high_p95`:**
  - It is the literal measure of the owner's complaint: dents in curved regions. The
    owner described local, small-scale irregularity, and a p95 captures that better than
    a mean, which dilutes it.
  - M5.1 showed this metric is robust across D9 settings.
- **The risk the data shows:** the metric ignores the low-curvature regions.
  `crease_angle=20` trials take ranks #2, #3, #7, #8 and #9 while their low-curvature p95
  is **2.6–2.85×** the target's. Those meshes are probably worse on the flat parts.
- **The alternative is `--rank-by worst_bucket`**, which ranks by max(high, low ratio).
  - It removes all the `c20` trials from the top.
  - Its top 5: `v3450_c45_s2`, `v3081_coff_s2`, `v3081_c45_s2`, `v3450_coff_s2`,
    `v3450_c45_s4`.
  - **The #1 is the same under both keys**, so D12 does not change the headline. It does
    change ranks 2–10, and which trial is best within the count band.
- My recommendation: switch the default to `worst_bucket` if the owner agrees that the
  flat regions must not get worse. I did not switch it, because the plan names the
  high-curvature p95 as the primary key.

### New, not in the plan — D14? Vertex-count control

- Fidelity improves with density over the whole sweep, and the #1 sits at the top edge
  of the swept `vertex_count` range. `v3450` was only swept in stage 1, so it has 9
  trials.
- A constraint-first ranking with no count gate will keep preferring "more vertices" up
  to wherever the sweep stops.
- **Options:**
  - (a) Add a G4, e.g. |ΔV| ≤ 5% (49 trials pass). The best is then `v2799_c20_s2`
    under `high_p95`, or `v2799_coff_s2` under `worst_bucket`. Either is cheap to add.
  - (b) Accept the higher density, if the owner only cares about the shape. The cost is
    26% more faces.
  - (c) Keep the plan's rule, and treat the #1 as "the direction to go" rather than the
    answer.
- The report already prints the count-band view, so the owner can choose without
  rerunning.

## Other observations

- **Spearman correlation between the new primary metric and M3's aggregate:** 0.522
  over 137 trials. The two scores agree on the broad strokes (`smooth_iter=0` is bad)
  but not at the top.
- **G1 rejects 4 trials, `v2799_c45_s{0,1,2,4}`, each with 1 degenerate quad.**
  `v2799_c45_s2` (1.486×) would otherwise rank #24 of the passing trials. This is the
  "safety net" working, not noise.
- **For D13 (whether to run Task 3's `align_to_boundaries` × `extrinsic` re-sweep):**
  - Every one of the 137 trials used `align_to_boundaries=0, extrinsic=1`, so this data
    cannot show a correlation with either parameter.
  - What it does show:
    - G2 rejects only 6 trials, all `c45` at low vertex counts. No cluster of good-fit
      trials fails G2.
    - The trials with the fewest artifact boundaries are the dense ones, and the 3
      boundary-free trials are all `v3450_c45`.
  - By the plan's own trigger ("a cluster of trials all failing G2"), the signal to run
    Task 3 is **weak**. The high-curvature fit is driven by `smooth_iter` and density,
    not by boundaries.

## What I got wrong on the way

- **The plan says to reuse `aggregate()`'s `ratio()`.** I read `score_remesh.py` before
  coding and found that `ratio()` was a nested function, so I lifted it out. There was no
  other way to reuse it without reimplementing it.
- **My first test fixture used p95 values 0.9 and 1.1 to make an exact tie** in the
  distance to the target. In floating point, |0.9 − 1| and |1.1 − 1| differ in the last
  bit. I switched to 0.75 and 1.25, which are exact. This was a wrong expectation in the
  test, not a code bug.
- **`test_rank_trials.py` first failed to import `test_mesh_locality`** when run as
  `python3 -m unittest tests/test_rank_trials.py`. It now adds its own directory to
  `sys.path`, so it works both under `discover` and run on its own.
- **My first end-to-end test set G2's limit at 30.** The synthetic strip's single
  boundary loop has 88 edges, so the trial I meant to pass would have failed G2. I caught
  this while writing the test and set the limit to 100.
- **The first full run had only the `high_p95` view.** Its output showed the density and
  `c20` effects, so I added `--rank-by worst_bucket`, `dV_pct` and the count-band view,
  then re-ran. Both runs gave identical numbers.

## Still open

1. **Visual check of `tuning_runs/meshes/v3450_c45_s2.obj`**, and ideally
   `v2799_coff_s2.obj` too, against `source.obj`. Nobody has looked at them yet.
2. D10 (N = 44), D11 (k = 2), D12 (`high_p95` against `worst_bucket`) and the new count
   question (D14?) are the owner's. All four are flags (`--g2-max`, `--g3-k`, `--rank-by`),
   except a count gate, which would need about 10 lines.
3. D13, Task 3: I did not start it, and no M5.3 work was done. The evidence above leans
   against running it.
4. **`rank_results.jsonl` is not versioned** (it lives under `tuning_runs/`). If the
   owner wants it kept with the repo, it would need to move or be un-ignored. That is
   their call.

## Tests run

- `toolbox run -c instant-meshes-build python3 -m unittest discover -s tests -p
  'test_*.py'` → **Ran 40 tests, OK**. The 9 new tests:
  - `mesh_status`: ok / missing / sha256 mismatch, with the mesh found by its file name
    under the mesh directory.
  - G2's percentile default and its override; G3's limit.
  - A target with a high-curvature p95 of 0 is refused.
  - The gates are inclusive at the limit, and each one fails alone.
  - Ranking by closeness to the target, with an exact three-way tie broken by the
    fidelity-mean ratio. A trial that matches the target but fails G2 gets rank null.
    The `aggregate_rank` is checked too.
  - `worst_bucket` reverses an order that `high_p95` gives.
  - A missing mesh is kept unranked.
  - A mismatch between the logged and the recomputed degenerate-quad count raises an
    error.
  - **End to end** on a synthetic log:
    - Four trials: one stale and one deleted, so rc is 1 and both get a `NOT VERIFIED`
      line.
    - A 2×-offset copy of the target gives ratio 1.0 and rank 1.
    - The two-plates candidate fails G3, and the `--compare` line says so.
    - The forked run (2 workers) and the serial run give identical rows.
- The `rank-trials` check, run by hand as in the driver: `toolbox run -c
  instant-meshes-build python3 scripts/rank_trials.py` → rc 0. I ran it twice, and the
  numbers above are identical in both runs.
- The `score-script` check, because `score_remesh.py` changed:
  `score_remesh.py --source source.obj --target quad-remeshed.obj --candidate
  quad-remeshed.obj --out /tmp/score_selfcheck_m52.jsonl` → aggregate 0.000000, rc 0.
- I did not run `tuning-sweep`/`build-core`: this unit does not touch `tune_params.py`,
  CMake or the C API.

## For the next unit, or the owner's review

- To re-rank with different decisions, use
  `rank_trials.py --g2-max N --g3-k K --rank-by worst_bucket`. D9's settings are
  `--pctl` and `--radius-scale`. Each run takes about 10 min.
- A count gate would go next to `gates()` (`row['score']['delta']['dV_pct']` is already
  copied into each result as `dV_pct`). It would need one more key in `thresholds()` and
  a test.
- If Task 3 is ever triggered, its 4 new rows enter the log under a new `stage`.
  `rank_trials.py` ranks every `rc == 0` row in the log, so they will be picked up with
  no change. But G2's default N is a percentile over all trials, so 4 new rows will shift
  it slightly. Pass `--g2-max 44` to keep today's limit.
