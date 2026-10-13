/*
    Program.cs -- minimal .NET console consumer of the instantmeshes_core C API
    (src/capi.h) via P/Invoke

    Without options it remeshes <repo>/source.obj with the parameter set recommended by
    M3 (decision D8: vertex_count 2799, no crease angle, 1 smoothing step, pure quad,
    deterministic, one thread). --smoke-test runs one small, fast remesh instead and
    exits 0 on success. Run with --help for the options, which mirror the CLI's.
*/

using System;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;

namespace InstantMeshesDemo
{
    /* Mirrors im_remesh_params: 10 ints and 2 floats in header order, 48 bytes */
    [StructLayout(LayoutKind.Sequential)]
    public struct RemeshParams
    {
        public int Rosy, Posy;
        public float Scale;
        public int FaceCount, VertexCount;
        public float CreaseAngle;
        public int Extrinsic, AlignToBoundaries, SmoothIter, KnnPoints, PureQuad, Deterministic;

        /* The CLI's defaults (see capi.h) */
        public static RemeshParams CliDefaults() => new RemeshParams {
            Rosy = 4, Posy = 4, Scale = -1, FaceCount = -1, VertexCount = -1, CreaseAngle = -1,
            Extrinsic = 1, AlignToBoundaries = 0, SmoothIter = 2, KnnPoints = 10, PureQuad = 1,
            Deterministic = 0
        };
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct RemeshResult
    {
        public int OutVertexCount, OutFaceCount;
    }

    public static class Native
    {
        public const string Library = "instantmeshes_core";
        public const int IM_OK = 0, IM_ERR_RUNTIME = 1, IM_ERR_UNKNOWN = 2, IM_ERR_INVALID_ARG = 3;

        [DllImport(Library, CallingConvention = CallingConvention.Cdecl, CharSet = CharSet.Ansi)]
        public static extern int im_remesh([MarshalAs(UnmanagedType.LPUTF8Str)] string inputPath,
                                           [MarshalAs(UnmanagedType.LPUTF8Str)] string outputPath,
                                           ref RemeshParams p, out RemeshResult result,
                                           StringBuilder? errBuf, int errBufLen);

        [DllImport(Library, CallingConvention = CallingConvention.Cdecl)]
        public static extern int im_set_thread_count(int nprocs);

        /* DllImport looks next to the assembly first (where the .csproj copies the library).
           If it isn't there, fall back to $IM_CORE_LIB, then to <repo>/build-core. */
        public static void InstallResolver(string? repoRoot)
        {
            NativeLibrary.SetDllImportResolver(typeof(Native).Assembly, (name, assembly, searchPath) => {
                if (name != Library)
                    return IntPtr.Zero;
                if (NativeLibrary.TryLoad(name, assembly, searchPath, out IntPtr handle))
                    return handle;
                string file = OperatingSystem.IsWindows() ? Library + ".dll"
                            : OperatingSystem.IsMacOS() ? "lib" + Library + ".dylib"
                            : "lib" + Library + ".so";
                string? env = Environment.GetEnvironmentVariable("IM_CORE_LIB");
                string?[] candidates = {
                    env,
                    repoRoot == null ? null : Path.Combine(repoRoot, "build-core", file),
                    repoRoot == null ? null : Path.Combine(repoRoot, "build-core", "Release", file)
                };
                foreach (string? path in candidates)
                    if (path != null && File.Exists(path) && NativeLibrary.TryLoad(path, out handle))
                        return handle;
                return IntPtr.Zero; /* DllNotFoundException, reported by Main */
            });
        }
    }

    public static class Program
    {
        const int ErrBufLen = 1024;
        const int ExitUsage = 64, ExitCountMismatch = 4, ExitNoLibrary = 5, ExitSmokeFailed = 6;

        /* M3's recommended set (decision D8, trial v2799_coff_s1, intended for the welded source) */
        static RemeshParams BestParams()
        {
            RemeshParams p = RemeshParams.CliDefaults();
            p.VertexCount = 2799;
            p.CreaseAngle = -1;
            p.SmoothIter = 1;
            p.Deterministic = 1;
            return p;
        }

