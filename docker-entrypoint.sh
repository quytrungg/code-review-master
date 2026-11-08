#!/bin/sh
# Seed the bundled skill library into the data volume on first run.
#
# The image carries the default foundation at /opt/code-review. The app reads SKILLS_DIR, which is
# /data/code-review inside the container so that single-file uploads and hand edits survive a
# container restart — /app would be replaced by the next image. An empty or missing target is
# seeded; an existing one is left alone so upgrades never clobber edited rules.
set -eu

seed="${SKILLS_SEED_DIR:-/opt/code-review}"
target="${SKILLS_DIR:-/data/code-review}"

if [ -d "$seed" ] && [ -z "$(ls -A "$target" 2>/dev/null || true)" ]; then
    mkdir -p "$target"
    cp -R "$seed"/. "$target"/
fi

exec "$@"
