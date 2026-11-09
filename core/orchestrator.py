"""
The agent team — a lead plans, specialists work, a reviewer checks.

    request ─► lead       one Claude call without tools turns it into a plan:
                          tasks, each owned by ONE skill space (core/spaces.py),
                          with its deliverables, acceptance criteria and the
                          tasks it depends on
            ─► specialists one fresh Claude Code agent per task — in parallel
                          when independent — each in a run folder holding ONLY
                          the skills of its own space. They share a work folder
                          and hand over through short files (handoffs/T1.md),
                          never through each other's transcripts
            ─► checks     the assistant checks every task itself (handoff
                          written, deliverables there) and sends what is
                          missing back to the specialist, once
            ─► reviewer   one agent reads the handoffs and the deliverables
                          against the acceptance criteria, writes the report
                          and lists issues; each task with an issue gets one
                          short correction run by its own specialist

WHERE A MISSION LIVES
    Documents/JARVIS/agents/<slug>/
        PLAN.md               the plan, as the user can read it
        work/                 every deliverable, and REPORT.md at the end
        handoffs/T1.md ...    what each specialist did, for the next ones
        handoffs/review.json  the reviewer's verdict per task
        .agents/T1-cyber/     a specialist's run folder: its .claude/skills
        .jarvis/mission.json  plan, task states, tokens — the assistant's own

WHY IT SPENDS LITTLE
    - The plan is one call without tools, and a delegation to one specialist
      skips it altogether.
    - The lead is told that every task is an agent run, to use as few as the
      request allows, and never more than "agents_max_tasks" (5).
    - A specialist starts fresh and reads the few handoffs it depends on —
      kilobytes — instead of a transcript replayed on every turn.
    - It sees the skills of its own domain only: every space's skill
      descriptions would otherwise be read on every one of its turns.
    - Specialists and the reviewer run on Sonnet unless the space or the
      config says otherwise ("agents_models", "agents_model",
      "agents_review_model"); only the plan uses the smart tier.
    - Checking is the assistant's, for free. Correction runs are short, are
      handed the exact problems, and happen once. The checks are the
      handoff, the promised deliverables and core/quality's licence and GDPR
      scan of the work folder and the targets, before and after the task:
      only what the task added is sent back.

TWO KINDS OF MISSION
    A mission either improves Jarvis (a target is this repository) or works on
    another project (the work folder, the user's project as a target). Every
    agent is told which, per folder (core/quality.describe); a specialist
    working on Jarvis also gets core/quality.SELF_RULES.
    - A mission with a single task is not reviewed unless asked.

CONCURRENCY
    A mission runs "agents_parallel" specialists at once (2 by default), and
    all missions together never hold more than claude_agent_slots - 1 agent
    slots, so ask_claude, documents and projects always have one left. A
    specialist waiting for a slot waits, rather than failing as a voice
    request would.

NOTHING HERE SPEAKS
    These functions return data. actions/agents.py turns it into what the
    voice model is told.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import tempfile
import threading
import time
import unicodedata
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Callable

from core import claude, quality, spaces
from core.user_dirs import jarvis_documents_dir

_STATE = Path(".jarvis") / "mission.json"

PENDING, RUNNING, DONE, PARTIAL = "pending", "running", "done", "partial"
FAILED, CANCELLED, BLOCKED = "failed", "cancelled", "blocked"
_OK = (DONE, PARTIAL)
_STUCK = (FAILED, CANCELLED, BLOCKED)

_PLAN_TIMEOUT = 150
_FIX_TIMEOUT = 8 * 60
_REVIEW_TIMEOUT = 12 * 60
# How long a specialist queues for an agent slot. A mission is background
# work: waiting for the user's document to finish beats failing.
_SLOT_WAIT = 45 * 60
_MAX_ISSUES = 5

# Every mission together: one agent slot fewer than Claude's own cap.
_MISSION_SLOTS = threading.BoundedSemaphore(max(1, claude.agent_slots() - 1))

_lock = threading.Lock()
_running: dict[str, threading.Event] = {}      # slug -> cancel event
_state_locks: dict[str, threading.Lock] = {}

_STEP_RE = re.compile(r"^\s*`?STEP:\s*(done|partial)\b\s*[—–:-]?\s*(.*?)`?\s*$",
                      re.I | re.M)


# ── Configuration ────────────────────────────────────────────────────────────

def _config() -> dict:
    try:
        from memory.config_manager import load_api_keys
        return load_api_keys() or {}
    except Exception:
        return {}


def _int_cfg(key: str, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(_config().get(key) or default)))
    except (TypeError, ValueError):
        return default


def max_tasks() -> int:
    return _int_cfg("agents_max_tasks", 5, 1, 8)


def parallel() -> int:
    return min(_int_cfg("agents_parallel", 2, 1, 4), max(1, claude.agent_slots() - 1))


def task_timeout() -> float:
    return _int_cfg("agents_task_minutes", 20, 3, 90) * 60.0


def review_by_default() -> bool:
    v = _config().get("agents_review", True)
    return v if isinstance(v, bool) else str(v).strip().lower() not in ("0", "false", "no", "off")


def review_model() -> str:
    return str(_config().get("agents_review_model") or "sonnet")


def planner_model() -> str:
    return str(_config().get("agents_planner_model") or claude.model_for(claude.SMART))


def _assistant_name() -> str:
    try:
        from memory.config_manager import get_assistant_name
        return get_assistant_name()
    except Exception:
        return "JARVIS"


# ── Small helpers ────────────────────────────────────────────────────────────

def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def _slug(text: str) -> str:
    ascii_ = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_.lower()).strip("-")[:40].strip("-")
    return slug or "mission"


def _text(v, limit: int = 4000) -> str:
    return " ".join(str(v).split())[:limit] if isinstance(v, (str, int, float)) else ""


def _strs(v, limit: int = 8, size: int = 400) -> list[str]:
    if isinstance(v, str):
        v = [v]
    if not isinstance(v, list):
        return []
    out = [_text(x, size) for x in v if _text(x, size)]
    return out[:limit]


def _rel_path(raw: str) -> str:
    """A deliverable as a path inside the work folder, or '' when it would
    point outside it."""
    p = str(raw or "").strip().strip("`'\"").replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    p = p.lstrip("/")
    if p.lower().startswith("work/"):
        p = p[5:]
    parts = [x for x in p.split("/") if x not in ("", ".")]
    if not parts or ".." in parts or re.match(r"^[A-Za-z]:", parts[0]) or len(p) > 200:
        return ""
    return "/".join(parts)


def _step_status(text: str) -> tuple[str, str, str]:
    """(status, what remains, the report without its STEP line). A report
    without the line is taken at its word that it finished."""
    found = list(_STEP_RE.finditer(text or ""))
    if not found:
        return DONE, "", (text or "").strip()
    m = found[-1]
    report = (text[:m.start()] + text[m.end():]).strip()
    return m.group(1).lower(), m.group(2).strip(), report


def _lang(state: dict) -> str:
    return state.get("language") or "the language of the user's request"


def _french(state: dict) -> bool:
    return str(state.get("language") or "").lower().startswith(("fr", "fra"))


def _take(sem: threading.BoundedSemaphore, cancel: threading.Event | None,
          wait_s: float = _SLOT_WAIT) -> bool:
    deadline = time.monotonic() + wait_s
    while not (cancel is not None and cancel.is_set()):
        if sem.acquire(timeout=1.0):
            return True
        if time.monotonic() > deadline:
            return False
    return False


# ── Mission state ────────────────────────────────────────────────────────────

def root() -> Path:
    return jarvis_documents_dir("agents")


def load(path: Path) -> dict | None:
    try:
        data = json.loads((path / _STATE).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _save(path: Path, state: dict) -> None:
    state["updated"] = _dt.datetime.now().isoformat()
    target = path / _STATE
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), prefix=".mission-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        os.replace(tmp, target)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


def _state_lock(path: Path) -> threading.Lock:
    with _lock:
        return _state_locks.setdefault(str(path), threading.Lock())


def update(path: Path, change: Callable[[dict], None]) -> dict:
    """Read, change and write the mission state under its lock: specialists
    finish on several threads at once."""
    with _state_lock(path):
        state = load(path) or {}
        change(state)
        _save(path, state)
        return state


def all_missions() -> list[tuple[Path, dict]]:
    out = []
    base = root()
    for d in sorted(base.iterdir()) if base.exists() else ():
        state = load(d) if d.is_dir() else None
        if state:
            out.append((d, state))
    out.sort(key=lambda ps: ps[1].get("updated", ""), reverse=True)
    return out


def find(name: str) -> tuple[Path, dict] | None:
    """The mission a spoken name means. Empty name: the one worked on last."""
    found = all_missions()
    if not found:
        return None
    if not str(name or "").strip():
        return found[0]
    from core.fuzzy_find import Query, score
    q = Query(name)
    best, best_score = None, 0.0
    for path, state in found:
        title = (state.get("plan") or {}).get("title", "")
        s = max(score(q, state.get("name", "")), score(q, path.name), score(q, title))
        if s > best_score:
            best, best_score = (path, state), s
    return best if best_score >= 0.55 else None


def is_running(slug: str) -> bool:
    with _lock:
        return slug in _running


def claim(slug: str) -> threading.Event | None:
    """Mark a mission as running and hand back its cancel event — None when it
    already runs. Claimed by the tool call, before the job thread starts, so
    two quick requests cannot both start it."""
    with _lock:
        if slug in _running:
            return None
        ev = threading.Event()
        _running[slug] = ev
        return ev


def release(slug: str) -> None:
    with _lock:
        _running.pop(slug, None)


def cancel(slug: str) -> bool:
    """Stop a running mission: its agents are killed within a second or two
    and the tasks not started are left for continue."""
    with _lock:
        ev = _running.get(slug)
    if ev is None:
        return False
    ev.set()
    return True


def create(request: str, *, name: str = "", language: str = "", targets=(),
           kind: str = "team", review: bool | None = None) -> tuple[Path, dict]:
    """A new mission folder and its state. Planned later (team) or now
    (delegate: see plan_for_space)."""
    base = _slug(name or request[:60])
    path = root() / base
    n = 2
    while path.exists():
        path = root() / f"{base}-{n}"
        n += 1
    (path / "work").mkdir(parents=True)
    (path / "handoffs").mkdir()
    state = {"name": name.strip() or " ".join(request.split())[:60], "slug": path.name,
             "kind": kind, "request": request.strip(), "language": language.strip(),
             "targets": [str(t) for t in targets], "review": review,
             "created": _now(), "status": "new", "plan": None, "tasks": {},
             "tokens": 0, "notes": []}
    with _state_lock(path):
        _save(path, state)
    return path, state


# ── The plan ─────────────────────────────────────────────────────────────────

_PLAN_SYSTEM = (
    "You are the lead of a team of IT specialist agents. You turn a request into "
    "the smallest plan that gets it done: tasks, each done by ONE specialist. "
    "Output only one JSON object, no prose, no code fence."
)


def _plan_prompt(state: dict, known: list, limit: int) -> str:
    listing = "\n".join(f"- {s.id}: {s.description}" for s in known)
    targets = state.get("targets") or []
    lang = state.get("language") or "the language of the request"
    tgt = ("\n\nTarget folders the team works on (the user's own files):\n"
           + "\n".join(f"- {quality.describe(t)}" for t in targets)) if targets else ""
    return (
        f"Request from the user:\n{state['request']}{tgt}\n\n"
        f"Specialists available (id: what they cover):\n{listing}\n\n"
        f"Rules:\n"
        f"- Every task is a separate agent run that costs time and tokens: use as FEW "
        f"tasks as the request allows. One task is right when one specialist can do it "
        f"all. Never more than {limit}.\n"
        f"- A specialist sees only its own task: its goal, deliverables, acceptance "
        f"criteria and the handoffs of the tasks it depends on. Put every detail of the "
        f"request it needs into its goal.\n"
        f"- deliverables: the files the task must produce, as paths relative to the "
        f"team's shared work folder (e.g. \"security-review.md\", \"docker/Dockerfile\"). "
        f"Changes made inside a target folder are described in the goal, not listed.\n"
        f"- depends_on: ids of earlier tasks whose results this task needs. Tasks without "
        f"a dependency between them run at the same time, so two tasks that write the "
        f"same files must depend on each other.\n"
        f"- acceptance: 1 to 4 short criteria a reviewer can check by reading the files.\n"
        f"- title and summary in {lang}; goals in {lang} or English, whichever keeps the "
        f"user's details exact.\n\n"
        f"JSON shape:\n"
        f'{{"title": "<mission title, max 8 words>", "summary": "<one sentence>", '
        f'"tasks": [{{"id": "T1", "space": "<specialist id>", "title": "<max 10 words>", '
        f'"goal": "<what to do, self-contained>", "deliverables": ["<path>"], '
        f'"depends_on": [], "acceptance": ["<criterion>"]}}]}}'
    )


def _json_of(raw: str):
    raw = (raw or "").strip()
    if "{" not in raw:
        return None
    raw = raw[raw.find("{"): raw.rfind("}") + 1]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _toposort(tasks: list[dict], notes: list[str]) -> list[dict]:
    """Tasks in an order where every dependency comes first — the plan's own
    order whenever it allows. A cycle is broken by dropping the dependencies
    of the first task caught in it."""
    out: list[dict] = []
    done: set[str] = set()
    rest = list(tasks)
    while rest:
        ready = [t for t in rest if all(d in done for d in t["depends_on"])]
        if not ready:
            victim = rest[0]
            dropped = [d for d in victim["depends_on"] if d not in done]
            notes.append(f"{victim['id']}: circular dependency on {', '.join(dropped)} dropped")
            victim["depends_on"] = [d for d in victim["depends_on"] if d in done]
            continue
        for t in ready:
            out.append(t)
            done.add(t["id"])
            rest.remove(t)
    return out


def validate_plan(raw, known: list, limit: int) -> tuple[dict | None, list[str]]:
    """The lead's answer made safe to run: known spaces only, unique ids,
    dependencies on tasks that exist and no cycle, deliverables inside the
    work folder, at most `limit` tasks. (plan or None, notes on what changed)."""
    notes: list[str] = []
    if not isinstance(raw, dict):
        return None, ["the answer was not a JSON object"]
    tasks_in = raw.get("tasks")
    if not isinstance(tasks_in, list) or not tasks_in:
        return None, ["the plan has no tasks"]
    by_id = {s.id: s for s in known}
    tasks: list[dict] = []
    idmap: dict[str, str] = {}
    for i, t in enumerate(tasks_in):
        if not isinstance(t, dict):
            notes.append(f"task {i + 1} is not an object — dropped")
            continue
        title = _text(t.get("title"), 120)
        goal = _text(t.get("goal"))
        if not goal and not title:
            notes.append(f"task {i + 1} has no goal — dropped")
            continue
        asked = _text(t.get("space"), 60)
        sp = by_id.get(asked.lower()) or (spaces.resolve(asked) if asked else None)
        if sp is None or sp.id not in by_id:
            hits = spaces.match(f"{title} {goal}", 1)
            sp = hits[0][0] if hits and hits[0][0].id in by_id else None
            if sp is None:
                notes.append(f"task {i + 1}: no specialist for {asked or 'it'} — dropped")
                continue
            notes.append(f"task {i + 1}: unknown specialist {asked!r}, given to {sp.id}")
        if len(tasks) >= limit:
            notes.append(f"task {i + 1} ({title or goal[:40]}) is beyond the limit of {limit} — dropped")
            continue
        new_id = f"T{len(tasks) + 1}"
        old_id = _text(t.get("id"), 20) or f"T{i + 1}"
        idmap.setdefault(old_id, new_id)
        idmap.setdefault(old_id.upper(), new_id)
        deliverables = []
        for d in _strs(t.get("deliverables"), 10, 200):
            rel = _rel_path(d)
            if rel and rel not in deliverables:
                deliverables.append(rel)
            elif not rel:
                notes.append(f"{new_id}: deliverable {d!r} is outside the work folder — dropped")
        tasks.append({"id": new_id, "space": sp.id, "title": title or goal[:80],
                      "goal": goal or title, "deliverables": deliverables[:8],
                      "acceptance": _strs(t.get("acceptance"), 4, 300),
                      "_deps": _strs(t.get("depends_on"), 8, 20)})
    if not tasks:
        return None, notes + ["no usable task"]
    ids = {t["id"] for t in tasks}
    for t in tasks:
        deps: list[str] = []
        for d in t.pop("_deps"):
            nd = idmap.get(d) or idmap.get(d.upper())
            if nd and nd in ids and nd != t["id"]:
                if nd not in deps:
                    deps.append(nd)
            else:
                notes.append(f"{t['id']}: dependency {d!r} is not a task of the plan — dropped")
        t["depends_on"] = deps
    ordered = _toposort(tasks, notes)
    title = _text(raw.get("title"), 80) or ordered[0]["title"]
    return {"title": title, "summary": _text(raw.get("summary"), 400),
            "tasks": ordered}, notes


def plan_for_space(space, request: str, title: str = "") -> dict:
    """A one-task plan, made locally: a delegation needs no lead."""
    return {"title": title or " ".join(request.split())[:60], "summary": "",
            "tasks": [{"id": "T1", "space": space.id,
                       "title": title or " ".join(request.split())[:80],
                       "goal": request.strip(), "deliverables": [], "acceptance": [],
                       "depends_on": []}]}


def _fallback_plan(state: dict, known: list) -> dict | None:
    hits = spaces.match(state["request"], 1)
    sp = hits[0][0] if hits else next((s for s in known if s.id == "programming"), None)
    sp = sp or (known[0] if known else None)
    return plan_for_space(sp, state["request"]) if sp else None


def set_plan(path: Path, plan: dict, notes: list[str] = (), planner: dict | None = None) -> dict:
    def change(st):
        st["plan"] = plan
        st["tasks"] = {t["id"]: {"status": PENDING} for t in plan["tasks"]}
        st["status"] = "planned"
        st["notes"] = list(st.get("notes") or []) + list(notes)
        if planner:
            st["planner"] = planner
            st["tokens"] = int(st.get("tokens") or 0) + int(planner.get("tokens") or 0)
    state = update(path, change)
    try:
        (path / "PLAN.md").write_text(plan_text(state), encoding="utf-8")
    except OSError:
        pass
    return state


def make_plan(path: Path, progress: Callable[[str], None] = lambda _t: None) -> dict:
    """Ask the lead for a plan, check it, and store it. Falls back to one task
    for the best-matching specialist when no usable plan comes back."""
    state = load(path) or {}
    known = spaces.all_spaces()
    if not known:
        raise RuntimeError("no skill space found in skill_spaces/")
    limit = max_tasks()
    prompt = _plan_prompt(state, known, limit)
    model = planner_model()
    tokens, notes, plan = 0, [], None
    progress(f"planning ({model})")
    for attempt in range(2):
        try:
            res = claude.ask_full(prompt, claude.SMART, system=_PLAN_SYSTEM,
                                  timeout=_PLAN_TIMEOUT, model=model)
        except claude.ClaudeError as e:
            resting = claude.cooling()
            if resting:                  # signed out or over the limit: so is every agent
                raise RuntimeError(f"Claude is unavailable ({resting})") from e
            notes.append(f"the lead could not plan: {str(e)[:160]}")
            break
        tokens += res.tokens_in + res.tokens_out
        plan, why = validate_plan(_json_of(res.text), known, limit)
        if plan is not None:
            notes += why
            break
        prompt += (f"\n\nYour previous answer could not be used ({'; '.join(why)}). "
                   f"Answer again with the JSON object only.")
    if plan is None:
        plan = _fallback_plan(state, known)
        if plan is None:
            raise RuntimeError("no usable plan and no specialist to fall back on")
        notes.append(f"one task for {plan['tasks'][0]['space']}, chosen by keywords")
    return set_plan(path, plan, notes, {"model": model, "tokens": tokens, "at": _now()})


_MARKS = {DONE: "✓", PARTIAL: "~", FAILED: "✕", CANCELLED: "⊘", BLOCKED: "⏸",
          RUNNING: "▸", PENDING: "·"}


def plan_text(state: dict) -> str:
    plan = state.get("plan") or {}
    lines = [plan.get("title") or state.get("name", "")]
    if plan.get("summary"):
        lines.append(plan["summary"])
    lines.append("")
    recs = state.get("tasks") or {}
    titles = {s.id: s.title for s in spaces.all_spaces()}
    for t in plan.get("tasks") or ():
        st = (recs.get(t["id"]) or {}).get("status", PENDING)
        after = f"  (after {', '.join(t['depends_on'])})" if t.get("depends_on") else ""
        lines.append(f"{_MARKS.get(st, '·')} {t['id']} · {titles.get(t['space'], t['space'])} — "
                     f"{t['title']}{after}")
        if t.get("deliverables"):
            lines.append(f"     → {', '.join(t['deliverables'])}")
    return "\n".join(lines)


# ── Running a specialist ─────────────────────────────────────────────────────

def _paths(path: Path) -> tuple[Path, Path]:
    return path / "work", path / "handoffs"


def _task_prompt(path: Path, state: dict, task: dict, space) -> str:
    work, handoffs = _paths(path)
    plan = state.get("plan") or {}
    recs = state.get("tasks") or {}
    by_id = {t["id"]: t for t in plan.get("tasks") or ()}
    titles = {s.id: s.title for s in spaces.all_spaces()}
    tid = task["id"]
    out = [f"You are agent {tid} of the mission \"{plan.get('title', '')}\", as its "
           f"{space.title} specialist."]
    if plan.get("summary"):
        out += ["", f"Mission: {plan['summary']}"]
    out += [f"The user's request, in their words: {state.get('request', '')}",
            "", f"## Your task — {task['title']}", task["goal"]]
    if task.get("deliverables"):
        out += ["", "Deliverables, in the shared work folder:"]
        out += [f"- {work / d}" for d in task["deliverables"]]
    if task.get("acceptance"):
        out += ["", "Acceptance criteria (a reviewer checks them):"]
        out += [f"- {a}" for a in task["acceptance"]]
    deps = [by_id[d] for d in task.get("depends_on") or () if d in by_id]
    if deps:
        out += ["", "Read these handoffs first — the tasks yours builds on:"]
        for d in deps:
            rec = recs.get(d["id"]) or {}
            left = (f" [left partial: {rec.get('remains')}]"
                    if rec.get("status") == PARTIAL and rec.get("remains") else "")
            out.append(f"- {handoffs / (d['id'] + '.md')} — {d['id']} "
                       f"({titles.get(d['space'], d['space'])}): {d['title']}{left}")
    others = [t for t in plan.get("tasks") or () if t["id"] != tid and t not in deps]
    if others:
        out += ["", "The rest of the team (their part is not yours):"]
        out += [f"- {t['id']} ({titles.get(t['space'], t['space'])}): {t['title']}"
                for t in others]
    if state.get("targets"):
        out += ["", "Target folders — the user's own files; change them only as your "
                    "task requires:"]
        out += [f"- {quality.describe(t)}" for t in state["targets"]]
        if any(quality.is_jarvis(t) for t in state["targets"]):
            out += ["", quality.SELF_RULES]
    # Only a run of THIS task writes its handoff or deliverables, and a task that
    # is done never runs again: finding them means an earlier run got that far.
    prev = recs.get(tid) or {}
    started = (handoffs / f"{tid}.md").is_file() or any(
        (work / d).exists() for d in task.get("deliverables") or ())
    if started:
        why = f" ({prev['remains']})" if prev.get("remains") else ""
        out += ["", f"A previous run of this task stopped before the end{why}. Read your "
                    f"handoff and the deliverables that exist, and carry on from there "
                    f"instead of starting over."]
    out += ["", "## Where to write",
            f"- Shared work folder, for every deliverable: {work}",
            f"- Your handoff, when you are done: {handoffs / (tid + '.md')}",
            "- Your current folder only holds your skills: write nothing there.",
            "- Other specialists may work at the same time: touch only your deliverables "
            "and the files your task is about.",
            "", "## Your handoff",
            f"Write {handoffs / (tid + '.md')} — short (under 60 lines), in "
            f"{_lang(state)} — with these sections:",
            "## Done — what you did, 3 to 8 bullets",
            "## Files — every file you created or changed, full paths",
            "## Decisions — the choices you made without the user",
            "## For the next agents — what they must know; open issues",
            "## For the user — what only the user can do (accounts, keys, commands to "
            "run, approvals), or 'Nothing'"]
    return "\n".join(out)


def _specialist_system(state: dict, space) -> str:
    return (
        f"\n\nYou are a specialist agent in a team working for {_assistant_name()}, a "
        f"voice assistant. Nobody can answer questions while you work: make reasonable "
        f"choices, record them in your handoff under Decisions, and finish.\n\n"
        f"{space.role}\n\n"
        f"Use a skill from .claude/skills when one fits; a skill's scripts run as "
        f"`python3 .claude/skills/<skill>/<script>.py` (`python` on Windows).\n"
        f"Keep token use low: read only what your task needs; prefer Grep, Glob and "
        f"partial reads to whole files; never read node_modules, lock files or build "
        f"output; do not re-read a file; do not paste file contents into your messages.\n"
        f"Bash runs only these commands (and their arguments): {space.commands()}. Run "
        f"one at a time, or as `cd \"<folder>\" && <command>`; git only as "
        f"`git -C \"<folder>\" <subcommand>` (`cd ... && git` is refused); never a shell "
        f"loop (`for`, `while`), never a command outside the list. A refused "
        f"command means only that this form is not allowed: use the allowed form or "
        f"another tool (Read, Grep, Glob) and carry on. The assistant checks your "
        f"deliverables after you; a refused command is never a reason to stop or to "
        f"skip a check.\n"
        f"Write text meant for the user in {_lang(state)}. Code, identifiers and commit "
        f"messages: English.\n"
        f"{quality.CODE_RULES}\n"
        f"{quality.LEGAL_RULES}\n"
        f"Your final message is read by the assistant: at most five sentences on what you "
        f"did, then, alone on the last line, `STEP: done` when your task is complete or "
        f"`STEP: partial — <what remains>` when it is not."
    )


def _problems(path: Path, task: dict) -> list[tuple[str, Path]]:
    """What the assistant can see is missing, without asking anyone: the
    handoff, and each deliverable the plan promised. [(kind, file)]"""
    work, handoffs = _paths(path)
    out: list[tuple[str, Path]] = []
    h = handoffs / f"{task['id']}.md"
    try:
        ok = h.is_file() and len(h.read_text(encoding="utf-8", errors="replace").strip()) >= 40
    except OSError:
        ok = False
    if not ok:
        out.append(("handoff", h))
    for d in task.get("deliverables") or ():
        f = work / d
        try:
            empty = not f.exists() or (f.is_file() and f.stat().st_size == 0)
        except OSError:
            empty = True
        if empty:
            out.append(("deliverable", f))
    return out


def _legal_baselines(path: Path, state: dict) -> dict[Path, Counter]:
    """What the licence and GDPR scan finds, before the task runs, in every
    folder it may write in: the shared work folder and the targets — Jarvis
    itself or the user's project."""
    folders = [_paths(path)[0]] + [Path(t) for t in state.get("targets") or () if Path(t).is_dir()]
    return {f: quality.legal_baseline(f) for f in folders}


