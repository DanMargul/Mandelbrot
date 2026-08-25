#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repository_root"

announce() { echo; echo "===== $1 ====="; }

announce "sync python tracks"
tools/sync_python_tracks.sh python_pure:volarb-py python_cpp:volarb-cpp

announce "conventions"
uv run --no-sync tools/check_no_comments.py .

announce "ruff"
uv run --no-sync ruff check python_pure python_cpp conformance ingestion research reporting tools benchmarks
uv run --no-sync ruff format --check python_pure python_cpp conformance ingestion research reporting tools benchmarks

announce "mypy"
for directory in conformance benchmarks ingestion research reporting tools; do
    uv run --no-sync mypy --strict "$directory"
done
uv run --no-sync --project python_pure mypy --strict python_pure/src
uv run --no-sync --project python_cpp mypy --strict python_cpp/src

announce "pytest ingestion"
uv run --no-sync pytest ingestion/tests -q

announce "pytest research"
uv run --no-sync pytest research/tests -q

announce "pytest reporting"
uv run --no-sync pytest reporting/tests -q

announce "pytest python_pure"
uv run --no-sync --project python_pure pytest python_pure -q

announce "c++ build"
cmake --build --preset release

announce "ctest"
ctest --preset release --output-on-failure

announce "pytest python_cpp"
uv run --no-sync --project python_cpp pytest python_cpp -q

announce "conformance"
uv run --no-sync conformance/run.py --all

echo
echo "all checks passed"
