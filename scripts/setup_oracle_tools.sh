#!/usr/bin/env bash
# Prefetch the Shuttle dependency and prepare the miri sysroot so the oracle
# can run offline afterwards.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "== cargo fetch (Shuttle shim) =="
cargo fetch --manifest-path "$root/tools/concir_sync_shuttle/Cargo.toml"

echo "== cargo miri setup =="
cargo miri setup

echo "oracle tools ready"