def _legal_problems(baselines: dict[Path, Counter]) -> list[str]:
    """The licence, copyright and GDPR errors the task added — not what the
    user or earlier tasks left there."""
    out = []
    for folder, before in baselines.items():
        out += [f"in {folder}: {x}" for x in quality.new_legal_errors(folder, before)]
    return out


def _problem_text(kind: str, f: Path) -> str:
    return (f"your handoff {f} is missing or empty" if kind == "handoff"
            else f"the deliverable {f} is missing or empty")


def _snapshot(folder: Path, cap: int = 4000) -> dict[str, float]:
    out: dict[str, float] = {}
    skip = {"node_modules", ".git", ".venv", "venv", "__pycache__", "dist", "build", ".next"}
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = [d for d in dirnames if d not in skip]
        for fn in filenames:
            p = Path(dirpath) / fn
            try:
                out[p.relative_to(folder).as_posix()] = p.stat().st_mtime
            except (OSError, ValueError):
                continue
            if len(out) >= cap:
                return out
    return out


def _fallback_handoff(path: Path, task: dict, report: str) -> None:
    h = _paths(path)[1] / f"{task['id']}.md"
    h.write_text(f"# {task['id']} — {task['title']} ({task['space']})\n\n## Done\n\n"
                 f"{report.strip() or '(no report)'}\n\n_(Written by the assistant from the "
                 f"agent's final message: the agent wrote no handoff.)_\n", encoding="utf-8")


