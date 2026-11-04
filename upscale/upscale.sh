#!/bin/sh
# macOS / Linux: upscale a video with AI.  ./upscale/upscale.sh VIDEO --to 4k --model photo
exec python3 "$(dirname "$0")/upscale.py" "$@"
