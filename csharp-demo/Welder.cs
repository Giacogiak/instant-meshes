/*
    Welder.cs -- merges source.obj's duplicated seam vertices before remeshing

    A port of scripts/tune_params.py's weld() (decision D6 in
    plan/roadmap/03_M3_tuning-harness.md): vertices closer than the tolerance (1e-5 world
    units) are merged, transitively, into the member with the lowest index, keeping the
    vertex order; faces that would lose a vertex are dropped. M3's sweep, and the D8
    parameters this demo defaults to, ran on that welded mesh.

    The point pairs are found with a uniform grid of cell size tol instead of a KD-tree:
    two points within tol of each other are in the same or in adjacent cells. Reading
    and writing follow score_remesh.load_obj() and tune_params.write_obj(), down to
    Python's repr() of a float, so that the welded OBJ is the same file byte for byte.
*/

using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;

namespace InstantMeshesDemo
{
    public sealed class ObjMesh
    {
        public readonly List<double[]> V = new List<double[]>();
        public readonly List<int[]> Faces = new List<int[]>();

        /* The 'v' and 'f' records of an OBJ file, as score_remesh.load_obj() reads them:
           the first three coordinates of each vertex, the vertex index of each face corner
           (negative indices count back from the vertices read so far) */
        public static ObjMesh Load(string path)
        {
            var mesh = new ObjMesh();
            char[] ws = { ' ', '\t', '\r', '\n', '\v', '\f' };
            int lineNo = 0;
            foreach (string line in File.ReadLines(path)) {
                ++lineNo;
                if (line.StartsWith("v ", StringComparison.Ordinal)) {
                    string[] tok = line.Split(ws, StringSplitOptions.RemoveEmptyEntries);
                    if (tok.Length < 4)
                        throw new FormatException(path + ":" + lineNo + ": vertex with fewer than 3 coordinates");
                    mesh.V.Add(new[] { ParseDouble(tok[1]), ParseDouble(tok[2]), ParseDouble(tok[3]) });
                } else if (line.StartsWith("f ", StringComparison.Ordinal)) {
                    string[] tok = line.Split(ws, StringSplitOptions.RemoveEmptyEntries);
                    if (tok.Length < 4)
                        throw new FormatException(path + ":" + lineNo + ": face with fewer than 3 vertices");
                    var face = new int[tok.Length - 1];
                    for (int k = 0; k < face.Length; ++k) {
                        string t = tok[k + 1];
                        int slash = t.IndexOf('/');
                        int i = int.Parse(slash < 0 ? t : t.Substring(0, slash), CultureInfo.InvariantCulture);
                        face[k] = i > 0 ? i - 1 : mesh.V.Count + i;
                    }
                    mesh.Faces.Add(face);
                }
            }
            if (mesh.V.Count == 0 || mesh.Faces.Count == 0)
                throw new FormatException(path + ": no vertices or no faces");
            foreach (int[] face in mesh.Faces)
                foreach (int i in face)
                    if (i < 0 || i >= mesh.V.Count)
                        throw new FormatException(path + ": face index out of range");
            return mesh;
        }

        static double ParseDouble(string s) =>
            double.Parse(s, NumberStyles.Float, CultureInfo.InvariantCulture);

        /* As tune_params.write_obj(): 'v %r %r %r' and 1-based 'f' lines, '\n' line ends */
        public void Save(string path)
        {
            using var w = new StreamWriter(path, false, new UTF8Encoding(false));
            w.NewLine = "\n";
            var sb = new StringBuilder();
            foreach (double[] v in V) {
                sb.Clear().Append("v ").Append(PyRepr(v[0])).Append(' ')
                  .Append(PyRepr(v[1])).Append(' ').Append(PyRepr(v[2]));
                w.WriteLine(sb);
            }
            foreach (int[] face in Faces) {
                sb.Clear().Append('f');
                foreach (int i in face)
                    sb.Append(' ').Append((i + 1).ToString(CultureInfo.InvariantCulture));
                w.WriteLine(sb);
            }
        }

        /* Python's repr() of a float: the shortest digits that round-trip (which .NET's
           "R" format also gives), laid out the way Python does -- positional with at
           least one digit after the point when the decimal exponent is in [-4, 16),
           otherwise d.ddde+XX */
        public static string PyRepr(double x)
        {
            if (double.IsNaN(x))
                return "nan";
            if (double.IsInfinity(x))
                return x > 0 ? "inf" : "-inf";
            string sign = x < 0 || (x == 0 && double.IsNegative(x)) ? "-" : "";
            if (x == 0)
                return sign + "0.0";

            /* "R" gives e.g. "105.67", "0.0001", "1E-05", "1.2345E+16": split it into the
               significant digits and the position of the decimal point */
            string r = Math.Abs(x).ToString("R", CultureInfo.InvariantCulture);
            int exp = 0, e = r.IndexOfAny(new[] { 'E', 'e' });
            if (e >= 0) {
                exp = int.Parse(r.Substring(e + 1), NumberStyles.AllowLeadingSign, CultureInfo.InvariantCulture);
                r = r.Substring(0, e);
            }
            int point = r.IndexOf('.');
            string digits = point < 0 ? r : r.Remove(point, 1);
            int decpt = (point < 0 ? r.Length : point) + exp;   /* value = 0.digits x 10^decpt */
            int lead = 0;
            while (lead < digits.Length - 1 && digits[lead] == '0')
                ++lead;
            digits = digits.Substring(lead).TrimEnd('0');
            decpt -= lead;

            var sb = new StringBuilder(sign);
            if (decpt > -4 && decpt <= 16) {
                if (decpt <= 0)
                    sb.Append("0.").Append('0', -decpt).Append(digits);
                else if (decpt >= digits.Length)
                    sb.Append(digits).Append('0', decpt - digits.Length).Append(".0");
                else
                    sb.Append(digits, 0, decpt).Append('.').Append(digits, decpt, digits.Length - decpt);
            } else {
                sb.Append(digits[0]);
                if (digits.Length > 1)
                    sb.Append('.').Append(digits, 1, digits.Length - 1);
                int e10 = decpt - 1;
                sb.Append(e10 < 0 ? "e-" : "e+").Append(Math.Abs(e10).ToString("00", CultureInfo.InvariantCulture));
            }
            return sb.ToString();
        }
    }