def _agent(path: Path, state: dict, space, prompt: str, cancel, progress, label: str,
           timeout: float, cwd: Path, model: str, append: str,
           extra_bash: tuple[str, ...] = ()) -> claude.Result:
    """One agent run of the mission, inside the mission-wide slot cap."""
    work, handoffs = _paths(path)

    def on_event(ev):
        act = claude.tool_activity(ev)
        if act:
            progress(f"{label} · {act}")

    if not _take(_MISSION_SLOTS, cancel):
        if cancel is not None and cancel.is_set():
            raise claude.ClaudeCancelled("cancelled while waiting for a slot")
        raise claude.ClaudeError("no agent slot came free")
    try:
        return claude.agent(prompt, model=model, cwd=cwd,
                            add_dirs=[str(work), str(handoffs)] + list(state.get("targets") or ()),
                            extra_bash=extra_bash or (space.bash if space else ()),
                            append_system=append, timeout=timeout, on_event=on_event,
                            cancel=cancel, slot_wait=_SLOT_WAIT, deny_bash=spaces.GIT_DENY)
    finally:
        _MISSION_SLOTS.release()


def run_task(path: Path, task: dict, cancel: threading.Event,
             progress: Callable[[str], None]) -> dict:
    """One specialist does one task, then the assistant checks it and sends
    what is missing back once. Returns the task's record (also stored)."""
    tid = task["id"]
    state = load(path) or {}
    space = spaces.get(task["space"])
    prev = (state.get("tasks") or {}).get(tid) or {}
    rec: dict = {"status": RUNNING, "space": task["space"], "at": _now()}
    if space is None:
        rec.update(status=FAILED, remains=f"the {task['space']} skill space no longer exists")
        update(path, lambda st: st.setdefault("tasks", {}).__setitem__(tid, rec))
        return rec
    model = spaces.model_for(space)
    rec["model"] = model
    update(path, lambda st: st.setdefault("tasks", {}).__setitem__(tid, dict(rec)))

    run_dir = path / ".agents" / f"{tid}-{space.id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    spaces.install_into(space, run_dir / ".claude" / "skills")
    work = _paths(path)[0]
    before = _snapshot(work)
    baselines = _legal_baselines(path, state)
    append = _specialist_system(state, space)
    label = f"{tid} {space.id}"
    progress(f"{label} · started ({model})")
    t0 = time.monotonic()
    tokens = cached = 0
    denied: list[str] = []

    def denials(res):
        for d in res.denials or ():
            if isinstance(d, dict):
                cmd = str((d.get("tool_input") or {}).get("command") or d.get("tool_name") or "")
                if cmd and cmd[:120] not in denied:
                    denied.append(cmd[:120])

    try:
        res = _agent(path, state, space, _task_prompt(path, state, task, space), cancel,
                     progress, label, task_timeout(), run_dir, model, append)
        tokens, cached = res.tokens_in + res.tokens_out, res.tokens_cached
        denials(res)
        status, remains, report = _step_status(res.text)
        problems = _problems(path, task)
        legal = _legal_problems(baselines)
        if (problems or legal) and not cancel.is_set():
            progress(f"{label} · sending back {len(problems) + len(legal)} problem(s)")
            found = [_problem_text(k, f) for k, f in problems]
            found += [f"licence / GDPR scan, {x}" for x in legal[:15]]
            fix = ("The assistant checked your task and found these problems:\n"
                   + "\n".join(f"- {x}" for x in found)
                   + "\n\nFix exactly these: write what is missing; for a licence or GDPR "
                     "finding, replace or remove the asset, link or code, or record a "
                     "licensed asset in credits.json, as your rules say. Then make sure "
                     "your handoff is complete. Keep everything else as it is.\n\n"
                     "For reference, your task was:\n\n"
                   + _task_prompt(path, load(path) or state, task, space))
            try:
                res2 = _agent(path, state, space, fix, cancel, progress, label, _FIX_TIMEOUT,
                              run_dir, model, append)
                tokens += res2.tokens_in + res2.tokens_out
                cached += res2.tokens_cached
                denials(res2)
                status2, remains2, report2 = _step_status(res2.text)
                if report2:
                    report = f"{report}\n\n{report2}".strip()
                if status2 == PARTIAL:
                    status, remains = PARTIAL, remains2 or remains
            except claude.ClaudeCancelled:
                raise
            except claude.ClaudeError as e:
                print(f"[Agents] {label}: correction run failed: {e}")
            problems = _problems(path, task)
            legal = _legal_problems(baselines)
        if any(k == "handoff" for k, _f in problems):
            _fallback_handoff(path, task, report)
            rec["handoff"] = "assistant"
            problems = [(k, f) for k, f in problems if k != "handoff"]
        if problems:
            status = PARTIAL
            missing = ", ".join(f.name for _k, f in problems)
            remains = f"missing: {missing}" + (f" — {remains}" if remains else "")
        if legal:
            status = PARTIAL
            rec["legal"] = legal[:10]
            remains = (f"{len(legal)} licence / GDPR problem(s) left, first: {legal[0]}"
                       + (f" — {remains}" if remains else ""))
        else:
            rec.pop("legal", None)                 # a task run again may have fixed them
        rec.update(status=DONE if status == DONE else PARTIAL, remains=remains,
                   report=report[:2500])
    except claude.ClaudeCancelled:
        rec.update(status=CANCELLED, remains="stopped by the user")
    except claude.ClaudeError as e:
        msg = str(e)
        if "did not answer within" in msg:
            rec.update(status=PARTIAL, remains=f"stopped after {int(task_timeout() // 60)} "
                                               f"minutes; continue carries on from its files")
        else:
            rec.update(status=FAILED, remains=msg[:300])
    after = _snapshot(work)
    changed = {k for k, v in after.items() if v > before.get(k, 0)}
    # A task run again (continue) keeps what its earlier runs did and cost.
    rec.update(minutes=round((time.monotonic() - t0) / 60 + float(prev.get("minutes") or 0), 1),
               tokens=tokens + int(prev.get("tokens") or 0),
               cached=cached + int(prev.get("cached") or 0),
               files=sorted(changed | set(prev.get("files") or ()))[:40])
    if denied:
        rec["denied"] = denied[:5]

    def store(st):
        st.setdefault("tasks", {})[tid] = rec
        st["tokens"] = int(st.get("tokens") or 0) + tokens
    update(path, store)
    progress(f"{label} · {rec['status']} ({rec['minutes']} min)")
    return rec


