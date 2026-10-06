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
"""
from __future__ import annotations

import json
import re
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

from core import claude, jobs
from core.user_dirs import jarvis_documents_dir

_DEFAULT_SOURCES = ("anthropics/skills",)
_INDEX_TTL = 24 * 3600
_HTTP_TIMEOUT = 20
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


# ── SKILL.md ─────────────────────────────────────────────────────────────────

def _frontmatter(text: str) -> dict:
    """name and description from a SKILL.md's YAML header. Deliberately small:
    plain, quoted and folded (> or |) values are all the format uses."""
    m = re.match(r"^﻿?---\s*\n(.*?)\n---\s*(\n|$)", text, re.S)
    if not m:
        return {}
    out: dict[str, str] = {}
    key, buf = None, []
    for line in m.group(1).splitlines():
        km = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if km and not line.startswith((" ", "\t")):
            if key:
                out[key] = " ".join(buf).strip()
            key, val = km.group(1), km.group(2).strip()
            buf = [] if val in (">", "|", ">-", "|-") else [val]
        elif key:
            buf.append(line.strip())
    if key:
        out[key] = " ".join(buf).strip()
    for k, v in out.items():
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1].replace('\\"', '"')
        out[k] = v
    return out


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:64].strip("-") or f"skill-{int(time.time())}"


def installed() -> list[dict]:
    out = []
    for md in sorted(claude.skills_dir().glob("*/SKILL.md")):
        try:
            fm = _frontmatter(md.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            fm = {}
        out.append({"name": fm.get("name") or md.parent.name, "folder": md.parent.name,
                    "description": fm.get("description", ""), "installed": True})
    return out


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

def _install(entry: dict, progress) -> Path:
    dest = claude.skills_dir() / _slug(entry["name"])
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


def _create(name: str, description: str, language: str, progress) -> Path:
    drafts = claude.workspace() / "skill_drafts"
    draft = drafts / name
    shutil.rmtree(draft, ignore_errors=True)
    draft.mkdir(parents=True, exist_ok=True)
    lang = (f" The user speaks {language}; write the description in English (it "
            f"is matched against requests) but add the {language} trigger words "
            f"too." if language else "")
    task = (
        f"Create a new Claude skill named '{name}' in the folder {draft}.\n\n"
        f"What the user wants the skill to do:\n{description}\n\n"
        f"{_SKILL_FORMAT.format(name=name)}\n"
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
    dest = claude.skills_dir() / name
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

    if action == "list":
        have = installed()
        if not have:
            return ("No skills are installed yet. Offer to find one in the public "
                    "catalogue or to create one.")
        return f"{len(have)} installed skills:\n{_describe(have)}"

    if action == "find":
        if not query:
            return "Say what the skill should help with, in 'query'."
        have = installed()
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
                    f"with action 'create'.")
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
            dest = _install(entry, progress)
            return (f"The skill '{entry['name']}' is installed in {dest} and Claude "
                    f"will use it from now on. Tell the user in one sentence.")

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
            dest = _create(slug, description, language, progress)
            return (f"The new skill '{slug}' is written ({dest / 'SKILL.md'}) and "
                    f"Claude will use it from the next task on. Tell the user in one "
                    f"or two sentences what it does.")

        jobs.start(player, f"SKILL CREATE — {slug}", work)
        return ("status=creating_in_background. Claude is writing the skill; you "
                "will be told when it is ready. Say one short sentence.")

    if action == "use":
        task = str(p.get("task") or "").strip()
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
        for h in installed():
            if h["name"].lower() == name.lower() or h["folder"] == _slug(name):
                _trash(claude.skills_dir() / h["folder"])
                return f"Skill '{h['name']}' moved to the trash."
        return f"No installed skill called '{name}'."

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
        "deletes one. install, create and use run in the background."
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
            "language": {"type": "STRING",
                         "description": "Language the user speaks, e.g. 'French'"},
        },
        "required": ["action"],
    },
    "handler": manage_skills,
}
