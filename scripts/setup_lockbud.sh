#!/usr/bin/env bash
# Build the pinned lockbud binary used by the STATIC baseline (K1 / D7).
# Idempotent: an existing checkout is reused; the build runs only when the
# release binary is missing or HEAD is not the pinned commit.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$ROOT/tools/lockbud"
COMMIT="cc78cb7"
CHANNEL="nightly-2026-02-07"
URL="https://github.com/BurtonQin/lockbud"

if ! command -v git >/dev/null 2>&1; then
  echo "setup_lockbud: git is not installed" >&2
  exit 1
fi
if ! command -v rustup >/dev/null 2>&1; then
  echo "setup_lockbud: rustup is not installed" >&2
  exit 1
fi
if ! command -v cargo >/dev/null 2>&1; then
  echo "setup_lockbud: cargo is not installed" >&2
  exit 1
fi

if [[ ! -d "$DEST/.git" ]]; then
  echo "setup_lockbud: cloning $URL"
  git clone "$URL" "$DEST"
fi

echo "setup_lockbud: checkout $COMMIT"
if ! git -C "$DEST" cat-file -e "${COMMIT}^{commit}" 2>/dev/null; then
  git -C "$DEST" fetch --tags origin
fi
git -C "$DEST" checkout --detach "$COMMIT"

echo "setup_lockbud: install $CHANNEL (rustc-dev, llvm-tools-preview, rust-src)"
if ! rustup toolchain install "$CHANNEL" \
    --component rustc-dev,llvm-tools-preview,rust-src; then
  echo "setup_lockbud: failed to install $CHANNEL" >&2
  exit 1
fi

HEAD="$(git -C "$DEST" rev-parse HEAD)"
BIN="$DEST/target/release/lockbud"
case "$HEAD" in
  "$COMMIT"*) ;;
  *)
    echo "setup_lockbud: HEAD $HEAD is not $COMMIT" >&2
    exit 1
    ;;
esac

if [[ -x "$BIN" ]]; then
  echo "setup_lockbud: $BIN already built at $HEAD"
  exit 0
fi

echo "setup_lockbud: cargo build --release"
(
  cd "$DEST"
  cargo +"$CHANNEL" build --release
)
if [[ ! -x "$BIN" ]]; then
  echo "setup_lockbud: build finished but $BIN is missing" >&2
  exit 1
fi
echo "setup_lockbud: built $BIN"
