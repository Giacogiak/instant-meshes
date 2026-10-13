# Handoff — M4 Task 2: Weld the demo's default input

Unit `M4.2`, plan `plan/roadmap/04_M4_pinvoke-demo.md`. The code commit is `9911231`. This
handoff is in the commit that adds this file.

**Status: done on Linux.** If you run the demo with no flags, it now welds `source.obj` and
then remeshes it. The output is **byte-identical** to M3's trial `v2799_coff_s1`
(`fd857df8…`, score 0.1461292849353033). The welded intermediate is byte-identical to M3's
`tuning_runs/source_welded.obj` (`b63990bc…`). Both of the plan's "if exact match is not
achievable" fallbacks were therefore unnecessary. The Windows `.dll` path is still **not
validated** (Open #1, carried over from M4.1).

## What changed and why

| File | Change |
|---|---|
| `csharp-demo/Welder.cs` | New. `Welder.Weld(ObjMesh, tol, out WeldStats)` is a port of `tune_params.weld()`. It finds every pair (j < i) with squared distance ≤ tol², using a uniform grid with cell size `tol` and searching the 27 surrounding cells instead of `cKDTree.query_pairs`. It merges each pair with a union-find whose root is always the lowest index, so clusters are transitive and the lowest-index vertex represents each one. It keeps the representatives in their original order and drops faces that would revisit a vertex. `ObjMesh.Load` follows `score_remesh.load_obj()`: `v`/`f` records, the first 3 coordinates, `i/…` tokens, negative indices, and the same validation errors. `ObjMesh.Save` follows `tune_params.write_obj()`, including `ObjMesh.PyRepr`, a re-implementation of Python's float `repr()`. PyRepr takes the shortest round-trip digits from .NET's `"R"` format and lays them out positionally when the decimal exponent is in [-4, 16), and as `d.ddde±XX` otherwise. Lines end in `\n` and the file is UTF-8 without a BOM, on every OS. `Welder.WeldFile(in, out)` combines load, weld and save. `Welder.DefaultTolerance = 1e-5` is `tune_params.WELD_TOL`. |
| `csharp-demo/Program.cs` | **Welding is now the default.** Before calling `im_remesh`, `Run` welds the input (`source.obj` or `--input`) into a temporary `welded.obj` and deletes it afterwards. It prints a `weld: …` stats line. New flags: `--no-weld` remeshes the input as it is, which is M4.1's behaviour. `--save-welded <file>` keeps the welded mesh, and the remesh reads it from there. Combining `--no-weld` with `--save-welded` is a usage error (exit 64). A non-`.obj` input without `--no-weld` is also exit 64, with a message saying to pass `--no-weld`. If the weld fails to read the file (a missing or malformed OBJ), the exit is 1 with `Error: cannot weld …`. **`--smoke-test`** now does more. First, `WeldChecks()` runs the three `WeldTest` cases from `tests/test_tune_params.py` (split square, a vertex beyond tolerance, a transitive cluster with a collapsed face) and 13 `repr()` cases, whose expected strings I checked against `python3 -c 'print(repr(x))'`. Then it welds `source.obj` and asserts M3's stats (10,287 pairs, V 97,400 → 87,691, F 175,566 → 175,566, 0 collapsed) and M3's sha256 `b63990bc…`. Finally it remeshes the **welded** mesh with the same small set as before (`-v 300 -S 0`). That makes the smoke trial the same one `tune_params.py --smoke-test` runs. |
| `csharp-demo/compare_with_cli.sh` | It now runs the demo with `--save-welded $work/welded.obj` and gives the CLI that welded file. Without this, the demo would weld and the CLI would not, so the comparison would no longer be fair. It prints the welded input's sha256. A leading `--no-weld` makes both sides use the raw input instead (M4.1's comparison). |
| `csharp-demo/README.md` | New "Welding" section. Updated the run examples and the parity section. |
| `plan/roadmap/04_M4_pinvoke-demo.md` | A status note after Task 2's exit criteria. The criteria themselves were correct and I did not edit them. |

No native code, CMake, Python script, test or manifest changed.

## Exit criteria, one by one

Both `## Exit criteria` blocks in the plan file are covered: the Task 1 block (still holds; the
Windows part stays open) and the Task 2 block.