# ── Reviewing ────────────────────────────────────────────────────────────────

def _review_prompt(path: Path, state: dict) -> str:
    work, handoffs = _paths(path)
    plan = state.get("plan") or {}
    recs = state.get("tasks") or {}
    titles = {s.id: s.title for s in spaces.all_spaces()}
    out = [f"You are the reviewer of the mission \"{plan.get('title', '')}\"."]
    if plan.get("summary"):
        out.append(f"Mission: {plan['summary']}")
    out += [f"The user's request: {state.get('request', '')}", "",
            "The tasks, each done by a specialist agent:"]
    for t in plan.get("tasks") or ():
        rec = recs.get(t["id"]) or {}
        out.append(f"{t['id']} · {titles.get(t['space'], t['space'])} · {rec.get('status', PENDING)}"
                   f" — {t['title']}")
        if t.get("acceptance"):
            out.append(f"   acceptance: {' | '.join(t['acceptance'])}")
        if t.get("deliverables"):
            out.append(f"   deliverables: {', '.join(str(work / d) for d in t['deliverables'])}")
        if rec.get("status") in _OK:
            out.append(f"   handoff: {handoffs / (t['id'] + '.md')}")
        elif rec.get("remains"):
            out.append(f"   not done: {rec['remains']}")
    if state.get("targets"):
        out += ["", "Target folders (the user's files the team worked on):"]
        out += [f"- {quality.describe(t)}" for t in state["targets"]]
    ex = json.dumps({"tasks": {"T1": {"ok": True, "issues": []},
                               "T2": {"ok": False, "issues": ["<file — what is wrong — what is expected>"]}},
                     "summary": "<two sentences>"}, ensure_ascii=False)
    out += ["",
            "Check each finished task against its acceptance criteria and the request: read "
            "its handoff, then its deliverables — partially when they are long (Grep for what "
            "a criterion needs); run a cheap check when one exists (the tests, a script's "
            "--help). Look also for contradictions between tasks (a name, a port, an API or a "
            "file one task defines and another uses differently). Do not redo the work and "
            "change no deliverable.",
            "", "Then write two files:",
            f"1. {handoffs / 'review.json'} — exactly this shape: {ex}",
            f"   One entry per finished task. An issue is a missed acceptance criterion, a real "
            f"defect (bug, security hole, broken reference) or a contradiction between tasks — "
            f"something its specialist can fix in a short run. Style preferences are not "
            f"issues. At most {_MAX_ISSUES} per task, the most important first.",
            f"2. {work / 'REPORT.md'} — the mission report for the user, in {_lang(state)}: "
            f"a three-sentence summary; what was asked; what each specialist delivered, with "
            f"file paths; how the pieces fit together; the issues found; what the user must do "
            f"next (gathered from the handoffs' 'For the user')."]
    return "\n".join(out)


