#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repository_root"

NATIVE_DEPENDENCIES=(cmake ninja apache-arrow nlohmann-json catch2)

require_homebrew_formula() {
    local formula="$1"
    if brew list --formula "$formula" >/dev/null 2>&1; then
        echo "ok      $formula"
        return
    fi
    echo "install $formula"
    brew install "$formula"
}

echo "== native toolchain =="
for formula in "${NATIVE_DEPENDENCIES[@]}"; do
    require_homebrew_formula "$formula"
done

echo
echo "== python tracks =="
uv python install
tools/sync_python_tracks.sh python_pure:volarb-py python_cpp:volarb-cpp

echo
echo "== c++ configure =="
cmake --preset release

echo
echo "bootstrap complete; run tools/check_all.sh"
