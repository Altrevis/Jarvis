"""
agents — a team of IT specialist agents, by voice.

    "Monte une équipe pour sécuriser et dockeriser mon API Flask"
        create    the lead plans (cyber: audit, devops: Dockerfile and CI),
                  the specialists work — in parallel when they can —, a
                  reviewer checks, and the report comes back in the background
    "Demande à l'agent réseau un plan d'adressage pour trois VLAN"
        delegate  one specialist, no plan, no review
    "Propose-moi d'abord le plan"  plan  ·  "Vas-y"  continue
    "Où en est la mission ?"  status  ·  "Arrête les agents"  cancel
    "Quels agents as-tu ?"  spaces

The team is core/orchestrator.py and the skill spaces are core/spaces.py;
this file only turns what they return into what the voice model is told.
Like projects, it needs Claude: "Gemini only" mode hides it.
"""
from __future__ import annotations

import os
from pathlib import Path

from actions.project import _claude_unavailable, _open
from core import jobs, orchestrator, spaces

_REPORT_CHARS = 900


def _show(player, title: str, text: str) -> None:
    if player is not None and hasattr(player, "show_content") and text:
        player.show_content(title, text)


def _title(state: dict) -> str:
    return (state.get("plan") or {}).get("title") or state.get("name") or "mission"


def _too_broad(folder: Path) -> bool:
    """A filesystem root, the home folder, one of the user's standard folders
    (Documents, Desktop...) or a system folder: agents get write access to a
    target, so it must be a project, not a whole tree."""
    try:
        folder = folder.resolve()
        home = Path.home().resolve()
    except OSError:
        return True
    if folder.parent == folder or folder == home:
        return True
    if folder.parent == home and folder.name.lower() in {
            "desktop", "bureau", "documents", "downloads", "téléchargements",
            "pictures", "images", "music", "musique", "videos", "vidéos", "public"}:
        return True
    try:
        from core.user_dirs import user_dir
        if folder in {user_dir(k).resolve() for k in ("desktop", "downloads", "documents",
                                                      "pictures", "music", "videos")}:
            return True
    except Exception:
        pass
    system = {"/etc", "/usr", "/bin", "/sbin", "/lib", "/var", "/opt", "/boot", "/sys", "/proc",
              "/System", "/Library", "/Applications"}
    if str(folder) in system or any(str(folder).startswith(s + "/") for s in ("/etc", "/usr", "/System")):
        return True
    win = str(folder).lower().rstrip("\\")
    return win.endswith((":\\windows", ":\\program files", ":\\program files (x86)", ":\\users"))


def _targets(raw) -> tuple[list[str], str, str]:
    """The folder the team works on, from a path or the name of one of the
    user's projects: ([folders], a line to add to the request, a note for
    the voice model)."""
    text = str(raw or "").strip().strip("\"'")
    if not text:
        return [], "", ""
    p = Path(os.path.expandvars(text)).expanduser()
    if p.exists():
        p = p.resolve()
        folder = p if p.is_dir() else p.parent
        if _too_broad(folder):
            return [], "", (f" The target {folder} is too broad to hand to unattended agents "
                            f"(they could change anything in it), so the team works without "
                            f"it; ask the user for the project folder itself.")
        if p.is_dir():
            return [str(p)], "", ""
        return [str(p.parent)], f"\n\nThe file this is about: {p}", ""
    try:
        from actions.project import _find as _find_project
        found = _find_project(text)
    except Exception:
        found = None
    if found:
        return [str(found[0])], "", f" It works on the project {found[1].get('name')}."
    return [], "", f" The target {text!r} was not found, so the team works without it."


