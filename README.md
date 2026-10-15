# Craft workspace

`craft.sh` updates every sibling Git fork from its `upstream` default branch and
pushes that branch to `origin`, then builds the requested desktop apps and their
CLI companions. The default app is PhotoCraft.

```bash
./craft.sh                                      # update all forks; build PhotoCraft
./craft.sh photocraft vectorcraft               # build an explicit set
./craft.sh --all                                # build all registered desktop apps
./craft.sh --all --release                      # optimized binaries
./craft.sh --update-only                        # only synchronize forks
./craft.sh --no-update craft-launcher           # build without network Git updates
./craft.sh --no-push photocraft                  # update locally without pushing
./craft.sh --list
./run-craft.sh photocraft
./run-craft.sh craft-launcher
./install-shortcuts.sh                          # install/update KDE shortcuts
python3 -m unittest discover -s tests -v
xvfb-run -a -s '-screen 0 1440x1000x24' dbus-run-session -- python3 tests/smoke_apps.py
```

Updates use fast forwards, preserve feature branches, and refuse dirty checkouts
or divergent default branches. They do not rebase or overwrite local work. Builds
use each current checkout, so a feature branch is built as checked out even when
its default branch has just been updated. A failed stage is logged and produces a
nonzero final status; independent apps still run. Review `.logs/` for details.
Completed runs record their result in `.logs/<run>/exit-status`.
Concurrent tool runs are refused with a lock. Build outputs share `.build/target`
to reuse dependencies; `bin/` points to each last successful build. Scripts and
binary symlinks can move with this directory; rerun `install-shortcuts.sh` after a
move so KDE's absolute desktop-entry paths follow it.
The shortcut installer refuses workspace paths containing `%` or `=` because
desktop launchers cannot reliably resolve these executable paths.

Requires Bash 4+, Git, flock, tee, rustup with Rust 1.95.0, and the system libraries
required by each app. `RUSTUP_TOOLCHAIN` overrides the Rust toolchain; `--jobs N`
controls Cargo jobs (default 4). The dev profile is the default; debug symbols and
incremental builds are disabled to keep this multi-app target directory smaller.
Explicit `CARGO_PROFILE_DEV_DEBUG` and `CARGO_INCREMENTAL` values take precedence.
When present, the sibling `craft-fonts` checkout is used unless `CRAFT_FONTS_DIR`
is already set. Tauri apps also need Node/npm and WebKit/GTK development packages.
The script builds their frontend before embedding it in the Rust binary; it does
not require a globally installed Nx or Tauri CLI and does not create installers.

`artcraft` selects the original Tauri app; `artcraft-native` selects its separate
native Rust app. `craft-launcher` selects the `artcraft-launcher` package/binary.
`craft-repo-status-app` selects the `craft-status-app` package. Shared libraries,
fonts, assets, CI repositories, corpora and backend services are synchronized as
repos, but are not standalone desktop app build targets. `placeholder-artcraft` is an
incomplete historical snapshot: its desktop crate and 100 workspace members are
absent, so it is synchronized without attempting to reconstruct missing source. Browser/server variants
are outside this desktop build tool's app selection.

GitHub does not allow forks of repositories with no Git content. AniCraft and
crafthub were empty when inspected, so their forks could not be created. They are
not silently treated as buildable apps.

The startup checks use an isolated X display and temporary HOME/XDG data for each
app, then verify and capture its rendered window. Evidence is saved under `.logs/`.
They need Xvfb, dbus-run-session, xwininfo, xprop and ImageMagick import/identify.
They test startup and rendering; they do not prove every editing operation or GPU
behavior on other platforms.

## Restore the workspace

Clone this tooling repository as the workspace root (for example `~/dev/craft`).
Install the prerequisites above and authenticate GitHub CLI with `gh auth login`.
`repositories.txt` records the 24 nonempty upstream repositories used by this
workspace as of 2026-10-15. To fork or reuse your forks and clone missing checkouts,
run from the workspace root:

```bash
while IFS= read -r repo; do
    if [ ! -e "$repo" ]; then
        gh repo fork "storytold/$repo" --clone --remote || break
    fi
done < repositories.txt
./craft.sh --all
./install-shortcuts.sh
```

Existing directories are left in place. Each checkout needs `origin` pointing to
your fork and `upstream` pointing to the storytold repository; verify with
`git -C photocraft remote -v` before updating. The inventory is a dated snapshot;
new upstream apps require checking their build recipe before registering them.
The tooling repository itself is updated with `git pull --ff-only` at the root;
`craft.sh` synchronizes the child repositories.

## Repository contents and checks

Only the orchestration scripts, repository inventory, documentation, and tests
are versioned. The root `.gitignore` uses an allowlist to keep app checkouts,
binaries, dependency caches, desktop backups, and runtime logs outside Git.
Local validation reports are also excluded. Changes to this allowlist should be
reviewed before adding any new paths.

```bash
python3 -m unittest discover -s tests -v
shellcheck craft.sh run-craft.sh install-shortcuts.sh
```

Offline tests use disposable Git repositories and fake Cargo/npm commands.
The separate Xvfb smoke command above exercises real built binaries. Its screenshot
color check is a startup heuristic; inspect the saved images when validating a
new app or frontend change. Probe subprocesses have bounded timeouts, and a failed
app is recorded without skipping the remaining apps.

Shortcut path escaping follows the [desktop entry specification](https://specifications.freedesktop.org/desktop-entry/latest/exec-variables.html).
