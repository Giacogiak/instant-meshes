# Milestone M3 — Parameter Tuning Harness

## Task 1 — Parameter Tuning Harness (Milestone M3)

**Decided (giacomo forcina, 2026-10-12), amending the original plan:** M1's `instant-meshes-build`
toolbox has CMake 4.x, and the vendored `ext/nanogui/ext/glfw` submodule's `CMakeLists.txt`
sets a `cmake_policy` that CMake 4 rejects outright — the full-GUI `InstantMeshes` target
cannot configure there (pre-existing breakage, not caused by M1). Rather than patch the
vendored submodule or pin an older CMake, M3 calls `instantmeshes_core`'s C API
(`im_remesh`, built in M1) **directly** instead of shelling out to the GUI CLI. M1's own
handoff confirmed this produces byte-identical output to the CLI (`-d -t 1`), so this is a
pure implementation-path change, not a behavior change. Use Python `ctypes` (or `cffi`) to
bind `im_remesh`/`im_remesh_params`/`im_remesh_result` from `src/capi.h` and call it from
`scripts/tune_params.py`; no GLFW/X11/OpenGL toolchain is needed for this milestone at all.

Map the originally-planned CLI flags onto `im_remesh_params` fields:
- `-v <v>` → `vertex_count = v`, `face_count = -1`
- `-c <c>` → `crease_angle = c` (or `-1` for "off")
- `-S <s>` → `smooth_iter = s`
- `-p 4` → `posy = 4`, `pure_quad = 1`
- `-r 4` (conventional pairing with `-p 4`) → `rosy = 4`
- `-d/--deterministic` → `deterministic = 1` — without it, TBB's parallel reductions make
  `optimizeOrientations`/`optimizePositions` nondeterministic run-to-run, which would inject
  noise into the score and corrupt the search signal; always set it.
- `scale = -1` (unset, letting `vertex_count` drive sizing, per the plan's original note that
  `-f`/`-v`/`-s` are three parameterizations of the same underlying scale)

> **Measured in M1.1 (read before choosing the anchors below):**
> - **`deterministic = 1` alone is not enough.** With >1 TBB thread, repeated `-d` runs still differ (8 threads: V=46401 vs. V=46313 for the same input and params). Runs are byte-identical only with **one thread**: call `im_set_thread_count(1)` once per process, before the first `im_remesh`. It can only be set once per process, so for parallelism run several single-threaded worker *processes* rather than threads.
> - **`pure_quad = 1` applies one subdivision step**, so the output has ~4× the requested size. Via ctypes, `vertex_count = 11082` with `rosy = posy = 4`, `smooth_iter = 2` and 1 thread gave **V=46322, F=41632**, not ~11k. To land near the target's 11,082 V / 11,054 F in pure-quad mode, the swept `vertex_count` must be anchored near **~2,770 (11,082 / 4)**, not 11,082. Verify the anchor with a trial before the grid.
> - Library path: `build-core/libinstantmeshes_core.so`. `ctypes.sizeof(im_remesh_params)` is 48 (10 `c_int` + 2 `c_float`, in header order). `im_remesh` logs progress to stdout.

### Weld `source.obj` before sweeping (decision D6, 2026-10-12)

