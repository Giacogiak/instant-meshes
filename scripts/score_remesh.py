#!/usr/bin/env python3
"""
score_remesh.py -- scores a remeshed candidate against a reference quad remesh
(Milestone M2, plan/roadmap/02_M2_scoring-script.md)

    score_remesh.py --source source.obj --target quad-remeshed.obj \
                    --candidate trial.obj --out results.jsonl

appends one JSON line per invocation to --out and prints the raw sub-metrics next
to the aggregate score. Sub-metrics, for both the candidate and the target:

  1. counts:       V and F, and their deltas vs. the target (raw and relative)
  2. quad quality: interior-angle deviation from 90 degrees (from 3D corner vectors,
                   no planarity assumed), edge-length coefficient of variation and
                   the non-quad face fraction
  3. valence:      histogram of incident faces per vertex, % of interior vertices with
                   valence 4 and the number of interior vertices with valence != 4.
                   This is a count on the realized mesh; it is NOT the orientation-field
                   singularity count that Instant Meshes' compute_orientation_singularities
                   reports before extraction.
  4. fidelity:     distance from points sampled on the mesh surface to the nearest point
                   of the source surface, divided by the source bounding-box diagonal.
                   The target's value is the bar to match, not zero.

The aggregate score is a weighted mean of per-term costs, each clamped to [0, 1]:
0 is a perfect score, 1 the worst. See TERMS below.

Quads must be preserved, so the OBJ files are parsed here (trimesh's OBJ loader
triangulates polygons). trimesh is used for surface sampling and point-triangle
distances; nearest-triangle queries use scipy's cKDTree, since trimesh's own
proximity queries need the optional rtree package.

The module can also be imported (e.g. by the M3 tuning harness): build a Reference
once, then call Reference.score() per candidate, which skips reloading the source
and rescoring the target.
"""

import argparse
import datetime
import hashlib
import json
import math
import os
import sys

import numpy as np
import scipy
import trimesh
from scipy.spatial import cKDTree

SCRIPT_VERSION = 1

DEFAULT_SAMPLES = 100000
DEFAULT_SEED = 0

# Aggregate score terms, all costs in [0, 1] (lower is better), equal weights by default
TERMS = {
    'count_v':   '|dV| / V_target',
    'count_f':   '|dF| / F_target',
    'angle':     'mean per-face angle deviation / 45 deg',
    'edge_cv':   'edge-length coefficient of variation',
    'valence4':  '|%valence4(candidate) - %valence4(target)| (as a fraction)',
    'fidelity':  '|fidelity_mean(candidate) - fidelity_mean(target)| / fidelity_mean(target)',
    'non_quad':  'non-quad face fraction',
}
DEFAULT_WEIGHTS = {name: 1.0 for name in TERMS}


class PolyMesh:
    """Polygon mesh: V is (n, 3) float64, faces is a list of int arrays (0-based)"""

    def __init__(self, V, faces):
        self.V = V
        self.faces = faces
        self.sizes = np.array([len(f) for f in faces], dtype=np.int64)
        self.flat = (np.concatenate(faces) if faces else np.zeros(0, dtype=np.int64))
        self.offsets = np.concatenate([[0], np.cumsum(self.sizes)])

    def quads(self):
        """(m, 4) array of the quad faces"""
        sel = np.flatnonzero(self.sizes == 4)
        return self.flat[self.offsets[sel][:, None] + np.arange(4)]

    def edges(self):
        """(e, 2) array of directed half-edges, one per face corner"""
        nxt = np.arange(len(self.flat)) + 1
        last = self.offsets[1:] - 1
        nxt[last] = self.offsets[:-1]
        return np.stack([self.flat, self.flat[nxt]], axis=1)

    def triangles(self):
        """(t, 3) fan triangulation of all faces"""
        tris = []
        for n in np.unique(self.sizes):
            if n < 3:
                continue
            sel = np.flatnonzero(self.sizes == n)
            f = self.flat[self.offsets[sel][:, None] + np.arange(n)]
            for k in range(1, n - 1):
                tris.append(f[:, [0, k, k + 1]])
        return np.concatenate(tris) if tris else np.zeros((0, 3), dtype=np.int64)

    def trimesh(self):
        return trimesh.Trimesh(vertices=self.V, faces=self.triangles(), process=False)


