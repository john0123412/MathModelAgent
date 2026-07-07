#!/bin/sh
set -eu

EXTRA_FONTS_DIR="${MMA_EXTRA_FONTS_DIR:-/usr/local/share/fonts/mma-extra}"

if [ -d "$EXTRA_FONTS_DIR" ]; then
    fc-cache -f "$EXTRA_FONTS_DIR" >/dev/null 2>&1 || true
fi

exec "$@"