        static void Usage()
        {
            Console.WriteLine(
@"Usage: InstantMeshesDemo [options]
       InstantMeshesDemo --smoke-test

Remeshes --input with im_remesh from the instantmeshes_core library. Defaults are M3's
recommended set (D8): -v 2799, no crease, -S 1, pure quad, deterministic, 1 thread.

      --input <file>        Input mesh (default: <repo>/source.obj)
  -o, --output <file>       Output OBJ/PLY (default: remeshed_csharp.obj)
  -t, --threads <count>     Threads, -1 = one per hardware thread (default: 1)
  -d, --deterministic       Prefer deterministic algorithms (default: on)
      --nondeterministic    Turn deterministic mode off
  -c, --crease <degrees>    Crease angle threshold, -1 = off (default: -1)
  -S, --smooth <iter>       Smoothing & reprojection steps (default: 1)
  -D, --dominant            Tri/quad dominant instead of pure tri/quad
  -i, --intrinsic           Intrinsic smoothness (extrinsic is the default)
  -b, --boundaries          Align to boundaries
  -r, --rosy <number>       Orientation symmetry 2, 4 or 6 (default: 4)
  -p, --posy <number>       Position symmetry 4 or 6 (default: 4)
  -s, --scale <scale>       Target edge length (clears --vertices)
  -f, --faces <count>       Target face count (clears --vertices)
  -v, --vertices <count>    Target vertex count (default: 2799)
  -k, --knn <count>         Point clouds: adjacent points (default: 10)
      --smoke-test          One small, fast remesh of <repo>/source.obj; exit 0 on success
  -h, --help                This message");
        }

        public static int Main(string[] args)
        {
            string? repoRoot = FindRepoRoot();
            Native.InstallResolver(repoRoot);

            RemeshParams p = BestParams();
            string? input = null, output = null;
            int threads = 1;
            bool smoke = false;
            try {
                for (int i = 0; i < args.Length; ++i) {
                    string a = args[i];
                    string Next() => i + 1 < args.Length ? args[++i]
                        : throw new ArgumentException("missing value after " + a);
                    int NextInt() => int.Parse(Next(), CultureInfo.InvariantCulture);
                    float NextFloat() => float.Parse(Next(), CultureInfo.InvariantCulture);
                    switch (a) {
                        case "--smoke-test": smoke = true; break;
                        case "-h": case "--help": Usage(); return 0;
                        case "--input": input = Next(); break;
                        case "-o": case "--output": output = Next(); break;
                        case "-t": case "--threads": threads = NextInt(); break;
                        case "-d": case "--deterministic": p.Deterministic = 1; break;
                        case "--nondeterministic": p.Deterministic = 0; break;
                        case "-c": case "--crease": p.CreaseAngle = NextFloat(); break;
                        case "-S": case "--smooth": p.SmoothIter = NextInt(); break;
                        case "-D": case "--dominant": p.PureQuad = 0; break;
                        case "-i": case "--intrinsic": p.Extrinsic = 0; break;
                        case "-b": case "--boundaries": p.AlignToBoundaries = 1; break;
                        case "-r": case "--rosy": p.Rosy = NextInt(); break;
                        case "-p": case "--posy": p.Posy = NextInt(); break;
                        case "-s": case "--scale": p.Scale = NextFloat(); p.VertexCount = -1; break;
                        case "-f": case "--faces": p.FaceCount = NextInt(); p.VertexCount = -1; break;
                        case "-v": case "--vertices": p.VertexCount = NextInt(); break;
                        case "-k": case "--knn": p.KnnPoints = NextInt(); break;
                        default: throw new ArgumentException("unknown option " + a);
                    }
                }
            } catch (Exception e) when (e is ArgumentException || e is FormatException || e is OverflowException) {
                Console.Error.WriteLine("Error: " + e.Message);
                Usage();
                return ExitUsage;
            }

            try {
                return smoke ? SmokeTest(repoRoot) : Run(repoRoot, input, output, p, threads);
            } catch (DllNotFoundException e) {
                Console.Error.WriteLine("Error: cannot load the instantmeshes_core native library (" +
                    e.Message + "). Build it first: cmake -S . -B build-core -G Ninja -DIM_CORE_ONLY=ON " +
                    "-DCMAKE_BUILD_TYPE=Release && cmake --build build-core --target instantmeshes_core, " +
                    "then rebuild this project, or set IM_CORE_LIB to the library's path.");
                return ExitNoLibrary;
            }
        }

        static int Run(string? repoRoot, string? input, string? output, RemeshParams p, int threads)
        {
            input ??= RepoFile(repoRoot, "source.obj");
            output ??= "remeshed_csharp.obj";
            if (input == null) {
                Console.Error.WriteLine("Error: no --input given and <repo>/source.obj not found");
                return ExitUsage;
            }
            int rv = SetThreads(threads);
            if (rv != Native.IM_OK)
                return rv;

            rv = Remesh(input, output, ref p, out RemeshResult r, out string message);
            if (rv != Native.IM_OK) {
                Console.Error.WriteLine("Error: im_remesh returned " + rv + ": " + message);
                return rv;
            }
            Console.WriteLine("out_vertex_count=" + r.OutVertexCount);
            Console.WriteLine("out_face_count=" + r.OutFaceCount);
            Console.WriteLine("output=" + Path.GetFullPath(output));
            return CheckObjCounts(output, r) ? 0 : ExitCountMismatch;
        }

        /* Small/fast parameter set (the same as tune_params.py --smoke-test, unwelded input),
           plus the error path for a missing input. Exits 0 only if everything checks out. */
        static int SmokeTest(string? repoRoot)
        {
            string? input = RepoFile(repoRoot, "source.obj");
            if (input == null) {
                Console.Error.WriteLine("smoke test FAILED: <repo>/source.obj not found");
                return ExitSmokeFailed;
            }
            if (Marshal.SizeOf<RemeshParams>() != 48 || Marshal.SizeOf<RemeshResult>() != 8) {
                Console.Error.WriteLine("smoke test FAILED: struct sizes " + Marshal.SizeOf<RemeshParams>() +
                                        "/" + Marshal.SizeOf<RemeshResult>() + ", expected 48/8");
                return ExitSmokeFailed;
            }
            if (SetThreads(1) != Native.IM_OK)
                return ExitSmokeFailed;

            RemeshParams p = RemeshParams.CliDefaults();
            p.VertexCount = 300;
            p.SmoothIter = 0;
            p.Deterministic = 1;

            string dir = Path.Combine(Path.GetTempPath(), "instantmeshes-demo-" + Environment.ProcessId);
            Directory.CreateDirectory(dir);
            try {
                int rv = Remesh(Path.Combine(dir, "missing.obj"), Path.Combine(dir, "never.obj"),
                                ref p, out RemeshResult bad, out string message);
                if (rv != Native.IM_ERR_RUNTIME || message.Length == 0 || bad.OutVertexCount != 0) {
                    Console.Error.WriteLine("smoke test FAILED: missing input gave rv=" + rv +
                                            " message='" + message + "'");
                    return ExitSmokeFailed;
                }
                Console.WriteLine("missing input -> IM_ERR_RUNTIME: " + message);

                string output = Path.Combine(dir, "smoke.obj");
                rv = Remesh(input, output, ref p, out RemeshResult r, out message);
                if (rv != Native.IM_OK || r.OutVertexCount <= 0 || r.OutFaceCount <= 0) {
                    Console.Error.WriteLine("smoke test FAILED: im_remesh returned " + rv + " (" + message +
                                            "), V=" + r.OutVertexCount + " F=" + r.OutFaceCount);
                    return ExitSmokeFailed;
                }
                if (!CheckObjCounts(output, r))
                    return ExitSmokeFailed;
                Console.WriteLine("smoke test OK: out_vertex_count=" + r.OutVertexCount +
                                  " out_face_count=" + r.OutFaceCount);
                return 0;
            } finally {
                Directory.Delete(dir, true);
            }
        }

        static int SetThreads(int threads)
        {
            int rv = Native.im_set_thread_count(threads);
            if (rv != Native.IM_OK)
                Console.Error.WriteLine("Error: im_set_thread_count(" + threads + ") returned " + rv);
            return rv;
        }

        static int Remesh(string input, string output, ref RemeshParams p, out RemeshResult r, out string message)
        {
            var err = new StringBuilder(ErrBufLen);
            int rv = Native.im_remesh(input, output, ref p, out r, err, err.Capacity);
            Console.Out.Flush();
            message = err.ToString();
            return rv;
        }

        /* The OBJ's v/f line counts must equal what im_remesh reported (PLY is not checked) */
        static bool CheckObjCounts(string path, RemeshResult r)
        {
            if (!path.EndsWith(".obj", StringComparison.OrdinalIgnoreCase))
                return true;
            int v = 0, f = 0;
            foreach (string line in File.ReadLines(path)) {
                if (line.StartsWith("v ", StringComparison.Ordinal)) ++v;
                else if (line.StartsWith("f ", StringComparison.Ordinal)) ++f;
            }
            if (v == r.OutVertexCount && f == r.OutFaceCount)
                return true;
            Console.Error.WriteLine("Error: " + path + " has " + v + " v / " + f + " f lines, im_remesh reported " +
                                    r.OutVertexCount + " / " + r.OutFaceCount);
            return false;
        }

        /* The repository root is the first ancestor of the assembly's (or the current)
           directory that contains src/capi.h */
        static string? FindRepoRoot()
        {
            foreach (string start in new[] { AppContext.BaseDirectory, Directory.GetCurrentDirectory() }) {
                for (var dir = new DirectoryInfo(start); dir != null; dir = dir.Parent)
                    if (File.Exists(Path.Combine(dir.FullName, "src", "capi.h")))
                        return dir.FullName;
            }
            return null;
        }

        static string? RepoFile(string? repoRoot, string name)
        {
            string? path = repoRoot == null ? null : Path.Combine(repoRoot, name);
            return path != null && File.Exists(path) ? path : null;
        }
    }
}
