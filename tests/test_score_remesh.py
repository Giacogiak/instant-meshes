"""
Unit tests for scripts/score_remesh.py, on small synthetic meshes with known metrics.

    python3 -m unittest discover -s tests -p 'test_*.py'
"""

import json
import math
import os
import sys
import tempfile
import unittest

import numpy as np
import trimesh

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', 'scripts'))
import score_remesh as S  # noqa: E402


def grid(n, size=1.0, z=0.0):
    """n x n unit quads in the plane at height z, as (V, faces)"""
    V = [(i * size, j * size, z) for j in range(n + 1) for i in range(n + 1)]
    F = [[j * (n + 1) + i, j * (n + 1) + i + 1, (j + 1) * (n + 1) + i + 1,
          (j + 1) * (n + 1) + i] for j in range(n) for i in range(n)]
    return V, F


def write_obj(path, V, F, style='plain'):
    with open(path, 'w') as f:
        f.write('# test\n')
        for v in V:
            f.write('v %r %r %r\n' % tuple(v))
        for face in F:
            if style == 'normals':      # like Instant Meshes' writer: "f 1//1 2//2 "
                f.write('f ' + ''.join('%d//%d ' % (i + 1, i + 1) for i in face) + '\n')
            elif style == 'negative':
                f.write('f ' + ' '.join(str(i - len(V)) for i in face) + '\n')
            else:
                f.write('f ' + ' '.join(str(i + 1) for i in face) + '\n')


class TempDirTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def path(self, name):
        return os.path.join(self.tmp.name, name)


class LoadObj(TempDirTest):
    def test_index_styles_and_polygons_preserved(self):
        V = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (2, 0, 0)]
        F = [[0, 1, 2, 3], [1, 4, 2]]
        for style in ('plain', 'normals', 'negative'):
            write_obj(self.path('m.obj'), V, F, style)
            m = S.load_obj(self.path('m.obj'))
            self.assertEqual(m.V.shape, (5, 3))
            self.assertEqual([f.tolist() for f in m.faces], F, style)
            self.assertEqual(m.quads().tolist(), [[0, 1, 2, 3]])
            self.assertEqual(len(m.triangles()), 3)


class QuadQuality(TempDirTest):
    def test_regular_grid(self):
        V, F = grid(4)
        q = S.quad_quality(S.PolyMesh(np.array(V, float), [np.array(f) for f in F]))
        self.assertAlmostEqual(q['angle_dev_mean_deg'], 0.0, places=9)
        self.assertAlmostEqual(q['angle_dev_p90_deg'], 0.0, places=9)
        self.assertAlmostEqual(q['edge_length_cv'], 0.0, places=9)
        self.assertEqual(q['edges'], 2 * 4 * 5)
        self.assertEqual(q['non_quad_fraction'], 0.0)

    def test_rhombus_and_nonplanar_quad(self):
        c, s = math.cos(math.radians(60)), math.sin(math.radians(60))
        rhombus = [(0, 0, 0), (1, 0, 0), (1 + c, s, 0), (c, s, 0)]
        q = S.quad_quality(S.PolyMesh(np.array(rhombus, float), [np.arange(4)]))
        self.assertAlmostEqual(q['angle_dev_mean_deg'], 30.0, places=9)
        self.assertAlmostEqual(q['corner_angle_dev_max_deg'], 30.0, places=9)
        self.assertAlmostEqual(q['edge_length_cv'], 0.0, places=9)

        # Non-planar quad: corner angles are taken from the 3D corner vectors,
        # 54.74 deg at (0,0,0) and (1,1,1), 90 deg at the other two corners
        skew = [(0, 0, 0), (1, 0, 0), (1, 0, 1), (1, 1, 1)]
        q = S.quad_quality(S.PolyMesh(np.array(skew, float), [np.arange(4)]))
        acute = math.degrees(math.acos(1 / math.sqrt(3)))
        self.assertAlmostEqual(q['angle_dev_mean_deg'], 2 * (90 - acute) / 4, places=9)
        self.assertAlmostEqual(q['corner_angle_dev_max_deg'], 90 - acute, places=9)

    def test_non_quad_fraction(self):
        V = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (2, 0, 0)]
        m = S.PolyMesh(np.array(V, float), [np.array([0, 1, 2, 3]), np.array([1, 4, 2])])
        q = S.quad_quality(m)
        self.assertEqual(q['non_quad_faces'], 1)
        self.assertAlmostEqual(q['non_quad_fraction'], 0.5)
        self.assertAlmostEqual(q['angle_dev_mean_deg'], 0.0, places=9)


