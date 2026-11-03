"""
scrum — project management deliverables, the Scrum way, one folder per project.

WHAT IT PRODUCES
    Everything a Scrum project file is graded on, drawn as diagrams:

        cadrage            bête à cornes, diagramme pieuvre, SWOT, vision
        parties-prenantes  stakeholders on a power/interest grid, RACI matrix
        discovery          personas, hypotheses, questions, experiments
        cahier-des-charges the specification (NF EN 16271): objectives, scope,
                           requirements tied to the pieuvre's functions,
                           constraints, acceptance; PDF and Word
        backlog            product goal, epics, user stories, bugs, spikes, DoR,
                           DoD; value / effort matrix; the Scrum framework page
        sprint             sprint goals, sprint backlog, tasks, burndown,
                           reviews, retrospectives, velocity, burn-up
        risques            risk register, risk matrix before / after treatment, heat map
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

WHY THE AGENT DOES NOT HAVE TO VALIDATE ITS OWN WORK
    An agent runs unattended with a short Bash allowlist (core/claude.py), so
    a command it composes can be refused — a shell loop over the JSON files
    is, and an agent that meets one refusal tends to stop checking. So the
    assistant runs render.py's check itself after every step and hands the
    exact errors to a short correction run, twice at most; a step is only
    "done" when the check passes.

WHY THIS SPENDS FEW TOKENS
    - One step per request by default; "steps" chains up to the whole
      pipeline when the user asks for everything, and asking for the
      cahier des charges runs every step not done yet.
    - Every step is a fresh session that reads a few kilobytes of JSON on
      purpose, not a transcript replayed on every turn.
    - Every step runs on Sonnet: this is structured writing, not code.
      "scrum_models" ({"step": "model"}) and "scrum_model" in
      config/api_keys.json override it.
    - The pack lives in each workspace's .claude/skills, never in
      workspace/, so ordinary ask_claude tasks do not list eight skills they
      never use.
"""
from __future__ import annotations

import datetime as _dt
import html
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

STEPS = ("cadrage", "parties-prenantes", "discovery", "cahier-des-charges", "backlog", "sprint",
         "risques", "planning")
# What each step writes, in the order the dashboard shows it.
STEP_FILES = {
    "cadrage": ("bete-a-cornes", "pieuvre", "swot"),
    "parties-prenantes": ("parties-prenantes", "raci"),
    "discovery": ("discovery",),
    "cahier-des-charges": ("cahier-des-charges",),
    "backlog": ("product-backlog",),
    "sprint": ("sprints",),
    "risques": ("risques",),
    "planning": ("planning",),
}
ARTEFACTS = {stem: step for step, stems in STEP_FILES.items() for stem in stems}
# Pages render.py draws from another deliverable's file (its VIEWS).
VIEWS = {"matrice-risques": "risques", "carte-chaleur": "risques",
         "cadre-scrum": "product-backlog", "priorisation": "product-backlog"}
# What goes on the display when a file changed, when the user named no page:
# the picture rather than the table.
_DISPLAY = {"risques": "matrice-risques"}
# HUD captions a stem does not spell out.
_CAPTIONS = {"bete-a-cornes": "bête à cornes", "risques": "registre des risques",
             "cahier-des-charges": "cahier des charges", "cadre-scrum": "cadre Scrum",
             "priorisation": "priorisation valeur / effort",
             "matrice-risques": "matrice des risques", "carte-chaleur": "carte de chaleur"}
