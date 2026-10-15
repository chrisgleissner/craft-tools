#!/usr/bin/env bash
# Install launch entries and pin ArtCraft Launcher beside PhotoCraft on KDE.
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
python3 - "$root" <<'PY'
from pathlib import Path
from datetime import datetime, timezone
import configparser
import os
import shutil
import sys
root = Path(sys.argv[1])
apps = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share'))) / 'applications'
apps.mkdir(parents=True, exist_ok=True)
backups = root / '.logs' / ('desktop-backup-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f'))
def escape_string(value):
    # Desktop-entry string escaping happens before Exec argument parsing.
    return str(value).replace('\\', '\\\\').replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
def quote(value):
    quoted = ''.join('\\' + char if char in '\\"$`' else char for char in str(value))
    return escape_string('"' + quoted.replace('%', '%%') + '"')
if any(char in str(root) for char in '=%'):
    # '=' is forbidden by the spec; GLib rejects '%' in executable paths even
    # when encoded as '%%'. Refuse instead of installing an unusable shortcut.
    raise SystemExit('Desktop shortcut paths cannot contain an equals sign or percent sign')
entries = [
    ('ai.storyteller.photocraft', 'PhotoCraft', 'photocraft', 'photocraft/assets/app-icon/hicolor/256x256/apps/ai.storyteller.photocraft.png', 'Graphics;2DGraphics;RasterGraphics;Photography;', 'ai.storyteller.photocraft', ' %F'),
    ('ai.storyteller.artcraft-launcher', 'ArtCraft Launcher', 'craft-launcher', 'craft-launcher/assets/app-icon/artcraft-launcher-1024.png', 'Utility;PackageManager;', 'ai.storyteller.artcraft-launcher', ''),
]
for ident, name, app, icon, categories, wmclass, args in entries:
    target = apps / (ident + '.desktop')
    if target.exists():
        backups.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, backups / target.name)
    config = configparser.ConfigParser(interpolation=None)
    config.optionxform = str
    if target.exists():
        config.read(target)
    if not config.has_section('Desktop Entry'):
        config.add_section('Desktop Entry')
    entry = config['Desktop Entry']
    entry.update(Type='Application', Name=name, Exec=f'{quote(root / "run-craft.sh")} {app}{args}',
                 Icon=escape_string(root / icon), Terminal='false', StartupNotify='false',
                 StartupWMClass=wmclass, Categories=categories)
    if app == 'photocraft':
        entry.setdefault('GenericName', 'Image Editor')
        entry.setdefault('Comment', 'Edit photos and layered PSD documents')
    if 'TryExec' in entry:
        entry['TryExec'] = escape_string(root / 'run-craft.sh')
    with target.open('w') as stream:
        config.write(stream, space_around_delimiters=False)
    print(target)
PY
if command -v update-desktop-database >/dev/null; then update-desktop-database "${XDG_DATA_HOME:-$HOME/.local/share}/applications"; fi
if [[ ${XDG_CURRENT_DESKTOP:-} == *KDE* ]] && command -v qdbus >/dev/null; then
    qdbus org.kde.plasmashell /PlasmaShell org.kde.PlasmaShell.evaluateScript '
var ps=panels();
var photo="applications:ai.storyteller.photocraft.desktop";
var launcher="applications:ai.storyteller.artcraft-launcher.desktop";
for(var i=0;i<ps.length;i++){
  var ws=ps[i].widgets();
  for(var j=0;j<ws.length;j++){
    if(ws[j].type!="org.kde.plasma.icontasks" && ws[j].type!="org.kde.plasma.taskmanager") continue;
    ws[j].currentConfigGroup=["General"];
    var raw=ws[j].readConfig("launchers").toString();
    var old=raw.split(","); var next=[];
    for(var k=0;k<old.length;k++) if(old[k]!==launcher) next.push(old[k]);
    var at=next.indexOf(photo);
    if(at<0) continue;
    next.splice(at+1,0,launcher);
    ws[j].writeConfig("launchers",next.join(","));
    print("Launcher pinned beside PhotoCraft on panel "+ps[i].id);
  }
}'
fi
