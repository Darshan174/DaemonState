#!/usr/bin/env bash
# Run the native macOS floating DaemonState control.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PACKAGE_PATH="${REPOSITORY_ROOT}/desktop/macos/DaemonStateOverlay"
SWIFT_CACHE_ROOT="${DAEMONSTATE_OVERLAY_SWIFT_CACHE_ROOT:-${PACKAGE_PATH}/.build/daemonstate-cache}"

umask 077
/bin/mkdir -p \
  "${SWIFT_CACHE_ROOT}/cache" \
  "${SWIFT_CACHE_ROOT}/configuration" \
  "${SWIFT_CACHE_ROOT}/module-cache" \
  "${SWIFT_CACHE_ROOT}/security"

# DaemonState can itself run inside a local app sandbox. Keep SwiftPM's
# writable build metadata inside the package and avoid nesting SwiftPM's
# subprocess sandbox inside the parent app sandbox.
export CLANG_MODULE_CACHE_PATH="${SWIFT_CACHE_ROOT}/module-cache"
export SWIFTPM_MODULECACHE_OVERRIDE="${SWIFT_CACHE_ROOT}/module-cache"

HAS_CONTROL_TOKEN=0
for argument in "$@"; do
  if [[ "${argument}" == "--control-token" ]]; then
    HAS_CONTROL_TOKEN=1
    break
  fi
done

OVERLAY_ARGUMENTS=("$@")
if [[ "${HAS_CONTROL_TOKEN}" -eq 0 ]]; then
  CONTROL_TOKEN="${DAEMONSTATE_OVERLAY_CONTROL_TOKEN:-$(/usr/bin/uuidgen)}"
  OVERLAY_ARGUMENTS+=(--control-token "${CONTROL_TOKEN}")
fi

FRESH_BINARY=""
for candidate in \
  "${PACKAGE_PATH}/.build/release/DaemonStateOverlay" \
  "${PACKAGE_PATH}/.build/debug/DaemonStateOverlay"
do
  if [[ ! -f "${candidate}" || ! -x "${candidate}" ]]; then
    continue
  fi
  if [[ "${PACKAGE_PATH}/Package.swift" -nt "${candidate}" ]]; then
    continue
  fi
  if /usr/bin/find "${PACKAGE_PATH}/Sources" \
    -type f -newer "${candidate}" -print -quit | /usr/bin/grep -q .
  then
    continue
  fi
  if [[ -z "${FRESH_BINARY}" || "${candidate}" -nt "${FRESH_BINARY}" ]]; then
    FRESH_BINARY="${candidate}"
  fi
done

if [[ -n "${FRESH_BINARY}" ]]; then
  exec "${FRESH_BINARY}" "${OVERLAY_ARGUMENTS[@]}"
fi

exec swift run \
  --disable-sandbox \
  --package-path "${PACKAGE_PATH}" \
  --cache-path "${SWIFT_CACHE_ROOT}/cache" \
  --config-path "${SWIFT_CACHE_ROOT}/configuration" \
  --manifest-cache local \
  --security-path "${SWIFT_CACHE_ROOT}/security" \
  --scratch-path "${PACKAGE_PATH}/.build" \
  DaemonStateOverlay \
  "${OVERLAY_ARGUMENTS[@]}"