_NEEDS = {"sprint": "product-backlog"}
# Asked for, the specification brings the whole dossier along: every step not
# done yet runs with it, in order — it is written on the need, the stakeholders
# and the discovery, and the backlog, sprints, risks and schedule follow from it.
_FULL_DOSSIER = "cahier-des-charges"
# The assistant checks every step itself, then sends the errors it found back
# to a short correction run, at most this many times.
_FIX_ROUNDS = 2
_FIX_TIMEOUT = 8 * 60
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
    "cahier-des-charges": ("cahier des charges", "cahier de charges", "cahier des charge", "cdc", "cdcf",
                           "cahier des charges fonctionnel", "specification", "specifications", "specs",
                           "spec", "exigences", "exigences fonctionnelles", "exigences non fonctionnelles",
                           "requirements", "cctp", "expression fonctionnelle du besoin"),
    "product-backlog": ("product backlog", "backlog produit", "backlog", "user stories",
                        "stories", "story", "epics", "epic", "story map"),
    "sprints": ("sprint backlog", "backlog de sprint", "sprint", "sprints", "burndown",
                "sprint planning", "velocite", "burn up", "burnup", "sprint review", "revue de sprint",
                "retrospective", "retro", "increment"),
    "cadre-scrum": ("cadre scrum", "scrum", "artefacts", "artefacts scrum", "engagements", "scrum team",
                    "equipe scrum", "roles scrum", "evenements scrum", "methodologie scrum", "methode scrum",
                    "scrum guide", "guide scrum"),
    "priorisation": ("priorisation", "matrice valeur effort", "valeur effort", "value effort",
                     "valeur et effort", "quick wins", "gains rapides"),
    "risques": ("registre des risques", "registre", "risk register", "register",
                "plan de mitigation", "mitigation"),
    "matrice-risques": ("matrice des risques", "matrice de risques", "matrice des risque",
                        "matrice de criticite", "criticite", "risk matrix", "probabilite impact",
                        "risques", "risque", "risks", "risk", "gestion des risques"),
    "carte-chaleur": ("carte de chaleur", "matrice de chaleur", "heat map", "heatmap", "chaleur",
                      "carte thermique", "thermique"),
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


def _step_of(stem: str) -> str:
    return ARTEFACTS.get(VIEWS.get(stem, stem), "?")


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
    _install_pack(path)
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
    first = _slug(str(p.get("step") or ""))
    if first not in STEPS:          # "fais-moi un cahier des charges": the step of what was named
        named = _artefact(str(p.get("step") or p.get("artefact") or ""))
        first = _step_of(named) if named not in ("", "index") else STEPS[0]
    steps = _with_dossier(first, state) if first == _FULL_DOSSIER else _chain(first, p.get("steps"))
    return f"{made} {_start(player, path, state, steps, language)}"


def _install_pack(path: Path) -> None:
    """The skills and the agents' copy of the renderer, as this version of the
    app ships them. Done again before every run, so a workspace made by an
    older version writes what the renderer now draws."""
    skills = path / ".claude" / "skills"
    skills.mkdir(parents=True, exist_ok=True)
    for d in sorted(_PACK.glob("scrum-*")):
        shutil.copytree(d, skills / d.name, dirs_exist_ok=True)
    kit = path / ".claude" / "scrum-kit"
    kit.mkdir(exist_ok=True)
    shutil.copy2(_PACK / "render.py", kit / "render.py")


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
        return f"{stem} has not been produced yet (step {_step_of(stem)})."
    if player is None or not hasattr(player, "show_image"):
        return ""
    png = path / "livrables" / "png" / f"{stem}.png"
    png.parent.mkdir(exist_ok=True)
    if not _snapshot(page, png):
        return "the picture could not be made (Chromium)."
    what = "dashboard" if stem == "index" else _CAPTIONS.get(stem, stem.replace("-", " "))
    player.show_image(str(png), f"{state['name'][:28]} · {what}")
    return ""


def _mtimes(path: Path) -> dict[str, float]:
    return {f.stem: f.stat().st_mtime for f in (path / "scrum").glob("*.json")}


