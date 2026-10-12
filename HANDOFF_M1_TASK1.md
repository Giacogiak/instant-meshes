# Handoff — M1 Task 1: GUI-Free Native Library + C API

Unit `M1.1`, plan `plan/roadmap/01_M1_native-library.md`. Code commit: `fab2960`.

**Status: blocked on one exit-criterion bullet, the Windows `.dll` via MSVC.** Everything
that can be built and checked on this Linux machine is done and verified (below). The MSVC
build needs a Windows machine; see "Open" and the question in the run status.

## What changed and why

| File | Change |
|---|---|
| `CMakeLists.txt` | `IM_CORE_ONLY` option (skips the NanoGUI submodule check, `add_subdirectory(nanogui)`, NanoGUI include dirs, bin2c and the `InstantMeshes` target via `return()`). New `SHARED` target `instantmeshes_core`, linking `tbb_static` only, with hidden visibility, `DEFINE_SYMBOL INSTANTMESHES_CORE_EXPORTS`, `-Wl,--no-undefined -Wl,--exclude-libs,ALL` on ELF and `PREFIX ""` on WIN32. `tbb_static` is now PIC. New `IM_EIGEN_INCLUDE_DIR` cache variable. `test_capi` target + `add_test`. Toolchain fixes (below). |
| `src/capi.h`, `src/capi.cpp` | The `extern "C"` API from plan §1.5, with the ABI unchanged (same structs, enum, signatures). Arguments are validated (`IM_ERR_INVALID_ARG` plus a message). `std::exception` maps to `IM_ERR_RUNTIME` and `...` to `IM_ERR_UNKNOWN`. The error buffer is always NUL-terminated and truncated to fit; NULL or length 0 is allowed. `result` may be NULL and is zeroed on failure. The header has `#ifdef __cplusplus` guards so it is valid C. `capi.cpp` defines `int nprocs` (needed by `field.cpp`). |
| `src/batch.h`, `src/batch.cpp` | Optional `int *out_vertex_count, int *out_face_count` (default `nullptr`; the CLI call site is unchanged). The BVH is now released by a scope guard, so a throw after it is built (e.g. an unwritable output path) no longer leaks it in a long-lived host. |
| `tests/test_capi.c` | Native harness in C, run via `ctest` (see below). |
| `plan/roadmap/01_M1_native-library.md` | Correction notes where the plan was wrong (below). |

### Places where the plan was wrong (corrected in the plan file)

1. **`serializer.{h,cpp}` cannot be excluded.** `field.cpp` and `hierarchy.cpp` include it and
   define `save()`/`load()` against it. It is GUI-free, so it is in the library.
   `-Wl,--no-undefined` now catches this class of mistake at link time.
2. **`extern int nprocs`** (`field.cpp:1537`, read by `Optimizer::run`) was only defined in
   `main.cpp`. `capi.cpp` defines it, and `im_set_thread_count` sets it.
3. **`F_extr.cols()` is not the face count written to file** in quad-dominant mode.
   `write_obj`/`write_ply` merge the degenerate-quad fans of each irregular face into one
   polygon. `out_face_count` replicates the writers' count. Measured: `F_extr.cols()` = 10723
   vs. 10417 faces written and reported (conditions in the table below).
4. **TBB lifecycle.** I first used a per-call `task_scheduler_init` (my reasoning: it is
   per-thread, so one created in `im_set_thread_count` would not cover calls from other
   threads). That turned out wrong for this TBB. In a MinGW build under Wine, TBB 4.4
   crashes on the **third** create/destroy cycle of the last `task_scheduler_init`.
   Reproduced with a 10-line program linking only `tbb_static` (`init; destroy` ×3 → page
   fault at `FFFFFFFFFFFFFFF7`), and exceptions alone (×5) are fine. With one persistent
   scheduler, nested per-thread inits on the main thread, inits on new `std::thread`s, and
   auto-initialised threads all ran 6/6 iterations. So the code now follows the plan:
   one process-wide scheduler created lazily (by `im_set_thread_count` or by the first
   `im_remesh`, then automatic) and **never destroyed**. Calling `im_set_thread_count`
   again returns `IM_OK` for the same count and `IM_ERR_INVALID_ARG` for a different one.
   Calls from other threads auto-initialise TBB, and the global worker pool (fixed at
   `nprocs-1` workers) still caps them.

