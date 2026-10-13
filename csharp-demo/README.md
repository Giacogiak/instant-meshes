# C# P/Invoke demo (Milestone M4)

A console app that calls `im_remesh` from the `instantmeshes_core` shared library
(`src/capi.h`) through P/Invoke. Target framework: `net8.0`.

## Build and run (Linux, inside the `instant-meshes-build` toolbox)

```sh
# 1. The native library (M1), once
cmake -S . -B build-core -G Ninja -DIM_CORE_ONLY=ON -DCMAKE_BUILD_TYPE=Release
cmake --build build-core --target instantmeshes_core

# 2. The demo; the build copies build-core/libinstantmeshes_core.so next to the assembly
sudo dnf install -y dotnet-sdk-8.0
dotnet build csharp-demo
dotnet run --project csharp-demo -- --smoke-test     # one small remesh, exits 0 on success
dotnet run --project csharp-demo -- --input tuning_runs/source_welded.obj --output out.obj
```

Without options the demo remeshes `<repo>/source.obj` to `remeshed_csharp.obj` with M3's
recommended set (decision D8): `-v 2799`, no crease angle, `-S 1`, pure quad,
deterministic, 1 thread. `--help` lists the options, which mirror the CLI's flags.

M3 tuned that set on the **welded** source (`tuning_runs/source_welded.obj`; write it with
`python3 -c "import sys; sys.path.insert(0, 'scripts'); import tune_params; tune_params.make_welded_source()"`).
On the unwelded `source.obj`, every parameter set leaves holes along the part's seams.

The output is reproducible only with one thread (`--threads 1`, the default):
`im_set_thread_count` is called once, before the first `im_remesh`.

## Finding the native library

`DllImport("instantmeshes_core")` resolves `libinstantmeshes_core.so` /
`instantmeshes_core.dll` next to the assembly. The `.csproj` copies it there from
`$(ImCoreDir)` (default `../build-core`; it also looks in `build-core/Release` for the
`.dll` of a Visual Studio build). Override with `dotnet build -p:ImCoreDir=<dir>`. If the
library was not there at build time, the app falls back to `$IM_CORE_LIB`, then to
`<repo>/build-core`.

## Parity with the CLI

`compare_with_cli.sh <"Instant Meshes" binary> <input mesh> [work dir]` runs the demo with
its defaults and the CLI with the equivalent `-d -t 1 -v 2799 -S 1`, then compares the
V/F counts, the output files byte for byte, and the M2 scorer's records for both. It
needs the GUI build of the CLI (see `HANDOFF_M4_TASK1.md` for how it was built here).

## Windows

Not validated yet. Build `instantmeshes_core.dll` with Visual Studio
(`cmake -G "Visual Studio …" -A x64 -DIM_CORE_ONLY=ON`), then `dotnet build csharp-demo`
and `dotnet run --project csharp-demo -- --smoke-test`.
