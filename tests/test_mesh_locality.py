"""
Unit tests for scripts/mesh_locality.py and the return_triangle / return_detail /
return_labels options it adds to score_remesh.py and tune_params.py, on synthetic
meshes with a known curvature split.

    python3 -m unittest discover -s tests -p 'test_*.py'
"""

import json
import os
import sys
import tempfile
import unittest

import numpy as np
import trimesh

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', 'scripts'))
import mesh_locality as L  # noqa: E402
import score_remesh as S  # noqa: E402
import tune_params as T  # noqa: E402

CREASE_X = 10.0
RADIUS = 0.25       # less than the strip's 0.5 x-spacing: a ball only sees its own crease


def mesh(V, F):
    return S.PolyMesh(np.array(V, dtype=np.float64),
                      [np.array(f, dtype=np.int64) for f in F])


def grid(xs, ys, z):
    """Quad grid over the x and y coordinates, z = z(x)"""
    nx = len(xs)
    V = [(x, y, z(x)) for y in ys for x in xs]
    F = [[j * nx + i, j * nx + i + 1, (j + 1) * nx + i + 1, (j + 1) * nx + i]
         for j in range(len(ys) - 1) for i in range(nx - 1)]
    return V, F


def zigzag(x):
    """0 up to CREASE_X, then folds of +-45 deg at every 0.5 step (between 0 and 0.5)"""
    if x <= CREASE_X:
        return 0.0
    k = int(round((x - CREASE_X) / 0.5))
    return 0.5 if k % 2 else 0.0


def bent_strip(split=False):
    """Flat half (x in [0, 10]) + sharply creased half (x in [10, 20]), 4 wide.
    With split, the halves are separate components with duplicated seam vertices at
    x = 10, like source.obj's unwelded seams."""
    ys = np.arange(0, 4.5, 1.0)
    if not split:
        return mesh(*grid(np.arange(0, 20.25, 0.5), ys, zigzag))
    V1, F1 = grid(np.arange(0, 10.25, 0.5), ys, zigzag)
    V2, F2 = grid(np.arange(10, 20.25, 0.5), ys, zigzag)
    return mesh(V1 + V2, F1 + [[i + len(V1) for i in f] for f in F2])


def two_plates():
    """Candidate: a plate on the flat half (z = 0, exact) and one over the creased half
    at the zigzag's mid-height (z = 0.25), as two components"""
    VA, FA = grid(np.arange(0, 9.5, 1.0), np.arange(0, 4.5, 1.0), lambda x: 0.0)
    VB, FB = grid(np.arange(10, 20.5, 1.0), np.arange(0, 4.5, 1.0), lambda x: 0.25)
    return VA + VB, FA + [[i + len(VA) for i in f] for f in FB]


def write_obj(path, m):
    with open(path, 'w') as f:
        for v in m.V:
            f.write('v %r %r %r\n' % tuple(float(x) for x in v))
        for face in m.faces:
            f.write('f ' + ' '.join(str(i + 1) for i in face) + '\n')


class SurfaceDistanceTriangle(unittest.TestCase):
    def test_nearest_triangle_matches_brute_force(self):
        # Same fixture as test_score_remesh's brute-force test: the huge triangles
        # send many points through the exhaustive fallback pass
        rng = np.random.default_rng(3)
        V = rng.uniform(-1, 1, size=(300, 3))
        V[:30] *= 20
        F = rng.integers(0, 300, size=(200, 3))
        F = F[(F[:, 0] != F[:, 1]) & (F[:, 1] != F[:, 2]) & (F[:, 0] != F[:, 2])]
        sd = S.SurfaceDistance(V, F)
        points = rng.uniform(-25, 25, size=(500, 3))
        d, tri = sd(points, return_triangle=True)
        np.testing.assert_array_equal(d, sd(points))
        tris = V[F]
        brute = np.array([np.linalg.norm(trimesh.triangles.closest_point(
            tris, np.repeat(p[None], len(tris), 0)) - p, axis=1) for p in points])
        np.testing.assert_allclose(d, brute.min(axis=1), rtol=0, atol=1e-12)
        np.testing.assert_allclose(brute[np.arange(len(points)), tri], d,
                                   rtol=0, atol=1e-12)