    public sealed class WeldStats
    {
        public double Tolerance;
        public int PairsWithinTolerance, VBefore, VAfter, FBefore, FAfter, CollapsedFaces;

        public override string ToString() => string.Format(CultureInfo.InvariantCulture,
            "weld: tolerance {0}, {1} vertex pairs within it, V {2} -> {3}, F {4} -> {5} ({6} collapsed)",
            ObjMesh.PyRepr(Tolerance), PairsWithinTolerance, VBefore, VAfter, FBefore, FAfter, CollapsedFaces);
    }

    public static class Welder
    {
        /* tune_params.WELD_TOL: source.obj's seam duplicates are exactly coincident, and the
           number of pairs closer than r is the same for every r from 0 to 1e-4 */
        public const double DefaultTolerance = 1e-5;

        public static ObjMesh Weld(ObjMesh mesh, double tol, out WeldStats stats)
        {
            int n = mesh.V.Count;
            var parent = new int[n];
            for (int i = 0; i < n; ++i)
                parent[i] = i;
            int Find(int i) {
                while (parent[i] != i)
                    i = parent[i] = parent[parent[i]];
                return i;
            }

            /* Every pair (j < i) with distance <= tol, as cKDTree.query_pairs(tol) finds them:
               j is in i's grid cell or one of the 26 around it */
            var grid = new Dictionary<(long, long, long), List<int>>();
            (long, long, long) Cell(double[] p) =>
                ((long)Math.Floor(p[0] / tol), (long)Math.Floor(p[1] / tol), (long)Math.Floor(p[2] / tol));
            double tol2 = tol * tol;
            int pairs = 0;
            for (int i = 0; i < n; ++i) {
                double[] p = mesh.V[i];
                var (cx, cy, cz) = Cell(p);
                for (long dx = -1; dx <= 1; ++dx)
                    for (long dy = -1; dy <= 1; ++dy)
                        for (long dz = -1; dz <= 1; ++dz) {
                            if (!grid.TryGetValue((cx + dx, cy + dy, cz + dz), out List<int>? bucket))
                                continue;
                            foreach (int j in bucket) {
                                double[] q = mesh.V[j];
                                double ex = p[0] - q[0], ey = p[1] - q[1], ez = p[2] - q[2];
                                if (ex * ex + ey * ey + ez * ez > tol2)
                                    continue;
                                ++pairs;
                                int a = Find(i), b = Find(j);   /* the root is the lowest index */
                                if (a != b)
                                    parent[Math.Max(a, b)] = Math.Min(a, b);
                            }
                        }
                if (!grid.TryGetValue((cx, cy, cz), out List<int>? own))
                    grid[(cx, cy, cz)] = own = new List<int>();
                own.Add(i);
            }

            /* Keep each cluster's lowest index, in the original order */
            var welded = new ObjMesh();
            var newIndex = new int[n];
            for (int i = 0; i < n; ++i) {
                int root = Find(i);
                if (root == i) {
                    newIndex[i] = welded.V.Count;
                    welded.V.Add(mesh.V[i]);
                } else {
                    newIndex[i] = newIndex[root];   /* root < i, so it is already numbered */
                }
            }
            int collapsed = 0;
            foreach (int[] face in mesh.Faces) {
                var merged = new int[face.Length];
                var seen = new HashSet<int>();
                bool ok = true;
                for (int k = 0; k < face.Length; ++k) {
                    merged[k] = newIndex[face[k]];
                    ok &= seen.Add(merged[k]);
                }
                if (ok)
                    welded.Faces.Add(merged);
                else
                    ++collapsed;
            }
            stats = new WeldStats {
                Tolerance = tol, PairsWithinTolerance = pairs,
                VBefore = n, VAfter = welded.V.Count,
                FBefore = mesh.Faces.Count, FAfter = welded.Faces.Count, CollapsedFaces = collapsed
            };
            return welded;
        }

        /* Loads an OBJ, welds it and writes the result to outputPath */
        public static WeldStats WeldFile(string inputPath, string outputPath, double tol = DefaultTolerance)
        {
            ObjMesh welded = Weld(ObjMesh.Load(inputPath), tol, out WeldStats stats);
            welded.Save(outputPath);
            return stats;
        }
    }
}
