"""
Unit tests for scripts/rank_trials.py: mesh verification, the gates, the ranking and
an end-to-end run on a synthetic trial log (no native library, no remeshing).

    python3 -m unittest discover -s tests -p 'test_*.py'
"""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'scripts'))
sys.path.insert(0, HERE)        # the synthetic meshes of test_mesh_locality
import rank_trials as R  # noqa: E402
import score_remesh as S  # noqa: E402
import test_mesh_locality as TL  # noqa: E402


def loc(p95=1.0, largest=0, degenerate=0, low_p95=0.5):
    """A locality record with only the fields the gates and the rank read"""
    return {'high_curv_fidelity': {'p95': p95, 'mean': p95 / 2, 'max': p95 * 2},
            'low_curv_fidelity': {'p95': low_p95, 'mean': 0.25, 'max': 1.0},
            'largest_boundary_component_edges': largest, 'degenerate_quads': degenerate,
            'boundary_edges': largest, 'boundary_edges_near_high_curv': 0,
            'boundary_components': 1 if largest else 0}


def row(name, aggregate=0.1, fid_mean=1.0, degenerate=0, path=None, sha='0' * 64):
    return {'name': name, 'stage': 'stage2', 'aggregate': aggregate,
            'params': {'vertex_count': 1, 'crease_angle': -1.0, 'smooth_iter': 0},
            'remesh': {'rc': 0}, 'score_settings': {'samples': 2000, 'seed': 0},
            'output': {'path': path or '/elsewhere/%s.obj' % name, 'sha256': sha},
            'score': {'candidate': {'fidelity': {'mean': fid_mean},
                                    'quad_quality': {'degenerate_quads': degenerate}},
                      'target': {'fidelity': {'mean': 1.0}},
                      'delta': {'dV_pct': 0.0}}}


TARGET = loc(p95=1.0)


class MeshStatus(unittest.TestCase):
    def test_ok_missing_and_changed(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, 'a.obj')
            with open(p, 'w') as f:
                f.write('v 0 0 0\n')
            sha = S.sha256(p)
            # Located by file name under mesh_dir, wherever the log says it was
            self.assertEqual(R.mesh_status(row('a', sha=sha), d), (p, 'ok'))
            self.assertEqual(R.mesh_status(row('a', sha='f' * 64), d)[1], 'sha256 mismatch')
            self.assertEqual(R.mesh_status(row('b', sha=sha), d)[1], 'missing')


class Gates(unittest.TestCase):
    def test_thresholds_default_to_percentile(self):
        locs = [loc(largest=n) for n in range(21)]          # 0..20
        lim = R.thresholds(locs, TARGET, g2_pctl=95, g3_k=2)
        self.assertEqual(lim['G2_max_largest_boundary_component_edges'], 19.0)
        self.assertEqual(lim['G3_max_high_curv_p95'], 2.0)
        lim = R.thresholds(locs, TARGET, g2_max=7, g3_k=1.5)
        self.assertEqual(lim['G2_max_largest_boundary_component_edges'], 7.0)
        self.assertEqual(lim['G2_rule'], 'given')
        self.assertEqual(lim['G3_max_high_curv_p95'], 1.5)

    def test_target_without_curvature_error_is_refused(self):
        with self.assertRaises(ValueError):
            R.thresholds([loc()], loc(p95=0.0))

    def test_gates_are_inclusive_limits(self):
        lim = R.thresholds([loc()], TARGET, g2_max=10, g3_k=2)
        self.assertEqual(R.gates(loc(p95=2.0, largest=10), lim),
                         {'G1': True, 'G2': True, 'G3': True})
        self.assertEqual(R.gates(loc(p95=2.01, largest=11, degenerate=1), lim),
                         {'G1': False, 'G2': False, 'G3': False})


class Rank(unittest.TestCase):
    def test_closeness_to_target_then_fidelity_mean(self):
        rows = [row('far', fid_mean=1.0), row('close', fid_mean=3.0),
                row('below', fid_mean=1.5), row('tie', fid_mean=1.2),
                row('holey', fid_mean=1.0)]
        locs = [loc(p95=1.75), loc(p95=1.25), loc(p95=0.75), loc(p95=1.25),
                loc(p95=1.0, largest=50)]
        statuses = [('/m/%s.obj' % r['name'], 'ok') for r in rows]
        lim, res = R.evaluate(rows, statuses, locs, TARGET, {}, g2_max=20, g3_k=2)
        rank = {x['name']: x['rank'] for x in res}
        # |p95 - target| / target: 0.25 for close, below and tie; tie-break on the
        # fidelity.mean ratio: tie 0.2 < below 0.5 < close 2.0. "holey" matches the
        # target exactly but fails G2
        self.assertEqual(rank, {'tie': 1, 'below': 2, 'close': 3, 'far': 4, 'holey': None})
        holey = res[-1]
        self.assertEqual(holey['gates'], {'G1': True, 'G2': False, 'G3': True})
        self.assertFalse(holey['passed'])
        self.assertEqual(res[0]['rank_key']['high_curv_p95_ratio'], 0.75)
        # M3's own order is kept alongside
        self.assertEqual(sorted(x['aggregate_rank'] for x in res), [1, 2, 3, 4, 5])

    def test_worst_bucket(self):
        # "uneven" is closest on high curvature but 3x the target's low-curvature p95
        rows = [row('uneven'), row('even')]
        locs = [loc(p95=1.25, low_p95=1.5), loc(p95=1.5, low_p95=0.75)]
        statuses = [('/m/a.obj', 'ok'), ('/m/b.obj', 'ok')]
        _, res = R.evaluate(rows, statuses, locs, TARGET, {})
        self.assertEqual([x['rank'] for x in res], [1, 2])
        self.assertEqual(res[0]['rank_key']['low_curv_p95_ratio'], 2.0)
        self.assertEqual(res[0]['rank_key']['worst_bucket_p95_ratio'], 2.0)
        _, res = R.evaluate(rows, statuses, locs, TARGET, {}, rank_by='worst_bucket')
        self.assertEqual([x['rank'] for x in res], [2, 1])
        self.assertEqual(res[0]['settings']['rank_by'], 'worst_bucket')

    def test_unverified_mesh_is_kept_unranked(self):
        rows = [row('a'), row('b')]
        statuses = [('/m/a.obj', 'ok'), ('/m/b.obj', 'missing')]
        _, res = R.evaluate(rows, statuses, [loc(), None], TARGET, {})
        self.assertEqual(res[0]['rank'], 1)
        self.assertEqual((res[1]['rank'], res[1]['passed'], res[1]['gates'],
                          res[1]['locality'], res[1]['mesh']['status']),
                         (None, False, None, None, 'missing'))

    def test_logged_and_recomputed_degenerate_quads_must_agree(self):
        with self.assertRaises(ValueError):
            R.evaluate([row('a', degenerate=1)], [('/m/a.obj', 'ok')], [loc()], TARGET, {})


class EndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = self.tmp.name
        os.makedirs(self.path('meshes'))

    def path(self, *names):
        return os.path.join(self.dir, *names)

    def test_rank_run(self):
        TL.write_obj(self.path('source.obj'), TL.bent_strip(split=True))
        strip = TL.bent_strip()
        # The target sits a little off the source, so its high-curvature p95 is > 0
        TL.write_obj(self.path('target.obj'), TL.mesh(strip.V + [0, 0, 0.01], strip.faces))
        cands = {'plates': TL.mesh(*TL.two_plates()),
                 'near': TL.mesh(strip.V + [0, 0, 0.02], strip.faces),
                 'stale': TL.mesh(strip.V + [0, 0, 0.03], strip.faces),
                 'gone': TL.mesh(strip.V, strip.faces)}
        log = []
        for i, (name, m) in enumerate(cands.items()):
            p = self.path('meshes', name + '.obj')
            TL.write_obj(p, m)
            r = row(name, aggregate=0.1 * i, path='/old/place/%s.obj' % name,
                    sha=S.sha256(p))
            log.append(r)
        # The logged mesh is changed or removed after the fact
        with open(self.path('meshes', 'stale.obj'), 'a') as f:
            f.write('v 0 0 0\n')
        os.remove(self.path('meshes', 'gone.obj'))
        with open(self.path('log.jsonl'), 'w') as f:
            for r in log:
                f.write(json.dumps(r) + '\n')

        scale = TL.RADIUS / S.quad_quality(strip)['edge_length_mean']
        out = self.path('rank.jsonl')
        args = ['--log', self.path('log.jsonl'), '--mesh-dir', self.path('meshes'),
                '--out', out, '--source', self.path('source.obj'),
                '--target', self.path('target.obj'), '--pctl', '40',
                '--radius-scale', repr(scale), '--g2-max', '100', '--g3-k', '2.5',
                '--compare', 'plates', '--workers', '2']
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = R.main(args)
        self.assertEqual(rc, 1)                 # two meshes not verified
        text = buf.getvalue()
        self.assertIn('NOT VERIFIED stale: sha256 mismatch', text)
        self.assertIn('NOT VERIFIED gone: missing', text)
        with open(out) as f:
            res = {x['name']: x for x in map(json.loads, f)}
        self.assertEqual(set(res), set(cands))
        # The near copy is 2x the target's offset: p95 ratio 1, within k = 2.5
        near = res['near']
        self.assertEqual(near['gates'], {'G1': True, 'G2': True, 'G3': True})
        self.assertEqual(near['rank'], 1)
        self.assertAlmostEqual(near['rank_key']['high_curv_p95_ratio'], 1.0, places=6)
        self.assertEqual(near['locality']['boundary_edges'],
                         S.valence(strip)['boundary_edges'])
        # The plates sit up to 0.25 cos 45 off the folds: far past 2.5x the target's
        plates = res['plates']
        self.assertEqual(plates['gates'], {'G1': True, 'G2': True, 'G3': False})
        self.assertIsNone(plates['rank'])
        self.assertIn('plates (M3/D8 pick): gates G1 pass G2 pass G3 FAIL -> rejected',
                      text)
        self.assertIn('new #1: near', text)
        for name in ('stale', 'gone'):
            self.assertIsNone(res[name]['locality'])
            self.assertIsNone(res[name]['rank'])
        self.assertEqual(near['settings']['G2_max_largest_boundary_component_edges'], 100.0)
        self.assertEqual(near['settings']['pctl'], 40.0)
        # Serial and forked runs give the same records
        with redirect_stdout(io.StringIO()):
            R.main(args[:-1] + ['1'])
        with open(out) as f:
            again = {x['name']: x for x in map(json.loads, f)}
        self.assertEqual(again, res)


if __name__ == '__main__':
    unittest.main()