class ReturnDetail(unittest.TestCase):
    def test_quad_quality_degenerate_mask(self):
        V = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (2, 0, 0)]
        m = mesh(V, [[0, 1, 2], [0, 1, 2, 3], [1, 4, 1, 2]])
        q, detail = S.quad_quality(m, return_detail=True)
        self.assertEqual(q, S.quad_quality(m))
        self.assertEqual(detail['quad_faces'].tolist(), [1, 2])
        self.assertEqual(detail['degenerate'].tolist(), [False, True])

    def test_valence_boundary_edges(self):
        V, F = grid(np.arange(3.0), np.arange(3.0), lambda x: 0.0)
        m = mesh(V, F)
        v, detail = S.valence(m, return_detail=True)
        self.assertEqual(v, S.valence(m))
        self.assertEqual(len(detail['boundary_edges']), v['boundary_edges'])
        self.assertEqual(len(detail['boundary_edges']), 8)
        self.assertEqual(np.flatnonzero(~detail['not_interior']).tolist(), [4])

    def test_components_labels(self):
        m = mesh([(0, 0, 0)] * 7, [[0, 1, 2], [3, 4, 5], [4, 5, 6]])
        self.assertEqual(T.components(7, m), 2)
        n, labels = T.components(7, m, return_labels=True)
        self.assertEqual(n, 2)
        self.assertEqual(len(set(labels[[0, 1, 2]])), 1)
        self.assertEqual(len(set(labels[[3, 4, 5, 6]])), 1)
        self.assertNotEqual(labels[0], labels[3])


class _AllSegments:
    """Exhaustive face_adjacency_tree: every segment is a candidate for every point"""

    def __init__(self, n):
        self.n = n

    def intersection_v(self, mins, maxs):
        return np.tile(np.arange(self.n), len(mins)), np.full(len(mins), self.n)


class Curvature(unittest.TestCase):
    def test_rtree_free_measure_matches_exhaustive_candidates(self):
        sphere = trimesh.creation.icosphere(subdivisions=2)
        rng = np.random.default_rng(0)
        points = np.vstack([sphere.vertices[:40], rng.uniform(-1.2, 1.2, (60, 3))])
        exhaustive = L._CurvatureMesh(sphere)
        exhaustive.face_adjacency_tree = _AllSegments(len(sphere.face_adjacency_edges))
        for radius in (0.1, 0.3, 1.0):
            expected = trimesh.curvature.discrete_mean_curvature_measure(
                exhaustive, points, radius)
            self.assertTrue((expected > 0).any())
            np.testing.assert_allclose(L.mean_curvature_measure(sphere, points, radius,
                                                                chunk=17),
                                       expected, rtol=0, atol=1e-12)

    def test_bent_strip_split(self):
        strip = bent_strip()
        curv = L.SourceCurvature(strip.trimesh(), RADIUS, pctl=40)
        x = strip.V[:, 0]
        H = np.abs(curv.mean)
        # Every vertex from x = 10 up to the strip's (straight) end lies on a fold
        self.assertTrue(np.all(H[x < CREASE_X] == 0))
        self.assertTrue(np.all(H[(x >= CREASE_X) & (x < 20)] > 0))
        self.assertTrue(np.all(H[x == 20] < 1e-6))      # arccos rounding only
        # 20 of 41 columns are folded: the top 40% are all on the creased half (ties
        # at the threshold can add a few more)
        self.assertTrue(np.all(x[curv.high_vertex] >= CREASE_X))
        self.assertGreaterEqual(curv.high_vertex.mean(), 0.4)
        T_ = strip.triangles()
        tri_x = strip.V[T_][:, :, 0]
        self.assertFalse(curv.high_triangle[tri_x.max(axis=1) < CREASE_X].any())
        s = curv.summary
        self.assertEqual(s['high_vertices'], int(curv.high_vertex.sum()))
        self.assertEqual(s['high_region_components'], 1)
        self.assertGreaterEqual(s['high_region_bbox'][0][0], CREASE_X)

    def test_seams_need_the_weld(self):
        # Unwelded, the x = 10 seam has no face adjacency, so its fold is invisible
        split = bent_strip(split=True)
        seam = np.isclose(split.V[:, 0], CREASE_X)
        unwelded = L.SourceCurvature(split.trimesh(), RADIUS, pctl=40)
        # (up to arccos rounding on the coplanar triangle pairs)
        self.assertTrue(np.all(np.abs(unwelded.mean[seam]) < 1e-6))
        sd = S.SurfaceDistance(split.V, split.triangles())
        welded = L.welded_source_trimesh(split, sd)
        curv = L.SourceCurvature(welded, RADIUS, pctl=40)
        seam_w = np.isclose(np.asarray(welded.vertices)[:, 0], CREASE_X)
        self.assertTrue(np.all(np.abs(curv.mean[seam_w]) > 0.05))