def _outcome(player, path: Path, res: dict) -> str:
    """What the voice model is told when a run ends."""
    state = res.get("state") or orchestrator.load(path) or {}
    title = _title(state)
    tasks = (state.get("plan") or {}).get("tasks") or []
    recs = state.get("tasks") or {}
    done, total = orchestrator.counts(state)
    per = ", ".join(f"{t['id']} {t['space']} {(recs.get(t['id']) or {}).get('status', 'pending')}"
                    for t in tasks)
    report_file = Path(res.get("report") or "")
    report = ""
    if report_file.is_file():
        report = report_file.read_text(encoding="utf-8", errors="replace").strip()
        _show(player, f"AGENTS — {title[:38]}", report)
    if res.get("status") == orchestrator.CANCELLED:
        return (f"The mission {title} was stopped ({done}/{total} tasks done: {per}). What is "
                f"done is kept; continue resumes the rest. Tell the user in one sentence.")
    out = f"Mission {title}: {done}/{total} tasks done ({per})."
    left = [f"{t['id']}: {(recs.get(t['id']) or {}).get('remains')}" for t in tasks
            if (recs.get(t["id"]) or {}).get("status") != orchestrator.DONE
            and (recs.get(t["id"]) or {}).get("remains")]
    if left:
        out += f" Not finished — {'; '.join(left)[:400]}."
    rv = res.get("review") or {}
    if rv.get("status") == orchestrator.DONE:
        out += f" The reviewer found {rv.get('issues', 0)} issue(s)"
        if rv.get("fixed"):
            out += f", fixed by {', '.join(rv['fixed'])}"
        if rv.get("unfixed"):
            out += f", still open in {', '.join(rv['unfixed'])}"
        out += "."
    elif rv:
        out += f" The review did not complete ({rv.get('error') or rv.get('status')})."
    where = report_file if report_file.is_file() else path / "work"
    out += f" Everything is in {path / 'work'}."
    if report:
        out += f" Report (also on the display, file {where}): {report[:_REPORT_CHARS]}"
    return out + "\nTell the user in one or two sentences, in their language."


def _launch(player, path: Path, state: dict, cancel_ev, what: str, note: str = "") -> str:
    label = f"AGENTS — {_title(state)[:30]} · {what}"

    def on_plan(st: dict) -> None:
        _show(player, f"AGENTS — {_title(st)[:38]}", orchestrator.plan_text(st))

    def work(progress) -> str:
        return _outcome(player, path, orchestrator.run(path, cancel_ev, progress, on_plan=on_plan))

    try:
        jobs.start(player, label, work)
    except Exception:
        orchestrator.release(path.name)
        raise
    planning = not (state.get("plan") or {}).get("tasks")
    first = ("the lead is planning, then the specialists work" if planning
             else f"{len(state['plan']['tasks'])} task(s)")
    return (f"status=started_in_background ({first}).{note} Say in one short sentence that the "
            f"team is on it; you will be told when it is done.")


def _spaces_text(space=None) -> tuple[str, str]:
    """(for the display, for the voice model)."""
    if space is not None:
        skills = "\n".join(f"  · {k['name']}: {k['description'][:160]}" for k in space.skills)
        text = f"{space.line()}\n{skills or '  (no skill yet)'}"
        return text, text
    sps = spaces.all_spaces()
    display = "\n".join(s.line() for s in sps)
    voice = "\n".join(f"- {s.id} ({s.title}): {len(s.skills)} skill(s)" for s in sps)
    return display, voice