def _pdf(path: Path, state: dict, page: str = "index.html", name: str = "dossier-scrum",
         footer: str = "") -> Path:
    """A page of livrables/ printed to PDF. The page's CSS sets the paper (the
    dossier is landscape, the specification portrait); `footer` adds a
    running footer with page numbers."""
    from playwright.sync_api import sync_playwright
    out = path / "livrables" / f"{state['slug']}-{name}.pdf"
    opts = {"path": str(out), "print_background": True, "prefer_css_page_size": True}
    if footer:
        opts.update(display_header_footer=True, header_template="<span></span>",
                    footer_template=("<div style='font-size:8px;color:#64748b;width:100%;margin:0 15mm;"
                                     "display:flex;justify-content:space-between'>"
                                     f"<span>{html.escape(footer)}</span><span>Page <span class='pageNumber'>"
                                     "</span> / <span class='totalPages'></span></span></div>"))
    else:
        opts.update(format="A4", landscape=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            tab = browser.new_page()
            tab.goto((path / "livrables" / page).as_uri(), wait_until="load", timeout=45_000)
            tab.pdf(**opts)
        finally:
            browser.close()
    return out


# ── The specification in Word ────────────────────────────────────────────────

def _cdc_blocks(path: Path) -> list[dict]:
    """The specification as render.py assembles it: the same blocks as the page."""
    out = subprocess.run([sys.executable, "-I", str(_PACK / "render.py"), str(path), "--blocks"],
                         capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise RuntimeError((out.stderr or out.stdout or "no output").strip()[-300:])
    return json.loads(out.stdout)


def _svg_pngs(svgs: list[str], folder: Path) -> list[Path]:
    """Each diagram as a PNG, for Word, in one browser session."""
    from playwright.sync_api import sync_playwright
    pngs = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            tab = browser.new_page(viewport={"width": 1100, "height": 900}, device_scale_factor=2)
            for i, svg in enumerate(svgs):
                tab.set_content("<html><head><style>body{margin:0;font-family:Inter,'Segoe UI',Roboto,"
                                "Arial,sans-serif}svg{display:block;width:100%;height:auto}</style></head>"
                                f"<body><div style='width:1000px'>{svg}</div></body></html>")
                png = folder / f"figure-{i + 1}.png"
                tab.query_selector("svg").screenshot(path=str(png))
                pngs.append(png)
        finally:
            browser.close()
    return pngs


def _docx(path: Path, state: dict, blocks: list[dict]) -> Path:
    """The specification as an editable Word file, block for block like the page."""
    import struct
    from docx import Document
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt, RGBColor

    grey, blue = RGBColor(0x5B, 0x6B, 0x7D), RGBColor(0x25, 0x63, 0xEB)

    def shade(cell, color):
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear"), shd.set(qn("w:color"), "auto"), shd.set(qn("w:fill"), color.lstrip("#"))
        cell._tc.get_or_add_tcPr().append(shd)

    def readable(color):
        r, g, b = (int(color.lstrip("#")[k:k + 2], 16) / 255 for k in (0, 2, 4))
        return RGBColor(0x17, 0x20, 0x33) if 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.6 else RGBColor(255, 255, 255)

    def field_start(par, code):
        """Opens a Word field (page number, table of contents); its result
        follows, then field_end. Word updates it when the file opens."""
        for kind in ("begin", None, "separate"):
            if kind:
                el = OxmlElement("w:fldChar")
                el.set(qn("w:fldCharType"), kind)
            else:
                el = OxmlElement("w:instrText")
                el.set(qn("xml:space"), "preserve")
                el.text = f" {code} "
            par.add_run()._r.append(el)

    def field_end(par):
        el = OxmlElement("w:fldChar")
        el.set(qn("w:fldCharType"), "end")
        par.add_run()._r.append(el)

    def field(par, code):
        field_start(par, code)
        field_end(par)

    def fill(cell, v, size=9, bold=False):
        cell.text = ""
        par = cell.paragraphs[0]

        def put(p, text, **style):
            run = p.add_run(str(text))
            run.font.size = Pt(style.get("size", size))
            run.bold = style.get("bold", bold)
            if style.get("color") is not None:
                run.font.color.rgb = style["color"]
        if isinstance(v, dict) and "color" in v:
            shade(cell, v["color"])
            put(par, v.get("text", ""), bold=True, color=readable(v["color"]))
        elif isinstance(v, dict):
            if str(v.get("strong") or "").strip():
                put(par, v["strong"], bold=True)
            if str(v.get("text") or "").strip():
                put(cell.add_paragraph() if par.runs else par, v["text"], size=size - 1, color=grey)
        elif isinstance(v, list):
            items = [str(x) for x in v if str(x).strip()]
            for k, x in enumerate(items):
                put(par if k == 0 else cell.add_paragraph(), ("• " if len(items) > 1 else "") + x)
        else:
            put(par, "" if v is None else v)

    def png_width(png, max_w=16.0, max_h=19.0):
        with open(png, "rb") as f:
            w, h = struct.unpack(">II", f.read(24)[16:24])
        return Cm(min(max_w, max_h * w / h))

    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21), Cm(29.7)
    sec.left_margin = sec.right_margin = Cm(2)
    sec.top_margin, sec.bottom_margin = Cm(1.8), Cm(1.8)
    doc.styles["Normal"].font.name = "Calibri"
    doc.styles["Normal"].font.size = Pt(10.5)
    update = OxmlElement("w:updateFields")
    update.set(qn("w:val"), "true")
    doc.settings.element.append(update)

    cover = next((b for b in blocks if b["t"] == "cover"), {})
    foot = sec.footer.paragraphs[0]
    foot.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = foot.add_run(f"{cover.get('title', '')} — {cover.get('project', '')} — v{cover.get('version', '')}    Page ")
    run.font.size = Pt(8)
    field(foot, "PAGE")
    foot.add_run(" / ").font.size = Pt(8)
    field(foot, "NUMPAGES")

    out = path / "livrables" / f"{state['slug']}-cahier-des-charges.docx"
    with tempfile.TemporaryDirectory() as tmp:
        figures = [b for b in blocks if b["t"] == "figure"]
        pngs = dict(zip(map(id, figures), _svg_pngs([b["svg"] for b in figures], Path(tmp)))) if figures else {}
        for b in blocks:
            k = b["t"]
            if k == "cover":
                for _ in range(6):
                    doc.add_paragraph()
                p = doc.add_paragraph()
                r = p.add_run(b["title"].upper())
                r.bold, r.font.size, r.font.color.rgb = True, Pt(11), blue
                r = doc.add_paragraph().add_run(b["project"])
                r.bold, r.font.size = True, Pt(30)
                if b.get("subtitle"):
                    r = doc.add_paragraph().add_run(b["subtitle"])
                    r.font.size, r.font.color.rgb = Pt(13), grey
                doc.add_paragraph()
                r = doc.add_paragraph().add_run(b.get("synthesis_title", ""))
                r.bold, r.font.size = True, Pt(11)
                t = doc.add_table(rows=2, cols=len(b["synthesis"]))
                t.style = "Table Grid"
                for i, (value, label) in enumerate(b["synthesis"]):
                    fill(t.cell(0, i), value, size=18, bold=True)
                    fill(t.cell(1, i), label, size=8)
                for _ in range(4):
                    doc.add_paragraph()
                t = doc.add_table(rows=0, cols=2)
                for label, value in b["facts"]:
                    cells = t.add_row().cells
                    fill(cells[0], label, size=10, bold=True)
                    fill(cells[1], value, size=10)
            elif k == "toc":
                r = doc.add_paragraph().add_run(b.get("title", ""))
                r.bold, r.font.size = True, Pt(16)
                # A real TOC field, so Word adds the page numbers when it opens the
                # file; its stored result already lists the sections, so the
                # contents read right in any viewer before that.
                heads = [h for h in blocks if h["t"] == "h" and not h.get("plain") and h["level"] <= 2]
                first = doc.add_paragraph()
                field_start(first, 'TOC \\o "1-3" \\h \\z \\u')
                par = first
                for i, h in enumerate(heads):
                    par = first if i == 0 else doc.add_paragraph()
                    par.add_run(f"{h['num']}  {h['text']}" if h.get("num") else h["text"])
                    par.paragraph_format.left_indent = Cm(0.7 * (h["level"] - 1))
                    par.paragraph_format.space_after = Pt(2)
                field_end(par)
            elif k == "h":
                text = f"{b['num']}  {b['text']}" if b.get("num") else b["text"]
                if b.get("plain"):
                    r = doc.add_paragraph().add_run(text)
                    r.bold, r.font.size = True, Pt(14)
                else:
                    doc.add_heading(text, level=min(3, b["level"]))
            elif k == "p":
                p = doc.add_paragraph()
                r = p.add_run(b["text"])
                if b.get("cls") == "statement":
                    r.bold = True
                    p.paragraph_format.left_indent = Cm(0.6)
                elif b.get("cls") == "note":
                    r.font.size, r.font.color.rgb = Pt(9), grey
            elif k == "ul":
                for item in b["items"]:
                    doc.add_paragraph(item, style="List Bullet")
            elif k == "ol":                       # numbered by hand: Word's list numbering runs on across lists
                for i, item in enumerate(b["items"], 1):
                    p = doc.add_paragraph(f"{i}. {item}")
                    p.paragraph_format.left_indent = Cm(0.6)
            elif k == "table":
                t = doc.add_table(rows=1, cols=len(b["head"]))
                t.style = "Table Grid"
                t.alignment = WD_TABLE_ALIGNMENT.CENTER
                for i, h in enumerate(b["head"]):
                    fill(t.rows[0].cells[i], h, bold=True)
                    shade(t.rows[0].cells[i], "#EEF3FB")
                for row in b["rows"]:
                    cells = t.add_row().cells
                    for i, v in enumerate(row[:len(cells)]):
                        fill(cells[i], v)
                doc.add_paragraph()
            elif k == "req":
                t = doc.add_table(rows=1, cols=2)
                t.style = "Table Grid"
                top = t.rows[0].cells[0].merge(t.rows[0].cells[1])
                fill(top, f"{b['id']} — {b['title']}", size=10, bold=True)
                shade(top, "#F1F5FB")
                r = top.paragraphs[0].add_run(f"   [{b['badge']['text']}]")
                r.bold, r.font.size, r.font.color.rgb = True, Pt(9), RGBColor.from_string(b["badge"]["color"].lstrip("#").upper())
                for label, value in b["rows"]:
                    cells = t.add_row().cells
                    fill(cells[0], label, bold=True)
                    fill(cells[1], value)
                for row in t.rows[1:]:
                    row.cells[0].width, row.cells[1].width = Cm(4), Cm(13)
                doc.add_paragraph()
            elif k == "figure" and id(b) in pngs:
                doc.add_picture(str(pngs[id(b)]), width=png_width(pngs[id(b)]))
                doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
                p = doc.add_paragraph()
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                r = p.add_run(b["caption"])
                r.italic, r.font.size, r.font.color.rgb = True, Pt(9), grey
            elif k == "break":
                doc.add_page_break()
        doc.save(str(out))
    return out


def _export_cdc(player, path: Path, state: dict, word: bool) -> str:
    """The specification as a PDF (portrait, numbered pages) and a Word file."""
    if not (path / "scrum" / "cahier-des-charges.json").is_file():
        return (f"{state['name']} has no cahier des charges yet. Offer to run the "
                f"cahier-des-charges step.")

    def work(progress) -> str:
        progress("printing the specification")
        blocks = _cdc_blocks(path)
        cover = next((b for b in blocks if b["t"] == "cover"), {})
        pdf = _pdf(path, state, "cahier-des-charges.html", "cahier-des-charges",
                   footer=f"{cover.get('title', '')} — {cover.get('project', '')} — v{cover.get('version', '')}")
        progress("writing the Word file")
        try:
            docx = _docx(path, state, blocks)
        except Exception as e:
            print(f"[Scrum] Word export failed: {e}")
            docx = None
        shown = docx if word and docx else pdf
        _open_file(shown)
        made = f"{pdf}" + (f" and {docx} (Word, editable)" if docx else " (the Word file could not be made)")
        return (f"The cahier des charges of {state['name']} is ready: {made}. {shown.name} is open. "
                f"Tell the user in one sentence.")
    jobs.start(player, f"SCRUM — {state['name'][:28]} · cahier des charges", work)
    return "status=started_in_background. Say in a few words that the cahier des charges is being exported."


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
        f"Check your files with this exact command, on its own: "
        f"`python3 .claude/scrum-kit/render.py . --check` (`python` on Windows) — never in a "
        f"loop (`for`, `while`) or a script: shell loops are refused. If a command is "
        f"refused, carry on and finish the files: the assistant runs the same check after "
        f"you and sends any error back to be fixed. A refused command is never a reason to "
        f"report the step as partial.\n"
        f"{lang_line}{final}")