def load_obj(path):
    """Reads the 'v' and 'f' records of an OBJ file, keeping polygons intact"""
    V, faces = [], []
    with open(path, 'r') as f:
        for line in f:
            if line.startswith('v '):
                V.append([float(x) for x in line.split()[1:4]])
            elif line.startswith('f '):
                idx = [int(tok.split('/')[0]) for tok in line.split()[1:]]
                if len(idx) < 3:
                    raise ValueError('%s: face with fewer than 3 vertices' % path)
                n = len(V)
                faces.append(np.array([i - 1 if i > 0 else n + i for i in idx],
                                      dtype=np.int64))
    V = np.array(V, dtype=np.float64).reshape(-1, 3)
    if len(V) == 0 or len(faces) == 0:
        raise ValueError('%s: no vertices or no faces' % path)
    mesh = PolyMesh(V, faces)
    if mesh.flat.min() < 0 or mesh.flat.max() >= len(V):
        raise ValueError('%s: face index out of range' % path)
    return mesh


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------- metrics 2 + 3

def quad_quality(mesh):
    """Angle deviation of quad corners from 90 deg, edge-length CV, non-quad fraction"""
    Q = mesh.quads()
    P = mesh.V[Q]                                   # (m, 4, 3)
    a = np.roll(P, 1, axis=1) - P                   # to the previous corner
    b = np.roll(P, -1, axis=1) - P                  # to the next corner
    la, lb = np.linalg.norm(a, axis=2), np.linalg.norm(b, axis=2)
    degenerate = np.any((la == 0) | (lb == 0), axis=1)
    angle = np.degrees(np.arctan2(np.linalg.norm(np.cross(a, b), axis=2),
                                  np.einsum('ijk,ijk->ij', a, b)))
    dev = np.abs(angle - 90.0)[~degenerate]         # (m', 4)
    face_dev = dev.mean(axis=1)

    E = mesh.edges()
    E = np.unique(np.sort(E, axis=1), axis=0)
    length = np.linalg.norm(mesh.V[E[:, 0]] - mesh.V[E[:, 1]], axis=1)

    return {
        'quad_faces': int(len(Q)),
        'degenerate_quads': int(degenerate.sum()),
        'angle_dev_mean_deg': float(face_dev.mean()) if len(face_dev) else None,
        'angle_dev_p90_deg': float(np.percentile(face_dev, 90)) if len(face_dev) else None,
        'corner_angle_dev_max_deg': float(dev.max()) if len(dev) else None,
        'edges': int(len(E)),
        'edge_length_mean': float(length.mean()),
        'edge_length_cv': float(length.std() / length.mean()) if length.mean() > 0 else None,
        'non_quad_faces': int((mesh.sizes != 4).sum()),
        'non_quad_fraction': float((mesh.sizes != 4).mean()),
    }


def valence(mesh):
    """Incident faces per vertex; interior = every incident edge has exactly two faces"""
    nV = len(mesh.V)
    # Each vertex appears once per incident face (in a valid polygon)
    face_valence = np.bincount(mesh.flat, minlength=nV)
    referenced = face_valence > 0

    E = np.sort(mesh.edges(), axis=1)
    uE, mult = np.unique(E, axis=0, return_counts=True)
    not_interior = np.zeros(nV, dtype=bool)
    irregular_edges = uE[mult != 2]
    not_interior[irregular_edges.ravel()] = True
    interior = referenced & ~not_interior

    def hist(mask):
        vals, counts = np.unique(face_valence[mask], return_counts=True)
        return {str(int(v)): int(c) for v, c in zip(vals, counts)}

    n_interior = int(interior.sum())
    n_val4 = int((interior & (face_valence == 4)).sum())
    return {
        'vertices_referenced': int(referenced.sum()),
        'vertices_unreferenced': int(nV - referenced.sum()),
        'interior_vertices': n_interior,
        'boundary_or_nonmanifold_vertices': int((referenced & not_interior).sum()),
        'boundary_edges': int((mult == 1).sum()),
        'nonmanifold_edges': int((mult > 2).sum()),
        'histogram': hist(referenced),
        'interior_histogram': hist(interior),
        'pct_valence4_interior': 100.0 * n_val4 / n_interior if n_interior else None,
        'mesh_valence_singularities': n_interior - n_val4,
    }


