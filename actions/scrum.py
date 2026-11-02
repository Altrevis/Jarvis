"""
scrum — project management deliverables, the Scrum way, one folder per project.

WHAT IT PRODUCES
    Everything a Scrum project file is graded on, drawn as diagrams:

        cadrage            bête à cornes, diagramme pieuvre, SWOT, vision
        parties-prenantes  stakeholders on a power/interest grid, RACI matrix
        discovery          personas, hypotheses, questions, experiments
        backlog            product goal, epics, user stories, DoR, DoD
        sprint             sprint goals, sprint backlog, tasks, burndown
        risques            risk register and 5×5 heat map
        planning           Gantt, milestones, Scrum ceremonies

    Each step is one fresh Claude agent running the matching skill of
    skill_packs/scrum/ — a sub-agent with one job, which reads what the
    previous steps wrote in scrum/ and nothing else.

WHY THE AGENT WRITES JSON AND NOT THE DIAGRAMS
    skill_packs/scrum/render.py draws every deliverable locally, standard
    library only, in milliseconds. An SVG is ten times the tokens of the data
    it shows and would look different on every run; moving one story would
    mean redrawing the page. So the agent writes scrum/*.json, this file runs
    the reviewed copy of the renderer (not the project's, which an agent could
    edit), and showing, reopening or exporting a deliverable costs no tokens.

WHY THIS SPENDS FEW TOKENS
    - One step per request by default; "steps" chains up to the whole
      pipeline when the user asks for everything.
    - Every step is a fresh session that reads a few kilobytes of JSON on
      purpose, not a transcript replayed on every turn.
    - Every step runs on Sonnet: this is structured writing, not code.
      "scrum_models" ({"step": "model"}) and "scrum_model" in
      config/api_keys.json override it.
    - The pack lives in each workspace's .claude/skills, never in
      workspace/, so ordinary ask_claude tasks do not list seven skills they
      never use.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from actions.create_document import _open as _open_file, _read_source
from actions.project import (_STEP_FINAL, _TASK_FINAL, _assistant_name, _claude_unavailable,
                             _config, _now, _slug, _step_status)
from core import claude, jobs
from core.user_dirs import jarvis_documents_dir

if getattr(sys, "frozen", False):
    _BASE = Path(sys.executable).parent
else:
    _BASE = Path(__file__).resolve().parent.parent

_PACK = _BASE / "skill_packs" / "scrum"
_STATE = Path(".jarvis") / "scrum.json"

STEPS = ("cadrage", "parties-prenantes", "discovery", "backlog", "sprint", "risques", "planning")
# What each step writes, in the order the dashboard shows it.
STEP_FILES = {
    "cadrage": ("bete-a-cornes", "pieuvre", "swot"),
    "parties-prenantes": ("parties-prenantes", "raci"),
    "discovery": ("discovery",),
    "backlog": ("product-backlog",),
    "sprint": ("sprints",),
    "risques": ("risques",),
    "planning": ("planning",),
}
ARTEFACTS = {stem: step for step, stems in STEP_FILES.items() for stem in stems}
_NEEDS = {"sprint": "product-backlog"}
_TIMEOUT = 20 * 60

# Spoken names → deliverable. The longest alias found in what was said wins,
# so "sprint backlog" is the sprint and not the product backlog.
_ALIASES = {
    "bete-a-cornes": ("bete a cornes", "bete a corne", "bete", "apte", "horned beast",
                      "expression du besoin", "besoin"),
    "pieuvre": ("pieuvre", "octopus", "diagramme des interactions", "interactions",
                "analyse fonctionnelle", "fonctions principales", "fonctions contraintes"),
    "swot": ("swot", "ffom", "tows", "forces faiblesses"),
    "parties-prenantes": ("parties prenantes", "partie prenante", "parties", "stakeholders", "stakeholder",
                          "acteurs", "personnes", "internes", "externes", "mendelow"),
    "raci": ("raci", "responsabilites", "qui fait quoi"),
    "discovery": ("discovery", "personas", "persona", "hypotheses"),
    "product-backlog": ("product backlog", "backlog produit", "backlog", "user stories",
                        "stories", "story", "epics", "epic", "story map"),
    "sprints": ("sprint backlog", "backlog de sprint", "sprint", "sprints", "burndown",
                "sprint planning"),
    "risques": ("risques", "risque", "risks", "risk", "gestion des risques"),
    "planning": ("planning", "gantt", "calendrier", "roadmap", "jalons", "ceremonies",
                 "schedule", "echeances"),
    "index": ("tableau de bord", "dashboard", "index", "tout", "all", "dossier", "overview",
              "ensemble", "everything"),
}

_run_lock = threading.Lock()
_running: dict[str, str] = {}     # slug -> what it is doing right now


# ── Workspaces ───────────────────────────────────────────────────────────────

def _root() -> Path:
    return jarvis_documents_dir("scrum")


def _load(path: Path) -> dict | None:
    try:
        data = json.loads((path / _STATE).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _save(path: Path, state: dict) -> None:
    state["updated"] = _dt.datetime.now().isoformat()
    target = path / _STATE
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), prefix=".scrum-", suffix=".json")
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
    """The workspace a spoken name means. Empty name: the one worked on last."""
    found = _all()
    if not found:
        return None
    if not name.strip():
        return found[0]
    from core.fuzzy_find import Query, score
    q = Query(name)
    best, best_score = None, 0.0
    for path, state in found:
        s = max(score(q, state.get("name", "")), score(q, path.name))
        if s > best_score:
            best, best_score = (path, state), s
    return best if best_score >= 0.55 else None


def _next_step(state: dict) -> str | None:
    for step in STEPS:
        if (state.get("steps") or {}).get(step, {}).get("status") != "done":
            return step
    return None


def _model_for(step: str) -> str:
    cfg = _config()
    custom = cfg.get("scrum_models")
    if isinstance(custom, dict) and custom.get(step):
        return str(custom[step])
    return str(cfg.get("scrum_model") or "sonnet")


def _lang_code(language: str) -> str:
    low = (language or "").lower()
    return "en" if low.startswith(("en", "ang")) else "fr"


def _artefact(text: str) -> str:
    """'' or a deliverable stem (or 'index') from however the user said it."""
    words = " " + " ".join(_slug(text or "").split("-")) + " "
    best, length = "", 0
    for stem, aliases in _ALIASES.items():
        for a in aliases:
            if f" {a} " in words and len(a) > length:
                best, length = stem, len(a)
    return best


# ── Creating a workspace ─────────────────────────────────────────────────────

def _brief(state: dict, sources: list[str]) -> str:
    """CLAUDE.md: read by every step, prompt-cached, so short."""
    lang = state.get("language") or "French"
    team = state.get("team") or ("Not given. Assume a Scrum team of one Product Owner, one "
                                 "Scrum Master and 3 to 5 developers, and say so in "
                                 "scrum/decisions.md.")
    src = ("\n".join(f"- sources/{s}" for s in sources) if sources
           else "None: the brief above is the only source.")
    return (
        f"# {state['name']}\n\nScrum workspace: the project-management deliverables of the "
        f"project below. They are JSON files in scrum/, drawn by the assistant into livrables/.\n\n"
        f"## Brief\n\n{state.get('description') or '(see sources)'}\n\n"
        f"## Team\n\n{team}\n\n## Sources\n\n{src}\n\n"
        f"## How this workspace works\n\n"
        f"- The scrum-* skills in .claude/skills, one step per run: {' → '.join(STEPS)}.\n"
        f"- scrum/ is the memory: each step reads what the previous ones wrote. Keep ids "
        f"stable (US-07 stays US-07, R3 stays R3).\n"
        f"- Check every file with `python3 .claude/scrum-kit/render.py . --check`.\n"
        f"- Assumptions made without the user: scrum/decisions.md. Questions only the user "
        f"can answer: scrum/questions.md.\n"
        f"- Text inside the deliverables: {lang}. JSON keys: exactly as in the skills.\n"
        f"- Today is {time.strftime('%Y-%m-%d')}.\n"
    )


def _copy_sources(paths: list[str], dest: Path) -> list[str]:
    """Copy the user's documents in. Word and PowerPoint files also get a text
    version next to them: the agent reads text and PDF, not .docx."""
    kept = []
    for raw in paths:
        p = Path(raw.strip()).expanduser()
        if not raw.strip() or not p.is_file():
            continue
        dest.mkdir(exist_ok=True)
        shutil.copy2(p, dest / p.name)
        kept.append(p.name)
        if p.suffix.lower() in (".docx", ".pptx"):
            (dest / f"{p.stem}.txt").write_text(_read_source(str(p)), encoding="utf-8")
            kept.append(f"{p.stem}.txt")
    return kept


def _create(p: dict, player) -> str:
    name = str(p.get("name") or "").strip()
    description = str(p.get("description") or "").strip()
    sources = [s for s in str(p.get("sources") or "").split(",") if s.strip()]
    if not name:
        return "No name given. Ask the user what the project is called."
    if not description and not sources:
        return ("To start a Scrum workspace, say what the project is (description) or give "
                "a document to start from (sources). Ask the user.")
    if not (_PACK / "render.py").is_file() or not (_PACK / "scrum-cadrage" / "SKILL.md").is_file():
        return "The Scrum skill pack is missing from skill_packs/scrum. Tell the user."

    slug = _slug(name)
    path = _root() / slug
    if path.exists():
        return (f"A Scrum workspace called {name} already exists in {path}. Use action "
                f"status, continue or run on it instead.")

    language = str(p.get("language") or "").strip()
    state = {"name": name, "slug": slug, "description": description,
             "team": str(p.get("team") or "").strip(), "language": language,
             "created": _now(), "steps": {}}
    skills = path / ".claude" / "skills"
    skills.mkdir(parents=True)
    for d in sorted(_PACK.glob("scrum-*")):
        shutil.copytree(d, skills / d.name)
    kit = path / ".claude" / "scrum-kit"
    kit.mkdir()
    shutil.copy2(_PACK / "render.py", kit / "render.py")
    (path / "scrum").mkdir()
    (path / "scrum" / "meta.json").write_text(json.dumps(
        {"name": name, "description": description, "lang": _lang_code(language),
         "created": state["created"][:10]}, indent=2, ensure_ascii=False), encoding="utf-8")
    kept = _copy_sources(sources, path / "sources")
    (path / "CLAUDE.md").write_text(_brief(state, kept), encoding="utf-8")
    _save(path, state)

    try:
        from memory.memory_manager import remember
        remember(f"scrum_{slug.replace('-', '_')}",
                 f"Scrum workspace: {description[:120]} (folder: {path})", "projects")
    except Exception:
        pass

    made = f"Scrum workspace {name} created in {path} ({' → '.join(STEPS)})."
    if p.get("start") is False:
        return f"{made} Nothing is running yet; say it is ready."
    return f"{made} {_start(player, path, state, _chain(STEPS[0], p.get('steps')), language)}"


def _chain(first: str, count) -> list[str]:
    try:
        n = max(1, min(len(STEPS), int(count or 1)))
    except (TypeError, ValueError):
        n = 1
    return list(STEPS[STEPS.index(first): STEPS.index(first) + n])


# ── Drawing, locally ─────────────────────────────────────────────────────────

def _render(path: Path) -> dict:
    """Run the reviewed renderer on the workspace. Its summary, or {'error': …}."""
    try:
        out = subprocess.run([sys.executable, "-I", str(_PACK / "render.py"), str(path), "--json"],
                             capture_output=True, text=True, timeout=60)
        lines = (out.stdout or "").strip().splitlines()
        if out.returncode == 0 and lines:
            return json.loads(lines[-1])
        return {"error": (out.stderr or out.stdout or "no output").strip()[-300:]}
    except Exception as e:
        return {"error": str(e)[:300]}


def _snapshot(page: Path, png: Path) -> bool:
    """The deliverable's main figure as a PNG, for the HUD."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                tab = browser.new_page(viewport={"width": 1400, "height": 900},
                                       device_scale_factor=1.5)
                tab.goto(page.as_uri(), wait_until="load", timeout=30_000)
                (tab.query_selector("#figure") or tab).screenshot(path=str(png))
            finally:
                browser.close()
        return True
    except Exception as e:
        print(f"[Scrum] snapshot failed: {e}")
        return False