def _review_system(bash: tuple[str, ...] = ()) -> str:
    return (
        f"\n\nYou are the reviewer of a team of specialist agents working for "
        f"{_assistant_name()}, a voice assistant. Nobody can answer questions while you "
        f"work. Be strict and specific: every issue names the file and what to change, and "
        f"you invent none. Keep token use low: read only what a criterion needs; never read "
        f"node_modules, lock files or build output. Bash runs only these commands: "
        f"{spaces.describe_commands(bash)} — one at a time or as `cd \"<folder>\" && "
        f"<command>`, git only as `git -C \"<folder>\" ...`, never a shell loop; when one "
        f"is refused, use Read, Grep or Glob and "
        f"carry on. Your final message: at most three sentences, then `STEP: done` alone "
        f"on the last line."
    )


def _read_review(path: Path, task_ids) -> dict | None:
    f = _paths(path)[1] / "review.json"
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("tasks"), dict):
        return None
    out = {}
    for tid, v in data["tasks"].items():
        tid = str(tid).strip().upper()
        if tid not in task_ids or not isinstance(v, dict):
            continue
        issues = _strs(v.get("issues"), _MAX_ISSUES, 500)
        ok = bool(v.get("ok")) and not issues
        out[tid] = {"ok": ok, "issues": issues}
    return {"tasks": out, "summary": _text(data.get("summary"), 600)}