def _step_task(step: str, focus: str, request: str, chain: tuple = ()) -> str:
    task = f"Run the scrum-{step} skill."
    if focus:
        task += (f" This time produce only scrum/{focus}.json; leave the other files of "
                 f"this step as they are.")
    if len(chain) > 1:
        task += (f"\n\nThis step is one of a run the assistant chains itself "
                 f"({' → '.join(chain)}). Do this step only and report on it only: the "
                 f"assistant starts the next one when you finish.")
    if request:
        task += f"\n\nWhat the user asked for: {request}"
    return task


def _with_dossier(step: str, state: dict) -> list[str]:
    """What runs when `step` is asked for. The specification brings every step
    not done yet along, in order; any other step runs alone."""
    if step != _FULL_DOSSIER:
        return [step]
    done = {k for k, r in (state.get("steps") or {}).items() if r.get("status") == "done"}
    return [s for s in STEPS if s == step or s not in done]


def _problems(path: Path, stems) -> tuple[list[str], list[str]]:
    """The errors and warnings render.py finds in these JSON files: the
    assistant's own check, which needs no permission from anyone."""
    sm = _render(path)
    if "error" in sm:
        return [], []
    mine = lambda found: [x for x in found or () if str(x).split(".json:", 1)[0] in stems]
    return mine(sm.get("errors")), mine(sm.get("warnings"))