class Locality(unittest.TestCase):
    def setUp(self):
        strip = bent_strip()
        self.sd = S.SurfaceDistance(strip.V, strip.triangles())
        self.curv = L.SourceCurvature(strip.trimesh(), RADIUS, pctl=40)

    def test_two_plates(self):
        cand = mesh(*two_plates())
        loc = L.locality(cand, self.sd, self.curv, diag=1.0, samples=4000, seed=2)
        points, _ = trimesh.sample.sample_surface(cand.trimesh(), 4000, seed=2)
        on_creased = int((points[:, 0] >= CREASE_X).sum())
        hi, lo = loc['high_curv_fidelity'], loc['low_curv_fidelity']
        # The flat plate lies on the flat half: low curvature, distance 0. The other
        # plate is over the folds: high curvature, 0 < distance <= 0.25 cos 45 deg
        self.assertEqual(hi['samples'], on_creased)
        self.assertEqual(lo['samples'], 4000 - on_creased)
        self.assertAlmostEqual(loc['high_curv_sample_fraction'], on_creased / 4000)
        self.assertAlmostEqual(lo['max'], 0.0, places=12)
        self.assertGreater(hi['mean'], 0.0)
        self.assertLessEqual(hi['max'], 0.25 * np.sqrt(0.5) + 1e-12)
        self.assertGreaterEqual(hi['p95'], hi['mean'])
        # Boundaries: flat plate 9 x 4 quads (26 edges), creased plate 10 x 4 (28)
        self.assertEqual(loc['boundary_edges'], 54)
        self.assertEqual(loc['boundary_edges_near_high_curv'], 28)
        self.assertEqual(loc['boundary_components'], 2)
        self.assertEqual(loc['largest_boundary_component_edges'], 28)
        self.assertEqual(loc['degenerate_quads'], 0)
        self.assertEqual(loc['degenerate_quads_near_high_curv'], 0)

    def test_degenerate_quads(self):
        V, F = two_plates()
        n = len(V)
        # Two folded [a v a b] quads, one over each half
        V = V + [(5, 1.5, 0), (5.5, 1.5, 0), (5, 2, 0),
                 (15, 1.5, 0.25), (15.5, 1.5, 0.25), (15, 2, 0.25)]
        F = F + [[n, n + 1, n, n + 2], [n + 3, n + 4, n + 3, n + 5]]
        loc = L.locality(mesh(V, F), self.sd, self.curv, diag=1.0, samples=2000, seed=0)
        self.assertEqual(loc['degenerate_quads'], 2)
        self.assertEqual(loc['degenerate_quads_near_high_curv'], 1)

    def test_closed_mesh_has_no_boundary(self):
        box = trimesh.creation.box(extents=(30, 10, 10))
        m = mesh(box.vertices, box.faces)
        loc = L.locality(m, self.sd, self.curv, diag=1.0, samples=500, seed=0)
        self.assertEqual(loc['boundary_edges'], 0)
        self.assertEqual(loc['boundary_components'], 0)
        self.assertEqual(loc['largest_boundary_component_edges'], 0)


class EndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def path(self, name):
        return os.path.join(self.tmp.name, name)

    def test_cli_record(self):
        # Unwelded source: LocalityReference welds it before computing curvature
        write_obj(self.path('source.obj'), bent_strip(split=True))
        target = bent_strip()
        write_obj(self.path('target.obj'), target)
        write_obj(self.path('cand.obj'), mesh(*two_plates()))
        out = self.path('loc.jsonl')
        scale = RADIUS / S.quad_quality(target)['edge_length_mean']
        args = ['--source', self.path('source.obj'), '--target', self.path('target.obj'),
                '--candidate', self.path('cand.obj'), '--out', out, '--samples', '3000',
                '--pctl', '40', '--radius-scale', repr(scale)]
        self.assertEqual(L.main(args), 0)
        L.main(args)
        with open(out) as f:
            a, b = (json.loads(line) for line in f)
        self.assertEqual(a, b)
        self.assertAlmostEqual(a['curvature']['radius'], RADIUS)
        self.assertEqual(a['settings'], {'samples': 3000, 'seed': 0, 'pctl': 40.0,
                                         'radius_scale': scale})
        for who in ('candidate', 'target'):
            loc = a[who]['locality']
            for bucket in ('high_curv_fidelity', 'low_curv_fidelity'):
                self.assertEqual(set(loc[bucket]), {'samples', 'mean', 'rms', 'p95', 'max'})
        # The target is the source surface itself
        self.assertAlmostEqual(a['target']['locality']['high_curv_fidelity']['max'], 0.0,
                               places=12)
        self.assertEqual(a['candidate']['locality']['boundary_edges_near_high_curv'], 28)


if __name__ == '__main__':
    unittest.main()