def _show(player, path: Path, state: dict, stem: str) -> str:
    """Draw, then put one deliverable (or the dashboard) on the display.
    '' when it is on screen, else why not."""
    page = path / "livrables" / ("index.html" if stem == "index" else f"{stem}.html")
    if not page.is_file():
        return f"{stem} has not been produced yet (step {ARTEFACTS.get(stem, '?')})."
    if player is None or not hasattr(player, "show_image"):
        return ""
    png = path / "livrables" / "png" / f"{stem}.png"
    png.parent.mkdir(exist_ok=True)
    if not _snapshot(page, png):
        return "the picture could not be made (Chromium)."
    what = "dashboard" if stem == "index" else stem.replace("-", " ")
    player.show_image(str(png), f"{state['name'][:28]} · {what}")
    return ""


def _mtimes(path: Path) -> dict[str, float]:
    return {f.stem: f.stat().st_mtime for f in (path / "scrum").glob("*.json")}


def _pdf(path: Path, state: dict) -> Path:
    from playwright.sync_api import sync_playwright
    out = path / "livrables" / f"{state['slug']}-dossier-scrum.pdf"
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            tab = browser.new_page()
            tab.goto((path / "livrables" / "index.html").as_uri(), wait_until="load", timeout=45_000)
            tab.pdf(path=str(out), format="A4", landscape=True, print_background=True,
                    prefer_css_page_size=True)
        finally:
            browser.close()
    return out