M2.1 found `source.obj` is **40 disconnected components with unwelded seams** (20,017
boundary vertices, 10,287 pairs coincident within 1e-6). Instant Meshes treats those seams
as open boundaries, which is very likely why M1's own `vertex_count=11082` trial had 9,512
boundary edges against the target's 242, plus degenerate/non-manifold faces — probably
swamping any signal from the swept parameters. **Before Stage 1**, produce a welded copy
(e.g. `source_welded.obj`, via `trimesh.load(..., process=False)` then
`merge_vertices(digits_vertex=5)` or equivalent — tune the tolerance so it merges only the
near-coincident (<1e-6) boundary pairs M2 measured, not unrelated nearby geometry) and feed
**that** to every `im_remesh` call in the sweep. Keep scoring against the original,
unwelded `source.obj` and `quad-remeshed.obj` exactly as M2 already does — welding changes
only what Instant Meshes remeshes, not the fidelity ground truth. Report the welded mesh's
boundary-edge count (should land near the target's 242, not 9,512) as part of validating
the weld before using it for the sweep proper, and note the chosen tolerance and its
justification in the handoff.

> **Corrections from M3.1 (measured, 2026-10-13):**
> - **The D6 boundary-edge numbers compare different things.** 9,512 is the boundary-edge count of M1's *remesh output* from the unwelded source; the unwelded `source.obj` itself has 20,392. Welding at tolerance 1e-5 gives a **closed** source (0 boundary edges, 0 non-manifold, 1 component), so the welded source does not "land near 242": it lands at 0. The comparable remesh output, with M1's exact params (`vertex_count=11082`, `smooth_iter=2`, crease off), has 0 boundary edges from the welded source and 9,512 from the unwelded one; the sweep's outputs have 0-264 (best: 52). The exit criterion is evidenced with both counts in `HANDOFF_M3_TASK1.md`.
> - **The pure-quad anchor holds on the welded source too:** `vertex_count=2770` gave V=11,240, so the sweep calibrates the centre to 2,731 (= 2770 x 11082 / 11240), and Stage 1 multiplies the plan's {8000 ... 14000}/11082 ratios onto that.
> - **Stage 2 is a finer grid**, not `scipy.optimize`: `vertex_count` integer, `smooth_iter` integer and a non-smooth response (neighbouring trials differ by ~0.005-0.01) make Nelder-Mead/Powell a poor fit; 5 x 5 x 4 trials run in ~6 min on 4 workers.

- **Swept**: `vertex_count` (anchored near 11,082), `crease_angle` (off, 20°, 30°, 45°, 60°), `smooth_iter` (0, 1, 2, 4).
- **Fixed**: `posy = 4`, `pure_quad = 1` (matches `quad-remeshed.obj`'s 100%-quad composition), `rosy = 4`.
- **Always on**: `deterministic = 1` (see above).
- **Search strategy**:
  1. **Stage 1 — coarse grid search** over `vertex_count` × `crease_angle` × `smooth_iter` (e.g. `vertex_count` ∈ {8000, 9500, 11082, 12500, 14000}, `crease_angle` ∈ {off, 30, 45}, `smooth_iter` ∈ {0, 2, 4}) — cheap, trivially parallelizable (independent `im_remesh` calls, each with its own output path), surfaces the overall response shape.
  2. **Stage 2 — local refinement** around the Stage-1 best point (tighter grid, or `scipy.optimize.minimize` with `Nelder-Mead`/`Powell` wrapping "call `im_remesh` → score" as the objective, focused on `crease_angle`/`smooth_iter` once Stage 1 has anchored `vertex_count`).
- **Logging**: one row per trial (full param set + raw sub-metrics + aggregate score) to a CSV/JSONL — the artifact that becomes the M3 deliverable (best params found + a short write-up of which parameter the score was most sensitive to).

### Optional secondary pass (not the primary mechanism)

Once a numerically-best parameter set is found, an LLM-in-the-loop step (the `/loop` skill) can do a qualitative spot-check — e.g. visually inspecting the worst-scoring or borderline trials for singularity placement or crease artifacts the aggregate score under-weights. This is explicitly secondary: a plain scripted search (this task) is the primary mechanism, not an LLM-driven loop tool.

### Naming convention for this unit

Name the sweep driver script `scripts/tune_params.py` and the trial log `tuning_results.jsonl`, and give the script a `--smoke-test` flag that runs exactly one cheap trial end-to-end (build `instantmeshes_core` if not already built, one `im_remesh` call via ctypes, one scoring call, one logged row) and exits 0/non-zero accordingly — this is what the project's automated check runs.

### Toolchain note for this unit

Building `instantmeshes_core` (`IM_CORE_ONLY=ON`) needs only a C/C++ compiler and CMake/Ninja — no GLFW/X11/OpenGL — so this unit does not need the full-GUI target at all. Build and run inside the `instant-meshes-build` toolbox container (see plan-run prompt notes), reusing M1's `build-core` CMake invocation.

## Exit criteria

- `source.obj` is welded before the sweep (D6); the welded mesh's boundary-edge count is measured and reported, and is substantially closer to the target's 242 than the unwelded mesh's 9,512.
- After the sweep, re-run the single best parameter set standalone and confirm the logged score matches a fresh scorer invocation (no drift from caching/logging bugs).
- `scripts/tune_params.py --smoke-test` must run one trial end-to-end and exit 0.
