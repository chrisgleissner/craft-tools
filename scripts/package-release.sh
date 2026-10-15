#!/usr/bin/env bash
# Package tracked source only, with executable modes and a reproducible checksum.
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
if (($# != 2)) || [[ ! $1 =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo 'Usage: package-release.sh vMAJOR.MINOR.PATCH OUTPUT_DIRECTORY' >&2
    exit 2
fi
version=$1
mkdir -p "$2"
output=$(cd -- "$2" && pwd -P)
archive=craft-tools-$version.tar.gz
git -C "$root" archive --format=tar.gz --prefix="craft-tools-$version/" \
    --output="$output/$archive" HEAD
(cd "$output"; sha256sum "$archive" > SHA256SUMS)
echo "$output/$archive"
