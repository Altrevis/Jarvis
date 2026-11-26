"""
How many tokens each engine spent, per day — so "use fewer tokens" is a number.

Every engine that answers a text call reports what it was billed for:
    claude          one-shot `claude -p` calls (core/claude.ask)
    claude-agent    agent runs: tasks, documents, projects (core/claude.agent)
    gateway         the free gateway, OmniRoute or FreeLLMAPI (core/gateway)
    gemini          REST text models (core/gemini; the Live rung reports nothing)
    gemini-live     the voice conversation itself, one entry per turn (main.py)

Kept in config/usage.json, one entry per day, the last two weeks only. It is
written on every call, which is a few times a minute at most; the write is
atomic, so a crash mid-write leaves yesterday's file rather than half of one.
Never raises: counting tokens must not be what breaks a reply.

/COMPACT
    Every token counted here (input and output; cache reads are not, they
    cost a fraction) also runs up a second counter, in config/compact.json.
    Each time it passes another `compact_every()` tokens — 400 000 unless
    "compact_every_tokens" in config/api_keys.json says otherwise, 0 to never
    ask — the notifier main.py registers is called, and the window asks
    whether to /compact. Compacting (main.py) resets the counter; "later"
    leaves it running, so the next question comes 400 000 tokens on.
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
_COMPACT_FILE = _BASE / "config" / "compact.json"
_KEY_FILE = _BASE / "config" / "api_keys.json"
_KEEP_DAYS = 14
COMPACT_EVERY = 400_000
_lock = threading.Lock()
_compact_notifier = None

# Display order and names for the settings panel.
_LABELS = (("claude", "Claude"), ("claude-agent", "Claude tasks"),
           ("gateway", "Gateway"), ("gemini", "Gemini"), ("gemini-live", "Voice"))


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.stem}-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1)
        os.replace(tmp, path)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


def _load() -> dict:
    return _read(_FILE)


def _save(data: dict) -> None:
    _write(_FILE, data)


def record(engine: str, tokens_in: int = 0, tokens_out: int = 0,
           cached: int = 0) -> None:
    """Add one call to today's count for `engine`."""
    day = _dt.date.today().isoformat()
    due = 0
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
            due = _count_for_compact(max(0, int(tokens_in or 0)) + max(0, int(tokens_out or 0)))
    except Exception as e:
        print(f"[Usage] could not record {engine}: {e}")
    # Outside the lock: the notifier reaches the window, and nothing it does
    # should be able to hold up the next call being counted.
    if due and _compact_notifier is not None:
        try:
            _compact_notifier(due)
        except Exception as e:
            print(f"[Usage] compact notifier failed: {e}")


# ── /compact ─────────────────────────────────────────────────────────────────

def compact_every() -> int:
    """Tokens between two /compact questions; 0 never asks."""
    try:
        n = int(_read(_KEY_FILE).get("compact_every_tokens", COMPACT_EVERY))
    except (TypeError, ValueError):
        n = COMPACT_EVERY
    return 0 if n <= 0 else max(10_000, n)


def _count_for_compact(tokens: int) -> int:
    """Add to the count since the last /compact; the new total when it has
    just passed another multiple of compact_every(), else 0. Under _lock."""
    every = compact_every()
    state = _read(_COMPACT_FILE)
    since = int(state.get("since") or 0) + tokens
    asked = int(state.get("asked") or 0)
    due = 0
    if every and since >= (asked + 1) * every:
        asked, due = since // every, since
    state.update(since=since, asked=asked)
    _write(_COMPACT_FILE, state)
    return due


def set_compact_notifier(fn) -> None:
    """Register fn(tokens_since_last_compact), called when a /compact is due.
    It runs on whichever thread counted the call that crossed the line."""
    global _compact_notifier
    _compact_notifier = fn


def compact_done() -> None:
    """A /compact just happened: the count starts over."""
    try:
        with _lock:
            _write(_COMPACT_FILE, {"since": 0, "asked": 0,
                                   "last": _dt.datetime.now().isoformat(timespec="seconds")})
    except Exception as e:
        print(f"[Usage] could not reset the /compact count: {e}")


def compact_status() -> dict:
    """{"since": tokens since the last /compact, "every": …, "last": ISO time or ''}."""
    state = _read(_COMPACT_FILE)
    return {"since": int(state.get("since") or 0), "every": compact_every(),
            "last": str(state.get("last") or "")}


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


def compact_line() -> str:
    """'Since the last /compact — 123.4k tok (asks every 400.0k)' for the settings panel."""
    st = compact_status()
    every = f"asks every {_k(st['every'])}" if st["every"] else "never asks"
    return f"Since the last /compact — {_k(st['since'])} tok ({every}; type /compact anytime)"
