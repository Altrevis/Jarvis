"""
project — software projects the assistant builds and keeps, one folder each.

WHY A TOOL OF ITS OWN
    ask_claude's task mode is one-shot: a fresh agent in workspace/, a report,
    and nothing that remembers the job afterwards. A project is the opposite —
    a codebase that grows over days and is asked about by name ("où en est mon
    clone de Calendly ?", "continue le projet budget"). So each one gets a
    folder under Documents/JARVIS/projects/<slug>/, a state file, and a method.

THE METHOD IS REPLICA
    github.com/Jakeschincariol/replica-skill (MIT, vendored in
    skill_packs/replica/): eleven Claude skills that take an app from recon to
    launch, each one reading what the last one wrote in replica/. Two pipelines:

        clone   recon → architect → design → build → backend → test → diff
                → entrepreneur → brand → launch
        idea    spec → architect → design → build → backend → test → diff

    "spec" is ours. Replica assumes an app to clone, and replica-architect stops
    when there is no recon map — so for an original idea the user's description
    is turned into the same recon.md and features.csv, and the pack runs as is.
    deploy is never part of a pipeline: it needs the user's accounts, DNS and a
    "go", so it only runs when asked for by name, and stops at the checklist.

WHY THIS SPENDS FEWER TOKENS THAN ONE BIG AGENT RUN
    - One step per request by default. A whole pipeline is hours of Opus; the
      user decides when the next step is worth it.
    - Every step is a fresh session. What carries over is replica/*.md — a few
      kilobytes the next skill reads on purpose — not a transcript replayed on
      every turn. CLAUDE.md holds the brief and is prompt-cached.
    - The pack lives in the PROJECT's .claude/skills, not in workspace/: every
      ask_claude task lists every skill it can see, and eleven descriptions it
      never uses would be paid for on each of them.
    - Only architect, build, backend and free-form tasks get the agent model
      (Opus by default). The other steps — research, specs, tests, scoring —
      get Sonnet. "project_models" ({"step": "model"}) and
      "project_model_light" in config/api_keys.json override this.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unicodedata
from pathlib import Path

from core import claude, jobs
from core.user_dirs import jarvis_documents_dir

if getattr(sys, "frozen", False):
    _BASE = Path(sys.executable).parent
else:
    _BASE = Path(__file__).resolve().parent.parent

_PACK = _BASE / "skill_packs" / "replica"
_STATE = Path(".jarvis") / "project.json"

CLONE_STEPS = ("recon", "architect", "design", "build", "backend", "test", "diff",
               "entrepreneur", "brand", "launch")
IDEA_STEPS = ("spec", "architect", "design", "build", "backend", "test", "diff")
MANUAL_STEPS = ("deploy",)
_HEAVY = {"architect", "build", "backend", "task"}
_MAX_CHAIN = 3
_HEAVY_TIMEOUT = 40 * 60
_LIGHT_TIMEOUT = 20 * 60

# On top of core/claude.AGENT_BASH. A project needs its package scripts and a
# local git history (replica-build commits once per screen). Still nothing that
# deletes, pushes or reaches a remote: git push is not here, neither is rm.
_PROJECT_BASH = ("npm install", "npm i *", "npm ci*", "npm run *", "npm test*",
                 "npm init *", "git init*", "git status*", "git add *",
                 "git commit *", "git diff*", "git log*")

_STEP_TASKS = {
    "recon": ("Run the replica-recon skill on {target}. Scope: {scope}. Public "
              "sources only, through WebSearch and WebFetch: there is no browser "
              "here and no user account to click through, so say which screens "
              "you could only infer."),
    "spec": ("There is no app to clone: the user's own idea, in CLAUDE.md, is the "
             "source. Do what the replica-recon skill does, from the idea instead "
             "of an existing app: write replica/recon.md from the template "
             ".claude/skills/replica-recon/recon-map.md and replica/features.csv "
             "from .claude/skills/replica-recon/features.csv — core loop, screens, "
             "flows, components, inferred data model, feature matrix, out of scope, "
             "size. Leave out Sources and screenshots. In features.csv the "
             "`original` column means 'in the spec' (yes) and `clone` starts at no. "
             "Be honest with priorities: the must-haves are the smallest version "
             "that is already useful."),
    "architect": "Run the replica-architect skill.",
    "design": "Run the replica-design skill.{idea_design}",
    "build": ("Run the replica-build skill. If replica/build-log.md exists, carry "
              "on from where it stops instead of starting over."),
    "backend": ("Run the replica-backend skill. Wherever the user's own accounts or "
                "keys are needed (database host, Stripe, email), build against "
                "environment variables with a local or fake provider behind them, "
                "and list what the user must create in replica/todo-user.md. Never "
                "invent a key."),
    "test": "Run the replica-test skill on this project.",
    "diff": "Run the replica-diff skill.{idea_diff}",
    "entrepreneur": "Run the replica-entrepreneur skill on {target}.",
    "brand": "Run the replica-brand skill.",
    "launch": "Run the replica-launch skill.",
    "deploy": ("Run the replica-deploy skill only as far as its preflight and the "
               "list of what the user has to do and decide. Deploy nothing, push "
               "nothing, create no account: write it all to replica/deploy-plan.md."),
}
_IDEA_DESIGN = (" There is no original to measure: design an original system that "
                "fits the brief in CLAUDE.md.")
_IDEA_DIFF = (" There is no original to screenshot: run only the feature parity "
              "score (parity.py) against the spec, and write replica/parity.md.")

_STEP_FINAL = ("Your final message is read out by the voice model: at most five "
               "sentences on what you did and what comes next, then, alone on the "
               "last line, `STEP: done` when this step is complete or "
               "`STEP: partial — <what remains>` when it is not.")
_TASK_FINAL = ("Your final message is read out by the voice model: at most five "
               "sentences on what you changed and anything the user must do.")
_STEP_RE = re.compile(r"^\s*`?STEP:\s*(done|partial)\b\s*[—–:-]?\s*(.*?)`?\s*$",
                      re.I | re.M)

_run_lock = threading.Lock()
_running: dict[str, str] = {}     # slug -> what it is doing right now


# ── Small helpers ────────────────────────────────────────────────────────────

def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def _assistant_name() -> str:
    try:
        from memory.config_manager import get_assistant_name
        return get_assistant_name()
    except Exception:
        return "JARVIS"


def _config() -> dict:
    try:
        from memory.config_manager import load_api_keys
        return load_api_keys()
    except Exception:
        return {}


def _slug(text: str) -> str:
    ascii_ = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_.lower()).strip("-")[:48].strip("-")
    return slug or "projet"


def _root() -> Path:
    return jarvis_documents_dir("projects")


def _load(path: Path) -> dict | None:
    try:
        data = json.loads((path / _STATE).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _save(path: Path, state: dict) -> None:
    # Full precision: "the project worked on last" is decided by this, and two
    # saves in the same second are ordinary when a step finishes.
    state["updated"] = _dt.datetime.now().isoformat()
    target = path / _STATE
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), prefix=".project-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    os.replace(tmp, target)


def _all() -> list[tuple[Path, dict]]:
    out = []
    for d in sorted(_root().iterdir()) if _root().exists() else ():
        state = _load(d) if d.is_dir() else None
        if state:
            out.append((d, state))
    out.sort(key=lambda ps: ps[1].get("updated", ""), reverse=True)
    return out


def _find(name: str) -> tuple[Path, dict] | None:
    """The project a spoken name means. Empty name: the one worked on last."""
    projects = _all()
    if not projects:
        return None
    if not name.strip():
        return projects[0]
    from core.fuzzy_find import Query, score
    q = Query(name)
    best, best_score = None, 0.0
    for path, state in projects:
        s = max(score(q, state.get("name", "")), score(q, path.name))
        if s > best_score:
            best, best_score = (path, state), s
    return best if best_score >= 0.55 else None


def _pipeline(state: dict) -> tuple[str, ...]:
    return CLONE_STEPS if state.get("kind") == "clone" else IDEA_STEPS


def _next_step(state: dict) -> str | None:
    for step in _pipeline(state):
        if (state.get("steps") or {}).get(step, {}).get("status") != "done":
            return step
    return None


def _model_for(step: str) -> str:
    cfg = _config()
    custom = cfg.get("project_models")
    if isinstance(custom, dict) and custom.get(step):
        return str(custom[step])
    if step in _HEAVY:
        return claude.model_for(claude.AGENT)
    return str(cfg.get("project_model_light") or "sonnet")


def _claude_unavailable() -> str:
    if claude.engine() != "claude":
        return ("Projects are built by Claude, and ⚙ SETUP → CLAUDE is set to Gemini "
                "only. Tell the user.")
    if not claude.binary():
        return ("Projects are built by Claude Code, which is not installed on this "
                "computer. Tell the user to install it from claude.com/claude-code.")
    resting = claude.cooling()
    if resting:
        return f"Claude is unavailable right now ({resting}). Tell the user briefly."
    return ""


# ── Creating a project ───────────────────────────────────────────────────────

def _brief(state: dict) -> str:
    """CLAUDE.md: loaded by every agent run in the folder, prompt-cached, so it
    holds the brief and the rules — and stays short, because it is read on
    every turn of every step."""
    if state["kind"] == "clone":
        what = (f"A clone of {state['target']}: its features and flows, rebuilt "
                f"clean-room under a name of its own.")
    else:
        what = ("An original project. There is no app to clone: the `spec` step "
                "turns this brief into replica/recon.md and replica/features.csv.")
    lang = state.get("language") or "the user's language"
    return (
        f"# {state['name']}\n\n{what}\n\n"
        f"## Brief\n\n{state.get('description') or '(none given beyond the target)'}\n\n"
        f"## How this project is built\n\n"
        f"- The Replica skills in .claude/skills, one step per run: "
        f"{' → '.join(_pipeline(state))}. `deploy` only when the user asks.\n"
        f"- replica/ is the project's memory: each step reads what the previous "
        f"ones wrote there. Keep it current.\n"
        f"- Choices made without the user go in replica/decisions.md; what only the "
        f"user can do (accounts, keys, DNS) goes in replica/todo-user.md.\n"
        f"- Text meant for the user: {lang}. Code, identifiers and commits: English.\n"
    )


def _create(p: dict, player) -> str:
    name = str(p.get("name") or "").strip()
    description = str(p.get("description") or "").strip()
    target = str(p.get("clone_of") or "").strip()
    if not name:
        name = target or ""
    if not name:
        return "No project name given. Ask the user what to call it."
    if not target and not description:
        return ("To start a project, say what it should do (description), or which "
                "existing app it clones (clone_of). Ask the user.")
    if not (_PACK / "replica-recon" / "SKILL.md").is_file():
        return "The Replica skill pack is missing from skill_packs/replica. Tell the user."

    slug = _slug(name)
    path = _root() / slug
    if path.exists():
        return (f"A project called {name} already exists in {path}. Use action "
                f"status or continue on it instead.")

    state = {
        "name": name, "slug": slug, "kind": "clone" if target else "idea",
        "target": target, "description": description,
        "language": str(p.get("language") or "").strip(),
        "created": _now(), "steps": {},
    }
    skills = path / ".claude" / "skills"
    skills.mkdir(parents=True)
    for d in sorted(_PACK.glob("replica-*")):
        shutil.copytree(d, skills / d.name)
    shutil.copy2(_PACK / "LICENSE", path / ".claude" / "REPLICA-LICENSE")
    (path / "replica").mkdir()
    (path / "CLAUDE.md").write_text(_brief(state), encoding="utf-8")
    (path / ".gitignore").write_text(
        "node_modules/\n.next/\ndist/\nbuild/\n.env*\n!.env.example\n"
        "# Reference screenshots of the original: never shipped\nreplica/screens/\n"
        "# The assistant's own bookkeeping\n.jarvis/\n", encoding="utf-8")
    _save(path, state)
    if shutil.which("git"):
        subprocess.run(["git", "init", "-q"], cwd=str(path), capture_output=True, timeout=20)

    try:
        from memory.memory_manager import remember
        what = f"clone of {target}" if target else description[:120]
        remember(slug.replace("-", "_"), f"{what} (project folder: {path})", "projects")
    except Exception:
        pass

    made = f"Project {name} created in {path} ({' → '.join(_pipeline(state))})."
    if p.get("start") is False:
        return f"{made} Nothing is running yet; say it is ready."
    return f"{made} {_start(player, path, state, [_pipeline(state)[0]], state['language'])}"


# ── Running steps ────────────────────────────────────────────────────────────

def _step_task(state: dict, step: str) -> str:
    idea = state.get("kind") != "clone"
    return _STEP_TASKS[step].format(
        target=state.get("target") or "the app",
        scope=state.get("description") or "the core loop, the one flow users pay for",
        idea_design=_IDEA_DESIGN if idea else "",
        idea_diff=_IDEA_DIFF if idea else "")


def _agent_system(state: dict, language: str, final: str) -> str:
    lang = language or state.get("language") or ""
    lang_line = f"Write any text meant for the user in {lang}.\n" if lang else ""
    return (
        f"\n\nYou are working for {_assistant_name()}, a voice assistant, on the "
        f"software project \"{state['name']}\" in the current directory; its brief "
        f"is in CLAUDE.md. Nobody can answer questions while you work: make "
        f"reasonable choices, note each one in replica/decisions.md, and finish.\n"
        f"Keep token use low. Read only the replica/ files this step needs; prefer "
        f"Grep, Glob and partial reads to opening whole files; never read "
        f"node_modules, lock files or build output; do not re-read a file you "
        f"already have; do not paste file contents into your messages.\n"
        f"{lang_line}{final}")


def _step_status(text: str) -> tuple[str, str, str]:
    """(status, what remains, the report without its STEP line). An agent that
    forgot the line is taken at its word that it finished: re-running a step
    nobody asked to re-run is the expensive mistake."""
    found = list(_STEP_RE.finditer(text or ""))
    if not found:
        return "done", "", (text or "").strip()
    m = found[-1]
    report = (text[:m.start()] + text[m.end():]).strip()
    return m.group(1).lower(), m.group(2).strip(), report


def _record(path: Path, key: str, rec: dict) -> dict:
    state = _load(path) or {}
    state.setdefault("steps", {})[key] = rec
    _save(path, state)
    return state


def _run_one(path: Path, state: dict, step: str, request: str, language: str,
             progress) -> dict:
    """One agent run: a pipeline step, or `request` as a free-form task."""
    is_task = step == "task"
    model = _model_for(step)
    timeout = _HEAVY_TIMEOUT if step in _HEAVY else _LIGHT_TIMEOUT
    prompt = request if is_task else _step_task(state, step)
    if is_task:
        prompt += ("\n\nRead CLAUDE.md and the replica/ files that matter first. If "
                   "you change the app, keep replica/features.csv and "
                   "replica/build-log.md up to date.")

    def on_event(ev):
        act = claude.tool_activity(ev)
        if act:
            progress(f"{step} · {act}")

    rec = {"model": model, "at": _now()}
    try:
        res = claude.agent(prompt, model=model, cwd=path, extra_bash=_PROJECT_BASH,
                           append_system=_agent_system(state, language,
                                                       _TASK_FINAL if is_task else _STEP_FINAL),
                           timeout=timeout, on_event=on_event)
    except claude.ClaudeError as e:
        msg = str(e)
        if "already running" in msg:
            raise                      # nothing ran: nothing to record
        if "did not answer within" in msg:
            rec.update(status="partial", report="",
                       remains=f"stopped after {timeout // 60} minutes; run the step "
                               f"again and it carries on from the replica/ files")
        else:
            rec.update(status="failed", report="", remains=msg[:300])
        if not is_task:
            _record(path, step, rec)
        if rec["status"] == "failed":
            raise
        return rec

    status, remains, report = _step_status(res.text)
    rec.update(status="done" if is_task else status, remains=remains,
               report=report[:2000], tokens=res.tokens_in + res.tokens_out,
               cached=res.tokens_cached, minutes=round(res.duration_s / 60, 1))
    if is_task:
        state = _load(path) or state
        state.setdefault("tasks", []).append({"request": request[:300], **rec})
        state["tasks"] = state["tasks"][-20:]
        _save(path, state)
    else:
        _record(path, step, rec)
    return rec


def _start(player, path: Path, state: dict, steps: list[str], language: str,
           request: str = "") -> str:
    """Run `steps` one after another in the background. Stops early at a step
    that did not finish: the next one would build on a missing piece."""
    unavailable = _claude_unavailable()
    if unavailable:
        return unavailable
    slug = state["slug"]
    with _run_lock:
        if slug in _running:
            return (f"Project {state['name']} is already busy ({_running[slug]}). "
                    f"Tell the user it will say when it is done.")
        _running[slug] = steps[0]
    what = "task" if steps == ["task"] else " → ".join(steps)
    label = f"PROJECT — {state['name'][:28]} · {what}"

    def work(progress) -> str:
        done: list[str] = []
        last: dict = {}
        try:
            for step in steps:
                with _run_lock:
                    _running[slug] = step
                progress(f"{step} …")
                last = _run_one(path, _load(path) or state, step, request, language,
                                progress)
                done.append(step)
                if last.get("status") != "done":
                    break
        finally:
            with _run_lock:
                _running.pop(slug, None)
        fresh = _load(path) or state
        nxt = _next_step(fresh)
        report = last.get("report") or ""
        if player is not None and hasattr(player, "show_content") and report:
            player.show_content(label, report)
        if last.get("status") == "partial":
            outcome = (f"Step {done[-1]} of project {state['name']} is only partly "
                       f"done: {last.get('remains') or 'see the report'}.")
        else:
            outcome = f"Project {state['name']}: {', '.join(done)} done."
        if nxt and steps != ["task"]:
            outcome += f" Next step: {nxt}."
        return (f"{outcome} Report (also on the display): {report[:1000]}\nTell the "
                f"user in one or two sentences, in their language.")

    jobs.start(player, label, work)
    return (f"status=started_in_background ({what}). Say in one short sentence that "
            f"work on {state['name']} has started; you will be told when it is done.")


# ── Reading a project ────────────────────────────────────────────────────────

def _parity(path: Path) -> str:
    """'Features 42% · must-haves 5/9' from replica/features.csv, or ''.
    Runs the vendored parity.py — the reviewed copy, not the project's own,
    which an agent may have edited."""
    matrix = path / "replica" / "features.csv"
    tool = _PACK / "replica-diff" / "parity.py"
    if not matrix.is_file() or not tool.is_file():
        return ""
    try:
        out = subprocess.run([sys.executable, "-I", str(tool), str(matrix), "--json"],
                             capture_output=True, text=True, timeout=20)
        data = json.loads(out.stdout or "{}")
        return (f"Features {round(float(data.get('feature_score', 0)))}% · must-haves "
                f"{data.get('must_have_done', 0)}/{data.get('must_have_total', 0)}")
    except Exception:
        return ""


def _status_text(path: Path, state: dict) -> str:
    steps = state.get("steps") or {}
    marks = {"done": "✓", "partial": "~", "failed": "✕"}
    line = "  ".join(f"{s} {marks.get(steps.get(s, {}).get('status'), '·')}"
                     for s in _pipeline(state))
    kind = (f"clone of {state['target']}" if state.get("kind") == "clone"
            else "original idea")
    out = [f"{state['name']} — {kind}", str(path), "", f"Steps: {line}"]
    with _run_lock:
        busy = _running.get(state.get("slug", ""))
    if busy:
        out.append(f"Working now: {busy}")
    nxt = _next_step(state)
    out.append(f"Next: {nxt}" if nxt else "Pipeline complete. deploy runs only when asked.")
    parity = _parity(path)
    if parity:
        out.append(parity)
    tokens = sum(int(r.get("tokens") or 0) for r in steps.values())
    tokens += sum(int(t.get("tokens") or 0) for t in state.get("tasks") or ())
    if tokens:
        out.append(f"Claude tokens spent on it: {tokens / 1000:.0f}k")
    if (path / "replica" / "todo-user.md").is_file():
        out.append("Waiting on the user: replica/todo-user.md")
    last = max(steps.items(), key=lambda kv: kv[1].get("at", ""), default=None)
    if last:
        rec = last[1]
        out += ["", f"Last step: {last[0]} ({rec.get('status')}, {rec.get('at', '')[:16]})"]
        if rec.get("remains"):
            out.append(f"Remains: {rec['remains']}")
        if rec.get("report"):
            out.append(rec["report"][:600])
    return "\n".join(out)


def _open(path: Path) -> str:
    code = shutil.which("code")
    try:
        if code:
            subprocess.Popen([code, str(path)])
            return f"Opened {path} in VS Code."
        if sys.platform == "win32":
            os.startfile(str(path))                      # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
        return f"Opened {path}."
    except Exception as e:
        return f"Could not open {path}: {e}"


# ── The tool ─────────────────────────────────────────────────────────────────

def project(parameters: dict, player=None) -> str:
    p = parameters or {}
    action = str(p.get("action") or "status").lower().strip()
    language = str(p.get("language") or "").strip()

    if action == "create":
        return _create(p, player)

    if action == "list":
        projects = _all()
        if not projects:
            return "There are no projects yet."
        rows = []
        for path, st in projects:
            done = sum(1 for s in _pipeline(st)
                       if (st.get("steps") or {}).get(s, {}).get("status") == "done")
            nxt = _next_step(st) or "complete"
            rows.append(f"{st['name']} — {st.get('kind')} — {done}/{len(_pipeline(st))} "
                        f"steps — next: {nxt} — {st.get('updated', '')[:10]}")
        return "Projects, most recent first:\n" + "\n".join(rows)

    found = _find(str(p.get("name") or ""))
    if found is None:
        names = ", ".join(st["name"] for _, st in _all()) or "none yet"
        return f"No project matches {p.get('name')!r}. Existing projects: {names}."
    path, state = found

    if action == "status":
        text = _status_text(path, state)
        if player is not None and hasattr(player, "show_content"):
            player.show_content(f"PROJECT — {state['name'][:40]}", text)
        return text + "\n\nGive the user the gist in two sentences; the detail is on the display."

    if action == "open":
        return _open(path)

    if action == "continue":
        nxt = _next_step(state)
        if not nxt:
            return (f"Every step of {state['name']} is done. Next would be deploy, "
                    f"which only runs when the user asks for it by name.")
        pipe = _pipeline(state)
        try:
            count = max(1, min(_MAX_CHAIN, int(p.get("steps") or 1)))
        except (TypeError, ValueError):
            count = 1
        steps = list(pipe[pipe.index(nxt): pipe.index(nxt) + count])
        return _start(player, path, state, steps, language)

    if action == "run":
        step = str(p.get("step") or "").lower().strip()
        valid = _pipeline(state) + MANUAL_STEPS
        if step not in valid:
            return f"Unknown step {step!r} for {state['name']}. Steps: {', '.join(valid)}."
        return _start(player, path, state, [step], language)

    if action == "task":
        request = str(p.get("request") or "").strip()
        if not request:
            return "No request given. Pass what to change in 'request'."
        return _start(player, path, state, ["task"], language, request=request)

    return "Unknown action. Use create, continue, run, task, status, list or open."


TOOL = {
    "name": "project",
    "description": (
        "Software projects the user builds with you (apps, sites, tools), kept "
        "over days in one folder each and built step by step by Claude with the "
        "Replica method: a clone of an existing app, or the user's own idea. "
        "create: new project (clone_of for a clone, else description), starts "
        "step 1. continue: next step(s). run: one named step. task: any other "
        "change. status, list, open. Steps run in the background. Use this, not "
        "ask_claude or code_helper, for anything about a project being built."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING",
                       "description": "create | continue | run | task | status | list | open"},
            "name": {"type": "STRING",
                     "description": "Project name as the user said it; empty = the last one worked on"},
            "description": {"type": "STRING",
                            "description": "create: what it should do, for whom, any stack wish"},
            "clone_of": {"type": "STRING",
                         "description": "create: the existing app to clone (name or URL)"},
            "step": {"type": "STRING",
                     "description": "run: recon|spec|architect|design|build|backend|test|diff|entrepreneur|brand|launch|deploy"},
            "steps": {"type": "INTEGER",
                      "description": "continue: how many steps in a row (1-3, default 1)"},
            "request": {"type": "STRING", "description": "task: the change, fully stated"},
            "language": {"type": "STRING", "description": "The user's language, e.g. 'French'"},
        },
        "required": ["action"],
    },
    "handler": project,
}
