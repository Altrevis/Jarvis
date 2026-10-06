"""
Long jobs a tool starts now and finishes later.

A Live tool call holds the conversation until it returns, so anything that
takes a minute — a document, a video, a skill, an agent task — returns at once
with a status line and finishes here, on a worker thread. The task bar shows it
running for as long as it really runs (the tool's own entry ends the moment it
returns), and when it is done the assistant is told with a [TASK_DONE] message
and says it in its own words, in the user's language.
"""
from __future__ import annotations

import itertools
import threading
import traceback
from typing import Callable

_ids = itertools.count(1)


def _call(player, method: str, *args) -> None:
    fn = getattr(player, method, None) if player is not None else None
    if fn is None:
        return
    try:
        fn(*args)
    except Exception:
        pass


def start(player, label: str, work: Callable[[Callable[[str], None]], str]) -> None:
    """Run `work(progress)` on a thread.

    `progress(text)` writes one line to the activity log. `work` returns what
    the assistant should tell the user when it is done (English, an instruction
    rather than a script); raising means the job failed, and the user is told
    that instead."""
    job_id = f"job-{next(_ids)}"
    _call(player, "task_start", job_id, label)

    def progress(text: str) -> None:
        _call(player, "write_log", f"SYS: {label.split(' — ')[0]} · {text}")

    def runner() -> None:
        ok = True
        try:
            instruction = work(progress)
        except Exception as e:                                  # noqa: BLE001
            ok = False
            traceback.print_exc()
            instruction = (f"{label} failed: {str(e)[:240]}. Tell the user in one "
                           f"short sentence, and what they could try instead if "
                           f"it is obvious.")
        _call(player, "task_end", job_id, ok)
        if instruction:
            _call(player, "request_say", f"[TASK_DONE] {instruction}")

    threading.Thread(target=runner, daemon=True, name=job_id).start()
