#!/usr/bin/env python3
"""
rank_trials.py -- constraint-first re-ranking of the trials M3 already logged
(Milestone M5, plan/roadmap/05_M5_locality-reranking.md, Task 2)

    rank_trials.py [--log tuning_results.jsonl] [--out tuning_runs/rank_results.jsonl]

For every trial in the M3 log, checks that its output mesh under tuning_runs/meshes/
still has the logged sha256, computes mesh_locality's `locality` block for it (and
for the target), applies three gates and ranks the trials that pass all three:

  G1  no degenerate quads             degenerate_quads == 0
  G2  no large boundary hole          largest_boundary_component_edges <= N
                                      (D10, default N = the trials' own 95th percentile)
  G3  curvature-region fidelity       high_curv_fidelity.p95 <= k * the target's
                                      (D11, default k = 2)

Rank (D12): score_remesh.ratio() of high_curv_fidelity.p95 relative to the target's,
i.e. |p95 - p95_target| / p95_target, lowest first; ties broken by the same ratio of
the global fidelity.mean that M3 logged, then by name. --rank-by worst_bucket ranks by
the larger of the high- and low-curvature p95 ratios instead.

Writes one JSON line per trial to --out (rewritten on every run) and prints a report.
A trial whose mesh is missing or whose sha256 differs from the log is reported, kept
in the output with mesh.status set and rank null, and makes the exit status 1.

This script never remeshes: it only reads OBJ files that already exist.
"""

import argparse
import json
import multiprocessing
import os
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import mesh_locality  # noqa: E402
import score_remesh  # noqa: E402
import tune_params  # noqa: E402

RANK_VERSION = 1

DEFAULT_LOG = tune_params.DEFAULT_LOG
DEFAULT_MESH_DIR = os.path.join(tune_params.WORK_DIR, 'meshes')
DEFAULT_OUT = os.path.join(tune_params.WORK_DIR, 'rank_results.jsonl')

# G2 (D10): N defaults to this percentile of the trials' own largest boundary components
DEFAULT_G2_PCTL = 95.0
# G3 (D11): high_curv_fidelity.p95 at most k times the target's
DEFAULT_G3_K = 2.0
# The M3/D8 pick, whose new status the report states
DEFAULT_COMPARE = 'v2799_coff_s1'

# D12: what the primary rank key is
RANK_BY = {'high_p95': 'high_curv_p95_ratio', 'worst_bucket': 'worst_bucket_p95_ratio'}
DEFAULT_RANK_BY = 'high_p95'
# The report also lists the best passing trials within this |dV| of the target
COUNT_BAND_PCT = 5.0

SWEPT = ('vertex_count', 'crease_angle', 'smooth_iter')
REPORT_PERCENTILES = (0, 5, 10, 25, 50, 75, 90, 95, 100)


# ---------------------------------------------------------------- inputs

def mesh_status(row, mesh_dir):
    """(path, status) of a trial's output mesh: status is 'ok', 'missing' or
    'sha256 mismatch'"""
    path = os.path.join(mesh_dir, os.path.basename(row['output']['path']))
    if not os.path.isfile(path):
        return path, 'missing'
    if score_remesh.sha256(path) != row['output']['sha256']:
        return path, 'sha256 mismatch'
    return path, 'ok'


def scored_rows(log_path):
    """The log's rows whose remesh succeeded, one per trial name"""
    rows = [r for r in tune_params.read_log(log_path) if r['remesh']['rc'] == 0]
    names = [r['name'] for r in rows]
    if len(set(names)) != len(names):
        raise ValueError('%s logs some trial names more than once' % log_path)
    return rows


# ---------------------------------------------------------------- locality

_shared = {}


def _locality(path):
    return _shared['lref'].locality(score_remesh.load_obj(path))


def localities(lref, paths, workers):
    """lref.locality() of every path. Workers are forked, so they share the built
    reference instead of rebuilding it."""
    _shared['lref'] = lref
    try:
        if workers <= 1 or len(paths) <= 1:
            return [_locality(p) for p in paths]
        with multiprocessing.get_context('fork').Pool(min(workers, len(paths))) as pool:
            return pool.map(_locality, paths, chunksize=1)
    finally:
        _shared.clear()


# ---------------------------------------------------------------- gates and rank

