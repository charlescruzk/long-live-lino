#!/bin/zsh
# Pick up new photos, refresh the review sheets, and re-render both videos.
#   build/update.sh            full quality
#   build/update.sh --preview  quick half-res check
set -e
cd "${0:A:h}/.."
.venv/bin/python build/prepare.py
.venv/bin/python build/render.py --format 16x9 "$@"
.venv/bin/python build/review.py
.venv/bin/python build/render.py --format 9x16 "$@"
