"""
manage_skills — find, install, create and use Claude skills by voice.

A skill is a folder with a SKILL.md: a name, a one-line description of when to
use it, and the instructions (plus any scripts) Claude follows when it does.
They live in workspace/.claude/skills/, which is where every Claude agent run
started by this app looks — so a skill installed or written here is used by
ask_claude's tasks from the next request on, with no restart.

    list      what is installed
    find      installed skills first, then the public catalogue
              (github.com/anthropics/skills, plus any "skill_sources" repos in
              config/api_keys.json), ranked by Claude against the request so a
              French "faire des présentations" still finds `pptx`
    install   copy one from the catalogue                        (background)
    create    Claude writes a new one from a description         (background)
    use       run a task with one named skill                    (background)
    remove    move one to the system trash

With `space`, list / find / install / create / remove work on one of the IT
skill spaces (skill_spaces/<id>/, core/spaces.py) instead: its specialist in
the agent team uses those skills, and no other Claude run pays for them.
"""
from __future__ import annotations

import json
import re
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

from core import claude, jobs, spaces
from core.spaces import frontmatter as _frontmatter
from core.user_dirs import jarvis_documents_dir

_DEFAULT_SOURCES = ("anthropics/skills",)
_INDEX_TTL = 24 * 3600
_HTTP_TIMEOUT = 20
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


# ── SKILL.md ─────────────────────────────────────────────────────────────────

def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:64].strip("-") or f"skill-{int(time.time())}"


def installed(root: Path | None = None) -> list[dict]:
    """The skills in `root` — Claude's own folder (workspace/.claude/skills)
    by default, or a skill space."""
    return spaces.skills_of(root or claude.skills_dir())


# ── The public catalogue ─────────────────────────────────────────────────────

def _sources() -> list[str]:
    try:
        from memory.config_manager import load_api_keys
        extra = load_api_keys().get("skill_sources") or []
    except Exception:
        extra = []
    out = list(_DEFAULT_SOURCES)
    for s in extra:
        s = str(s).strip().strip("/")
        if re.match(r"^[\w.-]+/[\w.-]+$", s) and s not in out:
            out.append(s)
    return out


def _index_path() -> Path:
    return claude.workspace() / ".skills_index.json"


def _fetch_repo(repo: str) -> list[dict]:
    r = requests.get(f"https://api.github.com/repos/{repo}/git/trees/HEAD?recursive=1",
                     timeout=_HTTP_TIMEOUT, headers={"Accept": "application/vnd.github+json"})
    r.raise_for_status()
    tree = r.json().get("tree") or []
    blobs = [t["path"] for t in tree if t.get("type") == "blob"]
    skill_dirs = sorted({p.rsplit("/", 1)[0] for p in blobs
                         if p.endswith("/SKILL.md") and not p.startswith("template/")})

    def one(d: str) -> dict | None:
        try:
            raw = requests.get(f"https://raw.githubusercontent.com/{repo}/HEAD/{d}/SKILL.md",
                               timeout=_HTTP_TIMEOUT).text
        except Exception:
            return None
        fm = _frontmatter(raw)
        return {"name": fm.get("name") or d.rsplit("/", 1)[-1], "repo": repo, "path": d,
                "description": fm.get("description", ""),
                "files": [p for p in blobs if p.startswith(d + "/")]}

    with ThreadPoolExecutor(max_workers=8) as ex:
        return [s for s in ex.map(one, skill_dirs) if s]


def catalogue(refresh: bool = False) -> list[dict]:
    """Every skill the configured repos publish. Cached for a day, because the
    list changes rarely and GitHub allows 60 unauthenticated calls an hour."""
    path = _index_path()
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
        if (not refresh and time.time() - cached.get("time", 0) < _INDEX_TTL
                and cached.get("sources") == _sources()):
            return cached["skills"]
    except Exception:
        cached = None
    skills: list[dict] = []
    errors = []
    for repo in _sources():
        try:
            skills += _fetch_repo(repo)
        except Exception as e:
            errors.append(f"{repo}: {e}")
            print(f"[Skills] catalogue {repo} failed: {e}")
    if skills:
        path.write_text(json.dumps({"time": time.time(), "sources": _sources(),
                                    "skills": skills}, ensure_ascii=False),
                        encoding="utf-8")
        return skills
    if cached:                       # offline: an old list beats no list
        return cached.get("skills", [])
    raise RuntimeError("could not reach the skill catalogue — " + "; ".join(errors))


# ── Finding ──────────────────────────────────────────────────────────────────