def thresholds(locs, target_loc, g2_max=None, g2_pctl=DEFAULT_G2_PCTL, g3_k=DEFAULT_G3_K):
    """The gates' limits. G2's N is g2_max if given, otherwise the g2_pctl percentile
    of the trials' largest_boundary_component_edges."""
    largest = [loc['largest_boundary_component_edges'] for loc in locs]
    if g2_max is None:
        if not largest:
            raise ValueError('no trials to take the G2 percentile of')
        g2_max = float(np.percentile(largest, g2_pctl))
        g2_rule = 'p%g of the trials' % g2_pctl
    else:
        g2_rule = 'given'
    target_p95 = target_loc['high_curv_fidelity']['p95']
    if not target_p95:
        raise ValueError("the target's high_curv_fidelity.p95 is %r: G3 needs it > 0"
                         % target_p95)
    return {'G2_max_largest_boundary_component_edges': float(g2_max), 'G2_rule': g2_rule,
            'G3_k': float(g3_k), 'G3_target_high_curv_p95': target_p95,
            'G3_max_high_curv_p95': g3_k * target_p95}


def gates(loc, limits):
    p95 = loc['high_curv_fidelity']['p95']
    return {
        'G1': loc['degenerate_quads'] == 0,
        'G2': loc['largest_boundary_component_edges'] <=
              limits['G2_max_largest_boundary_component_edges'],
        # A candidate with no high-curvature samples has nothing to bound
        'G3': p95 is None or p95 <= limits['G3_max_high_curv_p95'],
    }


def rank_key(loc, target_loc, fidelity_mean, target_fidelity_mean):
    """score_remesh.ratio() of each bucket's p95 and of the global fidelity.mean, all
    relative to the target. An undefined ratio sorts last."""
    def r(x, ref):
        v = score_remesh.ratio(x - ref, ref) if x is not None else None
        return float('inf') if v is None else v
    hi = r(loc['high_curv_fidelity']['p95'], target_loc['high_curv_fidelity']['p95'])
    lo = r(loc['low_curv_fidelity']['p95'], target_loc['low_curv_fidelity']['p95'])
    return {'high_curv_p95_ratio': hi, 'low_curv_p95_ratio': lo,
            'worst_bucket_p95_ratio': max(hi, lo),
            'fidelity_mean_ratio': r(fidelity_mean, target_fidelity_mean)}


def assign_ranks(results, rank_by=DEFAULT_RANK_BY):
    """Sets 'rank' (1 = best) on the results that passed, None on the others"""
    primary = RANK_BY[rank_by]
    passed = [x for x in results if x['passed']]
    passed.sort(key=lambda x: (x['rank_key'][primary],
                               x['rank_key']['fidelity_mean_ratio'], x['name']))
    for x in results:
        x['rank'] = None
    for i, x in enumerate(passed):
        x['rank'] = i + 1
    return results


def aggregate_ranks(rows):
    """M3's rank of each trial by its logged aggregate score (1 = best)"""
    order = sorted(rows, key=lambda r: (r['aggregate'], r['name']))
    return {r['name']: i + 1 for i, r in enumerate(order)}


def evaluate(rows, statuses, locs, target_loc, settings, g2_max=None,
             g2_pctl=DEFAULT_G2_PCTL, g3_k=DEFAULT_G3_K, rank_by=DEFAULT_RANK_BY):
    """The output rows. statuses[i] = (path, status); locs[i] is None unless status is
    'ok'. Returns (limits, results)."""
    ok_locs = [loc for loc in locs if loc is not None]
    limits = thresholds(ok_locs, target_loc, g2_max, g2_pctl, g3_k)
    agg_rank = aggregate_ranks(rows)
    results = []
    for row, (path, status), loc in zip(rows, statuses, locs):
        cf, tf = row['score']['candidate']['fidelity'], row['score']['target']['fidelity']
        x = {'name': row['name'], 'stage': row['stage'], 'params': row['params'],
             'mesh': {'path': path, 'sha256': row['output']['sha256'], 'status': status},
             'aggregate': row['aggregate'], 'aggregate_rank': agg_rank[row['name']],
             'dV_pct': row['score']['delta']['dV_pct'],
             'fidelity_mean': cf['mean'], 'gates': None, 'passed': False,
             'locality': loc, 'rank_key': None, 'rank': None}
        if loc is not None:
            logged = row['score']['candidate']['quad_quality']['degenerate_quads']
            if logged != loc['degenerate_quads']:
                raise ValueError('%s: %d degenerate quads logged, %d recomputed'
                                 % (row['name'], logged, loc['degenerate_quads']))
            x['gates'] = gates(loc, limits)
            x['passed'] = all(x['gates'].values())
            x['rank_key'] = rank_key(loc, target_loc, cf['mean'], tf['mean'])
        x['settings'] = dict(settings, rank_by=rank_by, **limits)
        results.append(x)
    assign_ranks(results, rank_by)
    for x in results:
        score_remesh.check_finite(x)
    return limits, results


