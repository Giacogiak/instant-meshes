#!/usr/bin/env python3
"""
tune_params.py -- parameter sweep of Instant Meshes against the reference quad remesh
(Milestone M3, plan/roadmap/03_M3_tuning-harness.md)

    tune_params.py --smoke-test        one cheap trial end-to-end (exit 0 = OK)
    tune_params.py --stage anchor      calibrate vertex_count -> output V (pure-quad)
    tune_params.py --stage 1           coarse grid around the calibrated anchor
    tune_params.py --stage 2           finer grid around the stage-1 best
    tune_params.py --report            best trial and per-parameter sensitivity
    tune_params.py --verify-best       re-runs the best trial standalone and checks that
                                       a fresh score_remesh.py invocation gives the
                                       logged score

Every trial remeshes a welded copy of source.obj (decision D6: source.obj's 40
components have duplicated seam vertices, which Instant Meshes would treat as open
boundaries) through instantmeshes_core's C API (im_remesh, via ctypes), scores the
result with scripts/score_remesh.py against the original source.obj and
quad-remeshed.obj, and appends one JSON line (params, remesh result, the full score
record) to the trial log.

Trials run in worker processes, each with one TBB thread: im_remesh output is only
reproducible with one thread, and the thread count can only be set once per process.
"""

import argparse
import contextlib
import ctypes
import datetime
import hashlib
import json
import multiprocessing
import os
import subprocess
import sys
import tempfile
import time

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import score_remesh  # noqa: E402

BUILD_DIR = os.path.join(ROOT, 'build-core')
LIB_PATH = os.path.join(BUILD_DIR, 'libinstantmeshes_core.so')
SOURCE = os.path.join(ROOT, 'source.obj')
TARGET = os.path.join(ROOT, 'quad-remeshed.obj')
WORK_DIR = os.path.join(ROOT, 'tuning_runs')       # meshes and logs, not versioned
DEFAULT_LOG = os.path.join(ROOT, 'tuning_results.jsonl')

# Welding tolerance (world units). source.obj's duplicated seam vertices are exactly
# coincident: the number of vertex pairs closer than r is 10,287 for every r from 0 to
# 1e-4, and only grows from r = 1e-3 on (where 10 triangles would collapse). 1e-5 sits
# in the middle of that plateau (the bounding-box diagonal is ~220).
WELD_TOL = 1e-5

CREASE_OFF = -1.0

# Stage-1 vertex_count multipliers: the plan's {8000, 9500, 11082, 12500, 14000}
# relative to 11,082, applied to the calibrated anchor (pure_quad subdivides once, so
# the requested vertex_count is ~1/4 of the output's)
STAGE1_VC_FACTORS = (8000 / 11082, 9500 / 11082, 1.0, 12500 / 11082, 14000 / 11082)
STAGE1_CREASE = (CREASE_OFF, 30.0, 45.0)
STAGE1_SMOOTH = (0, 2, 4)
STAGE2_VC_FACTORS = (0.95, 0.975, 1.0, 1.025, 1.05)
STAGE2_CREASE = (CREASE_OFF, 20.0, 30.0, 45.0, 60.0)
STAGE2_SMOOTH = (0, 1, 2, 4)
ANCHOR_VC = 2770           # 11,082 / 4 (M1.1's measurement)
SMOKE_VC = 300             # small enough for a fast trial


# ---------------------------------------------------------------- welding

def components(n_vertices, mesh):
    E = mesh.edges()
    g = coo_matrix((np.ones(len(E)), (E[:, 0], E[:, 1])), shape=(n_vertices,) * 2)
    labels = connected_components(g, directed=False)[1]
    return int(len(np.unique(labels[mesh.flat])))


