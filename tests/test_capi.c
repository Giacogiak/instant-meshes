/*
    test_capi.c -- native test harness for the instantmeshes_core C API

    Usage: test_capi <input mesh> <scratch directory>

    Written in C on purpose: it also checks that capi.h is valid C and that the
    library is usable through a plain C ABI (as P/Invoke does).
*/

#include "capi.h"
#include <stdio.h>
#include <string.h>

static int failures = 0;

#define CHECK(cond) do { \
        if (!(cond)) { \
            fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond); \
            ++failures; \
        } \
    } while (0)

/* CLI defaults (see "Instant Meshes -h") */
static im_remesh_params default_params(void) {
    im_remesh_params p;
    p.rosy = 4;
    p.posy = 4;
    p.scale = -1.f;
    p.face_count = -1;
    p.vertex_count = -1;
    p.crease_angle = -1.f;
    p.extrinsic = 1;
    p.align_to_boundaries = 0;
    p.smooth_iter = 2;
    p.knn_points = 10;
    p.pure_quad = 1;
    p.deterministic = 0;
    return p;
}

/* Counts the "v " and "f " lines of an OBJ file and the vertices of each face */
static int count_obj(const char *filename, int *vertices, int *faces, int *non_quads) {
    char line[1024];
    FILE *f = fopen(filename, "r");
    if (!f)
        return 0;
    *vertices = *faces = *non_quads = 0;
    while (fgets(line, sizeof(line), f)) {
        if (strncmp(line, "v ", 2) == 0) {
            ++*vertices;
        } else if (strncmp(line, "f ", 2) == 0) {
            int corners = 0;
            char *tok = strtok(line + 2, " \t\r\n");
            for (; tok; tok = strtok(NULL, " \t\r\n"))
                ++corners;
            ++*faces;
            if (corners != 4)
                ++*non_quads;
        }
    }
    fclose(f);
    return 1;
}

int main(int argc, char **argv) {
    char err[512], path[1024], small[8];
    im_remesh_result result;
    im_remesh_params p;
    int rv, vertices, faces, non_quads;

    if (argc != 3) {
        fprintf(stderr, "Usage: %s <input mesh> <scratch directory>\n", argv[0]);
        return 2;
    }

    /* Thread count: fixed once per process */
    CHECK(im_set_thread_count(0) == IM_ERR_INVALID_ARG);
    CHECK(im_set_thread_count(-2) == IM_ERR_INVALID_ARG);
    CHECK(im_set_thread_count(-1) == IM_OK);
    CHECK(im_set_thread_count(-1) == IM_OK);
    CHECK(im_set_thread_count(2) == IM_ERR_INVALID_ARG);

    /* Invalid arguments are rejected before any work is done */
    snprintf(path, sizeof(path), "%s/test_capi_invalid.obj", argv[2]);
    p = default_params();
    CHECK(im_remesh(argv[1], path, NULL, &result, err, sizeof(err)) == IM_ERR_INVALID_ARG);
    CHECK(strlen(err) > 0);
    CHECK(im_remesh(NULL, path, &p, &result, err, sizeof(err)) == IM_ERR_INVALID_ARG);
    p.rosy = 5;
    CHECK(im_remesh(argv[1], path, &p, &result, err, sizeof(err)) == IM_ERR_INVALID_ARG);
    p = default_params();
    p.face_count = 1000;
    p.vertex_count = 1000;
    CHECK(im_remesh(argv[1], path, &p, &result, err, sizeof(err)) == IM_ERR_INVALID_ARG);
    printf("invalid arguments: \"%s\"\n", err);

    /* A missing input file is reported as IM_ERR_RUNTIME, not as an exception/crash */
    p = default_params();
    result.out_vertex_count = result.out_face_count = 12345;
    memset(err, 0, sizeof(err));
    rv = im_remesh("/nonexistent/directory/missing.obj", path, &p, &result, err, sizeof(err));
    printf("missing input: rv=%d, \"%s\"\n", rv, err);
    CHECK(rv == IM_ERR_RUNTIME);
    CHECK(strstr(err, "missing.obj") != NULL);
    CHECK(result.out_vertex_count == 0 && result.out_face_count == 0);

    /* So is an unsupported extension; a too small error buffer is truncated and terminated */
    memset(small, 'x', sizeof(small));
    rv = im_remesh("/nonexistent/input.xyz", path, &p, NULL, small, sizeof(small));
    CHECK(rv == IM_ERR_RUNTIME);
    CHECK(strlen(small) == sizeof(small) - 1);

    /* No error buffer at all */
    CHECK(im_remesh("/nonexistent/missing.obj", path, &p, &result, NULL, 0) == IM_ERR_RUNTIME);

    /* The real thing: remesh the input, asking for as many faces as quad-remeshed.obj has */
    snprintf(path, sizeof(path), "%s/test_capi_output.obj", argv[2]);
    remove(path);
    p = default_params();
    p.face_count = 11054;
    p.deterministic = 1;
    rv = im_remesh(argv[1], path, &p, &result, err, sizeof(err));
    printf("remesh: rv=%d, \"%s\", out_vertex_count=%d, out_face_count=%d\n",
           rv, err, result.out_vertex_count, result.out_face_count);
    CHECK(rv == IM_OK);
    CHECK(strlen(err) == 0);
    CHECK(result.out_vertex_count > 0 && result.out_face_count > 0);
    /* Pure quad mode subdivides the extracted mesh once, giving ~4x the requested faces */
    CHECK(result.out_face_count > p.face_count * 2 && result.out_face_count < p.face_count * 8);
    /* A closed quad mesh has roughly as many vertices as faces (Euler) */
    CHECK(result.out_vertex_count > result.out_face_count / 2 &&
          result.out_vertex_count < result.out_face_count * 2);

    /* The reported counts are those of the file that was written */
    CHECK(count_obj(path, &vertices, &faces, &non_quads));
    printf("written file: %d vertices, %d faces, %d non-quad faces\n", vertices, faces, non_quads);
    CHECK(vertices == result.out_vertex_count);
    CHECK(faces == result.out_face_count);
    CHECK(non_quads == 0);

    /* Quad-dominant mode: ~ the requested face count, some of them triangles/n-gons */
    remove(path);
    p.pure_quad = 0;
    rv = im_remesh(argv[1], path, &p, &result, err, sizeof(err));
    printf("remesh (quad-dominant): rv=%d, \"%s\", out_vertex_count=%d, out_face_count=%d\n",
           rv, err, result.out_vertex_count, result.out_face_count);
    CHECK(rv == IM_OK);
    CHECK(result.out_face_count > p.face_count / 2 && result.out_face_count < p.face_count * 2);
    CHECK(count_obj(path, &vertices, &faces, &non_quads));
    printf("written file: %d vertices, %d faces, %d non-quad faces\n", vertices, faces, non_quads);
    CHECK(vertices == result.out_vertex_count);
    CHECK(faces == result.out_face_count);
    p.pure_quad = 1;

    /* An unwritable output path fails after the whole solve, still without escaping */
    rv = im_remesh(argv[1], "/nonexistent/directory/out.obj", &p, &result, err, sizeof(err));
    printf("unwritable output: rv=%d, \"%s\"\n", rv, err);
    CHECK(rv == IM_ERR_RUNTIME);
    CHECK(strlen(err) > 0);
    CHECK(result.out_vertex_count == 0 && result.out_face_count == 0);

    if (failures)
        fprintf(stderr, "%d check(s) FAILED\n", failures);
    else
        printf("All checks passed.\n");
    return failures ? 1 : 0;
}