def _keyword_rank(query: str, items: list[dict], limit: int) -> list[dict]:
    words = [w for w in re.findall(r"\w+", query.lower()) if len(w) > 2]
    scored = []
    for it in items:
        hay = f"{it['name']} {it.get('description', '')}".lower()
        s = sum(hay.count(w) for w in words) + (5 if it["name"].lower() in query.lower() else 0)
        if s:
            scored.append((s, it))
    scored.sort(key=lambda t: -t[0])
    return [it for _, it in scored[:limit]]


def _rank(query: str, items: list[dict], limit: int = 5) -> list[dict]:
    """The items that actually fit the request, best first. Claude reads the
    descriptions, so the request can be in any language and in any words; plain
    keyword overlap is the fallback when Claude is unavailable."""
    if not items:
        return []
    listing = "\n".join(f"{i}. {it['name']} — {it.get('description', '')[:260]}"
                        for i, it in enumerate(items))
    try:
        raw = claude.ask(
            f"Request: {query}\n\nSkills:\n{listing}\n\nWhich skills would actually "
            f"help with this request? Return JSON {{\"matches\": [numbers]}}, best "
            f"first, at most {limit}; an empty list if none fits.",
            claude.FAST, system="Output only valid JSON.", timeout=40)
        raw = raw[raw.find("{"): raw.rfind("}") + 1]
        idx = [int(i) for i in json.loads(raw).get("matches", [])]
        return [items[i] for i in idx if 0 <= i < len(items)][:limit]
    except Exception as e:
        print(f"[Skills] ranking by Claude failed ({e}) — keyword match instead")
        return _keyword_rank(query, items, limit)


def _describe(items: list[dict]) -> str:
    lines = []
    for it in items:
        where = "installed" if it.get("installed") else f"catalogue {it.get('repo', '')}"
        lines.append(f"- {it['name']} ({where}): {it.get('description', '')[:200]}")
    return "\n".join(lines)


# ── Installing ───────────────────────────────────────────────────────────────

def _install(entry: dict, progress, root: Path | None = None) -> Path:
    dest = (root or claude.skills_dir()) / _slug(entry["name"])
    tmp = dest.with_name(dest.name + ".part")
    shutil.rmtree(tmp, ignore_errors=True)
    files = entry.get("files") or [f"{entry['path']}/SKILL.md"]
    progress(f"downloading {len(files)} files")

    def fetch(rel: str) -> None:
        url = f"https://raw.githubusercontent.com/{entry['repo']}/HEAD/{rel}"
        r = requests.get(url, timeout=_HTTP_TIMEOUT)
        r.raise_for_status()
        out = tmp / rel[len(entry["path"]) + 1:]
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(r.content)

    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(fetch, files))         # re-raises the first failure
    if not (tmp / "SKILL.md").exists():
        raise RuntimeError("the download has no SKILL.md")
    if dest.exists():
        _trash(dest)
    tmp.rename(dest)
    return dest


def _trash(path: Path) -> None:
    try:
        from send2trash import send2trash
        send2trash(str(path))
    except Exception:
        shutil.rmtree(path, ignore_errors=True)


# ── Creating ─────────────────────────────────────────────────────────────────

_SKILL_FORMAT = """\
A skill is a folder holding a SKILL.md file, optionally with scripts/ and
reference files next to it. SKILL.md starts with YAML front matter:

---
name: {name}
description: <one or two sentences: what the skill does AND when to use it,
  with the words a user would say. Claude decides from this line alone whether
  to load the skill, so it must name the triggers.>
---

followed by Markdown instructions written for Claude, not for a person:
the steps to follow, the output format, conventions, pitfalls, and short
examples. Keep it under ~400 lines; put long reference material or reusable
code in separate files and say in SKILL.md when to read or run them. Scripts
must run with python3 and the standard library unless a package is essential.
"""