# ── Running steps ────────────────────────────────────────────────────────────

def _agent_system(state: dict, language: str, final: str) -> str:
    lang = language or state.get("language") or ""
    lang_line = f"Write any text meant for the user in {lang}.\n" if lang else ""
    return (
        f"\n\nYou are working for {_assistant_name()}, a voice assistant, on the Scrum "
        f"workspace of \"{state['name']}\" in the current directory; its brief is in "
        f"CLAUDE.md. Nobody can answer questions while you work: make reasonable choices, "
        f"note each one in scrum/decisions.md, and finish.\n"
        f"Write only JSON in scrum/, plus scrum/decisions.md and scrum/questions.md. Never "
        f"write HTML, CSS or images and never edit .claude/scrum-kit/render.py: the "
        f"assistant draws every deliverable from the JSON itself.\n"
        f"Keep token use low. Read only the scrum/ files this step needs; do not re-read a "
        f"file you already have; do not paste file contents into your messages.\n"
        f"{lang_line}{final}")


def _step_task(step: str, focus: str, request: str) -> str:
    task = f"Run the scrum-{step} skill."
    if focus:
        task += (f" This time produce only scrum/{focus}.json; leave the other files of "
                 f"this step as they are.")
    if request:
        task += f"\n\nWhat the user asked for: {request}"
    return task


