# Milestone M1 — GUI-Free Native Library + C API

## Task 1 — GUI-Free Native Library + C API (Milestone M1)

### 1.1 Why the GUI dependency can be dropped for this target

`src/batch.cpp`'s `batch_process()` function (declared `src/batch.h:18-22`) is already GUI-free end to end — confirmed by tracing its includes (`meshio`, `dedge`, `subdivide`, `meshstats`, `hierarchy`, `field`, `normal`, `extract`, `bvh` — no `glutil`/`viewer`/`widgets`/`nanogui`) and by grepping all of `src/*.{h,cpp}` for `nanogui|glutil|GLFW|opengl`, which only matches `glutil.*`, `widgets.*`, `viewer.*`, and `main.cpp`. `main.cpp:175-186` already shows that passing `-o <output>` with exactly one positional input returns from `batch_process` **before** `nanogui::init()` is ever reached — the existing CLI binary is already runtime-headless when invoked this way; it just isn't a separate build artifact, and `serializer.{h,cpp}` (GUI-only state-snapshot save/load) is unused by the batch path and can be excluded from the lib.

> **Correction (M1.1):** `serializer.{h,cpp}` can **not** be excluded — `field.cpp` and `hierarchy.cpp` include `serializer.h` and define `save()`/`load()` members against it, so the library would have unresolved symbols (caught by `-Wl,--no-undefined`). It is GUI-free (only `common.h` + rply), so it is in the lib. Likewise `field.cpp:1537` has `extern int nprocs;`, which only `main.cpp` defined; `capi.cpp` now defines it for the lib.

### 1.2 CMake configure-gate caveat

`CMakeLists.txt:14-18` has an unconditional `message(FATAL_ERROR ...)` if `ext/nanogui/ext/glfw` is missing — this runs **before any targets are declared**, so it gates the whole configure step, not just the GUI target. Since both Linux and Windows are in scope and we don't want the DLL/SO build to require GLFW/OpenGL/X11 toolchains, add a CMake option (e.g. `IM_CORE_ONLY`, declared near `CMakeLists.txt:4` alongside the existing `INSTANT_MESHES_DEV_MODE` option) that short-circuits past the nanogui submodule check, the `add_subdirectory(ext/nanogui ...)` call (`CMakeLists.txt:68`), and the `InstantMeshes` GUI executable target (`CMakeLists.txt:150-171`) entirely when set. The new `instantmeshes_core` target (below) should build correctly whether or not `IM_CORE_ONLY` is set, so local full-GUI dev builds keep working unchanged.

> **Toolchain addendum (M1.1):** the toolbox has CMake 4.4 and GCC 16, and the unmodified repo builds with neither. CMake ≥ 4.0 rejects `cmake_minimum_required(VERSION 2.8.3)` (now `2.8.3...3.5`) and the bundled TBB/NanoGUI minimums (`CMAKE_POLICY_VERSION_MINIMUM` is now set to 3.5 for them). GCC ≥ 13 rejects TBB 4.4's `tbb/task.h` (`-Wchanges-meaning`, now passed as `-Wno-changes-meaning` when supported). The full-GUI configure **still fails under CMake ≥ 4.0** because `ext/nanogui/ext/glfw/CMakeLists.txt:10` does `cmake_policy(SET CMP0042 OLD)`, which CMake 4 makes a hard error. That line is inside a submodule and was left alone; the GUI target was verified with CMake 3.31 (pip `cmake<4` in a venv).

### 1.3 New CMake target: `instantmeshes_core`

