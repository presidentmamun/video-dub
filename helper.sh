#!/bin/sh
# Video Dubbing helper (macOS / Linux): lets the Video Dubbing page use this computer's graphics card.
# Installs to ~/.video-dub (code from github.com/presidentmamun/video-dub) and runs it on 127.0.0.1 only.
#   curl -fsSL https://raw.githubusercontent.com/presidentmamun/video-dub/main/helper.sh | sh
D="$HOME/.video-dub"
T=$(mktemp -d) || exit 1
echo "Getting the latest helper..."
if curl -fsSL https://github.com/presidentmamun/video-dub/archive/refs/heads/main.tar.gz | tar -xz -C "$T"; then
  mkdir -p "$D" && cp -R "$T"/video-dub-main/. "$D"/
else
  echo "Could not download the helper. Check the internet connection."
fi
rm -rf "$T"
[ -f "$D/server.py" ] || exit 1
exec sh "$D/serve.sh" --helper