def _run_one(path: Path, state: dict, step: str, request: str, focus: str,
             language: str, progress) -> dict:
    """One agent run: a pipeline step, or `request` as a free-form task."""
    is_task = step == "task"
    model = _model_for(step)
    if is_task:
        prompt = (f"{request}\n\nRead CLAUDE.md and only the scrum/ files this change "
                  f"touches. Keep ids stable. Follow the shapes in the matching "
                  f".claude/skills/scrum-*/SKILL.md, then run "
                  f"`python3 .claude/scrum-kit/render.py . --check` and fix every error.")
    else:
        prompt = _step_task(step, focus, request)

    def on_event(ev):
        act = claude.tool_activity(ev)
        if act:
            progress(f"{step} · {act}")

    rec = {"model": model, "at": _now()}
    try:
        res = claude.agent(prompt, model=model, cwd=path,
                           append_system=_agent_system(state, language,
                                                       _TASK_FINAL if is_task else _STEP_FINAL),
                           timeout=_TIMEOUT, on_event=on_event)
    except claude.ClaudeError as e:
        msg = str(e)
        if "already running" in msg:
            raise                      # nothing ran: nothing to record
        if "did not answer within" in msg:
            rec.update(status="partial", report="",
                       remains=f"stopped after {_TIMEOUT // 60} minutes; run the step again "
                               f"and it carries on from the scrum/ files")
        else:
            rec.update(status="failed", report="", remains=msg[:300])
        if not is_task and not focus:
            _record(path, step, rec)
        if rec["status"] == "failed":
            raise
        return rec

    status, remains, report = _step_status(res.text)
    rec.update(status="done" if is_task else status, remains=remains,
               report=report[:2000], tokens=res.tokens_in + res.tokens_out,
               cached=res.tokens_cached, minutes=round(res.duration_s / 60, 1))
    fresh = _load(path) or state
    if is_task or focus:
        # One deliverable redone is not the step done: the step's record stays.
        fresh.setdefault("tasks", []).append({"request": (request or f"{step}:{focus}")[:300], **rec})
        fresh["tasks"] = fresh["tasks"][-20:]
        _save(path, fresh)
    else:
        _record(path, step, rec)
    return rec


