#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repository_root"

export VCPKG_ROOT="${VCPKG_ROOT:-$HOME/vcpkg}"

announce() { echo; echo "===== $1 ====="; }

announce "sync python tracks"
tools/sync_python_tracks.sh python_pure:volarb-py python_cpp:volarb-cpp

announce "conventions"
uv run --no-sync tools/check_no_comments.py .

announce "ruff"
uv run --no-sync ruff check python_pure python_cpp conformance tools benchmarks
uv run --no-sync ruff format --check python_pure python_cpp conformance tools benchmarks

announce "mypy"
uv run --no-sync mypy --strict conformance tools
uv run --no-sync --project python_pure mypy --strict python_pure/src

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
