#!/usr/bin/env bash
# Launch the most recently built binary, independent of the caller's directory.
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
app=${1:-photocraft}
(($# == 0)) || shift
case $app in
    craft-launcher) binary=artcraft-launcher;;
    artcraft-native) binary=artcraft-native;;
    craft-repo-status-app) binary=craft-status-app;;
    photocraft|vectorcraft|filmcraft|effectcraft|deckcraft|pdfcraft|designcraft|lightcraft|wordcraft|figcraft|gridcraft|soundcraft|cadcraft|artcraft|artcraftx) binary=$app;;
    *) echo "Unknown app: $app" >&2; exit 2;;
esac
if [[ ! -x $root/bin/$binary ]]; then
    message="$app has not been built. Run $root/craft.sh $app"
    echo "$message" >&2
    if command -v notify-send >/dev/null; then notify-send 'Craft build needed' "$message" || true; fi
    exit 1
fi
exec "$root/bin/$binary" "$@"
