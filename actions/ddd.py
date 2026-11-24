"""
ddd — runs the Domain-Driven Design pack (skill_packs/ddd/) in a Scrum workspace.

THE JOIN BETWEEN THE PROJECT FILE AND THE CODE
    The Scrum pack says what is wanted (cahier des charges, backlog); the
    Replica pipeline builds it. Between the two, this turns the words of the
    specification into the model the code is written in (Evans, 2003):

        domaine    the ubiquitous language, the subdomains (core, supporting,
                   generic) and how each is built, the domain vision statement
        contextes  the bounded contexts, the story and requirement each one
                   owns, the external systems, the context map
        modele     per context: aggregates and their invariants (from the RG
                   rules), value objects, services, specifications (from the
                   acceptance criteria), domain events, modules

    ddd.py checks them and writes livrables/ddd.md. Downstream, the chiffrage
    breaks the work down by context (a work package stays in one), and the
    code project gets docs/ddd/: its spec, architecture, build and tests
    follow the contexts, the aggregates and the names of the glossary. After
    the build, check_code() reads the code back against the model.

NOT A TOOL, ON PURPOSE
    No TOOL dict, like chiffrage: one more declaration would be paid for in
    tokens on every Gemini turn. actions/direction.py runs it.

WHY THE ASSISTANT CHECKS ITSELF
    Same as the Scrum and chiffrage packs: after every step the assistant
    runs the reviewed copy of ddd.py (skill_packs/, which no agent can edit),
    hands the exact errors to a short correction run, twice at most.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from actions.project import _STEP_FINAL, _assistant_name, _config, _denied, _now, _step_status
from core import claude

if getattr(sys, "frozen", False):
    _BASE = Path(sys.executable).parent
else:
    _BASE = Path(__file__).resolve().parent.parent

_PACK = _BASE / "skill_packs" / "ddd"
_STATE = Path(".jarvis") / "ddd.json"

STEPS = ("domaine", "contextes", "modele")
# The file each step owns, as ddd.py names it in its messages.
STEP_FILES = {"domaine": "domaine.json", "contextes": "contextes.json", "modele": "modele.json"}
# What the code project gets: the data, for agents that check a name, and
# the readable model, for everyone else.
CODE_DOCS = ("ddd/domaine.json", "ddd/contextes.json", "ddd/modele.json", "livrables/ddd.md")
_FIX_ROUNDS = 2
_FIX_TIMEOUT = 8 * 60
_TIMEOUT = 20 * 60


# ── State ────────────────────────────────────────────────────────────────────

def load(path: Path) -> dict:
    """The DDD records of a workspace ({} before the first step)."""
    try:
        data = json.loads((path / _STATE).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _record(path: Path, step: str, rec: dict) -> None:
    state = load(path)
    state.setdefault("steps", {})[step] = rec
    target = path / _STATE
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(target)


def done(path: Path, step: str) -> bool:
    return (load(path).get("steps") or {}).get(step, {}).get("status") == "done"


def model_for(step: str) -> str:
    """Sonnet: structured analysis, not code. "ddd_models" ({"step": "model"})
    and "ddd_model" in config/api_keys.json override it."""
    cfg = _config()
    custom = cfg.get("ddd_models")
    if isinstance(custom, dict) and custom.get(step):
        return str(custom[step])
    return str(cfg.get("ddd_model") or "sonnet")


# ── The pack and the checker ─────────────────────────────────────────────────

def install(path: Path) -> None:
    """The skills, the agents' copy of the checker and ddd/, as this version of
    the app ships them. Done before every run, like the other packs."""
    skills = path / ".claude" / "skills"
    skills.mkdir(parents=True, exist_ok=True)
    for d in sorted(_PACK.glob("ddd-*")):
        shutil.copytree(d, skills / d.name, dirs_exist_ok=True)
    kit = path / ".claude" / "ddd-kit"
    kit.mkdir(exist_ok=True)
    shutil.copy2(_PACK / "ddd.py", kit / "ddd.py")
    (path / "ddd").mkdir(exist_ok=True)


def calc(path: Path, check: bool = False, code: Path | None = None) -> dict:
    """The reviewed ddd.py on the workspace: {errors, warnings, written,
    summary}, or {'error': …} when it could not run. Without `check` it also
    writes livrables/ddd.md (when there is no error left); with `code` it
    reads that folder back against the model."""
    cmd = [sys.executable, "-I", str(_PACK / "ddd.py"), str(path), "--json"]
    if check:
        cmd.append("--check")
    if code is not None:
        cmd += ["--code", str(code)]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        return json.loads(out.stdout)
    except Exception as e:
        return {"error": str(e)[:300]}


def _problems(path: Path, step: str) -> tuple[list[str], list[str]]:
    """What the check finds in the file this step owns."""
    found = calc(path, check=True)
    if "error" in found:
        return [], []
    prefix = STEP_FILES[step] + ":"
    mine = lambda items: [x for x in items or () if str(x).startswith(prefix)]
    return mine(found.get("errors")), mine(found.get("warnings"))


# ── Running a step ───────────────────────────────────────────────────────────

def _agent_system(name: str, language: str, final: str) -> str:
    lang_line = f"Write any text meant for the user in {language}.\n" if language else ""
    return (
        f"\n\nYou are working for {_assistant_name()}, a voice assistant, on the domain "
        f"model (Domain-Driven Design) of \"{name}\" in the current directory; its brief is "
        f"in CLAUDE.md and its Scrum deliverables are in scrum/. Nobody can answer questions "
        f"while you work: make reasonable choices, note each one in ddd/decisions.md, keep "
        f"what a domain expert should confirm in the questions of ddd/domaine.json, and "
        f"finish.\n"
        f"Write only in ddd/: the file of your skill, ddd/domaine.json when the language "
        f"needs a new term, and ddd/decisions.md. Never edit scrum/ or "
        f".claude/ddd-kit/ddd.py.\n"
        f"Keep token use low. Read only the files this step needs; do not re-read a file "
        f"you already have; do not paste file contents into your messages.\n"
        f"Run the checker with these exact commands, each on its own: "
        f"`python3 .claude/ddd-kit/ddd.py . --check` to check, "
        f"`python3 .claude/ddd-kit/ddd.py .` to write livrables/ddd.md (`python` on "
        f"Windows). The assistant runs the same check after you, sends any error back to "
        f"be fixed and writes livrables/ddd.md itself.\n"
        f"{lang_line}{final}")


def _step_task(step: str, chain: tuple) -> str:
    task = f"Run the ddd-{step} skill."
    if len(chain) > 1:
        task += (f"\n\nThis step is one of a run the assistant chains itself "
                 f"({' → '.join(chain)}). Do this step only and report on it only: the "
                 f"assistant starts the next one when you finish.")
    return task


def _fix(path: Path, name: str, language: str, step: str, model: str, on_event,
         progress) -> tuple[list[str], int]:
    """Short correction runs on the exact errors the check found, until it
    passes or _FIX_ROUNDS is spent. The errors left, the tokens used."""
    spent = 0
    for _ in range(_FIX_ROUNDS):
        errors, warnings = _problems(path, step)
        if not errors:
            return [], spent
        progress(f"{step} · fixing {len(errors)} error(s)")
        prompt = (f"The assistant ran `ddd.py --check` on the workspace and found these "
                  f"errors in ddd/{STEP_FILES[step]}. Fix exactly them; keep every id and "
                  f"everything else:\n" + "\n".join(f"- {e}" for e in errors[:40]))
        if warnings:
            prompt += ("\n\nRemarks from the same check: act on them too unless you have a "
                       "reason, and write the reason in ddd/decisions.md.\n"
                       + "\n".join(f"- {w}" for w in warnings[:15]))
        try:
            res = claude.agent(prompt, model=model, cwd=path,
                               append_system=_agent_system(name, language, ""),
                               timeout=_FIX_TIMEOUT, on_event=on_event)
            spent += res.tokens_in + res.tokens_out
        except claude.ClaudeError as e:
            print(f"[DDD] correction run failed: {e}")
            break
    return _problems(path, step)[0], spent


def run_step(path: Path, name: str, step: str, language: str, progress,
             chain: tuple = ()) -> dict:
    """One step: the agent run, the assistant's check and corrections, then
    the report written. Its record, also saved in .jarvis/ddd.json.
    Raises claude.ClaudeError when the run itself failed."""
    model = model_for(step)

    def on_event(ev):
        act = claude.tool_activity(ev)
        if act:
            progress(f"{step} · {act}")

    rec = {"model": model, "at": _now()}
    try:
        res = claude.agent(_step_task(step, chain), model=model, cwd=path,
                           append_system=_agent_system(name, language, _STEP_FINAL),
                           timeout=_TIMEOUT, on_event=on_event)
    except claude.ClaudeError as e:
        msg = str(e)
        if "already running" in msg:
            raise                      # nothing ran: nothing to record
        if "did not answer within" in msg:
            rec.update(status="partial", report="",
                       remains=f"stopped after {_TIMEOUT // 60} minutes; run the step again "
                               f"and it carries on from the ddd/ files")
            _record(path, step, rec)
            return rec
        rec.update(status="failed", report="", remains=msg[:300])
        _record(path, step, rec)
        raise

    status, remains, report = _step_status(res.text)
    left, fix_tokens = _fix(path, name, language, step, model, on_event, progress)
    if left:
        status = "partial"
        remains = f"{len(left)} error(s) the check still finds — {left[0]}"
    elif not (path / "ddd" / STEP_FILES[step]).is_file():
        status, remains = "partial", f"ddd/{STEP_FILES[step]} was not written"
    calc(path)                         # livrables/ddd.md, for the next step
    rec.update(status=status, remains=remains, report=report[:2000],
               tokens=res.tokens_in + res.tokens_out + fix_tokens,
               cached=res.tokens_cached, minutes=round(res.duration_s / 60, 1),
               checked=not left)
    if _denied(res):
        rec["denied"] = _denied(res)
    _record(path, step, rec)
    return rec


# ── What the rest of the app reads ───────────────────────────────────────────

def headline(path: Path) -> str:
    """'3 contextes · 7 agrégats · 24 termes · cœur : …' from the check, or ''."""
    s = calc(path, check=True).get("summary") or {}
    parts = []
    if s.get("contexts"):
        parts.append(f"{s['contexts']} contexte(s)")
    if s.get("aggregates"):
        parts.append(f"{s['aggregates']} agrégat(s)")
    if s.get("terms"):
        parts.append(f"{s['terms']} termes")
    if s.get("core"):
        parts.append("cœur : " + ", ".join(s["core"]))
    return " · ".join(parts)


def copy_to(ws: Path, pdir: Path) -> bool:
    """The model into the code project's docs/ddd/ (data and report). True
    when there was one to copy."""
    copied = False
    for src in CODE_DOCS:
        if (ws / src).is_file():
            dest = pdir / "docs" / "ddd" / Path(src).name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes((ws / src).read_bytes())
            copied = True
    return copied


def check_code(ws: Path, pdir: Path) -> str:
    """Reads the built code back against the model: '12/15 noms du modèle
    dans le code · 1 mot à éviter', or '' when there is nothing to say.
    Local and free: no agent. Also refreshes livrables/ddd.md with it."""
    if not (ws / "ddd" / "contextes.json").is_file() or not pdir.is_dir():
        return ""
    conf = (calc(ws, code=pdir).get("summary") or {}).get("conformance") or {}
    if not conf.get("names"):
        return ""
    note = f"langage : {conf['found']}/{conf['names']} noms du modèle dans le code"
    if conf.get("avoid_used"):
        note += f" · {len(conf['avoid_used'])} mot(s) à éviter employé(s)"
    if (ws / "livrables" / "ddd.md").is_file():
        copy_to(ws, pdir)               # the report with its conformity section
    return note