def review(path: Path, cancel: threading.Event, progress: Callable[[str], None]) -> dict:
    """The reviewer's pass over the finished tasks; then one correction run for
    each task it found an issue in. Returns what happened (also stored)."""
    state = load(path) or {}
    plan = state.get("plan") or {}
    tasks = plan.get("tasks") or []
    recs = state.get("tasks") or {}
    run_dir = path / ".agents" / "review"
    run_dir.mkdir(parents=True, exist_ok=True)
    stale = _paths(path)[1] / "review.json"
    stale.unlink(missing_ok=True)
    involved = [spaces.get(t["space"]) for t in tasks if (recs.get(t["id"]) or {}).get("status") in _OK]
    bash: list[str] = []
    for sp in involved:
        for p in (sp.bash if sp else ()):
            if p not in bash:
                bash.append(p)
    model = review_model()
    out: dict = {"model": model, "at": _now(), "tokens": 0, "issues": 0, "fixed": [], "unfixed": []}
    progress(f"review · started ({model})")
    report = _paths(path)[0] / "REPORT.md"
    report_before = report.stat().st_mtime if report.is_file() else 0.0
    try:
        res = _agent(path, state, None, _review_prompt(path, state), cancel, progress, "review",
                     _REVIEW_TIMEOUT, run_dir, model, _review_system(tuple(bash)), tuple(bash))
        out["tokens"] = res.tokens_in + res.tokens_out
    except claude.ClaudeCancelled:
        out["status"] = CANCELLED
        return _store_review(path, out, 0)
    except claude.ClaudeError as e:
        out.update(status=FAILED, error=str(e)[:300])
        return _store_review(path, out, 0)
    verdict = _read_review(path, {t["id"] for t in tasks})
    out["report"] = report.is_file() and report.stat().st_mtime > report_before
    if verdict is None:
        out.update(status=PARTIAL, error="the reviewer wrote no usable review.json")
        return _store_review(path, out, out["tokens"])
    out.update(status=DONE, summary=verdict["summary"], verdict=verdict["tasks"])
    to_fix = [t for t in tasks if not (verdict["tasks"].get(t["id"]) or {"ok": True})["ok"]
              and (recs.get(t["id"]) or {}).get("status") in _OK]
    out["issues"] = sum(len(v["issues"]) for v in verdict["tasks"].values())
    _store_review(path, out, out["tokens"])
    if to_fix and not cancel.is_set():
        progress(f"review · {out['issues']} issue(s) in {', '.join(t['id'] for t in to_fix)}")
        fixes, spent = [], 0
        with ThreadPoolExecutor(max_workers=parallel(), thread_name_prefix="mission-fix") as pool:
            futs = {pool.submit(_fix_after_review, path, t, verdict["tasks"][t["id"]]["issues"],
                                cancel, progress): t for t in to_fix}
            for f, t in futs.items():
                try:
                    ok, text, tokens = f.result()
                except Exception as e:                       # noqa: BLE001
                    ok, text, tokens = False, f"correction failed: {e}", 0
                (out["fixed"] if ok else out["unfixed"]).append(t["id"])
                spent += tokens
                fixes.append((t, ok, text))
        out["tokens"] += spent
        _append_corrections(path, state, fixes)
        _store_review(path, out, spent)
    return out


