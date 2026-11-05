"""
Skill spaces — one folder of Claude skills per IT domain, and the specialist
agent that works with them.

WHAT A SPACE IS
    skill_spaces/<id>/SPACE.md          who the specialist is (front matter: id,
                                        title, description, routing keywords,
                                        model, Bash presets; body: its role)
    skill_spaces/<id>/<skill>/SKILL.md  the skills it works with, plus any
                                        scripts next to them

    programming, web, mobile, desktop, cyber, network, infra, cloud, devops,
    database, data, ml, ai-agents, design, qa, architecture — and whatever
    folder is added next to them: nothing here names a space.

WHY SPACES AND NOT ONE BIG SKILLS FOLDER
    Claude Code lists every skill it can see to the model, on every agent
    run. Sixteen domains of skills in workspace/.claude/skills would be paid
    for, in tokens, by every ask_claude task — and a security agent choosing
    among Flutter and Terraform skills chooses worse. So a space is copied into
    the run folder of the one specialist that needs it (core/orchestrator.py),
    and nowhere else. manage_skills installs and writes skills into a space.

WHAT THE SPACE FILE MAY NOT DECIDE
    Which shell commands a specialist may run is not written in SPACE.md: the
    file names presets, and the commands behind them are listed here, where
    no skill downloaded from a catalogue can widen them.

    python -m core.spaces            lists the spaces
    python -m core.spaces --check    validates every space and skill
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

if getattr(sys, "frozen", False):
    _BASE = Path(sys.executable).parent
else:
    _BASE = Path(__file__).resolve().parent.parent

ROOT = _BASE / "skill_spaces"
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
_SKILL_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")

# Shell commands a space may add on top of core/claude.AGENT_BASH, by preset.
# Read-only or local-only on purpose: nothing that deletes, deploys, pushes,
# scans someone else's machine or installs system packages. Patterns follow
# Claude Code's Bash(...) permission rules; a bare command is an exact match.
#
# Git is reached as `git -C <folder> <subcommand>`: a specialist's current
# folder is its run folder, never the repository, and Claude Code refuses
# `cd <folder> && git ...` (a repository's own config could run code). The
# `*` after -C matches any text, so `git -C * log *` would also match
# `git -C x push origin log`: GIT_DENY below closes those doors, and deny
# rules always win over allow rules. (Measured with Claude Code 2.1.299.)
BASH_PRESETS: dict[str, tuple[str, ...]] = {
    "git-read": ("git -C * status", "git -C * status *", "git -C * diff", "git -C * diff *",
                 "git -C * log", "git -C * log *", "git -C * show", "git -C * show *",
                 "git -C * branch", "git -C * branch --list*", "git -C * branch -a",
                 "git -C * branch -v*", "git -C * rev-parse *"),
    "git-local": ("git init *", "git -C * add *", "git -C * commit *"),
    "node-dev": ("npm ci", "npm ci *", "npm i", "npm i *", "npm run *", "npm test",
                 "npm test *", "npm init *"),
    "python-dev": ("pytest", "pytest *", "ruff check*", "ruff format --check*",
                   "ruff format --diff*", "mypy *"),
    "docker-read": ("docker compose config", "docker compose config *", "docker version",
                    "docker --version", "docker images", "docker ps", "docker ps *"),
    "net-read": ("ip addr", "ip a", "ip -br a", "ip -br addr", "ip route", "ip r",
                 "ip link", "ip -br link", "ping -c *", "dig *", "nslookup *", "host *",
                 "traceroute *", "tracepath *", "ipconfig", "ipconfig /all"),
    "audit": ("npm audit", "npm audit --json", "npm audit --omit=dev*", "pip-audit",
              "pip-audit *", "bandit *", "gitleaks detect*"),
}

# Refused for every specialist, whatever its presets allow: git subcommands
# that rewrite, discard or send work, and the options that inject config
# (-c), write files (--output) or swap the git binary (--exec-path).
GIT_DENY: tuple[str, ...] = tuple(
    f"git -C * {sub}" for sub in (
        "push*", "pull*", "fetch*", "remote*", "reset*", "clean*", "checkout*", "switch*",
        "restore*", "rebase*", "merge*", "cherry-pick*", "revert*", "am *", "apply*",
        "stash*", "rm *", "mv *", "tag*", "config*", "gc*", "prune*", "reflog expire*",
        "filter-branch*", "filter-repo*", "update-ref*", "replace*", "submodule*",
        "worktree*", "notes*", "branch -d*", "branch -D*", "branch -m*", "branch -M*",
        "branch --delete*", "branch --move*", "commit --amend*", "-c *", "*--output*",
        "*--exec-path*", "*--git-dir*", "*--work-tree*", "*--ext-diff*", "difftool*",
        "mergetool*"))

_MODELS = {"haiku", "sonnet", "opus", "fable", "agent"}


@dataclass
class Space:
    id: str
    title: str
    description: str
    keywords: tuple[str, ...]
    model: str
    presets: tuple[str, ...]
    role: str
    path: Path
    skills: list[dict] = field(default_factory=list)

    @property
    def bash(self) -> tuple[str, ...]:
        """The Bash patterns this specialist gets on top of AGENT_BASH."""
        out: list[str] = []
        for name in self.presets:
            for pat in BASH_PRESETS.get(name, ()):
                if pat not in out:
                    out.append(pat)
        return tuple(out)

    def commands(self) -> str:
        """The commands this specialist may run, in words for its prompt."""
        return describe_commands(self.bash)

    def line(self) -> str:
        n = len(self.skills)
        return f"{self.id} — {self.title} ({n} skill{'s' if n != 1 else ''}): {self.description}"


def describe_commands(extra: tuple[str, ...] = ()) -> str:
    """The base allowlist plus `extra` patterns as a list of commands for a
    prompt. An agent that knows the list tries the allowed form instead of
    deciding, after one refusal, that it has no shell at all."""
    from core.claude import AGENT_BASH
    seen: list[str] = []
    for pat in tuple(AGENT_BASH) + tuple(extra):
        cmd = pat.rstrip("*").strip().replace("git -C * ", 'git -C "<folder>" ')
        if cmd and cmd not in seen:
            seen.append(cmd)
    return ", ".join(f"`{c}`" for c in seen)


# ── SKILL.md / SPACE.md front matter ─────────────────────────────────────────

def frontmatter(text: str) -> dict:
    """name, description and the other keys of a SKILL.md / SPACE.md YAML
    header. Deliberately small: plain, quoted and folded (> or |) values are
    all the format uses."""
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


def _body(text: str) -> str:
    m = re.match(r"^﻿?---\s*\n.*?\n---\s*(\n|$)", text, re.S)
    return (text[m.end():] if m else text).strip()


def _split(value: str) -> tuple[str, ...]:
    return tuple(x.strip() for x in str(value or "").split(",") if x.strip())


# ── Discovery ────────────────────────────────────────────────────────────────

def skills_of(path: Path) -> list[dict]:
    """The skills in one space folder (or any skills folder)."""
    out = []
    for md in sorted(path.glob("*/SKILL.md")) if path.is_dir() else ():
        try:
            fm = frontmatter(md.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            fm = {}
        out.append({"name": fm.get("name") or md.parent.name, "folder": md.parent.name,
                    "description": fm.get("description", ""), "installed": True})
    return out


def _load(folder: Path) -> Space | None:
    md = folder / "SPACE.md"
    if not _ID_RE.match(folder.name) or not md.is_file():
        return None
    try:
        text = md.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    fm = frontmatter(text)
    model = str(fm.get("model") or "sonnet").strip().lower()
    return Space(id=folder.name, title=fm.get("title") or folder.name,
                 description=fm.get("description", ""),
                 keywords=tuple(k.lower() for k in _split(fm.get("keywords"))),
                 model=model if model in _MODELS or model.startswith("claude-") else "sonnet",
                 presets=_split(fm.get("bash")), role=_body(text), path=folder,
                 skills=skills_of(folder))


def all_spaces() -> list[Space]:
    """Every space on disk, read fresh each time (a few small files): a skill
    written a minute ago is already there."""
    if not ROOT.is_dir():
        return []
    return [s for s in (_load(d) for d in sorted(ROOT.iterdir()) if d.is_dir()) if s]


def get(space_id: str) -> Space | None:
    sid = str(space_id or "").strip().lower()
    if not _ID_RE.match(sid):
        return None
    return _load(ROOT / sid)


def ids() -> list[str]:
    return [s.id for s in all_spaces()]


# ── Routing, locally and for free ────────────────────────────────────────────

def _fold(text: str) -> str:
    """Lower case, accents dropped, whitespace collapsed: 'Réseau' == 'reseau'."""
    ascii_ = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
    return " ".join(ascii_.lower().split())


def _hit(phrase: str, text: str) -> bool:
    return re.search(r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])", text) is not None


def match(text: str, limit: int = 3) -> list[tuple[Space, float]]:
    """Spaces whose keywords appear in `text`, best first. A long phrase
    ('pipeline de donnees') outweighs a short one ('pipeline'), so the more
    specific domain wins."""
    t = _fold(text)
    scored = []
    for sp in all_spaces():
        s = 0.0
        for kw in {_fold(k) for k in sp.keywords} | {sp.id, _fold(sp.title)}:
            if kw and _hit(kw, t):
                s += len(kw)
        if s:
            scored.append((sp, s))
    scored.sort(key=lambda x: -x[1])
    return scored[:limit]


def resolve(name: str) -> Space | None:
    """The space a spoken or written name means: its id, its title, one of
    its keywords, or the best keyword match."""
    raw = str(name or "").strip()
    if not raw:
        return None
    sp = get(_fold(raw).replace(" ", "-"))
    if sp:
        return sp
    folded = _fold(raw)
    for s in all_spaces():
        if folded in (_fold(s.title), s.id.replace("-", " ")) or folded in {_fold(k) for k in s.keywords}:
            return s
    best = match(raw, limit=1)
    return best[0][0] if best else None


# ── Using a space ────────────────────────────────────────────────────────────

def skills_root(space_id: str) -> Path | None:
    """Where the skills of a space live (its own folder), or None."""
    sp = get(space_id)
    return sp.path if sp else None


def install_into(space: Space, skills_dir: Path) -> int:
    """Copy the space's skills into an agent's .claude/skills, replacing what a
    previous run left there. Copies, not links: an agent edits its copy, never
    the space."""
    if skills_dir.exists():
        shutil.rmtree(skills_dir)
    skills_dir.mkdir(parents=True)
    n = 0
    for sk in space.skills:
        src = space.path / sk["folder"]
        if (src / "SKILL.md").is_file():
            shutil.copytree(src, skills_dir / sk["folder"],
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            n += 1
    return n


def model_for(space: Space) -> str:
    """config/api_keys.json "agents_models" {"cyber": "opus"} wins, then
    "agents_model" for every space, then the space's own `model`. "agent"
    means the claude_model_agent tier (Opus by default)."""
    cfg: dict = {}
    try:
        cfg = json.loads((_BASE / "config" / "api_keys.json").read_text(encoding="utf-8"))
    except Exception:
        pass
    per = cfg.get("agents_models")
    model = ""
    if isinstance(per, dict) and per.get(space.id):
        model = str(per[space.id])
    model = model or str(cfg.get("agents_model") or "") or space.model or "sonnet"
    if model == "agent":
        from core import claude
        return claude.model_for(claude.AGENT)
    return model


# ── Checking ─────────────────────────────────────────────────────────────────

def check() -> tuple[list[str], list[str]]:
    """(errors, warnings) over every space folder and skill."""
    errors: list[str] = []
    warnings: list[str] = []
    if not ROOT.is_dir():
        return [f"{ROOT} does not exist"], []
    for d in sorted(p for p in ROOT.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))):
        md = d / "SPACE.md"
        if not md.is_file():
            warnings.append(f"{d.name}/: no SPACE.md — not a space")
            continue
        if not _ID_RE.match(d.name):
            errors.append(f"{d.name}/: folder name must be lower-case letters, digits and dashes")
            continue
        fm = frontmatter(md.read_text(encoding="utf-8", errors="replace"))
        if not fm:
            errors.append(f"{d.name}/SPACE.md: no front matter")
            continue
        if fm.get("name") != d.name:
            errors.append(f"{d.name}/SPACE.md: name {fm.get('name')!r} is not the folder name")
        for key in ("title", "description", "keywords"):
            if not fm.get(key):
                errors.append(f"{d.name}/SPACE.md: {key} is missing")
        model = str(fm.get("model") or "sonnet").lower()
        if model not in _MODELS and not model.startswith("claude-"):
            errors.append(f"{d.name}/SPACE.md: unknown model {model!r}")
        for p in _split(fm.get("bash")):
            if p not in BASH_PRESETS:
                errors.append(f"{d.name}/SPACE.md: unknown bash preset {p!r} "
                              f"(known: {', '.join(BASH_PRESETS)})")
        sp = _load(d)
        if sp and not sp.role:
            errors.append(f"{d.name}/SPACE.md: the role (body) is empty")
        if sp and not sp.skills:
            warnings.append(f"{d.name}/: no skill yet")
        names: set[str] = set()
        for sk in skills_of(d):
            where = f"{d.name}/{sk['folder']}/SKILL.md"
            if not _SKILL_RE.match(sk["folder"]):
                errors.append(f"{where}: folder name must be lower-case letters, digits and dashes")
            if sk["name"] != sk["folder"]:
                errors.append(f"{where}: name {sk['name']!r} is not the folder name")
            if not sk["description"]:
                errors.append(f"{where}: no description — Claude would never load it")
            elif len(sk["description"]) > 1024:
                errors.append(f"{where}: description is {len(sk['description'])} characters (max 1024)")
            if sk["name"] in names:
                errors.append(f"{where}: two skills named {sk['name']!r}")
            names.add(sk["name"])
    return errors, warnings


def _main(argv: list[str]) -> int:
    if "--check" in argv:
        errors, warnings = check()
        for w in warnings:
            print(f"WARN  {w}")
        for e in errors:
            print(f"ERROR {e}")
        spaces = all_spaces()
        print(f"{len(spaces)} spaces, {sum(len(s.skills) for s in spaces)} skills — "
              f"{len(errors)} error(s), {len(warnings)} warning(s)")
        return 1 if errors else 0
    spaces = all_spaces()
    if "--json" in argv:
        print(json.dumps([{"id": s.id, "title": s.title, "description": s.description,
                           "model": s.model, "presets": list(s.presets),
                           "skills": [k["name"] for k in s.skills]} for s in spaces],
                         ensure_ascii=False, indent=2))
        return 0
    for s in spaces:
        print(s.line())
        for k in s.skills:
            print(f"    · {k['name']}")
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