def agents(parameters: dict, player=None) -> str:
    p = parameters or {}
    action = str(p.get("action") or "status").lower().strip()
    language = str(p.get("language") or "").strip()
    request = str(p.get("request") or "").strip()
    name = str(p.get("name") or "").strip()
    review = p.get("review") if isinstance(p.get("review"), bool) else None

    if action == "spaces":
        if not spaces.all_spaces():
            return "No skill space is installed (the skill_spaces folder is empty). Tell the user."
        sp = spaces.resolve(str(p.get("space") or "")) if p.get("space") else None
        display, voice = _spaces_text(sp)
        _show(player, "AGENTS — " + (sp.title if sp else "skill spaces"), display)
        return (f"{voice}\n\nGive the user the gist in a sentence or two; the detail is on the "
                f"display. A skill is added to a space with manage_skills (space=...).")

    if action == "list":
        found = orchestrator.all_missions()
        if not found:
            return "There are no agent missions yet."
        rows = []
        for path, st in found[:15]:
            done, total = orchestrator.counts(st)
            running = " (running now)" if orchestrator.is_running(path.name) else ""
            rows.append(f"{_title(st)} — {st.get('kind', 'team')} — {done}/{total} tasks done — "
                        f"{st.get('status', 'new')}{running} — {st.get('updated', '')[:10]}")
        return "Agent missions, most recent first:\n" + "\n".join(rows)

    if action in ("create", "plan", "delegate"):
        if not request:
            return "No request given. Pass the full task, with every detail the user gave, in 'request'."
        unavailable = _claude_unavailable()
        if unavailable:
            return unavailable.replace("Projects are", "The agent team is")
        if not spaces.all_spaces():
            return "No skill space is installed (the skill_spaces folder is empty). Tell the user."
        targets, extra, note = _targets(p.get("target"))
        full = request + extra

        if action == "delegate":
            sp = spaces.resolve(str(p.get("space") or "")) if p.get("space") else None
            if sp is None:
                hits = spaces.match(request, 1)
                sp = hits[0][0] if hits else None
            if sp is None:
                return (f"Which specialist should do it? Spaces: {', '.join(spaces.ids())}. Ask "
                        f"the user, or use action create and let the lead choose.")
            path, state = orchestrator.create(full, name=name, language=language, targets=targets,
                                              kind="delegate", review=review)
            state = orchestrator.set_plan(path, orchestrator.plan_for_space(sp, full, title=name))
            ev = orchestrator.claim(path.name)
            return _launch(player, path, state, ev, sp.id, f" The {sp.title} specialist does it.{note}")

        path, state = orchestrator.create(full, name=name, language=language, targets=targets,
                                          kind="team", review=review)
        ev = orchestrator.claim(path.name)
        if action == "plan":
            def work(progress) -> str:
                try:
                    st = orchestrator.make_plan(path, progress)
                finally:
                    orchestrator.release(path.name)
                text = orchestrator.plan_text(st)
                _show(player, f"AGENTS — {_title(st)[:38]}", text)
                n = len(st["plan"]["tasks"])
                return (f"The plan '{_title(st)}' is ready, {n} task(s), not started yet:\n{text[:1500]}"
                        f"\nTell the user in one or two sentences what the team would do, and that "
                        f"saying continue starts it.")
            try:
                jobs.start(player, f"AGENTS — {name or request[:30]} · plan", work)
            except Exception:
                orchestrator.release(path.name)
                raise
            return (f"status=started_in_background. The lead is planning.{note} Say in one short "
                    f"sentence that the plan is coming.")
        return _launch(player, path, state, ev, "mission", note)

    found = orchestrator.find(name)
    if found is None:
        names = ", ".join(_title(st) for _, st in orchestrator.all_missions()[:10]) or "none yet"
        return f"No agent mission matches {name!r}. Missions: {names}."
    path, state = found
    title = _title(state)

    if action == "status":
        text = orchestrator.status_text(path, state)
        _show(player, f"AGENTS — {title[:38]}", text)
        return text + "\n\nGive the user the gist in two sentences; the detail is on the display."

    if action == "open":
        return _open(path / "work" if (path / "work").is_dir() else path)

    if action == "cancel":
        if orchestrator.cancel(path.name):
            return (f"Stopping the mission {title}: its agents stop within seconds; what is done "
                    f"is kept and continue resumes the rest. Say so in one sentence.")
        return f"The mission {title} is not running."

    if action == "continue":
        unavailable = _claude_unavailable()
        if unavailable:
            return unavailable.replace("Projects are", "The agent team is")
        done, total = orchestrator.counts(state)
        if total and done == total:
            return (f"Every task of {title} is done; the report is in "
                    f"{path / 'work' / 'REPORT.md'}. Offer status, or a new mission.")
        if review is not None:
            orchestrator.update(path, lambda s: s.update(review=review))
        ev = orchestrator.claim(path.name)
        if ev is None:
            return f"The mission {title} is already running. Tell the user it will say when it is done."
        return _launch(player, path, orchestrator.load(path) or state, ev, "continue")

    return "Unknown action. Use create, plan, delegate, continue, cancel, status, list, open or spaces."


TOOL = {
    "name": "agents",
    "description": (
        "A team of IT specialist agents (Claude), each with its own skill space: "
        f"{', '.join(spaces.ids()) or 'none installed'}. "
        "create: a mission — a lead plans the tasks, the specialists do them (in parallel when "
        "independent) and a reviewer checks; runs in the background. plan: the plan only, "
        "continue starts it. delegate: one specialist (space) does one task. continue: run what "
        "is not done yet. cancel, status, list, open, spaces (what each specialist covers). For "
        "IT work: code, security, networks, servers, cloud, DevOps, databases, data, ML, AI "
        "agents, UI design, tests, architecture. An app built step by step over days is the "
        "project tool."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING",
                       "description": "create | plan | delegate | continue | cancel | status | list | open | spaces"},
            "request": {"type": "STRING",
                        "description": "create/plan/delegate: the work, fully stated, with every detail the user gave"},
            "space": {"type": "STRING",
                      "description": "delegate: the specialist (e.g. cyber, network, devops); spaces: one to detail"},
            "name": {"type": "STRING",
                     "description": "create: a short mission name (optional); other actions: the mission as the user said it, empty = the last one"},
            "target": {"type": "STRING",
                       "description": "The folder or file the team works on (full path), or the name of one of the user's projects"},
            "review": {"type": "BOOLEAN",
                       "description": "Force the reviewer on or off (default: on when the plan has several tasks)"},
            "language": {"type": "STRING", "description": "The user's language, e.g. 'French'"},
        },
        "required": ["action"],
    },
    "handler": agents,
}
