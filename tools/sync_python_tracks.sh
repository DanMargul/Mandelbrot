#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repository_root"

remove_stale_editable_path_files() {
    local environment_directory="$1"
    [[ -d "$environment_directory" ]] || return 0
    find "$environment_directory" -name '_editable_impl_*.pth' -delete 2>/dev/null || true
}

sync_track() {
    local project_directory="$1"
    local package_name="$2"
    uv sync \
        --project "$project_directory" \
        --no-editable \
        --reinstall-package "$package_name" \
        --python-preference only-managed \
        --quiet
    remove_stale_editable_path_files "$project_directory/.venv"
}

uv sync --python-preference only-managed --quiet

for specification in "$@"; do
    sync_track "${specification%%:*}" "${specification##*:}"
done