# ---------------------------------------------------------------- metric 4

class SurfaceDistance:
    """Exact point-to-surface distance for a triangle mesh, without rtree"""

    K = 16          # nearest triangle centroids tried first
    CHUNK = 20000   # points per batch in the exhaustive fallback

    def __init__(self, V, T):
        self.tris = V[T]                                         # (t, 3, 3)
        centroid = self.tris.mean(axis=1)
        self.r_max = float(np.linalg.norm(self.tris - centroid[:, None], axis=2).max())
        self.tree = cKDTree(centroid)

    def __call__(self, points):
        k = min(self.K, len(self.tris))
        dc, idx = self.tree.query(points, k=k)
        if k == 1:
            dc, idx = dc[:, None], idx[:, None]
        best = np.full(len(points), np.inf)
        for j in range(k):
            cp = trimesh.triangles.closest_point(self.tris[idx[:, j]], points)
            best = np.minimum(best, np.linalg.norm(cp - points, axis=1))

        # Any untried triangle t has |p - centroid_t| >= dc[:, -1] and therefore a
        # distance >= dc[:, -1] - r_max. Points where that does not settle it are
        # checked against every triangle whose centroid is within best + r_max.
        if k < len(self.tris):
            todo = np.flatnonzero(best > dc[:, -1] - self.r_max)
            for start in range(0, len(todo), self.CHUNK):
                sel = todo[start:start + self.CHUNK]
                cand = self.tree.query_ball_point(points[sel], best[sel] + self.r_max)
                n = np.array([len(c) for c in cand])
                pi = np.repeat(sel, n)
                ti = np.concatenate(cand).astype(np.int64)
                cp = trimesh.triangles.closest_point(self.tris[ti], points[pi])
                d = np.linalg.norm(cp - points[pi], axis=1)
                np.minimum.at(best, pi, d)
        return best


def fidelity(mesh, source_distance, diag, samples, seed):
    """Distances from `samples` area-uniform points on mesh to the source surface"""
    points, _ = trimesh.sample.sample_surface(mesh.trimesh(), samples, seed=seed)
    d = source_distance(np.asarray(points, dtype=np.float64)) / diag
    return {
        'samples': int(samples),
        'mean': float(d.mean()),
        'rms': float(np.sqrt((d * d).mean())),
        'p95': float(np.percentile(d, 95)),
        'max': float(d.max()),
    }


# ---------------------------------------------------------------- scoring

def describe(mesh, source_distance, diag, samples, seed):
    return {
        'counts': {'V': int(len(mesh.V)), 'F': int(len(mesh.faces))},
        'quad_quality': quad_quality(mesh),
        'valence': valence(mesh),
        'fidelity': fidelity(mesh, source_distance, diag, samples, seed),
    }


def clamp01(x):
    return 1.0 if x is None or not math.isfinite(x) else min(max(x, 0.0), 1.0)


def aggregate(cand, target, weights):
    cc, tc = cand['counts'], target['counts']
    cq = cand['quad_quality']
    cv, tv = cand['valence'], target['valence']
    cf, tf = cand['fidelity'], target['fidelity']

    def ratio(x, ref):
        return abs(x) / ref if ref else None

    v4c, v4t = cv['pct_valence4_interior'], tv['pct_valence4_interior']
    terms = {
        'count_v': ratio(cc['V'] - tc['V'], tc['V']),
        'count_f': ratio(cc['F'] - tc['F'], tc['F']),
        'angle': (cq['angle_dev_mean_deg'] / 45.0
                  if cq['angle_dev_mean_deg'] is not None else None),
        'edge_cv': cq['edge_length_cv'],
        'valence4': (abs(v4c - v4t) / 100.0
                     if v4c is not None and v4t is not None else None),
        'fidelity': ratio(cf['mean'] - tf['mean'], tf['mean']),
        'non_quad': cq['non_quad_fraction'],
    }
    # An undefined term (e.g. no quads at all) counts as the worst cost
    terms = {name: clamp01(value) for name, value in terms.items()}
    wsum = sum(weights.values())
    score = sum(weights[n] * terms[n] for n in TERMS) / wsum
    return {'score': score, 'terms': terms, 'weights': dict(weights)}


