#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repository_root"

require_homebrew_formula() {
    local formula="$1"
    if brew list --formula "$formula" >/dev/null 2>&1; then
        echo "ok      $formula"
        return
    fi
    echo "install $formula"
    brew install "$formula"
}

ensure_vcpkg() {
    if [[ -n "${VCPKG_ROOT:-}" && -x "${VCPKG_ROOT}/vcpkg" ]]; then
        echo "ok      vcpkg at $VCPKG_ROOT"
        return
    fi
    local default_root="$HOME/vcpkg"
    if [[ ! -d "$default_root" ]]; then
        echo "install vcpkg into $default_root"
        git clone --depth 1 https://github.com/microsoft/vcpkg.git "$default_root"
    fi
    if [[ ! -x "$default_root/vcpkg" ]]; then
        "$default_root/bootstrap-vcpkg.sh" -disableMetrics
    fi
    echo "ok      vcpkg at $default_root"
    echo
    echo "Add this to your shell profile:"
    echo "    export VCPKG_ROOT=\"$default_root\""
}

echo "== host toolchain =="
require_homebrew_formula cmake
require_homebrew_formula ninja
ensure_vcpkg

echo
echo "== python tracks =="
uv sync --project python_pure
uv sync --project python_cpp

echo
echo "== c++ configure =="
export VCPKG_ROOT="${VCPKG_ROOT:-$HOME/vcpkg}"
cmake --preset release

echo
echo "bootstrap complete; run tools/check_all.sh"
