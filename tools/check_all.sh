#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repository_root"

announce() { echo; echo "===== $1 ====="; }

announce "conventions"
uv run tools/check_no_comments.py .

announce "ruff"
uv run --project python_pure ruff check python_pure conformance tools benchmarks
uv run --project python_pure ruff format --check python_pure conformance tools benchmarks

announce "mypy python_pure"
uv run --project python_pure mypy --strict python_pure/src conformance tools

announce "pytest python_pure"
uv run --project python_pure pytest python_pure -q

announce "c++ build"
export VCPKG_ROOT="${VCPKG_ROOT:-$HOME/vcpkg}"
cmake --build --preset release

announce "ctest"
ctest --preset release --output-on-failure

announce "pytest python_cpp"
uv run --project python_cpp pytest python_cpp -q

announce "conformance"
uv run conformance/run.py --all

echo
echo "all checks passed"