def _store_review(path: Path, out: dict, add_tokens: int) -> dict:
    """Keep the review's outcome; `add_tokens` are the ones not counted yet."""
    def change(st):
        st["review_result"] = dict(out)
        st["tokens"] = int(st.get("tokens") or 0) + max(0, int(add_tokens or 0))
    update(path, change)
    return out


def _fix_after_review(path: Path, task: dict, issues: list[str], cancel,
                      progress) -> tuple[bool, str, int]:
    state = load(path) or {}
    space = spaces.get(task["space"])
    if space is None:
        return False, "its skill space no longer exists", 0
    run_dir = path / ".agents" / f"{task['id']}-{space.id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    if not (run_dir / ".claude" / "skills").is_dir():
        spaces.install_into(space, run_dir / ".claude" / "skills")
    prompt = ("The mission's reviewer checked your task and found these issues:\n"
              + "\n".join(f"- {i}" for i in issues)
              + "\n\nFix exactly these in your deliverables (and in the target folders "
                "when that is where the problem is), add a line on each fix to the Done "
                "section of your handoff, and keep everything else as it is.\n\n"
                "For reference, your task was:\n\n" + _task_prompt(path, state, task, space))
    label = f"{task['id']} {space.id}"
    try:
        res = _agent(path, state, space, prompt, cancel, progress, f"{label} fix", _FIX_TIMEOUT,
                     run_dir, spaces.model_for(space), _specialist_system(state, space))
    except claude.ClaudeError as e:
        return False, str(e)[:200], 0
    status, remains, report = _step_status(res.text)
    tokens = res.tokens_in + res.tokens_out

    def change(st):
        rec = st.setdefault("tasks", {}).setdefault(task["id"], {})
        rec["review"] = {"issues": issues, "fixed": status == DONE,
                         "remains": remains, "report": report[:1200]}
        rec["tokens"] = int(rec.get("tokens") or 0) + tokens
    update(path, change)
    return status == DONE, report or remains, tokens


def _append_corrections(path: Path, state: dict, fixes) -> None:
    report = _paths(path)[0] / "REPORT.md"
    if not fixes or not report.is_file():
        return
    fr = _french(state)
    lines = ["", "", "## " + ("Corrections après la relecture" if fr else "Corrections after review"), ""]
    for t, ok, text in fixes:
        mark = "✓" if ok else "~"
        lines.append(f"- {mark} **{t['id']}** — {t['title']}: {' '.join(str(text).split())[:600]}")
    with report.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


# ── The report the assistant writes itself ───────────────────────────────────

def write_report(path: Path) -> Path:
    """REPORT.md from the plan and the handoffs, when no reviewer wrote one:
    no tokens."""
    state = load(path) or {}
    plan = state.get("plan") or {}
    recs = state.get("tasks") or {}
    work, handoffs = _paths(path)
    fr = _french(state)
    titles = {s.id: s.title for s in spaces.all_spaces()}
    words = ({"req": "Demande", "tasks": "Tâches", "files": "Fichiers", "handoff": "Passation"}
             if fr else {"req": "Request", "tasks": "Tasks", "files": "Files", "handoff": "Handoff"})
    out = [f"# {plan.get('title') or state.get('name', '')}", ""]
    if plan.get("summary"):
        out += [plan["summary"], ""]
    out += [f"**{words['req']}:** {state.get('request', '')}", "", f"## {words['tasks']}", ""]
    for t in plan.get("tasks") or ():
        rec = recs.get(t["id"]) or {}
        st = rec.get("status", PENDING)
        out.append(f"### {_MARKS.get(st, '·')} {t['id']} · {titles.get(t['space'], t['space'])} — "
                   f"{t['title']}")
        if rec.get("remains"):
            out.append(f"_{st}: {rec['remains']}_")
        if rec.get("report"):
            out += ["", rec["report"].strip()]
        rv = rec.get("review") or {}
        if rv.get("issues"):
            mark = "✓" if rv.get("fixed") else "~"
            out += ["", f"{mark} " + ("Relecture" if fr else "Review") + ": "
                    + "; ".join(rv["issues"])]
        h = handoffs / f"{t['id']}.md"
        if h.is_file() and rec.get("handoff") != "assistant":
            body = h.read_text(encoding="utf-8", errors="replace").strip()
            out += ["", f"<details><summary>{words['handoff']} {t['id']}</summary>", "",
                    body[:3000], "", "</details>"]
        out.append("")
    files = sorted({f for rec in recs.values() for f in rec.get("files") or ()})
    if files:
        out += [f"## {words['files']}", ""] + [f"- {work / f}" for f in files[:60]]
    report = work / "REPORT.md"
    report.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    return report


# ── A whole run ──────────────────────────────────────────────────────────────

def _should_review(state: dict) -> bool:
    if state.get("review") is not None:
        return bool(state["review"])
    n = len((state.get("plan") or {}).get("tasks") or ())
    return state.get("kind") != "delegate" and n >= 2 and review_by_default()


def run(path: Path, cancel: threading.Event, progress: Callable[[str], None] = lambda _t: None,
        on_plan: Callable[[dict], None] | None = None) -> dict:
    """Plan if needed, run every task not done yet in dependency order, review,
    and write the report. Blocks; call it from a job thread after claim().
    Always releases the claim."""
    slug = path.name
    try:
        return _run(path, cancel, progress, on_plan)
    except Exception as e:
        def change(s):
            s["status"] = FAILED
            s["notes"] = list(s.get("notes") or []) + [f"stopped: {type(e).__name__}: {str(e)[:200]}"]
        update(path, change)
        raise
    finally:
        release(slug)