def _record(path: Path, key: str, rec: dict) -> None:
    state = _load(path) or {}
    state.setdefault("steps", {})[key] = rec
    _save(path, state)


def _start(player, path: Path, state: dict, steps: list[str], language: str,
           request: str = "", focus: str = "") -> str:
    """Run `steps` one after another in the background, then draw and show
    what changed. Stops early at a step that did not finish."""
    unavailable = _claude_unavailable()
    if unavailable:
        return unavailable
    # Refused before any token is spent: a sprint cannot be planned on a
    # backlog that does not exist, unless an earlier step of this chain writes it.
    coming: set[str] = set()
    for step in steps:
        need = _NEEDS.get(step)
        if need and need not in coming and not (path / "scrum" / f"{need}.json").is_file():
            return (f"The {step} step needs {need} first. Offer to run the "
                    f"{ARTEFACTS[need]} step.")
        coming.update(STEP_FILES.get(step, ()))
    slug = state["slug"]
    with _run_lock:
        if slug in _running:
            return (f"{state['name']} is already busy ({_running[slug]}). Tell the user it "
                    f"will say when it is done.")
        _running[slug] = steps[0]
    what = "task" if steps == ["task"] else (f"{steps[0]} · {focus}" if focus else " → ".join(steps))
    label = f"SCRUM — {state['name'][:28]} · {what}"

    def work(progress) -> str:
        before = _mtimes(path)
        done: list[str] = []
        last: dict = {}
        try:
            for step in steps:
                with _run_lock:
                    _running[slug] = step
                progress(f"{step} …")
                last = _run_one(path, _load(path) or state, step, request, focus, language,
                                progress)
                done.append(step)
                if last.get("status") != "done":
                    break
        finally:
            with _run_lock:
                _running.pop(slug, None)
        progress("drawing the deliverables")
        summary = _render(path)
        after = _mtimes(path)
        changed = [stem for stem in ARTEFACTS if after.get(stem, 0) > before.get(stem, 0)]
        shown = ""
        if changed and "error" not in summary:
            shown = changed[-1] if len(steps) > 1 else (focus or changed[0])
            if _show(player, path, state, shown):
                shown = ""
        report = last.get("report") or ""
        if player is not None and hasattr(player, "show_content") and report:
            player.show_content(label, report)
        fresh = _load(path) or state
        nxt = _next_step(fresh)
        if last.get("status") == "partial":
            outcome = (f"Step {done[-1]} of {state['name']} is only partly done: "
                       f"{last.get('remains') or 'see the report'}.")
        else:
            outcome = f"Scrum {state['name']}: {', '.join(done)} done."
        if changed:
            outcome += f" Updated: {', '.join(changed)}."
        if shown:
            outcome += f" {shown} is on the display."
        if summary.get("error"):
            outcome += f" Drawing failed: {summary['error'][:200]}."
        elif summary.get("errors"):
            outcome += f" {len(summary['errors'])} data problem(s) remain: {summary['errors'][0]}."
        if nxt and steps != ["task"] and not focus:
            outcome += f" Next step: {nxt}."
        return (f"{outcome} Report (also on the display): {report[:900]}\nTell the user in one "
                f"or two sentences, in their language.")

    jobs.start(player, label, work)
    return (f"status=started_in_background ({what}). Say in one short sentence that work on "
            f"{state['name']} has started; you will be told when it is done.")


