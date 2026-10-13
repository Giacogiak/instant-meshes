#!/usr/bin/env bash
# compare_with_cli.sh -- checks that the C# P/Invoke path reproduces the Instant Meshes
# CLI's batch-mode result (Milestone M4 exit criterion)
#
#   csharp-demo/compare_with_cli.sh [--no-weld] <path to "Instant Meshes" CLI> <input mesh> [work dir]
#
# Runs the demo with its defaults (weld the input, then M3's D8 set: -v 2799, no crease,
# -S 1, pure quad, deterministic, 1 thread) and the CLI with the equivalent
# "-d -t 1 -v 2799 -S 1" on the same welded mesh (the demo's --save-welded), then compares
# the reported/written V and F, the output files byte for byte, and the M2 scorer's
# records for both outputs. Exits 0 only if all of them are identical. With --no-weld,
# both remesh the input as it is.
# Needs dotnet, python3 with numpy/scipy/trimesh, and the demo built (dotnet build).
set -euo pipefail

weld=1
if [ "${1:-}" = --no-weld ]; then
    weld=0
    shift
fi
cli=$1
input=$(realpath "$2")
here=$(cd "$(dirname "$0")" && pwd)
repo=$(dirname "$here")
work=${3:-$(mktemp -d)}
mkdir -p "$work"

if [ $weld = 1 ]; then
    rm -f "$work/welded.obj"
    demo_flags=(--save-welded "$work/welded.obj")
    cli_input=$work/welded.obj
else
    demo_flags=(--no-weld)
    cli_input=$input
fi
dotnet "$here/bin/Debug/net8.0/InstantMeshesDemo.dll" --input "$input" --output "$work/csharp.obj" \
    "${demo_flags[@]}" > "$work/csharp.log" 2>&1
"$cli" -o "$work/cli.obj" -d -t 1 -v 2799 -S 1 "$cli_input" > "$work/cli.log" 2>&1
if [ $weld = 1 ]; then
    echo "CLI input: the demo's welded mesh, sha256 $(sha256sum "$cli_input" | cut -d' ' -f1)"
else
    echo "CLI input: $input as it is (--no-weld)"
fi

score() {
    rm -f "$work/$1.jsonl"
    python3 "$repo/scripts/score_remesh.py" --source "$repo/source.obj" \
        --target "$repo/quad-remeshed.obj" --candidate "$work/$1.obj" \
        --out "$work/$1.jsonl" > /dev/null
}
score csharp
score cli

python3 - "$work" <<'EOF'
import json, re, sys
work = sys.argv[1]

def written(log):  # batch_process's 'Writing "..." (V=..., F=...)' line
    return tuple(map(int, re.search(r'\(V=(\d+), F=(\d+)\)', open(log).read()).groups()))

def file_counts(path):
    v = f = 0
    for line in open(path):
        v += line.startswith('v ')
        f += line.startswith('f ')
    return v, f

cs_log = open(work + '/csharp.log').read()
reported = (int(re.search(r'^out_vertex_count=(\d+)$', cs_log, re.M).group(1)),
            int(re.search(r'^out_face_count=(\d+)$', cs_log, re.M).group(1)))
cs_bytes, cli_bytes = (open(work + '/%s.obj' % n, 'rb').read() for n in ('csharp', 'cli'))
cs_score, cli_score = (json.loads(open(work + '/%s.jsonl' % n).read())
                       for n in ('csharp', 'cli'))
metrics = ('counts', 'quad_quality', 'valence', 'fidelity')
checks = {
    'C# out_vertex/face_count vs CLI written V/F': (reported, written(work + '/cli.log')),
    'C# .obj v/f lines vs CLI .obj v/f lines': (file_counts(work + '/csharp.obj'),
                                                 file_counts(work + '/cli.obj')),
    'output .obj bytes': (cs_bytes, cli_bytes),
    'aggregate score': (cs_score['aggregate'], cli_score['aggregate']),
    'candidate metrics': ({k: cs_score['candidate'][k] for k in metrics},
                          {k: cli_score['candidate'][k] for k in metrics}),
}
ok = True
for name, (a, b) in checks.items():
    ok &= a == b
    shown = '' if name == 'output .obj bytes' else ': %r' % (a,) if a == b else ': %r vs %r' % (a, b)
    print('%-45s %s%s' % (name, 'identical' if a == b else 'DIFFERS', shown if len(shown) < 200 else ''))
print('V/F %d/%d, aggregate score %r, work dir %s' % (reported + (cs_score['aggregate']['score'], work)))
sys.exit(0 if ok else 1)
EOF