def _run(path: Path, cancel: threading.Event, progress, on_plan) -> dict:
    slug = path.name
    state = load(path) or {}
    if not (state.get("plan") or {}).get("tasks"):
        state = make_plan(path, progress)
        if on_plan:
            on_plan(state)
    if cancel.is_set():
        state = update(path, lambda s: s.update(status=CANCELLED, finished=_now()))
        return {"ran": [], "review": None, "status": CANCELLED, "state": state,
                "path": str(path), "report": ""}
    tasks = state["plan"]["tasks"]
    by_id = {t["id"]: t for t in tasks}
    recs = state.get("tasks") or {}
    # Everything not done runs again, in dependency order: a task left partial,
    # failed, blocked, stopped — or "running" because the app was closed on it.
    todo = [t for t in tasks if (recs.get(t["id"]) or {}).get("status") != DONE]
    status = {t["id"]: (recs.get(t["id"]) or {}).get("status", PENDING) for t in tasks}

    def mark(tid: str, st: str, why: str = "") -> None:
        status[tid] = st

        def change(s):
            rec = s.setdefault("tasks", {}).setdefault(tid, {})
            rec["status"] = st
            if why:
                rec["remains"] = why
        update(path, change)

    update(path, lambda s: s.update(status=RUNNING, started=_now()))
    for t in todo:
        mark(t["id"], PENDING)
    par = parallel()
    ran: list[str] = []
    futures: dict = {}
    with ThreadPoolExecutor(max_workers=par, thread_name_prefix=f"mission-{slug[:12]}") as pool:
        while True:
            for t in todo:
                tid = t["id"]
                if status[tid] != PENDING or len(futures) >= par:
                    continue
                if cancel.is_set():
                    mark(tid, CANCELLED, "stopped by the user before it started")
                    continue
                deps = [d for d in t.get("depends_on") or () if d in by_id]
                stuck = [d for d in deps if status[d] in _STUCK]
                if stuck:
                    mark(tid, BLOCKED, f"waits for {', '.join(stuck)}, which did not finish")
                    continue
                if all(status[d] in _OK for d in deps):
                    status[tid] = RUNNING
                    futures[pool.submit(run_task, path, t, cancel, progress)] = tid
            if not futures:
                break
            finished, _ = wait(list(futures), return_when=FIRST_COMPLETED)
            for f in finished:
                tid = futures.pop(f)
                try:
                    status[tid] = f.result().get("status", FAILED)
                except Exception as e:                       # noqa: BLE001
                    mark(tid, FAILED, f"{type(e).__name__}: {str(e)[:200]}")
                ran.append(tid)

    state = load(path) or state
    result: dict = {"ran": ran, "review": None}
    if (not cancel.is_set() and ran and any(status[t["id"]] in _OK for t in tasks)
            and _should_review(state)):
        result["review"] = review(path, cancel, progress)
    report = _paths(path)[0] / "REPORT.md"
    rv = result["review"] or {}
    if not cancel.is_set() and ran and not (rv.get("status") == DONE and rv.get("report")):
        write_report(path)
    final = [status[t["id"]] for t in tasks]
    if cancel.is_set():
        overall = CANCELLED
    elif all(s == DONE for s in final):
        overall = DONE
    elif any(s in _OK for s in final):
        overall = PARTIAL
    else:
        overall = FAILED
    state = update(path, lambda s: s.update(status=overall, finished=_now()))
    try:
        (path / "PLAN.md").write_text(plan_text(state), encoding="utf-8")
    except OSError:
        pass
    result.update(status=overall, state=state, path=str(path),
                  report=str(report) if report.is_file() else "")
    return result


# ── Reading a mission ────────────────────────────────────────────────────────

def counts(state: dict) -> tuple[int, int]:
    """(tasks done, tasks in the plan)."""
    tasks = (state.get("plan") or {}).get("tasks") or ()
    recs = state.get("tasks") or {}
    return sum(1 for t in tasks if (recs.get(t["id"]) or {}).get("status") == DONE), len(tasks)


def status_text(path: Path, state: dict) -> str:
    plan = state.get("plan") or {}
    recs = state.get("tasks") or {}
    titles = {s.id: s.title for s in spaces.all_spaces()}
    done, total = counts(state)
    running = is_running(path.name)
    head = state.get("status", "new")
    if running:
        head = RUNNING
    elif head == RUNNING:
        head = "interrupted (the app stopped during it) — continue resumes it"
    out = [f"{plan.get('title') or state.get('name', '')} — {state.get('kind', 'team')} mission — "
           f"{head} — {done}/{total} tasks done", str(path)]
    if plan.get("summary"):
        out.append(plan["summary"])
    out.append("")
    if not plan.get("tasks"):
        out.append("No plan yet." if not running else "The lead is planning.")
    for t in plan.get("tasks") or ():
        rec = recs.get(t["id"]) or {}
        st = rec.get("status", PENDING)
        if st == RUNNING and not running:
            st = "interrupted"
        bits = [f"{_MARKS.get(st, '·')} {t['id']} · {titles.get(t['space'], t['space'])} — {t['title']}"]
        extra = []
        if rec.get("minutes"):
            extra.append(f"{rec['minutes']} min")
        if rec.get("tokens"):
            extra.append(f"{rec['tokens'] / 1000:.0f}k tok")
        if rec.get("model"):
            extra.append(rec["model"])
        if extra:
            bits.append(f"({', '.join(extra)})")
        out.append(" ".join(bits))
        if rec.get("remains") and st != DONE:
            out.append(f"     {st}: {rec['remains']}")
        if (rec.get("review") or {}).get("issues"):
            rv = rec["review"]
            out.append(f"     review: {len(rv['issues'])} issue(s), "
                       f"{'fixed' if rv.get('fixed') else 'not all fixed'}")
    rr = state.get("review_result") or {}
    if rr:
        out += ["", f"Review ({rr.get('model', '')}): {rr.get('status', '')} — "
                    f"{rr.get('issues', 0)} issue(s)"
                + (f", fixed by {', '.join(rr['fixed'])}" if rr.get("fixed") else "")
                + (f", still open in {', '.join(rr['unfixed'])}" if rr.get("unfixed") else "")]
        if rr.get("summary"):
            out.append(rr["summary"])
    if state.get("tokens"):
        out.append(f"Claude tokens spent: {int(state['tokens']) / 1000:.0f}k")
    report = _paths(path)[0] / "REPORT.md"
    if report.is_file():
        out.append(f"Report: {report}")
    for n in (state.get("notes") or [])[-3:]:
        out.append(f"Note: {n}")
    return "\n".join(out)