def weld(mesh, tol):
    """Merges the vertices of a PolyMesh closer than tol (transitively) into the one
    with the lowest index, keeping the vertex order. Faces that would lose a vertex
    are dropped. Returns the welded PolyMesh and statistics."""
    n = len(mesh.V)
    pairs = cKDTree(mesh.V).query_pairs(tol, output_type='ndarray')
    g = coo_matrix((np.ones(len(pairs)), (pairs[:, 0], pairs[:, 1])), shape=(n, n))
    labels = connected_components(g, directed=False)[1]
    rep = np.full(labels.max() + 1, n)
    np.minimum.at(rep, labels, np.arange(n))
    keep, new_index = np.unique(rep[labels], return_inverse=True)
    faces, collapsed = [], 0
    for f in mesh.faces:
        merged = new_index[f]
        if len(np.unique(merged)) < len(merged):
            collapsed += 1
        else:
            faces.append(merged)
    welded = score_remesh.PolyMesh(mesh.V[keep], faces)
    before, after = score_remesh.valence(mesh), score_remesh.valence(welded)
    stats = {
        'tolerance': tol,
        'pairs_within_tolerance': int(len(pairs)),
        'V_before': n, 'V_after': int(len(keep)),
        'F_before': len(mesh.faces), 'F_after': len(faces),
        'collapsed_faces': collapsed,
        'boundary_edges_before': before['boundary_edges'],
        'boundary_edges_after': after['boundary_edges'],
        'nonmanifold_edges_before': before['nonmanifold_edges'],
        'nonmanifold_edges_after': after['nonmanifold_edges'],
        'components_before': components(n, mesh),
        'components_after': components(len(keep), welded),
    }
    return welded, stats


def write_obj(path, mesh):
    with open(path, 'w') as f:
        for v in mesh.V:
            f.write('v %r %r %r\n' % tuple(float(x) for x in v))
        for face in mesh.faces:
            f.write('f ' + ' '.join(str(i + 1) for i in face) + '\n')


def make_welded_source(source=SOURCE, out_dir=WORK_DIR, tol=WELD_TOL):
    """Writes <out_dir>/source_welded.obj and returns (path, stats). Always rewritten
    (it takes a few seconds), so it cannot go stale."""
    os.makedirs(out_dir, exist_ok=True)
    welded, stats = weld(score_remesh.load_obj(source), tol)
    path = os.path.join(out_dir, 'source_welded.obj')
    write_obj(path, welded)
    stats.update(source=os.path.abspath(source), source_sha256=score_remesh.sha256(source),
                 path=path, sha256=score_remesh.sha256(path))
    return path, stats


# ---------------------------------------------------------------- C API

class ImRemeshParams(ctypes.Structure):
    _fields_ = [('rosy', ctypes.c_int), ('posy', ctypes.c_int),
                ('scale', ctypes.c_float), ('face_count', ctypes.c_int),
                ('vertex_count', ctypes.c_int), ('crease_angle', ctypes.c_float),
                ('extrinsic', ctypes.c_int), ('align_to_boundaries', ctypes.c_int),
                ('smooth_iter', ctypes.c_int), ('knn_points', ctypes.c_int),
                ('pure_quad', ctypes.c_int), ('deterministic', ctypes.c_int)]


class ImRemeshResult(ctypes.Structure):
    _fields_ = [('out_vertex_count', ctypes.c_int), ('out_face_count', ctypes.c_int)]


def trial_params(vertex_count, crease_angle, smooth_iter):
    """Full im_remesh_params: the swept values plus the plan's fixed ones"""
    return {'rosy': 4, 'posy': 4, 'scale': -1.0, 'face_count': -1,
            'vertex_count': int(vertex_count), 'crease_angle': float(crease_angle),
            'extrinsic': 1, 'align_to_boundaries': 0, 'smooth_iter': int(smooth_iter),
            'knn_points': 10, 'pure_quad': 1, 'deterministic': 1}


def trial_key(params):
    return json.dumps(params, sort_keys=True)


def trial_name(params):
    c = params['crease_angle']
    return 'v%d_c%s_s%d' % (params['vertex_count'],
                            'off' if c < 0 else '%g' % c, params['smooth_iter'])


def ensure_core_built():
    """Builds instantmeshes_core with M1's build-core invocation if the library is
    missing"""
    if os.path.exists(LIB_PATH):
        return
    print('building instantmeshes_core in %s' % BUILD_DIR, flush=True)
    subprocess.check_call(['git', '-C', ROOT, 'submodule', 'update', '--init', '--recursive',
                           '--', 'ext/pcg32', 'ext/dset', 'ext/pss', 'ext/tbb'])
    subprocess.check_call(['cmake', '-S', ROOT, '-B', BUILD_DIR, '-G', 'Ninja',
                           '-DIM_CORE_ONLY=ON', '-DCMAKE_BUILD_TYPE=Release'])
    subprocess.check_call(['cmake', '--build', BUILD_DIR, '--target', 'instantmeshes_core'])