def _create(name: str, description: str, language: str, progress,
            root: Path | None = None, space=None) -> Path:
    drafts = claude.workspace() / "skill_drafts"
    draft = drafts / name
    shutil.rmtree(draft, ignore_errors=True)
    draft.mkdir(parents=True, exist_ok=True)
    lang = (f" The user speaks {language}; write the description in English (it "
            f"is matched against requests) but add the {language} trigger words "
            f"too." if language else "")
    where = ""
    if space is not None:
        others = ", ".join(k["name"] for k in space.skills) or "none yet"
        where = (f"The skill belongs to the '{space.title}' skill space ({space.description}) "
                 f"and is used by that domain's specialist agent, unattended: it writes its "
                 f"deliverables in a shared work folder named in its task, runs bundled "
                 f"scripts as `python3 .claude/skills/{name}/<script>.py`, and has no browser, "
                 f"GUI or user accounts. Skills already in the space: {others} — do not "
                 f"duplicate them.\n\n")
    task = (
        f"Create a new Claude skill named '{name}' in the folder {draft}.\n\n"
        f"What the user wants the skill to do:\n{description}\n\n"
        f"{where}{_SKILL_FORMAT.format(name=name)}\n"
        f"If the skill-creator skill is installed, follow it. Write the files "
        f"directly into {draft} (SKILL.md at its root) and test any script you "
        f"write once with python3.{lang} Finish with one sentence describing "
        f"the skill."
    )

    def on_event(ev):
        act = claude.tool_activity(ev)
        if act:
            progress(act)

    res = claude.agent(task, add_dirs=[str(draft)], timeout=10 * 60, on_event=on_event)
    md = draft / "SKILL.md"
    if not md.exists():
        raise RuntimeError("Claude did not write a SKILL.md")
    fm = _frontmatter(md.read_text(encoding="utf-8", errors="replace"))
    if not fm.get("description"):
        raise RuntimeError("the SKILL.md it wrote has no description line")
    if fm.get("name") != name:
        # The folder name is what the skill is called by (/name); keep both the same.
        text = md.read_text(encoding="utf-8", errors="replace")
        if fm.get("name"):
            text = re.sub(r"(?m)^name:.*$", f"name: {name}", text, count=1)
        else:
            text = re.sub(r"^(﻿?---[ \t]*\r?\n)", rf"\g<1>name: {name}\n", text, count=1)
        md.write_text(text, encoding="utf-8")
    dest = (root or claude.skills_dir()) / name
    if dest.exists():
        _trash(dest)
    shutil.move(str(draft), str(dest))
    progress(res.text[:120])
    return dest


# ── Tool ─────────────────────────────────────────────────────────────────────