- **Type**: `SHARED` (required for P/Invoke `DllImport` on both platforms — a static lib can't be loaded at runtime by the CLR).
- **Sources**: `common.h`, `meshio.{h,cpp}`, `normal.{h,cpp}`, `adjacency.{h,cpp}`, `meshstats.{h,cpp}`, `hierarchy.{h,cpp}`, `extract.{h,cpp}`, `field.{h,cpp}`, `bvh.{h,cpp}`, `subdivide.{h,cpp}`, `reorder.{h,cpp}`, `batch.{h,cpp}`, `smoothcurve.{h,cpp}`, `cleanup.{h,cpp}`, `dedge.{h,cpp}`, plus `ext/rply/rply.c` (needed by `meshio.cpp` for PLY I/O, listed in the existing executable's source list at `CMakeLists.txt:168` and not GUI-specific). Exclude `serializer.*`, `glutil.*`, `widgets.*`, `viewer.*`, `main.cpp`, `resources.cpp`.
- **New files**: `src/capi.h` and `src/capi.cpp` (the `extern "C"` surface — see 1.5).
- **Link libraries**: `tbb_static` only — no `nanogui`/`${NANOGUI_EXTRA_LIBS}`.
- **Correction (M1.1)**: `serializer.{h,cpp}` *is* in the source list (see 1.1), and `aabb.h` (header-only) too.
- **Include dirs**: the existing TBB/dset/pss/pcg32/rply/half include paths; verify where Eigen resolves from (`common.h:21` includes `<Eigen/Core>`) — if it currently only resolves via nanogui's vendored copy, vendor/point to Eigen directly for the core-only build so it has zero nanogui dependency even at configure time.
- **Windows note**: export symbols via `__declspec(dllexport)`/`dllimport` guarded by an `INSTANTMESHES_CORE_EXPORTS` define (set by CMake for the target's own compile, unset for consumers) — see the `IM_API` macro in 1.5.

### 1.4 Returning real output counts (not just pre-solve approximations)

`batch_process` (src/batch.cpp:25-213) currently only logs **approximate pre-solve** vertex/face targets (batch.cpp:92-95 — these are inputs to the solver, derived from `stats.mSurfaceArea` at batch.cpp:78-90, not the realized output) and writes the final mesh straight to disk via `write_mesh(output, F_extr, O_extr, ...)` at batch.cpp:211, without ever reporting `F_extr.cols()`/`O_extr.cols()` back to the caller. It's also `void` and can throw `std::exception` (only caught today at the CLI boundary, main.cpp:175-186).

Refactor `batch_process`'s signature to add two optional out-parameters (default `nullptr`, so the existing CLI call site at `main.cpp:176-179` needs no change):
```cpp
void batch_process(const std::string &input, const std::string &output,
                    int rosy, int posy, Float scale, int face_count,
                    int vertex_count, Float creaseAngle, bool extrinsic,
                    bool align_to_boundaries, int smooth_iter, int knn_points,
                    bool pure_quad, bool deterministic,
                    int *out_vertex_count = nullptr, int *out_face_count = nullptr);
```
Populate them from `O_extr.cols()` / `F_extr.cols()` right after `extract_faces` (batch.cpp:207-208), before `write_mesh`.

> **Correction (M1.1):** `F_extr.cols()` is not the face count in the file. In quad-dominant mode (`pure_quad = 0`), `write_obj`/`write_ply` merge each irregular face (stored as several degenerate quads with `F(2,f) == F(3,f)`) into a single polygon. `out_face_count` therefore counts faces the way the writers do: `cols - nIrregular + |distinct F(2,f)|`. Measured on `source.obj` with `-f 11054 -D -d -t 1`: `F_extr.cols()` = 10723, faces written = 10417 = `out_face_count`. `out_vertex_count` = `O_extr.cols()` = the number of `v` lines. Note also that **pure-quad mode applies one subdivision step**, so a face target of 11054 yields ~41.7k faces. Callers must not compare `out_face_count` with `face_count` 1:1.
 This keeps one implementation shared by both the CLI and the new C API (no pipeline duplication/drift).

### 1.5 `extern "C"` API (`src/capi.h` / `src/capi.cpp`)

```c
#pragma once
#if defined(_WIN32)
  #ifdef INSTANTMESHES_CORE_EXPORTS
    #define IM_API __declspec(dllexport)
  #else
    #define IM_API __declspec(dllimport)
  #endif
#else
  #define IM_API __attribute__((visibility("default")))
#endif

extern "C" {

typedef struct {
    int   rosy;               // 2, 4, or 6
    int   posy;                // 4 (quad, target style) or 3 (tri)
    float scale;                // -1 = unset
    int   face_count;           // -1 = unset
    int   vertex_count;         // -1 = unset
    float crease_angle;         // -1 = disabled
    int   extrinsic;            // bool as int
    int   align_to_boundaries;  // bool as int
    int   smooth_iter;          // default 2
    int   knn_points;           // point clouds only
    int   pure_quad;            // bool as int (true = pure quad, matches target)
    int   deterministic;        // bool as int
} im_remesh_params;

typedef struct {
    int out_vertex_count;
    int out_face_count;
} im_remesh_result;

enum { IM_OK = 0, IM_ERR_RUNTIME = 1, IM_ERR_UNKNOWN = 2, IM_ERR_INVALID_ARG = 3 };

IM_API int im_remesh(const char *input_path, const char *output_path,
                      const im_remesh_params *params, im_remesh_result *result,
                      char *error_message_buf, int error_message_buf_len);

IM_API int im_set_thread_count(int nprocs);

}
```
`im_remesh` wraps the (refactored) `batch_process` call in `try { ... return IM_OK; } catch (const std::exception &e) { ...return IM_ERR_RUNTIME; } catch (...) { return IM_ERR_UNKNOWN; }` — mirroring the existing CLI's own exception handling (main.cpp:175-186) but translating to an error code instead of a `cerr`/exit path, since C++ exceptions must never cross an `extern "C"` boundary into a C# caller.

**TBB thread-count lifecycle**: `-t/--threads` is not a `batch_process` parameter — it's a local `tbb::task_scheduler_init` constructed once in `main()` (main.cpp:168) around the CLI's single `batch_process` call. Since a C# host will likely call `im_remesh` **repeatedly in one long-lived process**, `im_set_thread_count` should lazily create a single process-wide `task_scheduler_init` on first use (or `im_remesh` defaults it to automatic if never called) — document that it may only be called once, before the first `im_remesh` call.

> **As implemented (M1.1):** exactly this, and the scheduler is intentionally never destroyed. A per-call `task_scheduler_init` (tried first) crashes the bundled TBB 4.4 on the **third** create/destroy cycle in a MinGW build under Wine, reproduced without Instant Meshes code at all. A second `im_set_thread_count` call with the same count returns `IM_OK`; with a different count it returns `IM_ERR_INVALID_ARG`. The header also has `#ifdef __cplusplus` guards so it is valid C (the test harness is C). Also, `--deterministic` is **not** reproducible run-to-run with >1 thread (CLI and lib alike); it is byte-identical only with 1 thread (`-t 1` / `im_set_thread_count(1)`).

### 1.6 Minimal C# P/Invoke consumer (sketch, delivered as part of M4)

```csharp
[StructLayout(LayoutKind.Sequential)]
public struct RemeshParams { public int Rosy, Posy; public float Scale; public int FaceCount, VertexCount; public float CreaseAngle; public int Extrinsic, AlignToBoundaries, SmoothIter, KnnPoints, PureQuad, Deterministic; }

[StructLayout(LayoutKind.Sequential)]
public struct RemeshResult { public int OutVertexCount, OutFaceCount; }

[DllImport("instantmeshes_core", CallingConvention = CallingConvention.Cdecl)]
static extern int im_remesh(string inputPath, string outputPath, ref RemeshParams p, out RemeshResult result, StringBuilder errBuf, int errBufLen);
```
`DllImport("instantmeshes_core")` relies on .NET resolving `instantmeshes_core.dll` / `libinstantmeshes_core.so` by platform convention — the native binary must ship alongside the managed assembly (or a runtime-identifier-specific `runtimes/{win-x64,linux-x64}/native/` folder in a NuGet-style layout) for both platforms to work without extra `PATH`/`LD_LIBRARY_PATH` setup. (This consumer itself is implemented in M4; this section is here only for interface context.)

### Toolchain note for this unit

This machine has no system C/C++ compiler and host `sudo` requires a password. Build and verify inside the rootless `instant-meshes-build` toolbox container (see the plan-run prompt notes for how to create/use it and install packages there) rather than on the host directly.

## Exit criteria

- Build both the Linux `.so` and Windows `.dll` (via the existing VS2015/MSBuild path already proven by `.appveyor.yml`; the Linux `.so` is the one actually buildable and checkable in this environment via the toolbox).
  - *Status after M1.1:* the Linux `.so` is built and tested. No MSVC exists here. A MinGW-w64 cross-build of `instantmeshes_core.dll` builds and exports exactly `im_remesh`/`im_set_thread_count`, and its error paths pass under Wine, but a real remesh crashes inside TBB under MinGW+Wine (see `HANDOFF_M1_TASK1.md`). The MSVC `.dll` build is unverified and needs a Windows machine.
  - *Decided (giacomo forcina, 2026-10-12, D1):* the MinGW cross-build evidence is accepted for M1. The MSVC build stays an **explicitly open item (not yet proven)**. The TBB crash under MinGW+Wine is unresolved and should be re-checked once a real Windows/MSVC build exists (M4 or later). M4 proceeds Linux-only for now.
- Write a small native (C/C++) test harness that calls `im_remesh` on `source.obj` and checks `out_vertex_count`/`out_face_count` are populated and sane.
- Confirm a deliberately bad input path returns `IM_ERR_RUNTIME` with a populated error message rather than crashing or throwing across the `extern "C"` boundary.
- The existing full-GUI `InstantMeshes` executable target must still build unchanged when `IM_CORE_ONLY` is not set.