def load_core():
    """Loads the library and fixes it to one thread (call once per process)"""
    lib = ctypes.CDLL(LIB_PATH)
    lib.im_remesh.argtypes = [ctypes.c_char_p, ctypes.c_char_p,
                              ctypes.POINTER(ImRemeshParams),
                              ctypes.POINTER(ImRemeshResult), ctypes.c_char_p, ctypes.c_int]
    lib.im_remesh.restype = ctypes.c_int
    lib.im_set_thread_count.argtypes = [ctypes.c_int]
    lib.im_set_thread_count.restype = ctypes.c_int
    rc = lib.im_set_thread_count(1)
    if rc != 0:
        raise RuntimeError('im_set_thread_count(1) failed: %d' % rc)
    return lib


@contextlib.contextmanager
def stdout_to(path):
    """Redirects the process-level stdout (im_remesh's progress log) to a file"""
    libc = ctypes.CDLL(None)
    sys.stdout.flush()
    libc.fflush(None)
    saved = os.dup(1)
    with open(path, 'w') as f:
        os.dup2(f.fileno(), 1)
    try:
        yield
    finally:
        libc.fflush(None)
        os.dup2(saved, 1)
        os.close(saved)


def remesh(lib, input_path, output_path, params, log_path):
    p = ImRemeshParams(**params)
    r = ImRemeshResult()
    err = ctypes.create_string_buffer(1024)
    t0 = time.perf_counter()
    with stdout_to(log_path):
        rc = lib.im_remesh(input_path.encode(), output_path.encode(), ctypes.byref(p),
                           ctypes.byref(r), err, len(err))
    return {'rc': rc, 'error': err.value.decode(errors='replace') if rc else None,
            'out_V': r.out_vertex_count, 'out_F': r.out_face_count,
            'seconds': time.perf_counter() - t0}


# ---------------------------------------------------------------- trials

_worker = {}


def init_worker(samples, seed):
    _worker['lib'] = load_core()
    _worker['ref'] = score_remesh.Reference(SOURCE, TARGET, samples=samples, seed=seed)


def run_trial(job):
    """job = (stage, params, input_path, mesh_dir) -> one log row"""
    stage, params, input_path, mesh_dir = job
    name = trial_name(params)
    out = os.path.join(mesh_dir, name + '.obj')
    row = {'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(),
           'stage': stage, 'name': name, 'params': params,
           'input': {'path': input_path, 'sha256': score_remesh.sha256(input_path)},
           'threads': 1}
    rm = remesh(_worker['lib'], input_path, out, params, os.path.join(mesh_dir, name + '.log'))
    row['remesh'] = rm
    row['score'] = None
    row['aggregate'] = None
    if rm['rc'] == 0:
        row['output'] = {'path': out, 'sha256': score_remesh.sha256(out)}
        t0 = time.perf_counter()
        record = _worker['ref'].score(out)
        row['score_seconds'] = time.perf_counter() - t0
        row['score'] = record
        row['aggregate'] = record['aggregate']['score']
    return row


def read_log(path):
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def run_trials(stage, param_list, log_path, workers, samples, seed):
    """Runs the trials not already in the log (same params and input) and appends one
    row each. Returns all rows of the log that match param_list."""
    input_path, weld_stats = make_welded_source()
    input_sha = weld_stats['sha256']
    print('welded source: %(V_before)d -> %(V_after)d vertices, boundary edges '
          '%(boundary_edges_before)d -> %(boundary_edges_after)d, components '
          '%(components_before)d -> %(components_after)d' % weld_stats, flush=True)
    done = {trial_key(r['params']) for r in read_log(log_path)
            if r['input']['sha256'] == input_sha and r['score_settings'] ==
            {'samples': samples, 'seed': seed}}
    keys, todo = set(), []
    for p in param_list:
        k = trial_key(p)
        if k not in done and k not in keys:
            todo.append(p)
        keys.add(k)
    print('%s: %d trials, %d already logged' % (stage, len(keys), len(keys) - len(todo)),
          flush=True)
    mesh_dir = os.path.join(WORK_DIR, 'meshes')
    os.makedirs(mesh_dir, exist_ok=True)
    jobs = [(stage, p, input_path, mesh_dir) for p in todo]
    if jobs:
        ctx = multiprocessing.get_context('spawn')
        with ctx.Pool(min(workers, len(jobs)), initializer=init_worker,
                      initargs=(samples, seed)) as pool:
            for i, row in enumerate(pool.imap_unordered(run_trial, jobs)):
                row['score_settings'] = {'samples': samples, 'seed': seed}
                row['weld'] = weld_stats
                score_remesh.check_finite(row)
                score_remesh.append_jsonl(log_path, row)
                print('[%d/%d] %-22s V=%-6d F=%-6d score=%s  (%.0fs + %.0fs)'
                      % (i + 1, len(jobs), row['name'], row['remesh']['out_V'],
                         row['remesh']['out_F'],
                         'FAILED' if row['aggregate'] is None else '%.6f' % row['aggregate'],
                         row['remesh']['seconds'], row.get('score_seconds', 0)), flush=True)
    return [r for r in read_log(log_path) if trial_key(r['params']) in keys
            and r['input']['sha256'] == input_sha]