def deltas(cand, target):
    cc, tc = cand['counts'], target['counts']
    v4c = cand['valence']['pct_valence4_interior']
    v4t = target['valence']['pct_valence4_interior']
    fc, ft = cand['fidelity']['mean'], target['fidelity']['mean']
    return {
        'dV': cc['V'] - tc['V'],
        'dF': cc['F'] - tc['F'],
        'dV_pct': 100.0 * (cc['V'] - tc['V']) / tc['V'],
        'dF_pct': 100.0 * (cc['F'] - tc['F']) / tc['F'],
        'pct_valence4_delta': (v4c - v4t if v4c is not None and v4t is not None
                               else None),
        'fidelity_mean_rel_delta': (fc - ft) / ft if ft > 0 else None,
    }


class Reference:
    """The source surface and the scored target, shared by any number of candidates"""

    def __init__(self, source_path, target_path, samples=DEFAULT_SAMPLES,
                 seed=DEFAULT_SEED):
        self.source_path, self.target_path = source_path, target_path
        self.samples, self.seed = samples, seed
        source = load_obj(source_path)
        self.diag = float(np.linalg.norm(source.V.max(axis=0) - source.V.min(axis=0)))
        self.source_distance = SurfaceDistance(source.V, source.triangles())
        self.source_info = {'path': os.path.abspath(source_path),
                            'sha256': sha256(source_path),
                            'V': int(len(source.V)), 'F': int(len(source.faces)),
                            'bbox_diag': self.diag}
        self.target = describe(load_obj(target_path), self.source_distance, self.diag,
                               samples, seed)
        self.target_info = {'path': os.path.abspath(target_path),
                            'sha256': sha256(target_path)}

    def score(self, candidate_path, weights=None):
        """Scores one candidate OBJ and returns the JSON record"""
        w = dict(DEFAULT_WEIGHTS)
        w.update(weights or {})
        if set(w) != set(TERMS) or any(v < 0 for v in w.values()) or sum(w.values()) <= 0:
            raise ValueError('weights must be non-negative, not all zero, over %s'
                             % sorted(TERMS))
        cand = describe(load_obj(candidate_path), self.source_distance, self.diag,
                        self.samples, self.seed)
        record = {
            'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'script_version': SCRIPT_VERSION,
            'versions': {'python': sys.version.split()[0], 'numpy': np.__version__,
                         'scipy': scipy.__version__, 'trimesh': trimesh.__version__},
            'settings': {'samples': self.samples, 'seed': self.seed},
            'source': self.source_info,
            'target': dict(self.target_info, **self.target),
            'candidate': dict({'path': os.path.abspath(candidate_path),
                               'sha256': sha256(candidate_path)}, **cand),
            'delta': deltas(cand, self.target),
            'aggregate': aggregate(cand, self.target, w),
        }
        check_finite(record)
        return record


def check_finite(value, path='record'):
    """Every number in the record must be finite (None marks an undefined metric)"""
    if isinstance(value, dict):
        for k, v in value.items():
            check_finite(v, '%s.%s' % (path, k))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            check_finite(v, '%s[%d]' % (path, i))
    elif isinstance(value, float) and not math.isfinite(value):
        raise ValueError('non-finite value at %s' % path)


def append_jsonl(path, record):
    with open(path, 'a') as f:
        f.write(json.dumps(record, sort_keys=True, allow_nan=False) + '\n')


# ---------------------------------------------------------------- report

def fmt(x, spec):
    return 'n/a' if x is None else format(x, spec)


