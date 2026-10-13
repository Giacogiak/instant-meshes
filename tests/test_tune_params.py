"""
Unit tests for scripts/tune_params.py's pieces that do not need the native library:
welding, the ctypes struct layout and the trial bookkeeping.

    python3 -m unittest discover -s tests -p 'test_*.py'
"""

import ctypes
import os
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', 'scripts'))
import score_remesh as S  # noqa: E402
import tune_params as T  # noqa: E402


def mesh(V, F):
    return S.PolyMesh(np.array(V, dtype=np.float64),
                      [np.array(f, dtype=np.int64) for f in F])


def split_square():
    """Unit square as two triangles that do not share their diagonal's vertices:
    vertices 4 and 5 duplicate 0 and 2, like source.obj's unwelded seams"""
    V = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (0, 0, 0), (1, 1, 0)]
    return mesh(V, [[0, 1, 2], [4, 5, 3]])


class WeldTest(unittest.TestCase):
    def test_merges_duplicated_seam(self):
        w, st = T.weld(split_square(), 1e-5)
        self.assertEqual(len(w.V), 4)
        np.testing.assert_array_equal(w.V, split_square().V[:4])   # order kept
        self.assertEqual([list(f) for f in w.faces], [[0, 1, 2], [0, 2, 3]])
        self.assertEqual(st['pairs_within_tolerance'], 2)
        self.assertEqual((st['boundary_edges_before'], st['boundary_edges_after']), (6, 4))
        self.assertEqual((st['components_before'], st['components_after']), (2, 1))
        self.assertEqual(st['collapsed_faces'], 0)

    def test_keeps_vertices_beyond_tolerance(self):
        m = split_square()
        m.V[4] += (2e-5, 0, 0)
        w, st = T.weld(m, 1e-5)
        self.assertEqual(len(w.V), 5)
        self.assertEqual(st['pairs_within_tolerance'], 1)

    def test_transitive_cluster_and_collapsed_face(self):
        # vertices 0, 1, 2 within tolerance of each other in a chain: one cluster, and
        # the sliver triangle (0, 1, 3) collapses and is dropped
        V = [(0, 0, 0), (0.6e-5, 0, 0), (1.2e-5, 0, 0), (0, 1, 0), (1, 0, 0)]
        w, st = T.weld(mesh(V, [[0, 1, 3], [2, 4, 3]]), 1e-5)
        self.assertEqual(len(w.V), 3)
        self.assertEqual([list(f) for f in w.faces], [[0, 2, 1]])
        self.assertEqual(st['collapsed_faces'], 1)

    def test_write_obj_round_trip(self):
        m = mesh([(0.1, 1e-7, 105.67), (1, 0, 0), (0, 1, 0), (1, 1, 0)], [[0, 1, 3, 2]])
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'm.obj')
            T.write_obj(path, m)
            r = S.load_obj(path)
        np.testing.assert_array_equal(r.V, m.V)
        self.assertEqual([list(f) for f in r.faces], [[0, 1, 3, 2]])


class ParamsTest(unittest.TestCase):
    def test_struct_matches_capi_h(self):
        # 10 ints + 2 floats in header order (M1.1 measured sizeof = 48)
        self.assertEqual(ctypes.sizeof(T.ImRemeshParams), 48)
        self.assertEqual(T.ImRemeshParams.vertex_count.offset, 16)
        self.assertEqual(T.ImRemeshParams.deterministic.offset, 44)
        self.assertEqual(ctypes.sizeof(T.ImRemeshResult), 8)

    def test_trial_params(self):
        p = T.trial_params(2770, T.CREASE_OFF, 2)
        self.assertEqual(set(p), {f for f, _ in T.ImRemeshParams._fields_})
        self.assertEqual((p['rosy'], p['posy'], p['pure_quad'], p['deterministic']),
                         (4, 4, 1, 1))
        self.assertEqual((p['scale'], p['face_count']), (-1.0, -1))
        T.ImRemeshParams(**p)       # accepted by ctypes as is
        self.assertEqual(T.trial_name(p), 'v2770_coff_s2')
        self.assertEqual(T.trial_name(T.trial_params(2770, 22.5, 0)), 'v2770_c22.5_s0')
        self.assertEqual(T.trial_key(p), T.trial_key(dict(reversed(list(p.items())))))

    def test_best_row(self):
        rows = [{'aggregate': 0.3, 'name': 'b'}, {'aggregate': None, 'name': 'a'},
                {'aggregate': 0.2, 'name': 'c'}, {'aggregate': 0.2, 'name': 'a2'}]
        self.assertEqual(T.best_row(rows)['name'], 'a2')
        with self.assertRaises(RuntimeError):
            T.best_row([{'aggregate': None, 'name': 'x'}])


if __name__ == '__main__':
    unittest.main()
