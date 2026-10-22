"""
How many tokens each engine spent, per day — so "use fewer tokens" is a number.

Every engine that answers a text call reports what it was billed for:
    claude          one-shot `claude -p` calls (core/claude.ask)
    claude-agent    agent runs: tasks, documents, projects (core/claude.agent)
    gateway         the free gateway, OmniRoute or FreeLLMAPI (core/gateway)
    gemini          REST text models (core/gemini; the Live rung reports nothing)

Kept in config/usage.json, one entry per day, the last two weeks only. It is
written on every call, which is a few times a minute at most; the write is
atomic, so a crash mid-write leaves yesterday's file rather than half of one.
Never raises: counting tokens must not be what breaks a reply.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sys
import tempfile
import threading
from pathlib import Path

if getattr(sys, "frozen", False):
    _BASE = Path(sys.executable).parent
else:
    _BASE = Path(__file__).resolve().parent.parent

_FILE = _BASE / "config" / "usage.json"
_KEEP_DAYS = 14
_lock = threading.Lock()

# Display order and names for the settings panel.
_LABELS = (("claude", "Claude"), ("claude-agent", "Claude tasks"),
           ("gateway", "Gateway"), ("gemini", "Gemini"))


def _load() -> dict:
    try:
        data = json.loads(_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save(data: dict) -> None:
    _FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(_FILE.parent), prefix=".usage-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1)
        os.replace(tmp, _FILE)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


def record(engine: str, tokens_in: int = 0, tokens_out: int = 0,
           cached: int = 0) -> None:
    """Add one call to today's count for `engine`."""
    day = _dt.date.today().isoformat()
    try:
        with _lock:
            data = _load()
            entry = data.setdefault(day, {}).setdefault(
                engine, {"calls": 0, "in": 0, "out": 0, "cached": 0})
            entry["calls"] += 1
            entry["in"] += max(0, int(tokens_in or 0))
            entry["out"] += max(0, int(tokens_out or 0))
            entry["cached"] = entry.get("cached", 0) + max(0, int(cached or 0))
            for old in sorted(data)[:-_KEEP_DAYS]:
                del data[old]
            _save(data)
    except Exception as e:
        print(f"[Usage] could not record {engine}: {e}")


def day(date: str = "") -> dict:
    """{engine: {"calls", "in", "out", "cached"}} for one day (today by default)."""
    return _load().get(date or _dt.date.today().isoformat(), {})


def _k(n: int) -> str:
    return f"{n / 1000:.1f}k" if n >= 1000 else str(n)


def summary_line(date: str = "") -> str:
    """One line for the settings panel, e.g.
    'Today — Claude 12 calls · 31.2k tok   Gateway 40 calls · 9.8k tok'."""
    counts = day(date)
    parts = []
    for key, label in _LABELS:
        e = counts.get(key)
        if e and e.get("calls"):
            parts.append(f"{label} {e['calls']} calls · {_k(e['in'] + e['out'])} tok")
    return ("Today — " + "   ".join(parts)) if parts else "Today — no text calls yet"