def _fix(path: Path, state: dict, language: str, stems, model: str, on_event, progress,
         label: str) -> tuple[list[str], int]:
    """Short correction runs, each handed the exact errors the check found,
    until it passes or _FIX_ROUNDS is spent. The errors left, the tokens used."""
    spent = 0
    for _ in range(_FIX_ROUNDS):
        errors, warnings = _problems(path, stems)
        if not errors:
            return [], spent
        progress(f"{label} · fixing {len(errors)} error(s)")
        prompt = ("The assistant ran `render.py --check` on the workspace and found these errors. "
                  "Fix exactly them in the scrum/ JSON files; keep every id and everything else:\n"
                  + "\n".join(f"- {e}" for e in errors[:40]))
        if warnings:
            prompt += ("\n\nRemarks from the same check: fix them too unless you have a reason, "
                       "and write the reason in scrum/decisions.md.\n"
                       + "\n".join(f"- {w}" for w in warnings[:15]))
        try:
            res = claude.agent(prompt, model=model, cwd=path,
                               append_system=_agent_system(state, language, _TASK_FINAL),
                               timeout=_FIX_TIMEOUT, on_event=on_event)
            spent += res.tokens_in + res.tokens_out
        except claude.ClaudeError as e:
            print(f"[Scrum] correction run failed: {e}")
            break
    return _problems(path, stems)[0], spent