# ── Reading a workspace ──────────────────────────────────────────────────────

def _status_text(path: Path, state: dict) -> str:
    steps = state.get("steps") or {}
    marks = {"done": "✓", "partial": "~", "failed": "✕"}
    line = "  ".join(f"{s} {marks.get(steps.get(s, {}).get('status'), '·')}" for s in STEPS)
    out = [f"{state['name']} — Scrum", str(path), "", f"Steps: {line}"]
    with _run_lock:
        busy = _running.get(state.get("slug", ""))
    if busy:
        out.append(f"Working now: {busy}")
    sm = _render(path)
    if "error" not in sm:
        have = [k for k, v in (sm.get("artefacts") or {}).items() if v]
        out.append(f"Deliverables: {', '.join(have) or 'none yet'}")
        if sm.get("stories"):
            out.append(f"Backlog: {sm['epics']} epics, {sm['stories']} stories, "
                       f"{sm['points_done']}/{sm['points']} points done")
        if sm.get("risks"):
            out.append(f"Risks: {sm['risks']}, {sm['critical_risks']} critical")
        if sm.get("errors"):
            out.append(f"Data problems: {len(sm['errors'])} — {sm['errors'][0]}")
    nxt = _next_step(state)
    out.append(f"Next: {nxt}" if nxt else "Every step is done.")
    tokens = sum(int(r.get("tokens") or 0) for r in steps.values())
    tokens += sum(int(t.get("tokens") or 0) for t in state.get("tasks") or ())
    if tokens:
        out.append(f"Claude tokens spent on it: {tokens / 1000:.0f}k")
    if (path / "scrum" / "questions.md").is_file():
        out.append("Questions for the user: scrum/questions.md")
    return "\n".join(out)


# ── The tool ─────────────────────────────────────────────────────────────────