def write_results(path, results):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        for x in results:
            f.write(json.dumps(x, sort_keys=True, allow_nan=False) + '\n')
    os.replace(tmp, path)


# ---------------------------------------------------------------- report

def p95_ratio(x, limits):
    return x['locality']['high_curv_fidelity']['p95'] / limits['G3_target_high_curv_p95']


def percentile_line(values):
    return ', '.join('p%d=%.4g' % (p, np.percentile(values, p)) for p in REPORT_PERCENTILES)


def trial_line(x, limits):
    loc = x['locality']
    return ('%-4s %-15s dV %+5.1f%%  hi-p95 %.3fx  lo-p95 %.3e  fid-mean %.3e  '
            'largest-bnd %3d  bnd %3d (%3d near hi)  degen %d  M3 #%-3d %.6f' % (
                '#%d' % x['rank'] if x['rank'] else '-', x['name'], x['dV_pct'],
                p95_ratio(x, limits), loc['low_curv_fidelity']['p95'], x['fidelity_mean'],
                loc['largest_boundary_component_edges'], loc['boundary_edges'],
                loc['boundary_edges_near_high_curv'], loc['degenerate_quads'],
                x['aggregate_rank'], x['aggregate']))


def report(results, limits, target_loc, curvature, compare=DEFAULT_COMPARE, top=10,
           rank_by=DEFAULT_RANK_BY):
    ok = [x for x in results if x['locality'] is not None]
    bad = [x for x in results if x['locality'] is None]
    print('trials: %d logged, %d meshes verified, %d missing or changed'
          % (len(results), len(ok), len(bad)))
    for x in bad:
        print('  NOT VERIFIED %s: %s (%s)' % (x['name'], x['mesh']['status'],
                                             x['mesh']['path']))
    print('curvature: radius %.4f, top %g%% |mean curvature measure| (%.2f%% of the '
          'source area)' % (curvature['radius'], curvature['pctl'],
                            100 * curvature['high_area_fraction']))
    th, tl = target_loc['high_curv_fidelity'], target_loc['low_curv_fidelity']
    print('target: high_curv p95 %.4e mean %.4e | low_curv p95 %.4e mean %.4e | '
          'largest boundary component %d edges'
          % (th['p95'], th['mean'], tl['p95'], tl['mean'],
             target_loc['largest_boundary_component_edges']))
    if not ok:
        return

    print('\nG1 degenerate_quads == 0: %d fail' % sum(not x['gates']['G1'] for x in ok))
    for x in ok:
        if not x['gates']['G1']:
            print('  ' + trial_line(x, limits))

    largest = [x['locality']['largest_boundary_component_edges'] for x in ok]
    print('\nG2 largest_boundary_component_edges <= %g (%s), D10: %d fail'
          % (limits['G2_max_largest_boundary_component_edges'], limits['G2_rule'],
             sum(not x['gates']['G2'] for x in ok)))
    print('  distribution: ' + percentile_line(largest))
    values, counts = np.unique(largest, return_counts=True)
    print('  histogram (edges:trials): ' + ' '.join('%d:%d' % vc for vc in zip(values, counts)))
    for x in sorted(ok, key=lambda x: -x['locality']['largest_boundary_component_edges']):
        if not x['gates']['G2']:
            print('  ' + trial_line(x, limits))

    ratios = [p95_ratio(x, limits) for x in ok]
    print('\nG3 high_curv_fidelity.p95 <= %g x target (%.4e), D11: %d fail'
          % (limits['G3_k'], limits['G3_max_high_curv_p95'],
             sum(not x['gates']['G3'] for x in ok)))
    print('  p95 / target p95: ' + percentile_line(ratios))
    edges = np.arange(np.floor(min(ratios) * 10) / 10, max(ratios) + 0.1, 0.1)
    hist, _ = np.histogram(ratios, bins=edges)
    print('  histogram: ' + ' '.join('[%.1f,%.1f):%d' % (a, a + 0.1, n)
                                     for a, n in zip(edges, hist)))
    for x in sorted(ok, key=lambda x: -p95_ratio(x, limits)):
        if not x['gates']['G3']:
            print('  ' + trial_line(x, limits))

    passed = sorted((x for x in ok if x['passed']), key=lambda x: x['rank'])
    print('\npassed all gates: %d of %d, ranked by %s (D12)'
          % (len(passed), len(ok), RANK_BY[rank_by]))
    for x in passed[:top]:
        print('  ' + trial_line(x, limits))
    # What the D12 choice and the vertex count do to the top of the ranking
    for other in sorted(set(RANK_BY) - {rank_by}):
        print('the top %d if ranked by %s instead:' % (top // 2, RANK_BY[other]))
        for x in sorted(passed, key=lambda x: (x['rank_key'][RANK_BY[other]],
                                               x['rank_key']['fidelity_mean_ratio'],
                                               x['name']))[:top // 2]:
            print('  %s  %s %.3f' % (trial_line(x, limits), RANK_BY[other],
                                     x['rank_key'][RANK_BY[other]]))
    band = [x for x in passed if abs(x['dV_pct']) <= COUNT_BAND_PCT]
    print('the top %d within |dV| <= %g%% of the target V (%d passing trials):'
          % (top // 2, COUNT_BAND_PCT, len(band)))
    for x in band[:top // 2]:
        print('  ' + trial_line(x, limits))

    # Spearman rank correlation of the new primary metric with M3's aggregate
    hi = np.argsort(np.argsort(ratios))
    agg = np.argsort(np.argsort([x['aggregate'] for x in ok]))
    print('\nSpearman(high_curv p95, M3 aggregate) over %d trials: %.3f'
          % (len(ok), np.corrcoef(hi, agg)[0, 1]))

    # Main effect of each swept parameter on the primary metric and the pass rate
    for p in SWEPT:
        print('%s:' % p)
        for lv in sorted({x['params'][p] for x in ok}):
            sel = [x for x in ok if x['params'][p] == lv]
            print('  %-8g n %3d  hi-p95 ratio mean %.3f min %.3f  passed %d'
                  % (lv, len(sel), np.mean([p95_ratio(x, limits) for x in sel]),
                     min(p95_ratio(x, limits) for x in sel), sum(x['passed'] for x in sel)))

    by_name = {x['name']: x for x in results}
    c = by_name.get(compare)
    print()
    if c is None:
        print('%s: not in the log' % compare)
    elif c['locality'] is None:
        print('%s: mesh %s, not ranked' % (compare, c['mesh']['status']))
    else:
        print('%s (M3/D8 pick): gates %s -> %s, new rank %s of %d'
              % (compare, ' '.join('%s %s' % (g, 'pass' if v else 'FAIL')
                                    for g, v in c['gates'].items()),
                 'passed' if c['passed'] else 'rejected',
                 c['rank'] if c['rank'] else 'none', len(passed)))
        print('  ' + trial_line(c, limits))
    if passed:
        b = passed[0]
        print('new #1: %s  params %s' % (b['name'], json.dumps(
            {p: b['params'][p] for p in SWEPT}, sort_keys=True)))
        print('  mesh: %s' % b['mesh']['path'])
        print('  ' + trial_line(b, limits))
        if c is not None and c['locality'] is not None and c is not b:
            bl, cl = b['locality'], c['locality']
            print('  vs %s:' % compare)
            for key in ('high_curv_fidelity', 'low_curv_fidelity'):
                for stat in ('p95', 'mean', 'max'):
                    print('    %-24s %.4e vs %.4e' % ('%s.%s' % (key, stat),
                                                     bl[key][stat], cl[key][stat]))
            for key in ('boundary_edges', 'boundary_edges_near_high_curv',
                        'boundary_components', 'largest_boundary_component_edges'):
                print('    %-24s %d vs %d' % (key, bl[key], cl[key]))
            print('    %-24s %.4e vs %.4e' % ('fidelity.mean (M3)', b['fidelity_mean'],
                                              c['fidelity_mean']))
            print('    %-24s %.6f (#%d) vs %.6f (#%d)' % (
                'M3 aggregate', b['aggregate'], b['aggregate_rank'], c['aggregate'],
                c['aggregate_rank']))


# ---------------------------------------------------------------- main

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0].strip())
    parser.add_argument('--log', default=DEFAULT_LOG, help='M3 trial log (default %(default)s)')
    parser.add_argument('--mesh-dir', default=DEFAULT_MESH_DIR,
                        help="trials' output meshes (default %(default)s)")
    parser.add_argument('--out', default=DEFAULT_OUT,
                        help='rank results, rewritten (default %(default)s)')
    parser.add_argument('--source', default=tune_params.SOURCE)
    parser.add_argument('--target', default=tune_params.TARGET)
    parser.add_argument('--pctl', type=float, default=mesh_locality.DEFAULT_PCTL,
                        help='high-curvature percentile, D9 (default %(default)s)')
    parser.add_argument('--radius-scale', type=float,
                        default=mesh_locality.DEFAULT_RADIUS_SCALE,
                        help="curvature radius / target's mean edge length, D9 "
                             '(default %(default)s)')
    parser.add_argument('--g2-max', type=float,
                        help='G2 limit on largest_boundary_component_edges, D10 '
                             '(default: the --g2-pctl percentile of the trials)')
    parser.add_argument('--g2-pctl', type=float, default=DEFAULT_G2_PCTL,
                        help='percentile for the default G2 limit (default %(default)s)')
    parser.add_argument('--g3-k', type=float, default=DEFAULT_G3_K,
                        help="G3 limit, as a multiple of the target's high_curv p95, D11 "
                             '(default %(default)s)')
    parser.add_argument('--rank-by', choices=sorted(RANK_BY), default=DEFAULT_RANK_BY,
                        help='primary rank key, D12: high_p95 = high_curv p95 ratio, '
                             'worst_bucket = the larger of the high and low_curv p95 '
                             'ratios (default %(default)s)')
    parser.add_argument('--compare', default=DEFAULT_COMPARE,
                        help='trial whose new status the report states (default %(default)s)')
    parser.add_argument('--workers', type=int, default=max(1, min(4, os.cpu_count() or 1)),
                        help='forked worker processes (default %(default)s)')
    args = parser.parse_args(argv)
    if not (0 < args.pctl < 100) or args.radius_scale <= 0:
        parser.error('need 0 < --pctl < 100 and --radius-scale > 0')
    if not (0 <= args.g2_pctl <= 100) or args.g3_k <= 0:
        parser.error('need 0 <= --g2-pctl <= 100 and --g3-k > 0')

    rows = scored_rows(args.log)
    statuses = [mesh_status(r, args.mesh_dir) for r in rows]
    settings_list = {tuple(sorted(r['score_settings'].items())) for r in rows}
    if len(settings_list) > 1:
        raise ValueError('the log mixes score settings: %r' % settings_list)
    s = rows[0]['score_settings'] if rows else {'samples': score_remesh.DEFAULT_SAMPLES,
                                                 'seed': score_remesh.DEFAULT_SEED}

    t0 = time.perf_counter()
    lref = mesh_locality.LocalityReference(args.source, args.target, samples=s['samples'],
                                           seed=s['seed'], pctl=args.pctl,
                                           radius_scale=args.radius_scale)
    print('reference and curvature built in %.0fs' % (time.perf_counter() - t0), flush=True)
    t0 = time.perf_counter()
    ok = [i for i, (_, st) in enumerate(statuses) if st == 'ok']
    computed = localities(lref, [statuses[i][0] for i in ok], args.workers)
    locs = [None] * len(rows)
    for i, loc in zip(ok, computed):
        locs[i] = loc
    print('%d trials analyzed in %.0fs (%d workers)'
          % (len(ok), time.perf_counter() - t0, args.workers), flush=True)

    settings = {'rank_version': RANK_VERSION, 'locality_version':
                mesh_locality.LOCALITY_VERSION, 'samples': s['samples'], 'seed': s['seed'],
                'pctl': lref.curvature.pctl, 'radius_scale': lref.radius_scale,
                'curvature_radius': lref.curvature.radius,
                'source_sha256': lref.ref.source_info['sha256'],
                'target_sha256': lref.ref.target_info['sha256']}
    limits, results = evaluate(rows, statuses, locs, lref.target, settings,
                               g2_max=args.g2_max, g2_pctl=args.g2_pctl, g3_k=args.g3_k,
                               rank_by=args.rank_by)
    write_results(args.out, results)
    print('wrote %d rows to %s\n' % (len(results), args.out))
    report(results, limits, lref.target, lref.curvature.summary, compare=args.compare,
           rank_by=args.rank_by)
    return 0 if len(ok) == len(rows) else 1


if __name__ == '__main__':
    sys.exit(main())
