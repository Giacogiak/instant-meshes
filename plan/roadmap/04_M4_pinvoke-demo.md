# Milestone M4 — C# P/Invoke Demo Project

## Task 1 — C# P/Invoke Demo Project (Milestone M4)

A minimal console app consuming `instantmeshes_core` (see M1, section 1.6 for the P/Invoke sketch), calling `im_remesh` on `source.obj` with the M3-discovered best parameters, then using the M2 scorer to confirm the P/Invoke path reproduces the CLI path's result (sanity check that the M1 `batch_process` refactor didn't change behavior). Since both platforms are in scope, this should be validated against both the Linux `.so` and Windows `.dll` builds before considering M1 complete (the Windows `.dll` validation is a manual/CI-elsewhere step in this environment — see the Exit criteria).

### Naming convention for this unit

Put the console app in `csharp-demo/` at the repo root (a single `.csproj` + `Program.cs` is enough). Give it a `--smoke-test` command-line switch that runs `im_remesh` once against `source.obj` with a small/fast parameter set and exits 0/non-zero — this is what the project's automated check runs.

### Toolchain note for this unit

No `.NET` SDK is on the host. Build and run inside the `instant-meshes-build` toolbox container (see plan-run prompt notes), which installs `dotnet-sdk` on first use.

## Exit criteria

- Run the C# console app on Linux (via the toolbox) and diff its `out_vertex_count`/`out_face_count` and output `.obj` against the equivalent direct CLI invocation's result — should be identical under `-d` (deterministic mode).
- The Windows `.dll` path is not buildable in this environment; document in the handoff that it still needs manual validation on a Windows machine or CI runner, and leave that as an explicit open item rather than claiming it as done.

**Status after M4.1 (2026-10-13):** the Linux criterion is met. The C# output is byte-identical to the current CLI's, the pre-M1 (`05138b8`) CLI's and M3's ctypes trial `v2799_coff_s1`, on both the welded and the raw source (evidence in `HANDOFF_M4_TASK1.md`). The Windows `.dll` path stays an **explicit open item, not yet validated**.

## Task 2 — Weld the demo's default input (Milestone M4)

**Decided (giacomo forcina, 2026-10-13), resolving M4.1's Open #2:** the demo's default input
is currently the raw `source.obj`, so running it unmodified does not reproduce M3's D8-tuned
quality (D8's `vertex_count=2799, crease_angle=off, smooth_iter=1` was tuned on the welded
mesh — see `plan/roadmap/03_M3_tuning-harness.md`'s "Weld (D6): tolerance and justification").
Rather than document this as an open item, port the weld into the demo so the project's
own entry point reproduces M3's result without a separate preprocessing step.

- Port `tune_params.weld()`'s exact-coincidence merge (scipy `cKDTree.query_pairs`, tolerance
  `1e-5` world units, transitive clustering to the lowest-index member — see
  `03_M3_tuning-harness.md`'s "Weld (D6)" section for the exact algorithm and why
  `trimesh.merge_vertices(digits_vertex=5)` was rejected) to C#, in `csharp-demo/Program.cs`
  or a new file in `csharp-demo/`. A KD-tree or grid-hash implementation is fine; it does not
  need to depend on a C# KD-tree package if a hash-based near-coincident merge at this
  tolerance is simpler to write and verify.
- Make it the demo's **default** behavior on `source.obj` (weld first, then remesh), not an
  opt-in flag — the goal is that running the demo with no arguments reproduces M3's result.
  Keep a flag (e.g. `--no-weld`) to remesh the raw input instead, for comparison/debugging.
- Verify the ported weld reproduces M3's Python weld exactly: same output vertex/face count,
  and ideally the same sha256 as `tuning_runs/source_welded.obj` (`b63990bc…`) — if the C#
  weld's numerics can't guarantee an identical file, it must at minimum produce an input that
  `im_remesh` turns into the *same output* as the Python-welded source did (compare the
  remeshed `.obj`'s sha256 against M3's logged `v2799_coff_s1` output, not just vertex counts
  — M4.1's negative control showed vertex/face counts alone can hide a real difference).

### Naming convention for this unit

Keep it inside `csharp-demo/`; do not create a second project. Name the welding entry point
clearly (e.g. `Welder.Weld(...)`) so it is easy to find from `Program.cs`.

## Exit criteria

- Running the demo on `source.obj` with no extra flags welds first, then remeshes with M3's
  D8 defaults, and the resulting `.obj`'s sha256 matches M3's logged `v2799_coff_s1` output
  (`fd857df8…`, from `HANDOFF_M4_TASK1.md`'s comparison table) — or, if exact sha256 match is
  not achievable, the scorer's aggregate score on the new output matches M3's logged
  `0.1461292849353033` exactly (not just approximately).
- `--no-weld` still remeshes the raw, unwelded input (the Task 1 behavior), for comparison.
- The existing `csharp-demo` check and `compare_with_cli.sh` still pass; update
  `compare_with_cli.sh` if its CLI-comparison step needs to weld its own input first to stay
  a fair comparison.
