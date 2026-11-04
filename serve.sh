#!/bin/sh
# Starts Video Dubbing on http://localhost:8000 (macOS and Linux). Needs Python 3.8+.
cd "$(dirname "$0")" || exit 1
for py in python3 python; do
  if command -v "$py" >/dev/null 2>&1 && "$py" -c "import sys; sys.exit(sys.version_info < (3, 8))" 2>/dev/null; then
    exec "$py" server.py "$@"
  fi
done
echo "Python 3.8 or newer is needed."
echo "  macOS: brew install python   (or download it from python.org)"
echo "  Linux: sudo apt install python3   (or your distribution's package manager)"
exit 1
