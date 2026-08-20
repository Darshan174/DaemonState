#!/usr/bin/env bash
# Build the macOS Continue helper only when neither release nor debug is fresh.
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  exit 0
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd "${script_dir}/.." && pwd)"
package_path="${repository_root}/desktop/macos/DaemonStateOverlay"
swift_cache_root="${package_path}/.build/daemonstate-cache"

command -v swift >/dev/null 2>&1 || {
  echo "Swift is required for browser-to-desktop Continue on macOS." >&2
  exit 1
}

mkdir -p \
  "${swift_cache_root}/cache" \
  "${swift_cache_root}/configuration" \
  "${swift_cache_root}/module-cache" \
  "${swift_cache_root}/security"
export CLANG_MODULE_CACHE_PATH="${swift_cache_root}/module-cache"
export SWIFTPM_MODULECACHE_OVERRIDE="${swift_cache_root}/module-cache"

helper_is_fresh() {
  local candidate="$1"
  [[ -x "${candidate}" ]] || return 1
  [[ ! "${package_path}/Package.swift" -nt "${candidate}" ]] || return 1
  [[ -z "$(find "${package_path}/Sources" -type f -newer "${candidate}" -print -quit)" ]]
}

for candidate in \
  "${package_path}/.build/release/DaemonStateOverlay" \
  "${package_path}/.build/debug/DaemonStateOverlay"
do
  if helper_is_fresh "${candidate}"; then
    exit 0
  fi
done

echo "Building the stale native macOS Continue helper…"
swift build \
  --disable-sandbox \
  --package-path "${package_path}" \
  --cache-path "${swift_cache_root}/cache" \
  --config-path "${swift_cache_root}/configuration" \
  --manifest-cache local \
  --security-path "${swift_cache_root}/security" \
  --scratch-path "${package_path}/.build" \
  -c release
