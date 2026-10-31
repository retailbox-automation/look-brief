#!/bin/bash
# Clean export of HEAD for `zeabur deploy` (an upload of the working folder would ship .venv and data).
# Usage: scripts/export_for_deploy.sh <empty-dir>   -> prints the dir; writes src/lookbrief/BUILD = commit.
set -euo pipefail
dest="${1:?target dir}"
mkdir -p "$dest"
[ -z "$(ls -A "$dest")" ] || { echo "target dir not empty: $dest" >&2; exit 1; }
git archive HEAD | tar -x -C "$dest"
git rev-parse --short HEAD > "$dest/src/lookbrief/BUILD"
# the uploader skips git-ignored files: un-ignore the stamp in the exported copy only
grep -v '^src/lookbrief/BUILD$' "$dest/.gitignore" > "$dest/.gitignore.tmp" && mv "$dest/.gitignore.tmp" "$dest/.gitignore"
echo "$dest"
