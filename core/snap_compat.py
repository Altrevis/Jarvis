"""
Snap environment cleanup for Linux, for when JARVIS is started from inside a snap.

The snap build of VS Code (and other snapped apps that launch processes) exports
its own runtime into every child: GTK_PATH, GTK_EXE_PREFIX, GIO_MODULE_DIR,
GSETTINGS_SCHEMA_DIR and the like all point into /snap/<app>/. Launched from its
integrated terminal, Qt's GTK3 platform theme loads the system GTK, which then
loads the snap's older GTK modules. Those ask the host's gnome-settings-daemon
schema for an 'antialiasing' key that GNOME 46 removed, and GLib aborts the whole
process:

    GLib-GIO-ERROR **: Settings schema 'org.gnome.settings-daemon.plugins.xsettings'
    does not contain a key named 'antialiasing'

`apply()` puts back the host's own values before Qt starts. It must run before
QApplication is created. Programs JARVIS launches later (the browser,
Playwright's Chromium, xdg-open) inherit the cleaned environment too.
"""
import os
import sys

# Search paths a snap launcher points at its own runtime. None of them is set by
# a normal desktop session, so dropping a snap-provided value restores the
# host's default.
_SNAP_VARS = (
    "GTK_PATH", "GTK_EXE_PREFIX", "GTK_IM_MODULE_FILE",
    "GIO_MODULE_DIR", "GSETTINGS_SCHEMA_DIR",
    "GDK_PIXBUF_MODULE_FILE", "GDK_PIXBUF_MODULEDIR",
    "LOCPATH",
)

# VS Code's snap saves each variable it overrides as <NAME>_VSCODE_SNAP_ORIG.
_ORIG_SUFFIX = "_VSCODE_SNAP_ORIG"


def apply() -> None:
    if not sys.platform.startswith("linux"):
        return
    # No early return on a missing $SNAP: VS Code strips SNAP* from its terminal
    # environment but leaves GTK_PATH and the rest in place, so the leaked values
    # themselves are the only reliable sign.
    snap = os.environ.get("SNAP")
    if snap and sys.executable.startswith(snap):
        return       # JARVIS itself is the snap: its runtime is the right one

    for name in _SNAP_VARS:
        if "/snap/" in os.environ.get(name, ""):
            del os.environ[name]

    for key, value in list(os.environ.items()):
        if key.endswith(_ORIG_SUFFIX):
            name = key[: -len(_ORIG_SUFFIX)]
            if value:
                os.environ[name] = value
            else:
                os.environ.pop(name, None)
            del os.environ[key]

    # Without a saved copy, at least drop the snap's own XDG_DATA_DIRS entries.
    dirs = os.environ.get("XDG_DATA_DIRS")
    if dirs:
        os.environ["XDG_DATA_DIRS"] = ":".join(d for d in dirs.split(":") if "/snap/" not in d)