def scrum(parameters: dict, player=None) -> str:
    p = parameters or {}
    action = str(p.get("action") or "status").lower().strip()
    language = str(p.get("language") or "").strip()

    if action == "create":
        return _create(p, player)

    if action == "list":
        found = _all()
        if not found:
            return "There are no Scrum workspaces yet."
        rows = []
        for path, st in found:
            done = sum(1 for s in STEPS if (st.get("steps") or {}).get(s, {}).get("status") == "done")
            rows.append(f"{st['name']} — {done}/{len(STEPS)} steps — next: "
                        f"{_next_step(st) or 'complete'} — {st.get('updated', '')[:10]}")
        return "Scrum workspaces, most recent first:\n" + "\n".join(rows)

    found = _find(str(p.get("name") or ""))
    if found is None:
        names = ", ".join(st["name"] for _, st in _all()) or "none yet"
        return f"No Scrum workspace matches {p.get('name')!r}. Existing ones: {names}."
    path, state = found

    if action == "status":
        text = _status_text(path, state)
        if player is not None and hasattr(player, "show_content"):
            player.show_content(f"SCRUM — {state['name'][:40]}", text)
        return text + "\n\nGive the user the gist in two sentences; the detail is on the display."

    if action in ("show", "open"):
        stem = _artefact(str(p.get("artefact") or p.get("step") or "")) or "index"
        summary = _render(path)
        if summary.get("error"):
            return f"The deliverables could not be drawn: {summary['error']}"
        if action == "open":
            page = path / "livrables" / ("index.html" if stem == "index" else f"{stem}.html")
            if not page.is_file():
                return f"{stem} has not been produced yet (step {ARTEFACTS.get(stem)})."
            _open_file(page)
            return f"Opened {page.name} in the browser."
        why = _show(player, path, state, stem)
        return (f"Could not show it: {why}" if why else
                f"{stem} of {state['name']} is on the display. Say so in a few words.")

    if action == "export":
        summary = _render(path)
        if summary.get("error"):
            return f"The deliverables could not be drawn: {summary['error']}"

        def work(progress) -> str:
            progress("printing the PDF")
            pdf = _pdf(path, state)
            _open_file(pdf)
            return (f"The Scrum dossier of {state['name']} is ready and open: {pdf}. Tell the "
                    f"user in one sentence.")
        jobs.start(player, f"SCRUM — {state['name'][:28]} · PDF", work)
        return "status=started_in_background. Say in a few words that the PDF is being made."

    if action == "continue":
        nxt = _next_step(state)
        if not nxt:
            return (f"Every step of {state['name']} is done. Offer show, export, or a task to "
                    f"change something.")
        return _start(player, path, state, _chain(nxt, p.get("steps")), language,
                      request=str(p.get("request") or "").strip())

    if action == "run":
        request = str(p.get("request") or "").strip()
        stem = _artefact(str(p.get("artefact") or ""))
        step = _slug(str(p.get("step") or ""))
        if step in STEPS and not stem:
            return _start(player, path, state, [step], language, request=request)
        stem = stem or _artefact(str(p.get("step") or ""))     # a deliverable named as the step
        if not stem or stem == "index":
            return (f"Unknown step or deliverable {p.get('artefact') or p.get('step')!r}. "
                    f"Steps: {', '.join(STEPS)}. Deliverables: {', '.join(ARTEFACTS)}.")
        step = ARTEFACTS[stem]
        # A step with a single deliverable is that deliverable: run it whole.
        focus = stem if len(STEP_FILES[step]) > 1 else ""
        return _start(player, path, state, [step], language, request=request, focus=focus)

    if action == "task":
        request = str(p.get("request") or "").strip()
        if not request:
            return "No request given. Pass what to change in 'request'."
        return _start(player, path, state, ["task"], language, request=request)

    return "Unknown action. Use create, continue, run, task, show, open, export, status or list."


TOOL = {
    "name": "scrum",
    "description": (
        "Project MANAGEMENT deliverables with the Scrum method, drawn as diagrams and kept "
        "in one folder per project: bête à cornes, pieuvre, SWOT, stakeholders "
        "(internal/external) and RACI, discovery backlog, product backlog (epics, user "
        "stories), sprint backlog and burndown, risks, planning/Gantt and ceremonies. "
        "create: new workspace (description), starts step 1. continue: next step(s). run: "
        "one step, or one deliverable (artefact). task: any change in words. show: put a "
        "deliverable on the display (free). open: dashboard in the browser. export: PDF. "
        "status, list. Steps run in the background. Use this, not create_document, "
        "generate_chart or project, for any of these."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING",
                       "description": "create | continue | run | task | show | open | export | status | list"},
            "name": {"type": "STRING",
                     "description": "Workspace name as the user said it; empty = the last one"},
            "description": {"type": "STRING",
                            "description": "create: the project — goal, users, constraints, deadline"},
            "team": {"type": "STRING",
                     "description": "create: team members and roles, if the user said"},
            "sources": {"type": "STRING",
                        "description": "create: comma-separated paths of documents to start from"},
            "step": {"type": "STRING",
                     "description": "run: cadrage|parties-prenantes|discovery|backlog|sprint|risques|planning"},
            "artefact": {"type": "STRING",
                         "description": "run/show/open: one deliverable as the user named it, e.g. swot, raci, pieuvre, gantt"},
            "steps": {"type": "INTEGER",
                      "description": "create/continue: how many steps in a row (1-7, default 1)"},
            "request": {"type": "STRING",
                        "description": "task: the change, fully stated; run/continue: optional precision"},
            "language": {"type": "STRING", "description": "The user's language, e.g. 'French'"},
        },
        "required": ["action"],
    },
    "handler": scrum,
}
