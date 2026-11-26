"""
direction — « Direction Projet »: one brief in, the whole project file out.

WHAT IT DOES
    The user describes a project once, on the Direction Projet page of the
    window (ui.py: a free prompt, or a questionnaire), and this chains in one
    background job what would otherwise be five separate requests:

        scrum         the Scrum file, cahier des charges included, then its
                      PDF and Word export                    (actions/scrum.py)
        ddd           the domain model: ubiquitous language → bounded
                      contexts and context map → aggregates, in the same
                      workspace                                (actions/ddd.py)
        chiffrage     WBS → estimation → budget → TCO → pitch, in the same
                      workspace                          (actions/chiffrage.py)
        code          the Replica pipeline for an original idea, spec → diff,
                      started from the cahier des charges, the backlog and
                      the domain model                     (actions/project.py)
        presentation  the defence deck, PowerPoint and web
                                                   (actions/create_document.py)

    The order is the one the deliverables depend on: the domain model is
    drawn from the specification and the backlog, the estimate breaks the
    work down by bounded context, the code is written in the model's
    language, the deck tells all of it.

WHY IT CALLS THE STEP FUNCTIONS AND NOT THE TOOLS
    Each tool starts its own background job and returns at once, so chaining
    the tools would mean jobs racing on half-written files. Here every step is
    the same _run_one the tools use — same prompts, same checks, same records
    in each folder's state — one after another in a single job. A project
    started here can be continued by voice with the scrum and project tools,
    and the other way round.

WHAT IT COSTS, AND HOW THAT STAYS UNDER CONTROL
    It is the most expensive thing the assistant does: up to 24 agent runs
    (Scrum 8, DDD 3 and chiffrage 5 on Sonnet, the code 7 of which architect,
    build and backend on the agent model, the deck 1). So:
    - the page shows how many runs each phase is and on which model, and any
      phase can be left out;
    - the questionnaire is turned into a brief here, locally: no model call;
    - nothing is done twice: a launch on a name that exists resumes it, and
      every step already done in its folder is skipped;
    - it stops cleanly after the step in progress — on the STOP button, when
      Claude reaches its usage limit, or when a step the next ones build on
      is left partial;
    - a project already made is changed part by part (modify): one agent run
      on the part named, never the chain again.

NOT A TOOL
    No TOOL dict: the page is the way in, and the voice session does not pay
    for one more declaration. The end of the run is announced like any other
    job ([TASK_DONE]), and the scrum and project tools answer "where is it at".
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import random
import tempfile
import threading
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

from actions import chiffrage, create_document, ddd, project, scrum
from actions.project import _slug
from core import claude, jobs
from core.user_dirs import jarvis_documents_dir

PHASES = ("scrum", "ddd", "chiffrage", "code", "presentation")
LABELS = {
    "scrum": "Dossier Scrum & cahier des charges",
    "ddd": "Modèle du domaine DDD (langage → contextes → agrégats)",
    "chiffrage": "Chiffrage (WBS → budget → TCO → pitch)",
    "code": "Code (Replica : spec → build → tests)",
    "presentation": "Présentation de soutenance (PowerPoint + web)",
}
_STATE = "direction.json"
_DECK_SLIDES = 12
# Questionnaire types that are pages and content: nothing to store, no one to
# log in. Their code is a static site (no backend step), and the page unticks
# the domain model for them — Evans keeps DDD for complex domains, and a
# showcase site has no business logic to model.
STATIC_TYPES = ("Site vitrine",)
# Every Claude slot busy with other work (a voice request, another job): wait
# this long between tries rather than give up a run of twenty steps.
_SLOT_PAUSE = 30
_SLOT_TRIES = 10

_lock = threading.Lock()
_active: dict[str, threading.Event] = {}     # slug -> its stop request


class _Stop(Exception):
    """The run ends here on purpose; the message says why, in French."""


# ── State ────────────────────────────────────────────────────────────────────

def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def _root() -> Path:
    return jarvis_documents_dir("direction")


def _load(path: Path) -> dict:
    try:
        data = json.loads((path / _STATE).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save(path: Path, state: dict) -> None:
    state["updated"] = _now()
    path.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path), prefix=".direction-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path / _STATE)


def _set(path: Path, **values) -> dict:
    state = _load(path)
    state.update(values)
    _save(path, state)
    return state


def _scrum_dir(slug: str) -> Path:
    return scrum._root() / slug


def _project_dir(slug: str) -> Path:
    return project._root() / slug


def _done(state: dict | None, step: str) -> bool:
    return ((state or {}).get("steps") or {}).get(step, {}).get("status") == "done"


# ── What the page shows before a run ─────────────────────────────────────────

def _models(models) -> str:
    """'5 × sonnet · 3 × opus' — what a phase will be billed on."""
    return " · ".join(f"{n} × {m}" for m, n in Counter(models).items())


def plan() -> list[dict]:
    """Each phase with its number of agent runs and their models, from the
    same settings the steps will use."""
    agent = claude.model_for(claude.AGENT)
    runs = {
        "scrum": [scrum._model_for(s) for s in scrum.STEPS],
        "ddd": [ddd.model_for(s) for s in ddd.STEPS],
        "chiffrage": [chiffrage.model_for(s) for s in chiffrage.STEPS],
        "code": [project._model_for(s) for s in project.IDEA_STEPS],
        "presentation": [agent],
    }
    return [{"key": k, "label": LABELS[k], "runs": len(runs[k]), "models": _models(runs[k])}
            for k in PHASES]


def lookup(name: str) -> dict:
    """What already exists under this name: a launch on it resumes."""
    slug = _slug(name) if name.strip() else ""
    if not slug:
        return {"slug": "", "direction": False, "scrum": False, "project": False}
    return {"slug": slug,
            "direction": (_root() / slug / _STATE).is_file(),
            "scrum": (_scrum_dir(slug) / scrum._STATE).is_file(),
            "project": (_project_dir(slug) / project._STATE).is_file()}


def unavailable() -> str:
    """Why Claude cannot run the project right now, in French, or ''."""
    if claude.engine() != "claude":
        return "Claude est désactivé : ⚙ SETUP → CLAUDE est réglé sur Gemini seul."
    if not claude.binary():
        return "Claude Code n'est pas installé sur cet ordinateur (claude.com/claude-code)."
    resting = claude.cooling()
    if resting:
        return f"Claude se repose en ce moment ({resting}). Relance plus tard : rien ne sera refait."
    return ""


# ── The brief ────────────────────────────────────────────────────────────────

def _one_line(text) -> str:
    return " ".join(str(text or "").split())


def _bullets(text) -> str:
    items = [line.strip().lstrip("-•*·").strip() for line in str(text or "").splitlines()]
    return "\n".join(f"- {item}" for item in items if item)


def is_static(answers: dict | None) -> bool:
    """A project whose code is a static site: a STATIC_TYPES questionnaire
    answer. A free prompt is never guessed at ("un site vitrine et une
    boutique" is not one)."""
    return _one_line((answers or {}).get("type")) in STATIC_TYPES


def brief_from_answers(a: dict) -> str:
    """The questionnaire as the brief every agent reads (CLAUDE.md), in French
    like the deliverables. Empty answers are left out, never invented."""
    head = []
    if _one_line(a.get("type")):
        head.append(f"Type de projet : {_one_line(a['type'])}")
    if is_static(a):
        head.append("Taille : des pages et du contenu, sans back-end, base de données ni "
                    "comptes — chaque livrable reste à la mesure d'un site vitrine")
    if _one_line(a.get("cadre")):
        head.append(f"Cadre : {_one_line(a['cadre'])}")

    sections = [
        ("Le besoin", str(a.get("besoin") or "").strip()),
        ("Utilisateurs cibles", str(a.get("cible") or "").strip()),
        ("Fonctionnalités indispensables", _bullets(a.get("indispensable"))),
        ("Plus tard / hors périmètre", _bullets(a.get("plus_tard"))),
    ]
    data = {"Oui": "oui — le projet traite des données personnelles (RGPD à prendre en compte)",
            "Non": "non", "Je ne sais pas": "à déterminer pendant le cadrage"}
    constraints = [
        ("Délai", _one_line(a.get("delai"))),
        ("Budget", _one_line(a.get("budget"))),
        ("Technique imposée", _one_line(a.get("technique"))
         or "aucune — au choix de l'équipe, choix à justifier"),
        ("Données personnelles", data.get(_one_line(a.get("donnees")), "")),
    ]
    sections.append(("Contraintes", "\n".join(f"- {k} : {v}" for k, v in constraints if v)))
    sections.append(("Remarques", str(a.get("remarques") or "").strip()))

    out = "\n".join(head)
    for title, body in sections:
        if body:
            out += f"\n\n## {title}\n\n{body}"
    return out.strip()


# ── Launching ────────────────────────────────────────────────────────────────

def launch(form: dict, player=None) -> tuple[bool, str]:
    """Start (or resume) a Direction Projet run. (started, message for the page).

    form: name, language ("French" | "English"), phases (keys of PHASES),
    mode ("libre" | "questionnaire"), prompt (libre) or answers (questionnaire)."""
    name = _one_line(form.get("name"))
    if not name:
        return False, "Donne un nom au projet."
    phases = [p for p in PHASES if p in (form.get("phases") or ())]
    if not phases:
        return False, "Coche au moins une étape."
    mode = "questionnaire" if form.get("mode") == "questionnaire" else "libre"
    answers = form.get("answers") or {}
    if mode == "questionnaire":
        brief = brief_from_answers(answers) if str(answers.get("besoin") or "").strip() else ""
    else:
        brief = str(form.get("prompt") or "").strip()

    slug = _slug(name)
    path = _root() / slug
    state = _load(path)
    if not brief and not state.get("brief"):
        return False, ("Décris le projet : le prompt, ou au moins « Le besoin » "
                       "dans le questionnaire.")
    problem = unavailable()
    if problem:
        return False, problem

    with _lock:
        if slug in _active:
            return False, f"« {name} » est déjà en cours : suis-le ci-dessous."
        stop = threading.Event()
        _active[slug] = stop
    resumed = bool(state)
    old_brief = state.get("brief", "")
    state.update(name=state.get("name") or name, slug=slug, phases=phases,
                 language=str(form.get("language") or "French"), mode=mode,
                 status="running", current="", note="", started=_now())
    state.setdefault("created", _now())
    if brief:
        # Kept for the user to read and edit; the agents read it from CLAUDE.md.
        state["brief"] = brief
        path.mkdir(parents=True, exist_ok=True)
        (path / "brief.md").write_text(f"# {state['name']}\n\n{brief}\n", encoding="utf-8")
    if mode == "questionnaire" and answers:
        state["answers"] = answers
    if _one_line(answers.get("equipe")):
        state["team"] = _one_line(answers["equipe"])
    _save(path, state)
    synced = _sync_brief(slug, old_brief, brief) if brief and old_brief and brief != old_brief else []

    jobs.start(player, f"DIRECTION — {state['name'][:28]}",
               lambda progress: _work(player, path, slug, stop, progress))
    what = " → ".join(LABELS[p].split(" (")[0].lower() for p in phases)
    msg = (f"{'Reprise' if resumed else 'Lancement'} : {what}. Tu peux quitter cette "
           f"page, le suivi continue ici et dans la barre des tâches.")
    if synced:
        msg += (" Brief mis à jour pour la suite — ce qui est déjà produit ne change pas : "
                "pour ça, MODIFIER CE PROJET.")
    return True, msg


def request_stop(name: str) -> bool:
    """Ask the run to end after the step in progress. False if none runs."""
    with _lock:
        ev = _active.get(_slug(name)) if name.strip() else None
    if ev is None:
        return False
    ev.set()
    return True


# ── Running ──────────────────────────────────────────────────────────────────

@contextmanager
def _busy(module, slug: str):
    """Hold the tool's own "busy" mark on a folder for the whole phase, so a
    voice request on the same workspace waits instead of racing this run."""
    with module._run_lock:
        if slug in module._running:
            raise _Stop(f"le dossier est déjà occupé par une autre demande "
                        f"({module._running[slug]}) — relance quand elle est finie")
        module._running[slug] = "direction"
    try:
        yield
    finally:
        with module._run_lock:
            module._running.pop(slug, None)


def _guard(stop: threading.Event) -> None:
    """Checked before every step."""
    if stop.is_set():
        raise _Stop("arrêtée à ta demande")
    resting = claude.cooling()
    if resting:
        raise _Stop(f"Claude se repose ({resting})")


def _retrying(fn, stop: threading.Event, progress):
    """fn(), tried again while every Claude slot is taken by other work."""
    for attempt in range(_SLOT_TRIES):
        try:
            return fn()
        except claude.ClaudeError as e:
            if "already running" not in str(e) or attempt == _SLOT_TRIES - 1:
                raise
            progress("every Claude slot is busy — waiting for one")
            if stop.wait(_SLOT_PAUSE):
                raise _Stop("arrêtée à ta demande") from None


def _step(path: Path, module, slug: str, phase: str, step: str) -> None:
    """Show which step runs, on the page and in the tool's own status."""
    with module._run_lock:
        module._running[slug] = f"direction · {step}"
    _set(path, current=f"{phase} · {step}")


def _scrum_workspace(path: Path, state: dict) -> Path:
    """The project's Scrum workspace, made when missing. The chiffrage lives in
    it too, so it is made even when the Scrum phase is left out."""
    ws = _scrum_dir(state["slug"])
    if not (ws / scrum._STATE).is_file():
        made = scrum._create({"name": state["name"], "description": state.get("brief", ""),
                              "team": state.get("team", ""), "language": state["language"],
                              "start": False}, None)
        if not (ws / scrum._STATE).is_file():
            raise RuntimeError(made)
    if state.get("scrum") != str(ws):
        _set(path, scrum=str(ws))
    return ws


def _phase_scrum(player, path: Path, state: dict, stop, progress) -> dict:
    slug, lang = state["slug"], state["language"]
    ws = _scrum_workspace(path, state)
    scrum._install_pack(ws)
    todo = [s for s in scrum.STEPS if not _done(scrum._load(ws), s)]
    partial, skipped = [], []
    with _busy(scrum, slug):
        for step in todo:
            _guard(stop)
            need = scrum._NEEDS.get(step)
            if need and not (ws / "scrum" / f"{need}.json").is_file():
                skipped.append(f"{step} (il manque {need})")
                continue
            _step(path, scrum, slug, "scrum", step)
            progress(f"scrum · {step} …")
            rec = _retrying(lambda: scrum._run_one(ws, scrum._load(ws) or {}, step, "", "", lang,
                                                   progress, tuple(todo)), stop, progress)
            if rec.get("status") != "done":
                partial.append(f"{step} ({rec.get('remains') or 'voir le rapport'})")
    progress("scrum · drawing the deliverables")
    scrum._render(ws)
    if (ws / "scrum" / "cahier-des-charges.json").is_file():
        try:
            pdf, docx = scrum._cdc_files(ws, scrum._load(ws) or state, progress)
            _set(path, cdc=str(pdf), cdc_docx=str(docx) if docx else "")
        except Exception as e:                       # the JSON and the pages are there
            print(f"[Direction] cahier des charges export failed: {e}")
    left = partial + skipped
    return {"status": "partial" if left else "done", "note": "; ".join(left)}


def _phase_ddd(player, path: Path, state: dict, stop, progress) -> dict:
    """The domain model, in the Scrum workspace next to scrum/: drawn from the
    cahier des charges and the backlog, read by the chiffrage and the code."""
    slug, lang = state["slug"], state["language"]
    ws = _scrum_workspace(path, state)
    ddd.install(ws)
    todo = [s for s in ddd.STEPS if not ddd.done(ws, s)]
    with _busy(scrum, slug):                         # the same folder as the Scrum file
        for step in todo:
            _guard(stop)
            _step(path, scrum, slug, "ddd", step)
            progress(f"ddd · {step} …")
            rec = _retrying(lambda: ddd.run_step(ws, state["name"], step, lang, progress,
                                                 tuple(todo)), stop, progress)
            if rec.get("status") != "done":
                # The contexts are drawn on the language, the aggregates in the
                # contexts: going on would model on a boundary that does not hold.
                return {"status": "partial",
                        "note": f"{step} : {rec.get('remains') or 'voir le rapport'}"}
    ddd.calc(ws)
    report = ws / "livrables" / "ddd.md"
    if report.is_file():
        _set(path, ddd=str(report))
    return {"status": "done", "note": ddd.headline(ws)}


def _phase_chiffrage(player, path: Path, state: dict, stop, progress) -> dict:
    slug, lang = state["slug"], state["language"]
    ws = _scrum_workspace(path, state)
    chiffrage.install(ws)
    todo = [s for s in chiffrage.STEPS if not chiffrage.done(ws, s)]
    with _busy(scrum, slug):                         # the same folder as the Scrum file
        for step in todo:
            _guard(stop)
            _step(path, scrum, slug, "chiffrage", step)
            progress(f"chiffrage · {step} …")
            rec = _retrying(lambda: chiffrage.run_step(ws, state["name"], step, lang, progress,
                                                       tuple(todo)), stop, progress)
            if rec.get("status") != "done":
                # Each file is computed on the previous one: going on would
                # price a breakdown that does not hold.
                return {"status": "partial",
                        "note": f"{step} : {rec.get('remains') or 'voir le rapport'}"}
    chiffrage.calc(ws)
    report = ws / "livrables" / "chiffrage.md"
    if report.is_file():
        _set(path, chiffrage=str(report))
    return {"status": "done", "note": chiffrage.headline(ws)}


# What the code phase is told about the file made before it. Goes into the
# project's CLAUDE.md, so it stays short: it is read on every turn.
_DOCS_NOTE = (
    "\n\n## Dossier de projet\n\n"
    "The project file was written first, by the Direction Projet run: "
    "docs/cahier-des-charges.json (the specification: requirements, scope, out of "
    "scope, constraints), docs/product-backlog.json (epics and user stories with "
    "their priorities) and docs/chiffrage.md (the estimate and the budget). The "
    "`spec` step builds replica/recon.md and replica/features.csv from them: the "
    "must-have stories are the must-haves, and nothing out of scope is built.")
_DDD_NOTE = (
    " The domain model is in docs/ddd/ (ddd.md to read; domaine.json, contextes.json "
    "and modele.json for the exact names): the code is organised by its bounded "
    "contexts, an aggregate is a transaction boundary, and every class, table, route "
    "and test takes its name from the glossary — never a word of an `avoid` list.")
_DOCS = (("scrum/cahier-des-charges.json", "cahier-des-charges.json"),
         ("scrum/product-backlog.json", "product-backlog.json"),
         ("livrables/chiffrage.md", "chiffrage.md"))


def _copy_docs(ws: Path, pdir: Path) -> None:
    """The latest specification, backlog, domain model and estimate into the
    project's docs/."""
    for src, dest in _DOCS:
        if (ws / src).is_file():
            (pdir / "docs").mkdir(exist_ok=True)
            (pdir / "docs" / dest).write_bytes((ws / src).read_bytes())
    ddd.copy_to(ws, pdir)


def _phase_code(player, path: Path, state: dict, stop, progress) -> dict:
    slug, lang = state["slug"], state["language"]
    pdir = _project_dir(slug)
    ws = _scrum_dir(slug)
    has_docs = any((ws / src).is_file() for src, _ in _DOCS)
    note = (_DOCS_NOTE + (_DDD_NOTE if (ws / "livrables" / "ddd.md").is_file() else "")
            if has_docs else "")
    if not (pdir / project._STATE).is_file():
        made = project._create({"name": state["name"],
                                "description": state.get("brief", "") + note,
                                "static": is_static(state.get("answers")),
                                "language": lang, "start": False}, None)
        if not (pdir / project._STATE).is_file():
            raise RuntimeError(made)
    _copy_docs(ws, pdir)
    _set(path, project=str(pdir))
    pstate = project._load(pdir) or {}
    todo = [s for s in project._pipeline(pstate) if not _done(pstate, s)]
    with _busy(project, slug):
        for step in todo:
            _guard(stop)
            _step(path, project, slug, "code", step)
            progress(f"code · {step} …")
            rec = _retrying(lambda: project._run_one(pdir, project._load(pdir) or pstate, step, "",
                                                     lang, progress), stop, progress)
            if rec.get("status") != "done":
                # The next step would build on a missing piece (project.py's rule).
                return {"status": "partial",
                        "note": f"{step} : {rec.get('remains') or 'voir le rapport'}"}
    # The code read back against the domain model: local, no agent.
    notes = [n for n in (project._parity(pdir), ddd.check_code(ws, pdir)) if n]
    return {"status": "done", "note": " · ".join(notes)}


def _ddd_excerpt(ws: Path) -> str:
    """The strategic part of the domain model (vision, subdomains, language,
    contexts, map) for the deck: the per-context detail would only cost
    tokens there."""
    f = ws / "livrables" / "ddd.md"
    if not f.is_file():
        return ""
    head = f.read_text(encoding="utf-8").split("\n## 6.")[0]
    return f"--- ddd.md ---\n{head[:12_000]}"


def _deck_sources(path: Path, slug: str) -> str:
    """What the deck is built from: the brief, the pitch, the estimate, the
    domain model and the product's spec, whichever exist — in
    create_document's own format."""
    ws, pdir = _scrum_dir(slug), _project_dir(slug)
    files = [path / "brief.md", ws / "chiffrage" / "pitch.md", ws / "livrables" / "chiffrage.md",
             pdir / "replica" / "recon.md"]
    parts = [f"--- {f.name} ---\n{create_document._read_source(str(f))}"
             for f in files if f.is_file()]
    if _ddd_excerpt(ws):
        parts.insert(min(len(parts), 3), _ddd_excerpt(ws))
    if not parts:
        return ""
    return ("\nSOURCE MATERIAL — build the document from this; do not contradict it:\n"
            + "\n\n".join(parts) + "\n")


def _phase_presentation(player, path: Path, state: dict, stop, progress,
                        change: str = "") -> dict:
    """The deck — made once; `change` (MODIFIER CE PROJET) makes it again
    with the user's correction."""
    if not change and state.get("deck") and Path(state["deck"]).is_file():
        return {"status": "done", "note": Path(state["deck"]).name}
    _guard(stop)
    if not change:
        _set(path, current="presentation · deck")
    lang = state["language"]
    request = (f"La présentation de soutenance du projet « {state['name']} » devant un jury : "
               f"le besoin, la solution et son périmètre, le modèle du domaine quand les sources "
               f"en ont un (le cœur du domaine, la carte des contextes, le langage commun), le "
               f"chiffrage (charge, délai, budget, TCO), les risques et le planning, puis l'état "
               f"du produit. Elle suit le pitch des sources et en reprend les chiffres tels quels.")
    if change:
        request += (f" Une version précédente existe déjà ; l'utilisateur demande ce changement, "
                    f"qui prime sur le reste : {change}")
    sources = _deck_sources(path, state["slug"])
    out = web = preview = None
    if claude.enabled():
        try:
            deck = _retrying(lambda: create_document._design_pptx(
                request, lang, _DECK_SLIDES, "", sources, progress), stop, progress)
            out, web, preview = deck["pptx"], deck.get("web"), deck.get("preview")
        except _Stop:
            raise
        except Exception as e:                       # the standard layout still delivers
            print(f"[Direction] the deck designer failed: {e}")
            progress("the designer failed — using the standard layout")
    if out is None:
        theme = random.choice(list(create_document.THEMES.values()))
        out, _ = create_document._make_pptx(request, lang, _DECK_SLIDES, theme, sources, progress)
        preview = create_document._pptx_preview(out)
    _set(path, deck=str(out), deck_web=str(web) if web else "")
    if preview and player is not None and hasattr(player, "show_image"):
        player.show_image(str(preview), f"DIRECTION — {out.name}")
    return {"status": "done", "note": out.name}


_RUN = {"scrum": _phase_scrum, "ddd": _phase_ddd, "chiffrage": _phase_chiffrage,
        "code": _phase_code, "presentation": _phase_presentation}
_DECK_WAITS = ("en attente : la présentation se fait quand les autres étapes cochées sont "
               "terminées, pour reprendre leurs chiffres — relance pour la faire")


def _work(player, path: Path, slug: str, stop: threading.Event, progress) -> str:
    state = _load(path)
    results = dict(state.get("results") or {})
    status, note = "done", ""
    try:
        for phase in state["phases"]:
            _guard(stop)
            if phase == "presentation" and status != "done":
                # The deck repeats the pitch and the figures: made now, it would
                # miss them, and a resumed run keeps a deck that exists.
                results[phase] = {"status": "partial", "note": _DECK_WAITS}
                _set(path, results=results)
                continue
            progress(f"{phase} …")
            try:
                results[phase] = _RUN[phase](player, path, _load(path), stop, progress)
            finally:
                _set(path, results=results)
            if results[phase]["status"] != "done":
                status = "partial"
    except _Stop as e:
        status, note = "stopped", str(e)
    except claude.ClaudeError as e:
        status, note = "failed", f"Claude a échoué : {str(e)[:200]}"
    except Exception as e:                           # noqa: BLE001 — reported on the page
        status, note = "failed", str(e)[:240]
        raise
    finally:
        with _lock:
            _active.pop(slug, None)
        _set(path, status=status, note=note, current="", finished=_now())

    text = summary(path)
    if player is not None and hasattr(player, "show_content"):
        player.show_content(f"DIRECTION — {state['name'][:36]}", text)
    said = {"done": "is complete", "partial": "is finished with steps left partial",
            "stopped": f"stopped ({note}); launching it again resumes it",
            "failed": f"failed ({note}); launching it again resumes it"}[status]
    return (f"The Direction Projet run of {state['name']} {said}. Summary (also on the "
            f"display):\n{text[:1200]}\nTell the user in two sentences, in their language.")


# ── Earlier projects: reopen one, change it ──────────────────────────────────
#
# A relaunch never redoes a step that is done (that is what keeps a resumed
# run cheap), so changing a finished project cannot go through it. A change is
# one agent run on the part it concerns, in that part's folder, followed by the
# same check the step had — the scrum and project tools' own `task` runs for
# the Scrum file and the code, the same kind of run here for the domain model
# and the estimate, the deck made again with the change. Nothing else is
# redone: a change of scope is asked of each part that should follow it.

MODIFY_TARGETS = {
    "scrum": "Dossier Scrum & cahier des charges",
    "ddd": "Modèle du domaine",
    "chiffrage": "Chiffrage",
    "code": "Code",
    "presentation": "Présentation",
}


def projects() -> list[dict]:
    """Every Direction Projet run on this machine, most recently changed first."""
    root = _root()
    with _lock:
        running = set(_active)
    out = []
    for d in sorted(root.iterdir()) if root.is_dir() else ():
        state = _load(d) if d.is_dir() else {}
        if not state.get("name"):
            continue
        slug = state.get("slug") or d.name
        out.append({"name": state["name"], "slug": slug,
                    "status": _shown_status(state.get("status", ""), slug in running),
                    "updated": state.get("updated", ""), "created": state.get("created", ""),
                    "phases": list(state.get("phases") or ())})
    out.sort(key=lambda p: p["updated"], reverse=True)
    return out


def form_of(slug: str) -> dict:
    """What the page needs to show a saved project again: {} when none."""
    state = _load(_root() / slug) if slug else {}
    if not state.get("name"):
        return {}
    return {"name": state["name"], "language": state.get("language") or "French",
            "mode": state.get("mode") or "libre", "brief": state.get("brief", ""),
            "answers": dict(state.get("answers") or {}),
            "phases": list(state.get("phases") or PHASES)}


def modifiable(state: dict) -> list[str]:
    """The parts of this project that exist, so can be changed."""
    slug = state.get("slug", "")
    if not slug:
        return []
    ws, pdir = _scrum_dir(slug), _project_dir(slug)
    scrum_steps = ((scrum._load(ws) or {}).get("steps") or {})
    code_steps = ((project._load(pdir) or {}).get("steps") or {})
    found = {
        "scrum": any((r or {}).get("status") in ("done", "partial") for r in scrum_steps.values()),
        "ddd": any(ddd.done(ws, s) for s in ddd.STEPS),
        "chiffrage": any(chiffrage.done(ws, s) for s in chiffrage.STEPS),
        "code": any((r or {}).get("status") in ("done", "partial") for r in code_steps.values()),
        "presentation": bool(state.get("deck")) and Path(state["deck"]).is_file(),
    }
    return [k for k in MODIFY_TARGETS if found[k]]


def modify(name: str, target: str, request: str, player=None) -> tuple[bool, str]:
    """Change one part of a project already made. (started, message for the page)."""
    slug = _slug(name) if name.strip() else ""
    path = _root() / slug if slug else None
    state = _load(path) if path else {}
    request = str(request or "").strip()
    if not state:
        return False, "Ouvre d'abord un projet existant (MES PROJETS, en haut)."
    if target not in MODIFY_TARGETS:
        return False, "Choisis la partie à modifier."
    if target not in modifiable(state):
        return False, (f"« {MODIFY_TARGETS[target]} » n'a pas encore été produit : coche la "
                       f"phase et relance la conception.")
    if not request:
        return False, "Écris ce qu'il faut changer."
    problem = unavailable()
    if problem:
        return False, problem
    with _lock:
        if slug in _active:
            return False, f"« {state['name']} » est déjà en cours : attends la fin."
        stop = threading.Event()
        _active[slug] = stop
    changes = list(state.get("changes") or [])
    changes.append({"at": _now(), "target": target, "request": request[:600], "status": "running"})
    _set(path, changes=changes[-20:], current=f"modification · {MODIFY_TARGETS[target].lower()}")
    jobs.start(player, f"DIRECTION — {state['name'][:20]} · modification",
               lambda progress: _modify_work(path, slug, target, request, stop, player, progress))
    return True, (f"Modification lancée sur « {MODIFY_TARGETS[target]} » : un agent, puis la "
                  f"vérification. Tu peux quitter cette page, le suivi continue ici.")


def _modify_work(path: Path, slug: str, target: str, request: str, stop, player,
                 progress) -> str:
    state = _load(path)
    status, note = "failed", ""
    try:
        rec = _MODIFY[target](player, path, state, request, stop, progress)
        status, note = rec.get("status", "done"), rec.get("note", "")
    except _Stop as e:
        status, note = "stopped", str(e)
    except claude.ClaudeError as e:
        note = f"Claude a échoué : {str(e)[:200]}"
    except Exception as e:                           # noqa: BLE001 — reported on the page
        note = str(e)[:240]
        raise
    finally:
        with _lock:
            _active.pop(slug, None)
        changes = list(_load(path).get("changes") or [])
        if changes:
            changes[-1].update(status=status, note=str(note)[:400], finished=_now())
        _set(path, changes=changes, current="")
    said = {"done": "is done", "partial": "is done, with problems the check still finds",
            "stopped": f"stopped ({note})", "failed": f"failed ({note})"}.get(status, status)
    return (f"The change to {MODIFY_TARGETS[target]} of {state.get('name', slug)} {said}. "
            f"{str(note)[:600]}\nTell the user in one or two sentences, in their language.")


def _first_line(text: str, limit: int = 300) -> str:
    return " ".join(str(text or "").split())[:limit]


def _modify_scrum(player, path: Path, state: dict, request: str, stop, progress) -> dict:
    """The Scrum file's own task run (render check included), then the pages
    and the cahier des charges exports drawn again."""
    slug, lang = state["slug"], state["language"]
    ws = _scrum_dir(slug)
    scrum._install_pack(ws)
    with _busy(scrum, slug):
        _guard(stop)
        rec = _retrying(lambda: scrum._run_one(ws, scrum._load(ws) or {}, "task", request, "",
                                               lang, progress), stop, progress)
    progress("scrum · drawing the deliverables")
    scrum._render(ws)
    if (ws / "scrum" / "cahier-des-charges.json").is_file():
        try:
            pdf, docx = scrum._cdc_files(ws, scrum._load(ws) or state, progress)
            _set(path, cdc=str(pdf), cdc_docx=str(docx) if docx else "")
        except Exception as e:                       # the JSON and the pages are there
            print(f"[Direction] cahier des charges export failed: {e}")
    return {"status": rec.get("status", "done"),
            "note": rec.get("remains") or _first_line(rec.get("report"))}


def _modify_part(module, folder: str, what: str):
    """A change to the domain model or the estimate: one agent run in the
    Scrum workspace on `folder`/, then every file of that folder checked and
    corrected as its steps are, and the deliverable computed again."""
    def run(player, path: Path, state: dict, request: str, stop, progress) -> dict:
        slug, lang, name = state["slug"], state["language"], state["name"]
        ws = _scrum_dir(slug)
        module.install(ws)
        model = module.model_for(module.STEPS[0])
        prompt = (f"{request}\n\nThis is a change the user asked for on the {what} already "
                  f"written in {folder}/. Read CLAUDE.md and only the {folder}/ files this change "
                  f"touches, follow the shapes in the matching .claude/skills/{folder}-*/SKILL.md, "
                  f"keep every id stable, and carry the change into every {folder}/ file it "
                  f"reaches.")

        def on_event(ev):
            act = claude.tool_activity(ev)
            if act:
                progress(f"{folder} · {act}")

        with _busy(scrum, slug):                     # the same folder as the Scrum file
            _guard(stop)
            res = _retrying(lambda: claude.agent(
                prompt, model=model, cwd=ws, timeout=module._TIMEOUT, on_event=on_event,
                append_system=module._agent_system(name, lang, project._TASK_FINAL)),
                stop, progress)
            left = []
            for step in module.STEPS:
                if (ws / folder / module.STEP_FILES[step]).is_file():
                    errors, _ = module._fix(ws, name, lang, step, model, on_event, progress)
                    left += errors
            module.calc(ws)
        if left:
            return {"status": "partial",
                    "note": f"{len(left)} erreur(s) que la vérification trouve encore — {left[0]}"}
        return {"status": "done", "note": _first_line(res.text)}
    return run


def _modify_code(player, path: Path, state: dict, request: str, stop, progress) -> dict:
    """The project tool's own task run, after the latest specification,
    backlog, domain model and estimate are copied into docs/."""
    slug, lang = state["slug"], state["language"]
    pdir = _project_dir(slug)
    _copy_docs(_scrum_dir(slug), pdir)
    with _busy(project, slug):
        _guard(stop)
        rec = _retrying(lambda: project._run_one(pdir, project._load(pdir) or {}, "task", request,
                                                 lang, progress), stop, progress)
    notes = [n for n in (rec.get("remains") or _first_line(rec.get("report")),
                         project._parity(pdir)) if n]
    return {"status": rec.get("status", "done"), "note": " · ".join(notes)}


def _modify_deck(player, path: Path, state: dict, request: str, stop, progress) -> dict:
    return _phase_presentation(player, path, state, stop, progress, change=request)


_MODIFY = {"scrum": _modify_scrum,
           "ddd": _modify_part(ddd, "ddd", "domain model"),
           "chiffrage": _modify_part(chiffrage, "chiffrage", "estimate"),
           "code": _modify_code, "presentation": _modify_deck}


def _swap_text(md: Path, old: str, new: str) -> bool:
    """`old` replaced by `new` once in a file — False, and nothing written,
    when the file or the text is not there (someone edited it by hand)."""
    if not old or not md.is_file():
        return False
    text = md.read_text(encoding="utf-8")
    if old not in text:
        return False
    md.write_text(text.replace(old, new, 1), encoding="utf-8")
    return True


def _sync_brief(slug: str, old: str, brief: str) -> list[str]:
    """A brief edited on the page, into the workspaces made from the old one:
    their CLAUDE.md, which every later step and change reads, and their
    state. The old text is swapped in place, so the rest of each CLAUDE.md —
    and anything added to it since — stays as it is. Returns what changed."""
    done = []
    ws = _scrum_dir(slug)
    st = scrum._load(ws)
    if st and _swap_text(ws / "CLAUDE.md", st.get("description") or old, brief):
        st["description"] = brief
        scrum._save(ws, st)
        meta = ws / "scrum" / "meta.json"
        try:
            m = json.loads(meta.read_text(encoding="utf-8"))
            m["description"] = brief
            meta.write_text(json.dumps(m, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:                            # noqa: BLE001 — the cover keeps the old line
            pass
        done.append("scrum")
    pdir = _project_dir(slug)
    ps = project._load(pdir)
    if ps:
        # The code's brief is the page's brief plus the note on docs/ (_DOCS_NOTE).
        desc = ps.get("description", "")
        head = desc.split("\n\n## Dossier de projet")[0]
        if _swap_text(pdir / "CLAUDE.md", head, brief):
            ps["description"] = brief + desc[len(head):]
            project._save(pdir, ps)
            done.append("code")
    return done


# ── Following a run ──────────────────────────────────────────────────────────

_MARK = {"done": "✓", "partial": "~", "failed": "✕", "running": "⟳"}


def _phase_steps(key: str, state: dict) -> list[tuple[str, str]]:
    """(step, status) for each step of a phase, read from its folder."""
    slug = state.get("slug", "")
    current = state.get("current", "")
    if key == "scrum":
        records = (scrum._load(_scrum_dir(slug)) or {}).get("steps") or {}
        names = scrum.STEPS
    elif key == "ddd":
        records = ddd.load(_scrum_dir(slug)).get("steps") or {}
        names = ddd.STEPS
    elif key == "chiffrage":
        records = chiffrage.load(_scrum_dir(slug)).get("steps") or {}
        names = chiffrage.STEPS
    elif key == "code":
        pstate = project._load(_project_dir(slug)) or {}
        records, names = pstate.get("steps") or {}, project._pipeline(pstate)
    else:
        deck = state.get("deck") and Path(state["deck"]).is_file()
        records, names = ({"deck": {"status": "done"}} if deck else {}), ("deck",)
    out = []
    for step in names:
        st = (records.get(step) or {}).get("status", "")
        if current == f"{key} · {step}":
            st = "running"
        out.append((step, st))
    return out


def outputs(state: dict) -> dict[str, str]:
    """What there is to open, by kind, among the files that exist."""
    slug = state.get("slug", "")
    if not slug:
        return {}
    ws, pdir = _scrum_dir(slug), _project_dir(slug)
    found = {
        "dossier": ws / "livrables" / "index.html",
        "cdc": state.get("cdc_docx") or state.get("cdc"),   # Word first: it is the editable one
        "ddd": ws / "livrables" / "ddd.md",
        "chiffrage": ws / "livrables" / "chiffrage.md",
        "code": pdir / project._STATE,
        "deck": state.get("deck"),
        "folder": _root() / slug,
    }
    out = {k: str(p) for k, p in found.items() if p and Path(p).exists()}
    if "code" in out:
        out["code"] = str(pdir)                        # the folder, not its state file
    return out


def follow(name: str) -> dict:
    """Everything the page shows for this name. Cheap: a few small JSON reads."""
    return _follow(_slug(name) if name.strip() else "")


_INTERRUPTED = ("interrompu : Jarvis a été fermé pendant le travail — REPRENDRE continue "
                "là où il en était")


def _shown_status(status: str, running: bool) -> str:
    """A state still at 'running' with no job behind it was cut short by
    Jarvis closing: shown as stopped, never as a run that is going on."""
    return "running" if running else ("stopped" if status == "running" else status)


def _follow(slug: str) -> dict:
    state = _load(_root() / slug) if slug else {}
    with _lock:
        running = slug in _active
    if not state:
        return {"exists": False, "running": False, "phases": [], "outputs": {}}
    if not running and state.get("status") == "running":
        state = dict(state, status="stopped", current="", note=_INTERRUPTED)
    elif not running and state.get("current"):
        state = dict(state, current="")
    changes = [dict(c) for c in (state.get("changes") or [])[-5:]]
    for c in changes:
        if not running and c.get("status") == "running":
            c.update(status="stopped", note=_INTERRUPTED.split(" — ")[0])
    phases = []
    for key in PHASES:
        steps = _phase_steps(key, state)
        phases.append({"key": key, "label": LABELS[key], "on": key in (state.get("phases") or ()),
                       "steps": steps, "done": sum(1 for _, s in steps if s == "done"),
                       "note": ((state.get("results") or {}).get(key) or {}).get("note", "")})
    return {"exists": True, "running": running,
            "status": "running" if running else state.get("status", ""),
            "current": state.get("current", ""), "note": state.get("note", ""),
            "phases": phases, "outputs": outputs(state), "updated": state.get("updated", ""),
            "modifiable": modifiable(state), "changes": changes}


def summary(path: Path) -> str:
    """The run in a few lines, in French, for the display and the voice."""
    state = _load(path)
    info = _follow(path.name)
    lines = [f"Direction Projet — {state.get('name', '')}", str(path), ""]
    for ph in info["phases"]:
        if not ph["on"]:
            continue
        marks = "  ".join(f"{s} {_MARK.get(st, '·')}" for s, st in ph["steps"])
        lines.append(f"◆ {ph['label']} — {ph['done']}/{len(ph['steps'])}")
        lines.append(f"   {marks}")
        if ph["note"]:
            lines.append(f"   {ph['note']}")
    if info.get("note"):
        lines += ["", f"Arrêt : {info['note']}"]
    out = info.get("outputs") or {}
    for key, label in (("cdc", "Cahier des charges"), ("ddd", "Modèle du domaine"),
                       ("chiffrage", "Chiffrage"), ("code", "Code"), ("deck", "Présentation")):
        if key in out:
            lines.append(f"{label} : {out[key]}")
    return "\n".join(lines)


def open_output(name: str, kind: str) -> str:
    """Open one output ('dossier', 'cdc', 'ddd', 'chiffrage', 'code', 'deck', 'folder').
    '' when done, else why not."""
    state = _load(_root() / _slug(name)) if name.strip() else {}
    target = outputs(state).get(kind)
    if not target:
        return "Pas encore produit."
    if kind == "code":
        project._open(Path(target))                   # VS Code when it is installed
    else:
        create_document._open(Path(target))
    return ""
