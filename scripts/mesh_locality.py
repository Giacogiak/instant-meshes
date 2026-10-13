#!/usr/bin/env python3
"""
mesh_locality.py -- curvature/locality metrics of a remesh against the source surface
(Milestone M5, plan/roadmap/05_M5_locality-reranking.md, Task 1)

    mesh_locality.py --source source.obj --target quad-remeshed.obj \\
                     --candidate tuning_runs/meshes/v2799_coff_s1.obj [--out f.jsonl]

prints the source's curvature distribution and a `locality` block for the candidate
and for the target:

  high_curv_fidelity / low_curv_fidelity
      score_remesh.fidelity()'s {mean, rms, p95, max, samples}, over the samples
      whose nearest source triangle is / is not high-curvature. The samples are the
      same points fidelity() draws (same count, same seed).
  boundary_edges, boundary_edges_near_high_curv, boundary_components,
  largest_boundary_component_edges
      the mesh's boundary edges (edges in exactly one face), how many have their
      midpoint nearest a high-curvature source triangle, and their connected
      components (tune_params.components()).
  degenerate_quads, degenerate_quads_near_high_curv
      the same for score_remesh.quad_quality()'s degenerate quads (by centroid).
  high_curv_sample_fraction
      the fraction of all samples that are high-curvature: the baseline to compare
      the boundary-edge and degenerate-quad fractions with.

High curvature: SourceCurvature computes trimesh's discrete mean and Gaussian
curvature measures at every source vertex, in a ball whose radius is the target's mean
edge length, and flags the top PCTL% of |mean curvature| vertices. A source triangle is
high-curvature if any of its vertices is.

The curvature is computed on the welded source (tune_params.weld(), decision D6):
source.obj's 40 components are only joined by duplicated seam vertices, so without the
weld the dihedral angles across the seams, which carry most of the curvature measure,
would be missing. The weld keeps every face in order, so triangle i of the welded mesh
is triangle i of score_remesh's SurfaceDistance on the unwelded source.

This module never remeshes: it only reads OBJ files that already exist.
"""

import argparse
import json
import os
import sys

import numpy as np
import trimesh
from scipy.spatial import cKDTree

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import score_remesh  # noqa: E402
import tune_params  # noqa: E402

LOCALITY_VERSION = 1

# Top PCTL% of source vertices by |mean curvature measure| are "high-curvature" (D9)
DEFAULT_PCTL = 10.0
# Curvature ball radius, as a multiple of the target's mean edge length (D9)
DEFAULT_RADIUS_SCALE = 1.0

CURVATURE_PERCENTILES = (0, 1, 5, 10, 25, 50, 75, 90, 95, 99, 100)


# ---------------------------------------------------------------- curvature

class _SegmentBallTree:
    """Stands in for trimesh's rtree-backed face_adjacency_tree (rtree is not
    installed): intersection_v() returns, per query box, a superset of the segments
    that can meet the ball inscribed in the box. discrete_mean_curvature_measure only
    uses the candidates to compute each segment's exact length inside the ball, so
    extra candidates contribute 0."""

    def __init__(self, segments):
        self.mid = segments.mean(axis=1)
        self.half = np.linalg.norm(segments[:, 1] - segments[:, 0], axis=1) / 2

    def intersection_v(self, mins, maxs):
        centers = (mins + maxs) / 2
        radius = float((maxs - mins).max()) / 2
        # A segment meets a ball only if its midpoint is within radius + half length
        hits = cKDTree(centers).query_ball_point(self.mid, self.half + radius)
        seg = np.repeat(np.arange(len(hits)), [len(h) for h in hits])
        point = (np.concatenate(hits).astype(np.int64) if len(seg)
                 else np.zeros(0, dtype=np.int64))
        order = np.argsort(point, kind='stable')
        return seg[order], np.bincount(point, minlength=len(centers))


class _CurvatureMesh:
    """The attributes discrete_mean_curvature_measure reads, with the tree above"""

    def __init__(self, mesh):
        self.vertices = mesh.vertices
        self.face_adjacency_edges = mesh.face_adjacency_edges
        self.face_adjacency_angles = mesh.face_adjacency_angles
        self.face_adjacency_convex = mesh.face_adjacency_convex
        self.face_adjacency_tree = _SegmentBallTree(
            np.asarray(mesh.vertices)[mesh.face_adjacency_edges])


def mean_curvature_measure(mesh, points, radius, chunk=5000):
    """trimesh.curvature.discrete_mean_curvature_measure without rtree, in chunks"""
    proxy = _CurvatureMesh(mesh)
    points = np.asarray(points, dtype=np.float64)
    return np.concatenate([
        trimesh.curvature.discrete_mean_curvature_measure(
            proxy, points[i:i + chunk], radius)
        for i in range(0, len(points), chunk)]) if len(points) else np.zeros(0)