def manage_skills(parameters: dict, player=None) -> str:
    p = parameters or {}
    action = str(p.get("action") or "list").lower().strip()
    name = str(p.get("name") or "").strip()
    query = str(p.get("query") or p.get("description") or name).strip()
    language = str(p.get("language") or "").strip()

    # An IT skill space instead of Claude's own skills folder.
    space = None
    asked = str(p.get("space") or "").strip()
    if asked:
        space = spaces.resolve(asked)
        if space is None:
            return (f"There is no skill space called '{asked}'. Spaces: "
                    f"{', '.join(spaces.ids()) or 'none'}.")
    root = space.path if space else claude.skills_dir()
    where = f"the {space.title} skill space" if space else "Claude's skills"
    used_by = (f"the {space.title} specialist of the agent team uses it from its next task"
               if space else "Claude will use it from now on")

    if action == "list":
        have = installed(root)
        if space:
            if not have:
                return (f"The {space.title} skill space has no skill yet. Offer to find one in "
                        f"the public catalogue or to create one there.")
            return f"{len(have)} skills in the {space.title} space:\n{_describe(have)}"
        sps = spaces.all_spaces()
        tail = ("\nIT skill spaces, one per specialist of the agent team: "
                + ", ".join(f"{s.id} ({len(s.skills)})" for s in sps) if sps else "")
        if not have:
            return ("No skills are installed yet. Offer to find one in the public "
                    "catalogue or to create one." + tail)
        return f"{len(have)} installed skills:\n{_describe(have)}{tail}"

    if action == "find":
        if not query:
            return "Say what the skill should help with, in 'query'."
        have = installed(root)
        try:
            cat = catalogue()
        except Exception as e:
            cat, note = [], f"\n(The online catalogue could not be reached: {e})"
        else:
            note = ""
        names = {h["folder"] for h in have} | {h["name"] for h in have}
        cat = [c for c in cat if _slug(c["name"]) not in names and c["name"] not in names]
        hits = _rank(query, have + cat)
        if not hits:
            return (f"No existing skill fits '{query}'.{note} Offer to create one "
                    f"with action 'create'" + (f" in the {space.title} space." if space else "."))
        if space:
            return (f"Skills that fit '{query}', best first (installed = already in the "
                    f"{space.title} space):\n{_describe(hits)}{note}\nOffer to install a "
                    f"catalogue one into the space, or to create a new one if none fits.")
        return (f"Skills that fit '{query}', best first:\n{_describe(hits)}{note}\n"
                f"Installed ones are used automatically by ask_claude tasks; offer "
                f"to install a catalogue one, or to create a new skill if none fits.")

    if action == "install":
        if not name:
            return "Give the 'name' of the catalogue skill to install (from find)."
        try:
            cat = catalogue()
        except Exception as e:
            return f"The skill catalogue could not be reached: {e}"
        entry = next((c for c in cat if c["name"].lower() == name.lower()
                      or _slug(c["name"]) == _slug(name)), None)
        if entry is None:
            close = _keyword_rank(name, cat, 3)
            hint = f" Closest: {', '.join(c['name'] for c in close)}." if close else ""
            return f"No skill called '{name}' in the catalogue.{hint}"

        def work(progress) -> str:
            dest = _install(entry, progress, root)
            return (f"The skill '{entry['name']}' is installed in {dest} ({where}) and "
                    f"{used_by}. Tell the user in one sentence.")

        jobs.start(player, f"SKILL INSTALL — {entry['name']}", work)
        return ("status=installing_in_background. Say one short sentence that the "
                "skill is being installed.")

    if action == "create":
        description = str(p.get("description") or "").strip()
        if not description:
            return ("Describe what the new skill should do in 'description' — the "
                    "task, the inputs, the expected result.")
        slug = _slug(name or description[:40])
        if not _NAME_RE.match(slug):
            slug = f"skill-{int(time.time())}"

        def work(progress) -> str:
            dest = _create(slug, description, language, progress, root, space)
            return (f"The new skill '{slug}' is written ({dest / 'SKILL.md'}, {where}) and "
                    f"{used_by}. Tell the user in one or two sentences what it does.")

        jobs.start(player, f"SKILL CREATE — {slug}", work)
        return ("status=creating_in_background. Claude is writing the skill; you "
                "will be told when it is ready. Say one short sentence.")

    if action == "use":
        task = str(p.get("task") or "").strip()
        if space:
            return (f"The skills of the {space.title} space are used by its specialist: call "
                    f"the agents tool with action delegate, space '{space.id}' and the task.")
        if not name or not task:
            return "Give the skill's 'name' and the 'task' to do with it."
        folder = next((h["folder"] for h in installed()
                       if h["name"].lower() == name.lower() or h["folder"] == _slug(name)), None)
        if folder is None:
            return (f"No installed skill called '{name}'. Use action 'find' or "
                    f"'install' first.")
        out_dir = jarvis_documents_dir("claude")

        def work(progress) -> str:
            def on_event(ev):
                act = claude.tool_activity(ev)
                if act:
                    progress(act)
            lang = f" Write any text for the user in {language}." if language else ""
            res = claude.agent(
                f"/{folder} {task}",
                append_system=(f"\n\nSave deliverables in {out_dir}. Nobody can "
                               f"answer questions while you work. End with at most "
                               f"five sentences on what you did, then the full path "
                               f"of each file you created.{lang}"),
                add_dirs=[str(out_dir)], timeout=15 * 60, on_event=on_event)
            if player is not None and hasattr(player, "show_content"):
                player.show_content(f"SKILL — {folder}", res.text)
            return (f"The task with the skill '{folder}' is done. Report: "
                    f"{res.text[:1200]}\nTell the user in one or two sentences.")

        jobs.start(player, f"SKILL — {folder}", work)
        return "status=started_in_background. Say one short sentence that it has started."

    if action == "remove":
        if not name:
            return "Give the 'name' of the installed skill to remove."
        for h in installed(root):
            if h["name"].lower() == name.lower() or h["folder"] == _slug(name):
                _trash(root / h["folder"])
                return f"Skill '{h['name']}' moved to the trash ({where})."
        return f"No skill called '{name}' in {where}."

    return f"Unknown action '{action}'. Use list, find, install, create, use or remove."


TOOL = {
    "name": "manage_skills",
    "description": (
        "Manages Claude's skills — reusable instructions that teach Claude a task "
        "(make presentations, fill PDFs, follow a brand style, any workflow the "
        "user describes). 'find' searches the installed skills AND the public "
        "catalogue for one that fits; ALWAYS find before create, unless the user "
        "explicitly wants a new one. 'install' adds a catalogue skill. 'create' "
        "has Claude write a new skill from the user's description. 'use' runs a "
        "task with one named skill. 'list' shows what is installed, 'remove' "
        "deletes one. install, create and use run in the background. With 'space' "
        "(an IT skill space of the agent team: cyber, devops, network...), list, find, "
        "install, create and remove work on that space's skills."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING",
                       "description": "list | find | install | create | use | remove"},
            "query": {"type": "STRING",
                      "description": "find: what the skill should help with, in the user's words"},
            "name": {"type": "STRING",
                     "description": "install / use / remove: the skill's name; create: optional short name"},
            "description": {"type": "STRING",
                            "description": "create: everything the skill must do — task, inputs, steps, output, style"},
            "task": {"type": "STRING",
                     "description": "use: the task to perform with the skill"},
            "space": {"type": "STRING",
                      "description": "Optional: the IT skill space to work on (e.g. cyber, devops, network)"},
            "language": {"type": "STRING",
                         "description": "Language the user speaks, e.g. 'French'"},
        },
        "required": ["action"],
    },
    "handler": manage_skills,
}