class Valence(TempDirTest):
    def test_grid(self):
        V, F = grid(4)
        v = S.valence(S.PolyMesh(np.array(V, float), [np.array(f) for f in F]))
        self.assertEqual(v['interior_vertices'], 9)
        self.assertEqual(v['pct_valence4_interior'], 100.0)
        self.assertEqual(v['mesh_valence_singularities'], 0)
        self.assertEqual(v['boundary_edges'], 16)
        self.assertEqual(v['histogram'], {'1': 4, '2': 12, '4': 9})

    def test_cube_has_eight_valence3_singularities(self):
        m = trimesh.creation.box()
        # Merge the box's triangle pairs back into its 6 quads
        V = np.array(m.vertices)
        quads = []
        for axis in range(3):
            for sign in (-1, 1):
                ids = np.flatnonzero(np.isclose(V[:, axis], sign * 0.5))
                P = V[ids] - V[ids].mean(axis=0)
                u, w = [a for a in range(3) if a != axis]
                order = np.argsort(np.arctan2(P[:, w], P[:, u]))
                quads.append(ids[order])
        v = S.valence(S.PolyMesh(V, quads))
        self.assertEqual(v['interior_vertices'], 8)
        self.assertEqual(v['mesh_valence_singularities'], 8)
        self.assertEqual(v['pct_valence4_interior'], 0.0)
        self.assertEqual(v['boundary_edges'], 0)


class Fidelity(TempDirTest):
    def test_matches_brute_force_with_large_triangles(self):
        rng = np.random.default_rng(3)
        V = rng.uniform(-1, 1, size=(300, 3))
        V[:30] *= 20                                # a few huge triangles
        T = rng.integers(0, 300, size=(200, 3))
        T = T[(T[:, 0] != T[:, 1]) & (T[:, 1] != T[:, 2]) & (T[:, 0] != T[:, 2])]
        sd = S.SurfaceDistance(V, T)
        points = rng.uniform(-25, 25, size=(500, 3))
        tris = V[T]
        brute = np.array([np.linalg.norm(trimesh.triangles.closest_point(
            tris, np.repeat(p[None], len(tris), 0)) - p, axis=1).min() for p in points])
        np.testing.assert_allclose(sd(points), brute, rtol=0, atol=1e-12)

    def test_offset_plane(self):
        V, F = grid(10)
        src = S.PolyMesh(np.array(V, float), [np.array(f) for f in F])
        sd = S.SurfaceDistance(src.V, src.triangles())
        V2, F2 = grid(5, size=2.0, z=0.25)
        cand = S.PolyMesh(np.array(V2, float), [np.array(f) for f in F2])
        fid = S.fidelity(cand, sd, diag=2.0, samples=2000, seed=1)
        for key in ('mean', 'rms', 'p95', 'max'):
            self.assertAlmostEqual(fid[key], 0.125, places=9)


class EndToEnd(TempDirTest):
    def make(self):
        V, F = grid(10)
        write_obj(self.path('source.obj'), V, F)
        V, F = grid(5, size=2.0, z=0.01)
        write_obj(self.path('target.obj'), V, F, 'normals')
        # Candidate: finer, one quad split into two triangles, raised further
        V, F = grid(6, size=10 / 6, z=0.02)
        F = F[1:] + [[F[0][0], F[0][1], F[0][2]], [F[0][0], F[0][2], F[0][3]]]
        write_obj(self.path('cand.obj'), V, F, 'normals')

    def test_self_check_and_jsonl(self):
        self.make()
        out = self.path('results.jsonl')
        args = ['--source', self.path('source.obj'), '--target', self.path('target.obj'),
                '--out', out, '--samples', '5000']
        S.main(args + ['--candidate', self.path('target.obj')])
        S.main(args + ['--candidate', self.path('cand.obj'), '--weight', 'non_quad=0'])
        with open(out) as f:
            lines = f.read().splitlines()
        self.assertEqual(len(lines), 2)
        own, cand = (json.loads(line) for line in lines)

        terms = own['aggregate']['terms']
        for name in ('count_v', 'count_f', 'valence4', 'fidelity', 'non_quad'):
            self.assertEqual(terms[name], 0.0, name)
        self.assertAlmostEqual(own['target']['fidelity']['mean'], 0.01 / math.sqrt(200))
        self.assertEqual(own['candidate']['fidelity'], own['target']['fidelity'])

        self.assertEqual(cand['candidate']['counts'], {'V': 49, 'F': 37})
        self.assertEqual(cand['delta']['dV'], 49 - 36)
        self.assertEqual(cand['delta']['dF'], 37 - 25)
        t = cand['aggregate']['terms']
        self.assertAlmostEqual(t['count_v'], 13 / 36)
        self.assertAlmostEqual(t['count_f'], 12 / 25)
        self.assertAlmostEqual(t['fidelity'], 1.0)          # 0.02 vs 0.01: +100%
        self.assertAlmostEqual(t['non_quad'], 2 / 37)
        self.assertEqual(cand['aggregate']['weights']['non_quad'], 0.0)
        expected = sum(v for k, v in t.items() if k != 'non_quad') / 6
        self.assertAlmostEqual(cand['aggregate']['score'], expected)

    def test_deterministic(self):
        self.make()
        ref = S.Reference(self.path('source.obj'), self.path('target.obj'), samples=3000)
        a = ref.score(self.path('cand.obj'))
        b = S.Reference(self.path('source.obj'), self.path('target.obj'),
                        samples=3000).score(self.path('cand.obj'))
        for key in ('candidate', 'target', 'delta', 'aggregate'):
            self.assertEqual(a[key], b[key], key)

    def test_rejects_non_finite(self):
        with self.assertRaises(ValueError):
            S.check_finite({'a': [1.0, {'b': float('nan')}]})


if __name__ == '__main__':
    unittest.main()
