/*
    capi.h -- C interface to the Instant Meshes batch remesher, e.g. for
    P/Invoke from .NET (exported by the instantmeshes_core shared library)

    This file is part of the implementation of

        Instant Field-Aligned Meshes
        Wenzel Jakob, Daniele Panozzo, Marco Tarini, and Olga Sorkine-Hornung
        In ACM Transactions on Graphics (Proc. SIGGRAPH Asia 2015)

    All rights reserved. Use of this source code is governed by a
    BSD-style license that can be found in the LICENSE.txt file.
*/

#pragma once

#if defined(_WIN32)
  #ifdef INSTANTMESHES_CORE_EXPORTS
    #define IM_API __declspec(dllexport)
  #else
    #define IM_API __declspec(dllimport)
  #endif
#else
  #define IM_API __attribute__((visibility("default")))
#endif

#ifdef __cplusplus
extern "C" {
#endif

/* Mirrors the command line options of the batch mode ("Instant Meshes -o ..."),
   the CLI default of each field is given in parentheses */
typedef struct {
    int   rosy;                /* Orientation symmetry: 2, 4, or 6 (4) */
    int   posy;                /* Position symmetry: 4 = quads or 3 = triangles; 6 is accepted as 3 (4) */
    float scale;               /* Target edge length in world units, -1 = unset (-1) */
    int   face_count;          /* Target face count, -1 = unset (-1) */
    int   vertex_count;        /* Target vertex count, -1 = unset (-1). If scale, face_count
                                  and vertex_count are all unset, vertex_count defaults to
                                  1/16 of the input vertex count. At most one may be set. */
    float crease_angle;        /* Dihedral angle threshold for creases in degrees, -1 = disabled (-1) */
    int   extrinsic;           /* bool: extrinsic (1) or intrinsic (0) smoothness (1) */
    int   align_to_boundaries; /* bool: align to open mesh boundaries (0) */
    int   smooth_iter;         /* Smoothing & ray tracing reprojection steps, >= 0 (2) */
    int   knn_points;          /* Point clouds only: number of adjacent points, > 0 (10) */
    int   pure_quad;           /* bool: pure tri/quad mesh (1) or tri/quad dominant mesh (0) (1) */
    int   deterministic;       /* bool: prefer (slower) deterministic algorithms (0) */
} im_remesh_params;

typedef struct {
    int out_vertex_count;      /* Vertices in the written mesh */
    int out_face_count;        /* Faces in the written mesh */
} im_remesh_result;

enum { IM_OK = 0, IM_ERR_RUNTIME = 1, IM_ERR_UNKNOWN = 2, IM_ERR_INVALID_ARG = 3 };

/**
 * Remeshes the mesh or point cloud at input_path (.obj/.ply/.aln) and writes the
 * result to output_path (.obj/.ply). Never throws. On success returns IM_OK and fills
 * in *result (which may be NULL). Otherwise returns IM_ERR_INVALID_ARG (bad
 * parameters), IM_ERR_RUNTIME (e.g. unreadable input, unwritable output) or
 * IM_ERR_UNKNOWN, zeroes *result and writes a NUL-terminated (possibly truncated)
 * description into error_message_buf, if given. Progress is logged to stdout.
 * Concurrent calls from several threads are not supported.
 */
IM_API int im_remesh(const char *input_path, const char *output_path,
                     const im_remesh_params *params, im_remesh_result *result,
                     char *error_message_buf, int error_message_buf_len);

/**
 * Sets the number of threads used by im_remesh: -1 = automatic (one per hardware
 * thread), or a positive count. Like the CLI's --threads option, the count is fixed
 * once per process: call this before the first im_remesh call, which otherwise fixes
 * it to automatic. Returns IM_OK, or IM_ERR_INVALID_ARG if the count is invalid or
 * differs from the one already fixed.
 */
IM_API int im_set_thread_count(int nprocs);

#ifdef __cplusplus
}
#endif