def report(r):
    c, t, d, a = r['candidate'], r['target'], r['delta'], r['aggregate']
    rows = [
        ('V', c['counts']['V'], t['counts']['V'], 'd'),
        ('F', c['counts']['F'], t['counts']['F'], 'd'),
        ('angle dev mean (deg)', c['quad_quality']['angle_dev_mean_deg'],
         t['quad_quality']['angle_dev_mean_deg'], '.3f'),
        ('angle dev p90 (deg)', c['quad_quality']['angle_dev_p90_deg'],
         t['quad_quality']['angle_dev_p90_deg'], '.3f'),
        ('corner angle dev max (deg)', c['quad_quality']['corner_angle_dev_max_deg'],
         t['quad_quality']['corner_angle_dev_max_deg'], '.3f'),
        ('edge length CV', c['quad_quality']['edge_length_cv'],
         t['quad_quality']['edge_length_cv'], '.4f'),
        ('non-quad fraction', c['quad_quality']['non_quad_fraction'],
         t['quad_quality']['non_quad_fraction'], '.4f'),
        ('% valence 4 (interior)', c['valence']['pct_valence4_interior'],
         t['valence']['pct_valence4_interior'], '.3f'),
        ('mesh valence singularities', c['valence']['mesh_valence_singularities'],
         t['valence']['mesh_valence_singularities'], 'd'),
        ('interior vertices', c['valence']['interior_vertices'],
         t['valence']['interior_vertices'], 'd'),
        ('boundary edges', c['valence']['boundary_edges'],
         t['valence']['boundary_edges'], 'd'),
        ('non-manifold edges', c['valence']['nonmanifold_edges'],
         t['valence']['nonmanifold_edges'], 'd'),
        ('fidelity mean (/diag)', c['fidelity']['mean'], t['fidelity']['mean'], '.3e'),
        ('fidelity rms (/diag)', c['fidelity']['rms'], t['fidelity']['rms'], '.3e'),
        ('fidelity p95 (/diag)', c['fidelity']['p95'], t['fidelity']['p95'], '.3e'),
        ('fidelity max (/diag)', c['fidelity']['max'], t['fidelity']['max'], '.3e'),
    ]
    print('candidate: %s' % c['path'])
    print('target:    %s' % t['path'])
    print('source:    %s (bbox diag %.4f, %d samples, seed %d)'
          % (r['source']['path'], r['source']['bbox_diag'], r['settings']['samples'],
             r['settings']['seed']))
    print('%-28s %14s %14s' % ('metric', 'candidate', 'target'))
    for name, cv, tv, spec in rows:
        print('%-28s %14s %14s' % (name, fmt(cv, spec), fmt(tv, spec)))
    print('valence histogram (faces/vertex), candidate: %s'
          % json.dumps(c['valence']['histogram']))
    print('valence histogram (faces/vertex), target:    %s'
          % json.dumps(t['valence']['histogram']))
    print('(mesh valence singularities = interior vertices with valence != 4 on the '
          'realized mesh, not the orientation-field singularity count)')
    print('dV = %+d (%+.2f%%), dF = %+d (%+.2f%%), %%valence4 delta = %s, '
          'fidelity mean rel. delta = %s'
          % (d['dV'], d['dV_pct'], d['dF'], d['dF_pct'],
             fmt(d['pct_valence4_delta'], '+.3f'), fmt(d['fidelity_mean_rel_delta'], '+.4f')))
    print('aggregate terms (cost in [0,1], weight): ' + ', '.join(
        '%s=%.4f (w%g)' % (n, a['terms'][n], a['weights'][n]) for n in TERMS))
    print('aggregate score: %.6f  (0 = best, 1 = worst)' % a['score'])


def parse_weight(text):
    name, sep, value = text.partition('=')
    if not sep or name not in TERMS:
        raise argparse.ArgumentTypeError('expected NAME=VALUE with NAME in %s'
                                         % ', '.join(TERMS))
    return name, float(value)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__.split('\n\n')[0].strip(),
        epilog='aggregate terms: ' + '; '.join('%s = %s' % kv for kv in TERMS.items()))
    parser.add_argument('--source', required=True, help='original mesh (OBJ)')
    parser.add_argument('--target', required=True, help='reference remesh (OBJ)')
    parser.add_argument('--candidate', required=True, help='remesh to score (OBJ)')
    parser.add_argument('--out', required=True, help='JSONL file to append to')
    parser.add_argument('--samples', type=int, default=DEFAULT_SAMPLES,
                        help='surface samples for fidelity (default %(default)s)')
    parser.add_argument('--seed', type=int, default=DEFAULT_SEED,
                        help='sampling seed (default %(default)s)')
    parser.add_argument('--weight', type=parse_weight, action='append', default=[],
                        metavar='NAME=VALUE', help='override one term weight (default 1)')
    args = parser.parse_args(argv)
    if args.samples <= 0:
        parser.error('--samples must be positive')

    ref = Reference(args.source, args.target, samples=args.samples, seed=args.seed)
    record = ref.score(args.candidate, weights=dict(args.weight))
    append_jsonl(args.out, record)
    report(record)
    return 0


if __name__ == '__main__':
    sys.exit(main())