### Toolchain fixes, all required to build anything in the toolbox (Fedora 44 toolbox, GCC 16.2.1, CMake 4.4.3)

- The `cmake` on `PATH` inside the toolbox is `~/.local/bin/cmake` 4.4.3. The dnf one is
  `/usr/bin/cmake` 4.3.0. Both are ≥ 4.0.
- `cmake_minimum_required(VERSION 2.8.3)` → `2.8.3...3.5`, because CMake ≥ 4.0 refuses
  < 3.5 otherwise.
- `CMAKE_POLICY_VERSION_MINIMUM` is set to 3.5 (only on CMake ≥ 4, and only if the
  user hasn't set it) so `ext/tbb` and `ext/nanogui` configure.
- `-Wno-changes-meaning` is added when the compiler supports it: GCC ≥ 13 makes TBB 4.4's
  `tbb/task.h:263` a hard error. This also applies to the GUI build, which hit the same
  error at baseline.
- **Not fixed:** the full-GUI configure still fails on CMake ≥ 4.0, because
  `ext/nanogui/ext/glfw/CMakeLists.txt:10` sets `cmake_policy(SET CMP0042 OLD)`, a hard
  error in CMake 4. It is inside a submodule, so I left it. I verified the GUI build with
  CMake 3.31.10 from a venv: `python3 -m venv ~/.cache/im-cmake3 && ~/.cache/im-cmake3/bin/pip install "cmake<4"`, run inside the toolbox.

### Eigen

`common.h` includes `<Eigen/Core>`, which previously resolved only through NanoGUI's
`NANOGUI_EXTRA_INCS`. The core target now uses `IM_EIGEN_INCLUDE_DIR`, with this
precedence: an explicit value, then `ext/nanogui/ext/eigen` if it is checked out, then
`find_package(Eigen3)`, then a fatal error with instructions. Only NanoGUI's bundled
**Eigen 3.2.9 headers** are used; the NanoGUI target, GLFW and OpenGL are not touched.

I deliberately did not prefer the system Eigen, for two reasons:
- Fedora 44 ships **Eigen 5.0.1**, which needs C++14 (the project uses gnu++11).
- Byte-identical output with the GUI CLI requires the same Eigen.

The catch: a fresh clone that initialises only `ext/{pcg32,dset,pss,tbb}` (as the
`build-core` check does) needs `ext/nanogui` initialised too, or an Eigen 3.x via
`IM_EIGEN_INCLUDE_DIR`. In this working tree NanoGUI is checked out, so the check passes.
Vendoring Eigen 3.2.9 (3.6 MB of headers) into `ext/eigen` would remove the soft
dependency if wanted.

## Exit criteria, one by one

### 1. Build the Linux `.so` and the Windows `.dll` — **Linux: met. Windows: not met (blocked)**

- **Linux `.so`:** I ran the driver's exact `build-core` command (toolbox create check, dnf
  install, submodule update of the 4 submodules, configure `-DIM_CORE_ONLY=ON -G Ninja
  -DCMAKE_BUILD_TYPE=Release`, then `--target instantmeshes_core`) from a deleted
  `build-core/`.
  - Result: exit 0, 56/56 Ninja steps, **0 lines** matching `^(CMake Error|error:|FAILED)`.
  - `build-core/libinstantmeshes_core.so`: 1,496,712 bytes.
  - `nm -D --defined-only` shows `T im_remesh` and `T im_set_thread_count` as the only
    exported functions; the rest are libstdc++ weak/vague template instantiations, and
    there are no TBB symbols.
  - `ldd`: libstdc++, libm, libgcc_s, libc only, with no GL/X11.
  - About 1900 compiler warning lines, almost all from TBB 4.4 / Eigen 3.2.9 headers under
    GCC 16.