Conditions for every number: Fedora 44 toolbox `instant-meshes-build`. .NET SDK 8.0.131 /
runtime 8.0.31 (`dotnet-sdk-8.0`). `build-core/libinstantmeshes_core.so` from M1, unchanged
and copied into `csharp-demo/bin/Debug/net8.0/` by the build. One thread (the demo's default,
the CLI's `-t 1`). Python 3.14.8 / numpy 2.5.4 / scipy 1.18.1 / trimesh 5.1.1 for the scorer,
with `--samples 100000 --seed 0`. `source.obj` sha256 `3e2e44ee…`.

### Task 2 / 1. No flags → weld, D8 remesh, sha256 = M3's `v2799_coff_s1` — **met (exact sha256)**

From the repo root: `toolbox run -c instant-meshes-build dotnet run --project csharp-demo`
(no arguments). rc 0, 4.5 s wall. Output:

```
weld: tolerance 1e-05, 10287 vertex pairs within it, V 97400 -> 87691, F 175566 -> 175566 (0 collapsed)
out_vertex_count=11355
out_face_count=11415
```

`sha256sum remeshed_csharp.obj` gives
`fd857df8cc3cb34dc09f88ae39925659f0a93d1d30919a4898e7b41eb6cba702`. That is the full hash
`tuning_results.jsonl` logs for `v2799_coff_s1` (line 99). The scorer's aggregate on it is
**0.1461292849353033**, the same value M3 logged; `compare_with_cli.sh` printed it, see 3
below. I ran this twice: once during development and once after the final clean rebuild.
Both runs gave the same sha.

The intermediate welded file matches too. With `--save-welded` (and in the smoke test's
temporary file) it is `b63990bc57c86b6787b43405b35a7b1c1cc2d7695ae0578537fa2825a12b3022`,
which is M3's `source_welded.obj`. The weld stats equal M3's `smoke_results.jsonl` `weld`
record: 10,287 pairs, 97,400 → 87,691 V, 175,566 F, 0 collapsed.

### Task 2 / 2. `--no-weld` remeshes the raw input — **met**

`dotnet run --project csharp-demo -- --no-weld --output /tmp/m42_nw/raw.obj`: rc 0, no
`weld:` line, V/F **11551 / 9908**, sha256 `7411eab1…`. These are exactly M4.1's raw-input
numbers.

### Task 2 / 3. The `csharp-demo` check and `compare_with_cli.sh` still pass — **met**

**The `csharp-demo` check.** I ran the driver's command verbatim, after `rm -rf
csharp-demo/bin csharp-demo/obj`. rc 0, 8.25 s wall. 0 warnings, 0 errors. **0 lines** match
`^(error|Unhandled exception)`. Key lines:

```
weld checks OK
weld: tolerance 1e-05, 10287 vertex pairs within it, V 97400 -> 87691, F 175566 -> 175566 (0 collapsed)
welded source.obj sha256 b63990bc…3022 = M3's source_welded.obj
smoke test OK: out_vertex_count=766 out_face_count=618
```

766/618 is exactly what `tune_params.py --smoke-test` reports. Its output sha is `8805c2ce…`
in `tuning_runs/smoke_results.jsonl`. I did not assert that sha in C#, because the remesh
part is native code and may differ across platforms.

**`compare_with_cli.sh`** (updated). Each row is one run of `toolbox run -c
instant-meshes-build csharp-demo/compare_with_cli.sh [--no-weld] <CLI> <input> <dir>`. All
rc 0, and every comparison said `identical`: reported vs. written V/F, file v/f lines,
`.obj` bytes, aggregate, and candidate metrics.

| CLI | mode | input | CLI got | V/F | sha256 (both) | aggregate (both) |
|---|---|---|---|---|---|---|
| current `build/` | weld (default) | `source.obj` | demo's welded `b63990bc…` | 11355/11415 | `fd857df8…` | 0.1461292849353033 |
| pre-M1 `05138b8` | weld (default) | `source.obj` | demo's welded `b63990bc…` | 11355/11415 | `fd857df8…` | 0.1461292849353033 |
| current `build/` | `--no-weld` | `source.obj` | raw `source.obj` | 11551/9908 | `7411eab1…` | 0.1786561965752647 |
| pre-M1 `05138b8` | `--no-weld` | `source.obj` | raw `source.obj` | 11551/9908 | `7411eab1…` | 0.1786561965752647 |
| current `build/` | weld (default) | `tuning_runs/source_welded.obj` | re-welded `b63990bc…` | 11355/11415 | `fd857df8…` | 0.1461292849353033 |

The last row shows that welding is idempotent. Re-welding M3's already-welded file gives the
same bytes, so `--input tuning_runs/source_welded.obj` (M4.1's recipe) still gives the same
result. The CLIs are the ones M4.1 built and left in place (`build/` and
`/tmp/im_base/build/`); I did not rebuild them, and no native source has changed since.

### Task 1 / 1. C# vs. direct CLI on Linux, identical under `-d` — **still met**

The table above covers it. Under `-d -t 1`, C# and the CLI are byte-identical on the welded
input and on the raw input, against both the current and the pre-M1 CLI.

### Task 1 / 2. Windows `.dll` — **not buildable here; explicit open item, not done**

Nothing in this unit ran on Windows. See Open #1.

### Negative control for the smoke test's weld guard

I temporarily set `Welder.DefaultTolerance = 1e-3` and ran `--smoke-test`. It **failed with
exit 6**: 10,307 pairs, V → 87,686, F → 175,556 (**10 collapsed**), sha `4ec96ff9…`. Then I
restored the file; `git diff` was empty afterwards. So the guard does catch a weld that
differs from M3's. The 10 collapsed triangles at 1e-3 also confirm, independently, M3's note
that "10 triangles would collapse" from r = 1e-3 on.

### Error paths checked by hand

- `--no-weld --save-welded /tmp/x.obj` → exit 64, `--save-welded needs welding (drop --no-weld)`.
- `--input /nonexistent.obj` → exit 1, `Error: cannot weld /nonexistent.obj: Could not find file …`.
- `--input /tmp/foo.ply` → exit 64, `only OBJ input can be welded; pass --no-weld …`.

## What I got wrong on the way

- My first draft put the `--no-weld`/`--save-welded` conflict check in its own try/catch
  between the parser and the run. That block was redundant, and it skipped the usage
  message the parser's own catch prints. I moved the check to the end of the parse loop
  before building.
- The stats line first printed the tolerance with .NET `"R"` (`1E-05`). I changed it to
  `PyRepr` (`1e-05`) so it reads like M3's logs. This is cosmetic.
- I expected that matching the welded file's sha256 might take some iteration on float
  formatting, which is why the plan allows a fallback. It matched on the first build. The
  `repr()` cases in `WeldChecks()` are there so that a future .NET change to `"R"` fails
  loudly in the smoke test and not silently in the hash.

## Open

1. **Windows `.dll` validation: still explicitly open, not done.** The steps are unchanged
   from `HANDOFF_M4_TASK1.md` Open #1. There is one new point for whoever runs it: the smoke
   test now also asserts the welded `source.obj` sha256 `b63990bc…`. The weld is managed
   code only: IEEE double parsing, comparisons and shortest-round-trip formatting, with
   `\n` line ends forced. It should therefore give the same bytes on Windows, even with a
   CRLF checkout of `source.obj`, because `File.ReadLines` strips `\r`. If it does not,
   that is a real porting bug in `Welder.cs`, not MSVC floating point. For the
   `compare_with_cli.sh` parity step on Windows, the CLI must get the demo's
   `--save-welded` file. A hand-run comparison must do the same.
2. The `csharp-demo` check still relies on an already-built
   `build-core/libinstantmeshes_core.so`. This is M4.1 Open #3, and the manifest is the
   owner's.
3. The weld is a third implementation of the same algorithm. The other two are
   `tune_params.weld()` and the merge that `trimesh` would have done (rejected in D6). If
   `tune_params.WELD_TOL` or `weld()` ever changes, `Welder.cs` and the smoke test's M3
   constants (`SourcePairs`, `SourceVAfter`, `SourceWeldedSha256` in `Program.cs`) must
   change with it. The smoke test will flag the mismatch, but it cannot say which side is
   right.
4. Earlier open items stand: M4.1 #4 (the GUI CLI needs CMake < 4), M1 #3–5, M2's, and M3's
   (nobody has looked at the D8 mesh).

## Tests run

- The driver's `csharp-demo` check, verbatim, from a clean `bin/obj`: rc 0 (above).
- `compare_with_cli.sh` × 5 (table above): all rc 0, all identical.
- No-flag run and `--no-weld` run, with sha256 of each output (above).
- Negative control (tolerance 1e-3 → smoke exit 6) and 3 error paths (above).
- `toolbox run -c instant-meshes-build python3 -m unittest discover -s tests -p 'test_*.py'`:
  **Ran 20 tests, OK** (tests unchanged).
- `ctest` in `build-core`: **1/1 passed**, 4.3 s.

## For whoever picks this up next

- **M4 is finished on Linux.** Both units are done. Only the Windows validation (Open #1) is
  left, and it needs a Windows machine or CI runner.
- If the demo prints a `weld:` line, it welded. To reproduce the raw-input numbers, use
  `--no-weld`.
- `remeshed_csharp.obj` in the repo root is the git-ignored output of the no-flag run.
  `/tmp/m42_*` holds this unit's comparison work dirs and can be deleted.
