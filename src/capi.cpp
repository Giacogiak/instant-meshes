/*
    capi.cpp -- C interface to the Instant Meshes batch remesher

    This file is part of the implementation of

        Instant Field-Aligned Meshes
        Wenzel Jakob, Daniele Panozzo, Marco Tarini, and Olga Sorkine-Hornung
        In ACM Transactions on Graphics (Proc. SIGGRAPH Asia 2015)

    All rights reserved. Use of this source code is governed by a
    BSD-style license that can be found in the LICENSE.txt file.
*/

#include "capi.h"
#include "batch.h"
#include <cstring>

/* Thread count, also read by Optimizer::run() (main.cpp defines it for the GUI executable) */
int nprocs = -1;

/* Process-wide TBB scheduler, created on first use and intentionally never destroyed:
   with the bundled TBB 4.4, repeatedly creating and destroying the last
   task_scheduler_init of a process crashed on the third cycle (MinGW build under Wine) */
static std::mutex scheduler_mutex;
static tbb::task_scheduler_init *scheduler = nullptr;

static bool init_scheduler(int count) {
    std::lock_guard<std::mutex> guard(scheduler_mutex);
    if (scheduler)
        return false;
    nprocs = count;
    scheduler = new tbb::task_scheduler_init(
        count == -1 ? tbb::task_scheduler_init::automatic : count);
    return true;
}

static void set_error(char *buf, int buf_len, const char *message) {
    if (!buf || buf_len <= 0)
        return;
    size_t n = std::min(std::strlen(message), (size_t) buf_len - 1);
    std::memcpy(buf, message, n);
    buf[n] = '\0';
}

static const char *check_params(const char *input_path, const char *output_path,
                                const im_remesh_params *p) {
    if (!input_path || !output_path || !p)
        return "im_remesh: input_path, output_path and params must not be NULL!";
    if (p->rosy != 2 && p->rosy != 4 && p->rosy != 6)
        return "im_remesh: rosy must be 2, 4, or 6!";
    if (p->posy != 3 && p->posy != 4 && p->posy != 6)
        return "im_remesh: posy must be 3 (or 6) or 4!";
    int nConstraints = (p->scale > 0 ? 1 : 0) + (p->face_count > 0 ? 1 : 0) +
                       (p->vertex_count > 0 ? 1 : 0);
    if (nConstraints > 1)
        return "im_remesh: only one of scale, face_count and vertex_count can be set at once!";
    if (p->smooth_iter < 0)
        return "im_remesh: smooth_iter must be >= 0!";
    if (p->knn_points <= 0)
        return "im_remesh: knn_points must be > 0!";
    return nullptr;
}

extern "C" IM_API int im_remesh(const char *input_path, const char *output_path,
                                const im_remesh_params *params, im_remesh_result *result,
                                char *error_message_buf, int error_message_buf_len) {
    if (result)
        result->out_vertex_count = result->out_face_count = 0;
    set_error(error_message_buf, error_message_buf_len, "");

    if (const char *message = check_params(input_path, output_path, params)) {
        set_error(error_message_buf, error_message_buf_len, message);
        return IM_ERR_INVALID_ARG;
    }

    try {
        init_scheduler(-1);

        int vertex_count = 0, face_count = 0;
        batch_process(input_path, output_path, params->rosy,
                      params->posy == 6 ? 3 : params->posy, params->scale,
                      params->face_count, params->vertex_count,
                      params->crease_angle, params->extrinsic != 0,
                      params->align_to_boundaries != 0, params->smooth_iter,
                      params->knn_points, params->pure_quad != 0,
                      params->deterministic != 0, &vertex_count, &face_count);
        if (result) {
            result->out_vertex_count = vertex_count;
            result->out_face_count = face_count;
        }
        return IM_OK;
    } catch (const std::exception &e) {
        set_error(error_message_buf, error_message_buf_len, e.what());
        return IM_ERR_RUNTIME;
    } catch (...) {
        set_error(error_message_buf, error_message_buf_len, "im_remesh: unknown error!");
        return IM_ERR_UNKNOWN;
    }
}

extern "C" IM_API int im_set_thread_count(int count) {
    if (count != -1 && count <= 0)
        return IM_ERR_INVALID_ARG;
    try {
        if (init_scheduler(count))
            return IM_OK;
    } catch (...) {
        return IM_ERR_UNKNOWN;
    }
    /* Already fixed by an earlier call */
    return count == nprocs ? IM_OK : IM_ERR_INVALID_ARG;
}
