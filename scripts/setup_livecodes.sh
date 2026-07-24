#!/bin/sh
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
target="$project_root/vendor/livecodes"
[ -f "$target/index.html" ] && exit 0

scratch=$(mktemp -d "$project_root/work/livecodes.XXXXXX")
trap 'rm -rf "$scratch"' EXIT
asset_id=$(gh api repos/live-codes/livecodes/releases/tags/v49 --jq '.assets[] | select(.name=="livecodes-v49.tar.gz") | .id')
gh api -H 'Accept: application/octet-stream' "repos/live-codes/livecodes/releases/assets/$asset_id" > "$scratch/livecodes.tar.gz"
tar -xzf "$scratch/livecodes.tar.gz" -C "$scratch"
test -f "$scratch/build/index.html"
mv "$scratch/build" "$target"