class SourceCurvature:
    """Per-vertex curvature of the source and its high-curvature triangles. Built once
    and shared by every candidate, like score_remesh.SurfaceDistance.

    source_trimesh must be connected across seams (welded) and its faces must be the
    triangles SurfaceDistance was built from, in the same order."""

    def __init__(self, source_trimesh, radius, pctl=DEFAULT_PCTL):
        if not (radius > 0 and 0 < pctl < 100):
            raise ValueError('need radius > 0 and 0 < pctl < 100')
        self.radius, self.pctl = float(radius), float(pctl)
        V = np.asarray(source_trimesh.vertices, dtype=np.float64)
        T = np.asarray(source_trimesh.faces, dtype=np.int64)
        self.mean = mean_curvature_measure(source_trimesh, V, radius)
        self.gaussian = trimesh.curvature.discrete_gaussian_curvature_measure(
            source_trimesh, V, radius)
        abs_mean = np.abs(self.mean)
        self.threshold = float(np.percentile(abs_mean, 100 - pctl))
        self.high_vertex = abs_mean >= self.threshold
        self.high_triangle = self.high_vertex[T].any(axis=1)

        area = source_trimesh.area_faces
        high_V = V[np.unique(T[self.high_triangle])]
        patches = score_remesh.PolyMesh(V, list(T[self.high_triangle]))
        self.summary = {
            'radius': self.radius,
            'pctl': self.pctl,
            'threshold_abs_mean': self.threshold,
            'abs_mean_percentiles': {str(p): float(np.percentile(abs_mean, p))
                                     for p in CURVATURE_PERCENTILES},
            'gaussian_percentiles': {str(p): float(np.percentile(self.gaussian, p))
                                     for p in CURVATURE_PERCENTILES},
            'vertices': int(len(V)),
            'high_vertices': int(self.high_vertex.sum()),
            'triangles': int(len(T)),
            'high_triangles': int(self.high_triangle.sum()),
            'high_area_fraction': float(area[self.high_triangle].sum() / area.sum()),
            'high_region_components': (tune_params.components(len(V), patches)
                                       if len(patches.faces) else 0),
            'high_region_bbox': ([high_V.min(axis=0).tolist(), high_V.max(axis=0).tolist()]
                                 if len(high_V) else None),
        }


def welded_source_trimesh(source, source_distance, tol=tune_params.WELD_TOL):
    """The source PolyMesh welded as M3 welded it, as a trimesh whose triangle i is
    source_distance's triangle i"""
    welded, stats = tune_params.weld(source, tol)
    T = welded.triangles()
    if stats['collapsed_faces'] or T.shape != source_distance.tris.shape[:2] or \
            not np.allclose(welded.V[T], source_distance.tris, rtol=0, atol=tol):
        raise ValueError('welding changed the source triangles; their indices would '
                         'no longer match the distance queries')
    return trimesh.Trimesh(vertices=welded.V, faces=T, process=False)


# ---------------------------------------------------------------- locality

def _distance_stats(d):
    if len(d) == 0:
        return {'samples': 0, 'mean': None, 'rms': None, 'p95': None, 'max': None}
    return {
        'samples': int(len(d)),
        'mean': float(d.mean()),
        'rms': float(np.sqrt((d * d).mean())),
        'p95': float(np.percentile(d, 95)),
        'max': float(d.max()),
    }


def locality(mesh, source_distance, source_curvature, diag, samples, seed):
    """Curvature-split fidelity plus boundary-edge and degenerate-quad locality"""
    points, _ = trimesh.sample.sample_surface(mesh.trimesh(), samples, seed=seed)
    d, tri = source_distance(np.asarray(points, dtype=np.float64), return_triangle=True)
    d = d / diag
    high = source_curvature.high_triangle[tri]

    def near_high(P):
        if len(P) == 0:
            return 0
        return int(source_curvature.high_triangle[
            source_distance(P, return_triangle=True)[1]].sum())

    _, vdetail = score_remesh.valence(mesh, return_detail=True)
    B = vdetail['boundary_edges']
    if len(B):
        n_comp, labels = tune_params.components(
            len(mesh.V), score_remesh.PolyMesh(mesh.V, list(B)), return_labels=True)
        largest = int(np.bincount(labels[B[:, 0]]).max())
    else:
        n_comp, largest = 0, 0

    _, qdetail = score_remesh.quad_quality(mesh, return_detail=True)
    Q = mesh.quads()[qdetail['degenerate']]

    return {
        'samples': int(samples),
        'high_curv_sample_fraction': float(high.mean()),
        'high_curv_fidelity': _distance_stats(d[high]),
        'low_curv_fidelity': _distance_stats(d[~high]),
        'boundary_edges': int(len(B)),
        'boundary_edges_near_high_curv': near_high(mesh.V[B].mean(axis=1)),
        'boundary_components': n_comp,
        'largest_boundary_component_edges': largest,
        'degenerate_quads': int(len(Q)),
        'degenerate_quads_near_high_curv': near_high(mesh.V[Q].mean(axis=1)),
    }