def best_row(rows):
    scored = [r for r in rows if r['aggregate'] is not None]
    if not scored:
        raise RuntimeError('no scored trials')
    return min(scored, key=lambda r: (r['aggregate'], r['name']))


# ---------------------------------------------------------------- stages

def stage_anchor(args):
    rows = run_trials('anchor', [trial_params(ANCHOR_VC, CREASE_OFF, 2)], args.log,
                      args.workers, args.samples, args.seed)
    print_best(rows)


def calibrated_center(log_path):
    anchors = [r for r in read_log(log_path) if r['stage'] == 'anchor' and r['remesh']['rc'] == 0]
    if not anchors:
        raise SystemExit('run --stage anchor first')
    a = anchors[-1]
    target_V = a['score']['target']['counts']['V']
    return a['params']['vertex_count'] * target_V / a['remesh']['out_V']


def stage1(args):
    center = calibrated_center(args.log)
    print('calibrated vertex_count for V = target: %.1f' % center)
    grid = [trial_params(round(center * f), c, s) for f in STAGE1_VC_FACTORS
            for c in STAGE1_CREASE for s in STAGE1_SMOOTH]
    print_best(run_trials('stage1', grid, args.log, args.workers, args.samples, args.seed))


def stage2(args):
    b = best_row([r for r in read_log(args.log) if r['stage'] == 'stage1'])['params']
    print('stage-1 best: %s' % trial_name(b))
    grid = [trial_params(round(b['vertex_count'] * f), c, s) for f in STAGE2_VC_FACTORS
            for c in STAGE2_CREASE for s in STAGE2_SMOOTH]
    print_best(run_trials('stage2', grid, args.log, args.workers, args.samples, args.seed))


def print_best(rows):
    b = best_row(rows)
    print('best of %d: %s  score %.6f  terms %s' % (
        len(rows), b['name'], b['aggregate'],
        ', '.join('%s %.4f' % kv for kv in b['score']['aggregate']['terms'].items())))


def report(args):
    rows = [r for r in read_log(args.log) if r['aggregate'] is not None]
    b = best_row(rows)
    print_best(rows)
    for stage in ('stage1', 'stage2'):
        sr = [r for r in rows if r['stage'] == stage]
        if not sr:
            continue
        print('\n%s: %d trials, scores %.6f .. %.6f' % (
            stage, len(sr), min(r['aggregate'] for r in sr), max(r['aggregate'] for r in sr)))
        # Main effect of each parameter: mean score per level, and the same with the
        # other two parameters held at the stage's best values
        sb = best_row(sr)['params']
        for p in ('vertex_count', 'crease_angle', 'smooth_iter'):
            levels = sorted({r['params'][p] for r in sr})
            means = {lv: np.mean([r['aggregate'] for r in sr if r['params'][p] == lv])
                     for lv in levels}
            others = [q for q in ('vertex_count', 'crease_angle', 'smooth_iter') if q != p]
            line = {lv: [r['aggregate'] for r in sr if r['params'][p] == lv and
                         all(r['params'][q] == sb[q] for q in others)] for lv in levels}
            print('  %-13s mean-effect range %.6f  | at best others range %.6f' % (
                p, max(means.values()) - min(means.values()),
                np.ptp([v[0] for v in line.values() if v]) if any(line.values()) else 0))
            for lv in levels:
                print('    %-8g mean %.6f   at-best-others %s' % (
                    lv, means[lv], '%.6f' % line[lv][0] if line[lv] else '-'))
    print('\nbest params: %s' % json.dumps(b['params'], sort_keys=True))


