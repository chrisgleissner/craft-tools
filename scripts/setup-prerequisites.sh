#!/usr/bin/env bash
# Install the Linux Craft build/startup-test prerequisites on apt-based systems.
set -euo pipefail
root=$1
shift
check=0 skip_auth=0
while (($#)); do
    case $1 in
        --check) check=1;;
        --no-auth) skip_auth=1;;
        -h|--help) echo 'Usage: craft setup [--check] [--no-auth]'; exit 0;;
        *) echo 'Usage: craft setup [--check] [--no-auth]' >&2; exit 2;;
    esac
    shift
done
if ! command -v apt-get >/dev/null || ! command -v dpkg-query >/dev/null; then
    echo 'Automatic setup currently requires Linux with apt-get and dpkg-query (Ubuntu/Debian).' >&2
    exit 1
fi
packages=(
    build-essential pkg-config cmake clang libclang-dev git gh curl ca-certificates
    python3 python3-gi gir1.2-glib-2.0 shellcheck util-linux xz-utils
    libxkbcommon-dev libwayland-dev libx11-dev libx11-xcb-dev libxcursor-dev
    libxrandr-dev libxi-dev libxinerama-dev libgl1-mesa-dev libvulkan-dev
    libgtk-3-dev libwebkit2gtk-4.1-dev libayatana-appindicator3-dev librsvg2-dev
    libssl-dev libfontconfig-dev libfreetype-dev libasound2-dev libudev-dev
    libdbus-1-dev patchelf xvfb xauth x11-utils imagemagick dbus-x11
    desktop-file-utils libnotify-bin
)
missing=()
for package in "${packages[@]}"; do
    status=$(dpkg-query -W -f='${db:Status-Status}' "$package" 2>/dev/null || true)
    [[ $status == installed ]] || missing+=("$package")
done
export PATH="$root/.build/tools/node/bin:$PATH:${CARGO_HOME:-$HOME/.cargo}/bin"
node_ready() {
    command -v node >/dev/null && command -v npm >/dev/null &&
        node -e 'process.exit(Number(process.versions.node.split(".")[0]) >= 22 ? 0 : 1)' &&
        npm --version >/dev/null 2>&1
}
rust_ready() {
    command -v rustup >/dev/null &&
        rustup run "${RUSTUP_TOOLCHAIN:-1.95.0}" rustc --version >/dev/null 2>&1 &&
        rustup component list --toolchain "${RUSTUP_TOOLCHAIN:-1.95.0}" --installed | grep -q '^rustfmt-' &&
        rustup component list --toolchain "${RUSTUP_TOOLCHAIN:-1.95.0}" --installed | grep -q '^clippy-' &&
        rustup target list --toolchain "${RUSTUP_TOOLCHAIN:-1.95.0}" --installed | grep -qx 'wasm32-unknown-unknown'
}
if ((check)); then
    failed=0
    if ((${#missing[@]})); then printf 'Missing system packages: %s\n' "${missing[*]}"; failed=1; fi
    if ! node_ready; then echo 'Missing Node.js 22+ and npm'; failed=1; fi
    if ! rust_ready; then echo 'Missing Rust toolchain/components/wasm target'; failed=1; fi
    if ((!skip_auth)); then
        if ! command -v gh >/dev/null || ! gh auth status --hostname github.com >/dev/null 2>&1; then
            echo 'GitHub authentication needed'; failed=1
        fi
    fi
    if ((failed)); then echo 'Run ./craft setup to install/configure prerequisites'; else echo 'Prerequisites ready'; fi
    exit "$failed"
fi
mkdir -p "$root/.build"
exec 9>"$root/.build/craft.lock"
flock -n 9 || { echo 'Another craft/setup run is active' >&2; exit 1; }
if ((${#missing[@]})); then
    admin=()
    if ((EUID != 0)); then
        command -v sudo >/dev/null || { echo 'Installing system packages requires sudo or root' >&2; exit 1; }
        admin=(sudo)
    fi
    "${admin[@]}" apt-get update
    "${admin[@]}" apt-get install -y --no-install-recommends "${missing[@]}"
fi
if ! command -v rustup >/dev/null; then
    installer=$(mktemp)
    trap 'rm -f -- "$installer"' EXIT
    curl --proto '=https' --tlsv1.2 --fail --show-error --location https://sh.rustup.rs -o "$installer"
    sh "$installer" -y --profile minimal --default-toolchain none
    rm -f -- "$installer"
    trap - EXIT
fi
rustup toolchain install "${RUSTUP_TOOLCHAIN:-1.95.0}" --profile minimal --component rustfmt --component clippy
rustup target add --toolchain "${RUSTUP_TOOLCHAIN:-1.95.0}" wasm32-unknown-unknown
if ! node_ready; then
    case $(uname -m) in
        x86_64) arch=x64;;
        aarch64|arm64) arch=arm64;;
        *) echo 'Automatic Node installation supports Linux x86_64 and arm64 only' >&2; exit 1;;
    esac
    version=v24.11.0
    archive=node-$version-linux-$arch.tar.xz
    mkdir -p "$root/.build/tools"
    download=$(mktemp -d "$root/.build/tools/node-install-XXXXXX")
    trap 'rm -rf -- "$download"' EXIT
    curl --proto '=https' --tlsv1.2 --fail --show-error --location "https://nodejs.org/dist/$version/$archive" -o "$download/$archive"
    curl --proto '=https' --tlsv1.2 --fail --show-error --location "https://nodejs.org/dist/$version/SHASUMS256.txt" -o "$download/SHASUMS256.txt"
    (cd "$download"; awk -v file="$archive" '$2 == file {print; found=1} END {if (!found) exit 1}' SHASUMS256.txt > checksum
        sha256sum --check checksum)
    mkdir "$download/runtime"
    tar -xJf "$download/$archive" --strip-components=1 -C "$download/runtime"
    # Keep any previous local runtime until the replacement is fully verified.
    if [[ -e $root/.build/tools/node ]]; then
        mv "$root/.build/tools/node" "$download/previous"
    fi
    mv "$download/runtime" "$root/.build/tools/node"
    hash -r
    rm -rf -- "$download"
    trap - EXIT
fi
if ((!skip_auth)); then
    if ! gh auth status --hostname github.com >/dev/null 2>&1; then
        gh auth login --hostname github.com --git-protocol https --web
    fi
    gh auth setup-git --hostname github.com
fi
if ! node_ready || ! rust_ready; then
    echo 'Setup validation failed: Node or Rust prerequisites are still unavailable' >&2
    exit 1
fi
echo 'Setup complete. Run ./craft pull to discover and synchronize Craft forks.'