- **Windows `.dll` via VS2015/MSBuild:** there is no MSVC here, so this could not be done.
  As a substitute I did a MinGW-w64 cross-build in the toolbox (`dnf install
  mingw64-gcc-c++`; configure with
  `-DCMAKE_TOOLCHAIN_FILE=/usr/share/mingw/toolchain-mingw64.cmake -DIM_CORE_ONLY=ON`).
  - It builds and produces `instantmeshes_core.dll` (1,988,439 bytes).
  - `objdump -p` shows the export table is exactly `im_remesh` and `im_set_thread_count`,
    so `__declspec(dllexport)` via `INSTANTMESHES_CORE_EXPORTS` works.
  - Under Wine (`wine-core`, prefix `~/.cache/im-wineprefix`, `WINEDLLOVERRIDES="mscoree,mshtml="`):
    - Every error-path check of `test_capi.exe` passes: invalid args, missing input
      (`IM_ERR_RUNTIME` with message), unknown extension, truncated buffer, NULL buffer.
    - The first **real remesh crashes** inside TBB parallel code ("Computing mesh
      statistics", page fault in a runtime DLL).
    - I did not determine whether this is Wine, TBB 4.4 on MinGW, or something that would
      also hit MSVC. A trivial `tbb::parallel_for` ran fine in the same setup.
  - Note: Wine's first-time prefix setup (`rundll32 setupapi … wine.inf`) spins at 100% CPU
    for over 10 minutes and never finishes. Programs still run while it spins.

### 2. Native harness calls `im_remesh` on `source.obj`, counts populated and sane — **met**

- Run with `cd build-core && toolbox run -c instant-meshes-build ctest --output-on-failure`.
  Result: **1/1 passed, 4.3 s**, 8 hardware threads, Release.
- The harness `tests/test_capi.c` is C on purpose. It checks:
  - the thread-count contract;
  - invalid args: NULL params, NULL path, `rosy = 5`, two size targets;
  - error paths: missing input, unknown extension, a too-small error buffer (truncated and
    terminated), a NULL error buffer;
  - a real remesh with `face_count = 11054` (the face count of `quad-remeshed.obj`),
    `deterministic = 1`, CLI defaults otherwise:
    - pure quad: `rv = IM_OK`, faces in [2×, 8×] the target because of the subdivision
      step, V/F ratio in [0.5, 2], **the written OBJ's `v`/`f` line counts equal
      `out_vertex_count`/`out_face_count`**, 0 non-quads;
    - quad-dominant: faces in [0.5×, 2×] the target, file counts equal reported counts;
  - an unwritable output path after the whole solve.
- Measured counts (automatic threads, `-d`; numbers vary run to run, see "Determinism"):

| Mode | Run | V | F |
|---|---|---|---|
| pure quad | 1 | 46469 | 41754 |
| pure quad | 2 | 46451 | 41826 |
| pure quad | 3 | 46551 | 41902 |
| quad-dominant | 1 | 12843 | 10456 |
| quad-dominant | 2 | 12813 | 10423 |

- **Parity with the CLI** (`-d -t 1 -f 11054`, `im_set_thread_count(1)` on the API side):
  - pure quad: the baseline CLI built from `05138b8` (pre-change), the new CLI and the C API
    all wrote a **byte-identical** OBJ (md5 `f78affea…`, V=46324, F=41677);
  - quad-dominant (`-D`): byte-identical again (md5 `587906af…`, V=12834). 10417 faces
    were written and reported, against `F_extr.cols()` = 10723.

### 3. A bad input path returns `IM_ERR_RUNTIME` with a populated message, no crash or throw — **met**

`im_remesh("/nonexistent/directory/missing.obj", …)` returns 1 (`IM_ERR_RUNTIME`) with
`Unable to open OBJ file "/nonexistent/directory/missing.obj"!`, and the result is zeroed.
The harness also covers:
- unknown extension → `IM_ERR_RUNTIME`;
- unwritable output → `IM_ERR_RUNTIME` (`Unable to open OBJ file "/nonexistent/directory/out.obj"!`);
- invalid parameters → `IM_ERR_INVALID_ARG` (e.g. `only one of scale, face_count and vertex_count can be set at once!`).

All of these hold on Linux, and also under Wine for the MinGW DLL.

### 4. The full-GUI `InstantMeshes` target still builds unchanged without `IM_CORE_ONLY` — **met, with a toolchain caveat**

- With CMake 3.31.10 + GCC 16 in the toolbox (`-G Ninja -DCMAKE_BUILD_TYPE=Release`, after
  `dnf install mesa-libGL-devel libXrandr-devel libXinerama-devel libXcursor-devel libXi-devel libXxf86vm-devel mesa-libGLU-devel`),
  the build of all targets succeeds:
  - `Instant Meshes`, `libinstantmeshes_core.so` and `test_capi` are built;
  - 0 lines match `^(CMake Error|error:|FAILED)`.
- Its batch output is byte-identical to the pre-change build (criterion 2).
- The GUI source list, link libraries and post-build steps are untouched. Only moved
  blocks, the toolchain flags and the PIC property on `tbb_static` affect it.
- GUI-mode runtime (an actual window) was **not** exercised. It needs a display, so it is
  a human check.
- **The baseline (pre-change) repo does not build in this toolbox either.** It fails under
  CMake 4 (GLFW policy) and under GCC 16 (TBB). The baseline was built with CMake 3.31
  and `-DCMAKE_CXX_FLAGS=-Wno-changes-meaning`.

## Determinism (matters for M3)

`--deterministic` is **not reproducible across runs with more than one thread**. Two
identical CLI runs `-d -f 11054` on 8 threads gave V=46401/F=41858 and V=46313/F=41680.
With `-t 1`, repeated runs are byte-identical. This was true before this change as well.
The tuning harness should either use `-t 1` (or `im_set_thread_count(1)`) or treat metrics
as noisy.

## What I got wrong on the way

- I trusted the plan's source list: no `serializer.cpp`, and `nprocs` was missed. The
  `--no-undefined` link flag is what makes this visible now.
- I first reported `F_extr.cols()` as the face count, as the plan said. The harness's
  "file counts equal reported counts" check is what exposed the quad-dominant mismatch.
- I first expected faces ≈ target. Pure-quad mode subdivides once, giving ~4× the target.
- I first used a per-call TBB init (see above), and reverted to the plan's design after the
  Wine crash.
- I initially linked the `.so` with `-static-libgcc`. CMake 4.4 then pulled libgcc's
  unwinder statically into a library that catches exceptions, so I dropped it.
- My MinGW configure left a generated `ext/tbb/src/tbb/win32-gcc-tbb-export.def` in the
  TBB submodule. I deleted it; the submodule is clean.

## Open

1. **MSVC `.dll` build and runtime** (exit criterion 1). Needs a Windows box with VS:
   `cmake -G "Visual Studio …" -A x64 -DIM_CORE_ONLY=ON` then build `instantmeshes_core`
   and `test_capi`, and run `ctest -C Release`.
   - Things to watch: `/MT` static CRT inside a DLL (fine for this API: no CRT objects
     cross the boundary); MSVC compiling `tests/test_capi.c` as C; `<windows.h>`
     `min`/`max` (not seen so far).
   - Also unresolved: whether the MinGW+Wine remesh crash is a real TBB 4.4-on-Windows
     issue.
2. **Full-GUI configure under CMake ≥ 4** is blocked by GLFW's `CMP0042 OLD`. This affects
   M3's `tuning-sweep` check, which uses the toolbox's default `cmake` and the `build/`
   directory. Options: patch the submodule; bump the nanogui submodule; a top-level
   workaround (none found, since CMake 4 rejects setting removed policies to OLD); or
   install `cmake<4` in the toolbox. Today that check will fail at configure time.
3. **The Eigen soft dependency** on the `ext/nanogui` checkout (see Eigen above).
4. **Concurrency:** `im_remesh` is documented as "concurrent calls not supported". Nothing
   in `batch_process` was audited for re-entrancy beyond the global `nprocs`.
5. **`Optimizer` has no destructor that joins its thread.** If anything threw between its
   construction and `shutdown()` in `batch_process`, `std::thread`'s destructor would call
   `std::terminate` and take down the host. No realistic throw site exists there today; I
   left it alone.

## For the next units

- **M2/M3:**
  - Pure-quad output has ~4× the requested `-f` faces.
  - Use `-t 1` for reproducible runs.
  - Building the GUI CLI in the toolbox needs CMake < 4 (see Open #2). A working one is at
    `~/.cache/im-cmake3/bin/cmake` inside the toolbox.
- **M4 (C#):**
  - Library names: Linux `build-core/libinstantmeshes_core.so`; Windows `instantmeshes_core.dll`
    (`PREFIX ""` also applies to MinGW).
  - The struct layout matches plan §1.6 exactly: 10 `int`s and 2 `float`s in order, 48 bytes.
  - Call `im_set_thread_count` at most once, before the first `im_remesh`.
  - `StringBuilder errBuf` with `errBufLen = errBuf.Capacity` works; the message is always
    NUL-terminated.
  - `im_remesh` logs progress to stdout.
- **Build commands:** the check's command builds only `instantmeshes_core`.
  `cmake --build build-core` (all targets) plus `ctest` in `build-core` runs the harness.