def verify_best(args):
    """Re-runs the best logged trial in a fresh process (remesh) and a fresh
    score_remesh.py CLI invocation, and compares both with the log"""
    b = best_row(read_log(args.log))
    print('best logged: %s score %r (stage %s)' % (b['name'], b['aggregate'], b['stage']))
    input_path, weld_stats = make_welded_source()
    if weld_stats['sha256'] != b['input']['sha256']:
        raise SystemExit('welded source differs from the logged one')
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, 'best.obj')
        code = ('import sys, json; sys.path.insert(0, %r); import tune_params as t; '
                'lib = t.load_core(); '
                'r = t.remesh(lib, %r, %r, json.loads(%r), %r); print(json.dumps(r))'
                % (os.path.join(ROOT, 'scripts'), input_path, out,
                   json.dumps(b['params']), os.path.join(tmp, 'best.log')))
        rm = json.loads(subprocess.check_output([sys.executable, '-c', code]).decode()
                        .strip().splitlines()[-1])
        sha = score_remesh.sha256(out)
        jsonl = os.path.join(tmp, 'fresh.jsonl')
        subprocess.check_call([sys.executable, os.path.join(ROOT, 'scripts', 'score_remesh.py'),
                               '--source', SOURCE, '--target', TARGET, '--candidate', out,
                               '--out', jsonl, '--samples', str(b['score_settings']['samples']),
                               '--seed', str(b['score_settings']['seed'])],
                              stdout=subprocess.DEVNULL)
        fresh = read_log(jsonl)[0]
    checks = {
        'output V/F': ((rm['out_V'], rm['out_F']), (b['remesh']['out_V'], b['remesh']['out_F'])),
        'output sha256': (sha, b['output']['sha256']),
        'aggregate score': (fresh['aggregate']['score'], b['aggregate']),
        'aggregate terms': (fresh['aggregate']['terms'], b['score']['aggregate']['terms']),
        'candidate metrics': ({k: fresh['candidate'][k] for k in
                               ('counts', 'quad_quality', 'valence', 'fidelity')},
                              {k: b['score']['candidate'][k] for k in
                               ('counts', 'quad_quality', 'valence', 'fidelity')}),
    }
    ok = True
    for name, (got, logged) in checks.items():
        same = got == logged
        ok &= same
        print('%-18s %s' % (name, 'identical' if same else 'DIFFERS: fresh %r vs logged %r'
                            % (got, logged)))
    print('fresh score %r, logged score %r' % (fresh['aggregate']['score'], b['aggregate']))
    return 0 if ok else 1


def smoke_test(args):
    """One cheap trial end-to-end: build if needed, weld, im_remesh, score, log a row"""
    ensure_core_built()
    log_path = os.path.join(WORK_DIR, 'smoke_results.jsonl')
    os.makedirs(WORK_DIR, exist_ok=True)
    if os.path.exists(log_path):
        os.remove(log_path)
    rows = run_trials('smoke', [trial_params(SMOKE_VC, CREASE_OFF, 0)], log_path, 1,
                      args.samples, args.seed)
    if len(rows) != 1 or rows[0]['aggregate'] is None:
        print('smoke test FAILED: %r' % (rows[0]['remesh'] if rows else 'no row logged'))
        return 1
    r = rows[0]
    print('smoke test OK: %s V=%d F=%d aggregate %.6f, logged to %s' % (
        r['name'], r['remesh']['out_V'], r['remesh']['out_F'], r['aggregate'], log_path))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0].strip())
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--smoke-test', action='store_true', help='one cheap trial end-to-end')
    mode.add_argument('--stage', choices=('anchor', '1', '2'), help='run a sweep stage')
    mode.add_argument('--report', action='store_true', help='summarize the trial log')
    mode.add_argument('--verify-best', action='store_true',
                      help='re-run the best trial standalone and compare with the log')
    parser.add_argument('--log', default=DEFAULT_LOG, help='trial log (default %(default)s)')
    parser.add_argument('--workers', type=int, default=max(1, min(4, os.cpu_count() or 1)),
                        help='single-threaded worker processes (default %(default)s)')
    parser.add_argument('--samples', type=int, default=score_remesh.DEFAULT_SAMPLES)
    parser.add_argument('--seed', type=int, default=score_remesh.DEFAULT_SEED)
    args = parser.parse_args(argv)
    if args.smoke_test:
        return smoke_test(args)
    if args.report:
        return report(args)
    if args.verify_best:
        return verify_best(args)
    ensure_core_built()
    {'anchor': stage_anchor, '1': stage1, '2': stage2}[args.stage](args)
    return 0


if __name__ == '__main__':
    sys.exit(main())