def _run_one(path: Path, state: dict, step: str, request: str, focus: str,
             language: str, progress, chain: tuple = ()) -> dict:
    """One agent run — a pipeline step, or `request` as a free-form task —
    then the assistant's own check, and corrections until it passes."""
    is_task = step == "task"
    model = _model_for(step)
    before = _mtimes(path)
    if is_task:
        prompt = (f"{request}\n\nRead CLAUDE.md and only the scrum/ files this change "
                  f"touches. Keep ids stable. Follow the shapes in the matching "
                  f".claude/skills/scrum-*/SKILL.md, then run "
                  f"`python3 .claude/scrum-kit/render.py . --check` and fix every error.")
    else:
        prompt = _step_task(step, focus, request, chain)

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
    if is_task:
        status = "done"
    # The step is checked by the assistant, not taken on the agent's word: the
    # files it owns (a task: the files it changed) must pass render.py --check.
    if is_task:
        stems = tuple(k for k, t in _mtimes(path).items() if t > before.get(k, 0))
    else:
        stems = (focus,) if focus else STEP_FILES.get(step, ())
    left, fix_tokens = _fix(path, state, language, stems, model, on_event, progress, step)
    if left:
        status = "partial"
        remains = f"{len(left)} error(s) the check still finds — {left[0]}"
    denied = [str((d.get("tool_input") or {}).get("command") or d.get("tool_name") or "")[:120]
              for d in res.denials or () if isinstance(d, dict)]
    rec.update(status=status, remains=remains,
               report=report[:2000], tokens=res.tokens_in + res.tokens_out + fix_tokens,
               cached=res.tokens_cached, minutes=round(res.duration_s / 60, 1),
               checked=not left)
    if denied:
        rec["denied"] = denied[:5]          # what the allowlist refused, to widen it knowingly
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
           request: str = "", focus: str = "", show: str = "") -> str:
    """Run `steps` one after another in the background, then draw and show
    what changed (`show`: the page the user asked for). A step left partial
    does not stop the run — the next ones work from what exists; only a
    failure does."""
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
        partial: list[str] = []
        failed = ""
        reports: list[tuple[str, str]] = []
        last: dict = {}
        try:
            _install_pack(path)
        except OSError as e:
            print(f"[Scrum] could not refresh the skills, using the workspace's own: {e}")
        try:
            for step in steps:
                with _run_lock:
                    _running[slug] = step
                progress(f"{step} …")
                try:
                    last = _run_one(path, _load(path) or state, step, request, focus, language,
                                    progress, tuple(steps))
                except claude.ClaudeError as e:
                    failed = f"{step}: {str(e)[:200]}"
                    break
                done.append(step)
                if last.get("status") != "done":
                    partial.append(f"{step} ({last.get('remains') or 'see the report'})")
                if last.get("report"):
                    reports.append((step, last["report"]))
        finally:
            with _run_lock:
                _running.pop(slug, None)
        progress("drawing the deliverables")
        summary = _render(path)
        after = _mtimes(path)
        changed = [stem for stem in ARTEFACTS if after.get(stem, 0) > before.get(stem, 0)]
        shown = ""
        if changed and "error" not in summary:
            auto = changed[-1] if len(steps) > 1 else (focus or changed[0])
            if len(steps) > 1 and _FULL_DOSSIER in changed:
                auto = _FULL_DOSSIER          # the document that sums the run up
            shown = show or _DISPLAY.get(auto, auto)
            if _show(player, path, state, shown):
                shown = ""
        if len(reports) > 1:
            report = "\n\n".join(f"— {step} —\n{text[:700]}" for step, text in reports)
        else:
            report = reports[0][1] if reports else ""
        if player is not None and hasattr(player, "show_content") and report:
            player.show_content(label, report)
        fresh = _load(path) or state
        nxt = _next_step(fresh)
        ok = [s for s in done if not any(p.startswith(s + " ") for p in partial)]
        outcome = f"Scrum {state['name']}:"
        if ok:
            outcome += f" done and checked: {', '.join(ok)}."
        if partial:
            outcome += f" Partly done: {'; '.join(partial)}."
        if failed:
            outcome += f" Stopped at {failed}."
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
        if sm.get("requirements"):
            out.append(f"Cahier des charges: {sm['requirements']} functional and {sm.get('nfr', 0)} "
                       f"non-functional requirements")
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
                return f"{stem} has not been produced yet (step {_step_of(stem)})."
            _open_file(page)
            return f"Opened {page.name} in the browser."
        why = _show(player, path, state, stem)
        return (f"Could not show it: {why}" if why else
                f"{stem} of {state['name']} is on the display. Say so in a few words.")

    if action == "export":
        summary = _render(path)
        if summary.get("error"):
            return f"The deliverables could not be drawn: {summary['error']}"
        fmt = str(p.get("format") or "").lower()
        if _artefact(str(p.get("artefact") or "")) == "cahier-des-charges" or fmt in ("docx", "word"):
            return _export_cdc(player, path, state, word=fmt in ("docx", "word"))

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
            return _start(player, path, state, _with_dossier(step, state), language, request=request)
        stem = stem or _artefact(str(p.get("step") or ""))     # a deliverable named as the step
        if not stem or stem == "index":
            return (f"Unknown step or deliverable {p.get('artefact') or p.get('step')!r}. "
                    f"Steps: {', '.join(STEPS)}. Deliverables: {', '.join([*ARTEFACTS, *VIEWS])}.")
        page, stem = stem, VIEWS.get(stem, stem)
        step = ARTEFACTS[stem]
        # A step with a single deliverable is that deliverable: run it whole.
        focus = stem if len(STEP_FILES[step]) > 1 else ""
        return _start(player, path, state, [step] if focus else _with_dossier(step, state), language,
                      request=request, focus=focus, show=page)

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
        "(internal/external) and RACI, discovery backlog, cahier des charges (functional "
        "specification, NF EN 16271, PDF and Word), product backlog (epics, user "
        "stories, bugs, spikes, value/effort matrix), Scrum framework (artefacts, commitments, "
        "events), sprint backlog, burndown, velocity, reviews and retrospectives, risks (register, "
        "risk matrix, heat map), "
        "planning/Gantt and ceremonies. "
        "create: new workspace (description), starts step 1 or `step`; asking for the cahier "
        "des charges runs the whole dossier with it. continue: next step(s). run: "
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
                     "description": "create/run: cadrage|parties-prenantes|discovery|cahier-des-charges|backlog|sprint|risques|planning"},
            "artefact": {"type": "STRING",
                         "description": "run/show/open/export: one deliverable as the user named it, e.g. swot, raci, pieuvre, gantt, heat map, cahier des charges"},
            "steps": {"type": "INTEGER",
                      "description": "create/continue: how many steps in a row (1-8, default 1)"},
            "request": {"type": "STRING",
                        "description": "task: the change, fully stated; run/continue: optional precision"},
            "format": {"type": "STRING", "description": "export: pdf (default) or docx — Word, for the cahier des charges"},
            "language": {"type": "STRING", "description": "The user's language, e.g. 'French'"},
        },
        "required": ["action"],
    },
    "handler": scrum,
}
