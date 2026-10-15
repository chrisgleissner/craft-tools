# Craft Tools

**Discover, update, build, and launch the Craft desktop apps from one workspace.**

[![Tests](https://github.com/chrisgleissner/craft-tools/actions/workflows/test.yml/badge.svg)](https://github.com/chrisgleissner/craft-tools/actions/workflows/test.yml)
[![Platform](https://img.shields.io/badge/platform-Linux-blue)](#setup)
[![Runtime](https://img.shields.io/badge/runtime-Bash%204%2B%20%7C%20Python%203.10%2B-blue)](#setup)
[![Upstream](https://img.shields.io/badge/upstream-storytold%20Craft-blue)](https://github.com/storytold)

This is an independent build companion for the **[Craft projects published by
storytold](https://github.com/storytold?tab=repositories&q=craft)**, including
[PhotoCraft](https://github.com/storytold/photocraft),
[VectorCraft](https://github.com/storytold/vectorcraft), and
[Craft Launcher](https://github.com/storytold/craft-launcher).
The apps and their source code live upstream. This repository contains the scripts
that manage your forks and local builds; it is not an official Craft distribution.

## Quick start

Check out the **v0.1.0** release using your GitHub access, then run:

```bash
git clone --branch v0.1.0 --depth 1 \
    https://github.com/chrisgleissner/craft-tools.git ~/dev/craft
cd ~/dev/craft
./craft setup                  # install prerequisites; sign in to GitHub if needed
./craft pull                   # discover, fork, clone, and update all Craft repos
./craft                        # build PhotoCraft (the default)
./run-craft                    # launch PhotoCraft
```

Run the setup command without `sudo`; it requests elevated access only for system packages.

### Release archive

Each version tag runs the tests and publishes a ready-to-extract source archive
with a checksum on the [Releases page](https://github.com/chrisgleissner/craft-tools/releases).
If you already use GitHub CLI, you can download and verify it with:

```bash
gh release download v0.1.0 --repo chrisgleissner/craft-tools \
    --pattern craft-tools-v0.1.0.tar.gz --pattern SHA256SUMS
sha256sum --check SHA256SUMS
tar -xzf craft-tools-v0.1.0.tar.gz
cd craft-tools-v0.1.0
./craft setup
./craft pull
./craft
./run-craft
```

The archive includes executable commands, helpers, docs, and tests. Apps and
dependencies are downloaded by `setup` and `pull`; prebuilt app binaries are not
included. To upgrade an archive installation, unpack the next release separately.

## Setup

`./craft setup` automates setup on **Ubuntu/Debian systems with apt**. Run it as
your normal user; it uses `sudo` only when system packages need installing.

It installs:

- Compilers, Git, GitHub CLI, Python, ShellCheck, and native build libraries.
- GTK/WebKit dependencies for Tauri apps and Xvfb/ImageMagick for startup tests.
- Rust **1.95.0**, with rustfmt, Clippy, and the WebAssembly target.
- Node.js **24.11.0** and npm when no working Node 22+ runtime is available.
  The downloaded archive is checked against Node's published SHA-256 checksums.

Rust uses your user installation. An automatically installed Node runtime stays
inside `.build/tools/node` and is used by `craft`; system Node is left in place.
`RUSTUP_TOOLCHAIN` can select a different Rust toolchain.

Setup starts `gh auth login` when needed and configures Git's GitHub credentials.
Complete GitHub's browser authorization when prompted. Existing authentication is
reused; credentials are managed by GitHub CLI and are never stored in this repo.
For unattended provisioning, `./craft setup --no-auth` installs prerequisites
without requesting or modifying credentials. Configure authentication before
running `craft pull`.

To check an existing machine without installing or changing anything:

```bash
./craft setup --check
```

## Commands

| Command | What it does |
| --- | --- |
| `./craft pull` | Discover upstream Craft repos, fork/clone missing ones, update them all |
| `./craft` | Update existing forks and build PhotoCraft |
| `./craft photocraft vectorcraft` | Update existing forks and build the named apps |
| `./craft --all` | Update existing forks and build all registered desktop targets |
| `./craft --all --release` | Build all registered targets with the release profile |
| `./craft --update-only` | Update existing checkouts without discovering or building |
| `./craft --no-update craft-launcher` | Build from the current checkout without Git updates |
| `./craft --no-push` | Update locally and build PhotoCraft without pushing default branches |
| `./craft --list` | List registered desktop targets |
| `./run-craft craft-launcher` | Launch the latest successful launcher build |
| `./install-shortcuts.sh` | Install shortcuts; pin launcher beside PhotoCraft on KDE |

Use `--jobs N` to control Cargo parallelism (default **4**). `run-craft` accepts an
app name followed by arguments to pass through, for example
`./run-craft photocraft 'photo with spaces.png'`.

### How discovery works

`craft pull` reads **every page** of the live
[storytold repository listing](https://github.com/storytold?tab=repositories&q=craft).
It selects names containing `craft`, ignoring case, including shared libraries,
assets, services, and archived repositories.

For each match, it reuses a valid checkout or creates/reuses your personal fork
and clones it with `origin` pointing to your fork and `upstream` to storytold.
It then updates default branches using fast forwards. Run the same command later
to pick up newly published repositories; no inventory edit is needed.

Empty repositories are reported and retried on the next run. Existing files,
folders, or checkouts with conflicting remotes are reported and left unchanged.
A failed repository does not prevent other valid repositories from being handled.
An API failure returns a failure; it does not silently use an old inventory.

`craft pull --no-push` skips pushing default branches. It still creates missing
forks, because this workspace builds from your own forks.

**Discovery and build registration are separate.** New repos are downloaded and
updated automatically. New desktop apps need a verified build recipe before they
appear in `craft --list` or `craft --all`. `repositories.txt` is a historical
snapshot, not the source of discovery.

### How updates protect local work

Updates preserve your checked-out feature branch and refuse dirty checkouts or
divergent default branches. They use no resets, rebases, force pushes, or stashes.
Builds use the currently checked-out branch. Independent failures are collected;
the command returns a nonzero status if any stage or log writer fails.

## Workspace layout

```text
craft/                         # this tooling repository
├── craft                      # setup, discovery, update, and build command
├── run-craft                  # app launcher
├── install-shortcuts.sh
├── scripts/                   # discovery and prerequisite helpers
├── tests/
├── photocraft/                # independent fork checkout (ignored by this repo)
├── craft-launcher/            # independent fork checkout
├── ...                        # other discovered Craft repos
├── bin/                       # links to the latest successful builds
├── .build/                    # shared Cargo output and local Node runtime
└── .logs/                     # per-run logs, status, and startup screenshots
```

For a branch checkout, update the tooling with `git pull --ff-only` at the root.
The versioned quick start checks out a fixed tag; use another release checkout to
upgrade it. `craft` updates child app repositories. The Git allowlist excludes app sources, credentials,
builds, caches, logs, desktop backups, and local validation reports.

## Build details

- PhotoCraft is the default. `craft-launcher` builds `artcraft-launcher`;
  `craft-repo-status-app` builds `craft-status-app`.
- `artcraft` builds the original Tauri app; `artcraft-native` builds the separate
  native app from the same checkout. Tauri frontends are built and embedded.
- Desktop and available CLI companions build together, using locked dependencies
  and the shared `.build/target` directory.
- Dev builds disable debug symbols and incremental compilation by default.
  `CARGO_PROFILE_DEV_DEBUG` and `CARGO_INCREMENTAL` override these defaults.
- A sibling `craft-fonts` checkout supplies fonts unless `CRAFT_FONTS_DIR` is set.
- Support repos are synchronized without being treated as desktop targets.
  `placeholder-artcraft` is an incomplete historical snapshot, so it is sync-only.
  Browser and backend services are outside the desktop build selection.

Runs write `.logs/<run>/exit-status` and separate logs for each stage. Concurrent
build, pull, and setup runs are refused with a shared lock.

After moving the workspace or upgrading from the old `run-craft.sh` command,
rerun `./install-shortcuts.sh`. It preserves custom desktop fields and backs up
existing entries. Workspace paths containing `%` or `=` are unsupported by the
shortcut installer; its escaping follows the
[desktop entry specification](https://specifications.freedesktop.org/desktop-entry/latest/exec-variables.html).

## Tests and CI

GitHub Actions runs **the complete tooling regression suite, ShellCheck, and a
fresh Ubuntu prerequisite installation on every push and pull request**, with no
credentials or cloned apps required.
Tests use disposable Git repositories and fake GitHub, Cargo, package-manager,
and download commands. The desktop-entry test also launches a fake app through GIO.

Run the same checks locally:

```bash
python3 -m unittest discover -s tests -v
shellcheck craft run-craft install-shortcuts.sh scripts/*.sh
```

To test **real built apps** separately on an isolated Linux display:

```bash
xvfb-run -a -s '-screen 0 1440x1000x24' dbus-run-session -- \
    python3 tests/smoke_apps.py
```

Pass app names to test a subset. The harness uses temporary user data, checks for
a visible app-owned window, captures it, and terminates its process group. Inspect
the saved screenshots: the color check is a rendering heuristic. These checks
cover startup, not every editing operation, physical GPU, or other platforms.
