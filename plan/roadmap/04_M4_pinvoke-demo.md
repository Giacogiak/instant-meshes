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
