# Milestone M3 — Parameter Tuning Harness

## Task 1 — Parameter Tuning Harness (Milestone M3)

Runs directly against the built `InstantMeshes` CLI binary (no need to wait on M1 — faster iteration):
```
InstantMeshes source.obj -o trial_<id>.obj -v <v> -c <c> -S <s> -p 4 -d
```

- **Swept**: `-v` (vertex count target, anchored near 11,082; `-f`/`-v`/`-s` are three parameterizations of the same underlying scale via `stats.mSurfaceArea`, batch.cpp:78-90, so sweeping only `-v` is sufficient), `-c` (crease angle: off, 20°, 30°, 45°, 60°), `-S` (smooth iterations: 0, 1, 2, 4).
- **Fixed**: `-p 4` (pure quad, matches target style), `-D` omitted (keeps `pure_quad=true`, matching `quad-remeshed.obj`'s 100%-quad composition), `-r 4` (conventional pairing with `-p 4`).
- **Always on**: `-d/--deterministic` — without it, TBB's parallel reductions make `optimizeOrientations`/`optimizePositions` nondeterministic run-to-run (CMakeLists.txt:163-164 links `tbb_static`), which would inject noise into the score and corrupt the search signal.
- **Search strategy**:
  1. **Stage 1 — coarse grid search** over `-v` × `-c` × `-S` (e.g. `-v` ∈ {8000, 9500, 11082, 12500, 14000}, `-c` ∈ {off, 30, 45}, `-S` ∈ {0, 2, 4}) — cheap, trivially parallelizable (independent subprocesses), surfaces the overall response shape.
  2. **Stage 2 — local refinement** around the Stage-1 best point (tighter grid, or `scipy.optimize.minimize` with `Nelder-Mead`/`Powell` wrapping "run CLI → score" as the objective, focused on `-c`/`-S` once Stage 1 has anchored `-v`).
- **Logging**: one row per trial (full param set + raw sub-metrics + aggregate score) to a CSV/JSONL — the artifact that becomes the M3 deliverable (best params found + a short write-up of which parameter the score was most sensitive to).

### Optional secondary pass (not the primary mechanism)

Once a numerically-best parameter set is found, an LLM-in-the-loop step (the `/loop` skill) can do a qualitative spot-check — e.g. visually inspecting the worst-scoring or borderline trials for singularity placement or crease artifacts the aggregate score under-weights. This is explicitly secondary: a plain scripted search (this task) is the primary mechanism, not an LLM-driven loop tool.

### Naming convention for this unit

Name the sweep driver script `scripts/tune_params.py` and the trial log `tuning_results.jsonl`, and give the script a `--smoke-test` flag that runs exactly one cheap trial end-to-end (build/skip build, one `InstantMeshes` invocation, one scoring call, one logged row) and exits 0/non-zero accordingly — this is what the project's automated check runs.

### Toolchain note for this unit

Building the full-GUI `InstantMeshes` CLI binary needs a C/C++ compiler plus GLFW/X11/OpenGL dev headers, none of which are on the host. Build and run inside the `instant-meshes-build` toolbox container (see plan-run prompt notes).

## Exit criteria

- After the sweep, re-run the single best parameter set standalone and confirm the logged score matches a fresh scorer invocation (no drift from caching/logging bugs).
- `scripts/tune_params.py --smoke-test` must run one trial end-to-end and exit 0.