class LocalityReference:
    """A score_remesh.Reference plus the source curvature, shared by any number of
    candidates. The curvature radius is radius_scale times the target's mean edge
    length."""

    def __init__(self, source_path, target_path, samples=score_remesh.DEFAULT_SAMPLES,
                 seed=score_remesh.DEFAULT_SEED, pctl=DEFAULT_PCTL,
                 radius_scale=DEFAULT_RADIUS_SCALE, reference=None):
        self.ref = reference or score_remesh.Reference(source_path, target_path,
                                                       samples=samples, seed=seed)
        self.radius_scale = float(radius_scale)
        radius = radius_scale * self.ref.target['quad_quality']['edge_length_mean']
        source = welded_source_trimesh(score_remesh.load_obj(self.ref.source_path),
                                       self.ref.source_distance)
        self.curvature = SourceCurvature(source, radius, pctl)
        self.target = self.locality(score_remesh.load_obj(self.ref.target_path))

    def locality(self, mesh):
        return locality(mesh, self.ref.source_distance, self.curvature, self.ref.diag,
                        self.ref.samples, self.ref.seed)

    def record(self, candidate_path):
        rec = {
            'locality_version': LOCALITY_VERSION,
            'settings': {'samples': self.ref.samples, 'seed': self.ref.seed,
                         'pctl': self.curvature.pctl, 'radius_scale': self.radius_scale},
            'source': self.ref.source_info,
            'curvature': self.curvature.summary,
            'target': dict(self.ref.target_info, locality=self.target),
            'candidate': {'path': os.path.abspath(candidate_path),
                          'sha256': score_remesh.sha256(candidate_path),
                          'locality': self.locality(score_remesh.load_obj(candidate_path))},
        }
        score_remesh.check_finite(rec)
        return rec


# ---------------------------------------------------------------- report

def report(rec):
    c = rec['curvature']
    print('source:    %s (bbox diag %.4f)' % (rec['source']['path'],
                                              rec['source']['bbox_diag']))
    print('curvature: radius %.4f, top %g%% |mean curvature measure| >= %.4g'
          % (c['radius'], c['pctl'], c['threshold_abs_mean']))
    print('  |H| percentiles: ' + ', '.join('p%s=%.4g' % kv
                                           for kv in c['abs_mean_percentiles'].items()))
    print('  K percentiles:   ' + ', '.join('p%s=%.4g' % kv
                                           for kv in c['gaussian_percentiles'].items()))
    print('  high-curvature: %d / %d vertices, %d / %d triangles, %.2f%% of the area, '
          '%d connected patches' % (c['high_vertices'], c['vertices'], c['high_triangles'],
                                    c['triangles'], 100 * c['high_area_fraction'],
                                    c['high_region_components']))
    print('candidate: %s' % rec['candidate']['path'])
    print('target:    %s' % rec['target']['path'])
    cl, tl = rec['candidate']['locality'], rec['target']['locality']
    print('%-36s %14s %14s' % ('locality', 'candidate', 'target'))
    for bucket in ('high_curv_fidelity', 'low_curv_fidelity'):
        for key in ('samples', 'mean', 'rms', 'p95', 'max'):
            spec = 'd' if key == 'samples' else '.3e'
            print('%-36s %14s %14s' % ('%s.%s' % (bucket, key),
                                       score_remesh.fmt(cl[bucket][key], spec),
                                       score_remesh.fmt(tl[bucket][key], spec)))
    for key in ('high_curv_sample_fraction', 'boundary_edges',
                'boundary_edges_near_high_curv', 'boundary_components',
                'largest_boundary_component_edges', 'degenerate_quads',
                'degenerate_quads_near_high_curv'):
        spec = '.4f' if key == 'high_curv_sample_fraction' else 'd'
        print('%-36s %14s %14s' % (key, format(cl[key], spec), format(tl[key], spec)))
    print('locality: ' + json.dumps(cl, sort_keys=True))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0].strip())
    parser.add_argument('--source', required=True, help='original mesh (OBJ)')
    parser.add_argument('--target', required=True, help='reference remesh (OBJ)')
    parser.add_argument('--candidate', required=True, help='remesh to analyze (OBJ)')
    parser.add_argument('--out', help='JSONL file to append the record to')
    parser.add_argument('--samples', type=int, default=score_remesh.DEFAULT_SAMPLES,
                        help='surface samples (default %(default)s)')
    parser.add_argument('--seed', type=int, default=score_remesh.DEFAULT_SEED,
                        help='sampling seed (default %(default)s)')
    parser.add_argument('--pctl', type=float, default=DEFAULT_PCTL,
                        help='top percent of |mean curvature| flagged high '
                             '(default %(default)s)')
    parser.add_argument('--radius-scale', type=float, default=DEFAULT_RADIUS_SCALE,
                        help="curvature radius / target's mean edge length "
                             '(default %(default)s)')
    args = parser.parse_args(argv)
    if args.samples <= 0:
        parser.error('--samples must be positive')
    if not (0 < args.pctl < 100) or args.radius_scale <= 0:
        parser.error('need 0 < --pctl < 100 and --radius-scale > 0')

    lref = LocalityReference(args.source, args.target, samples=args.samples,
                             seed=args.seed, pctl=args.pctl,
                             radius_scale=args.radius_scale)
    rec = lref.record(args.candidate)
    if args.out:
        score_remesh.append_jsonl(args.out, rec)
    report(rec)
    return 0


if __name__ == '__main__':
    sys.exit(main())
