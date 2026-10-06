"""
The user's standard folders, under the names their system actually uses.

On a French Ubuntu the Desktop is ~/Bureau, Downloads is ~/Téléchargements and
Pictures is ~/Images. Those names live in ~/.config/user-dirs.dirs — the
XDG_*_DIR environment variables the old code read are almost never exported to
a normal session — so "desktop" used to resolve to a ~/Desktop that does not
exist on this machine.
"""
from __future__ import annotations

import os
import platform
import re
from pathlib import Path

_KEYS = {
    "desktop":   ("XDG_DESKTOP_DIR",   "Desktop"),
    "downloads": ("XDG_DOWNLOAD_DIR",  "Downloads"),
    "documents": ("XDG_DOCUMENTS_DIR", "Documents"),
    "pictures":  ("XDG_PICTURES_DIR",  "Pictures"),
    "music":     ("XDG_MUSIC_DIR",     "Music"),
    "videos":    ("XDG_VIDEOS_DIR",    "Videos"),
}

_LINE = re.compile(r'^\s*(XDG_[A-Z]+_DIR)\s*=\s*"?([^"\n]*)"?\s*$')


def _from_user_dirs_file() -> dict[str, str]:
    cfg = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    out: dict[str, str] = {}
    try:
        for line in (cfg / "user-dirs.dirs").read_text(encoding="utf-8").splitlines():
            m = _LINE.match(line)
            if m:
                out[m.group(1)] = m.group(2).replace("$HOME", str(Path.home()))
    except Exception:
        pass
    return out


def user_dir(kind: str) -> Path:
    """Path of 'desktop', 'downloads', 'documents', 'pictures', 'music' or
    'videos'. Falls back to the English name under home when nothing better is
    known, which is also the right answer on Windows and macOS."""
    env_key, english = _KEYS[kind]
    if platform.system() == "Linux":
        val = os.environ.get(env_key) or _from_user_dirs_file().get(env_key, "")
        if val and Path(val).exists():
            return Path(val)
    return Path.home() / english


def jarvis_output_dir(sub: str) -> Path:
    """Where generated files go: <Pictures>/JARVIS/<sub>, created on demand."""
    d = user_dir("pictures") / "JARVIS" / sub
    d.mkdir(parents=True, exist_ok=True)
    return d


def jarvis_documents_dir(sub: str) -> Path:
    """Where generated documents go: <Documents>/JARVIS/<sub>, created on demand."""
    d = user_dir("documents") / "JARVIS" / sub
    d.mkdir(parents=True, exist_ok=True)
    return d


def jarvis_videos_dir(sub: str) -> Path:
    """Where generated videos go: <Videos>/JARVIS/<sub>, created on demand."""
    d = user_dir("videos") / "JARVIS" / sub
    d.mkdir(parents=True, exist_ok=True)
    return d
