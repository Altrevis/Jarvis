"""
chiffrage — runs the chiffrage pack (skill_packs/chiffrage/) in a Scrum workspace.

NOT A TOOL, ON PURPOSE
    There is no TOOL dict here, so the action loader leaves this file out of
    the voice session: one more declaration would be paid for in tokens on
    every Gemini turn. Today only actions/direction.py runs a chiffrage; a
    voice tool can be put on top of these functions later.

WHERE IT RUNS
    In the project's Scrum workspace (Documents/JARVIS/scrum/<slug>/), next to
    scrum/: chiffrage-wbs reads the cahier des charges and maps every story of
    scrum/product-backlog.json to a work package, so an estimate is built on
    the backlog when there is one. The steps write chiffrage/*.json and
    chiffrage/pitch.md; chiffrage.py computes chiffrage/synthese.json and
    livrables/chiffrage.md from them.

WHY THE ASSISTANT CHECKS AND COMPUTES ITSELF
    Same reason as the Scrum pack: an unattended agent can have a command
    refused and stop checking, and a language model adding forty three-point
    estimates gets a digit wrong sooner or later. So after every step the
    assistant runs the reviewed copy of chiffrage.py (skill_packs/, which no
    agent can edit), hands the exact errors to a short correction run, twice
    at most, then computes the figures.
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

_PACK = _BASE / "skill_packs" / "chiffrage"
_STATE = Path(".jarvis") / "chiffrage.json"

STEPS = ("wbs", "estimation", "budget", "tco", "pitch")
# The file each step owns, as chiffrage.py names it in its messages.
STEP_FILES = {"wbs": "wbs.json", "estimation": "estimation.json", "budget": "budget.json",
              "tco": "tco.json", "pitch": "pitch.md"}
_FIX_ROUNDS = 2
_FIX_TIMEOUT = 8 * 60
_TIMEOUT = 20 * 60


# ── State ────────────────────────────────────────────────────────────────────

def load(path: Path) -> dict:
    """The chiffrage records of a workspace ({} before the first step)."""
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
    # Same atomic write as the Scrum state, next to it in .jarvis/.
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(target)


def done(path: Path, step: str) -> bool:
    return (load(path).get("steps") or {}).get(step, {}).get("status") == "done"


def model_for(step: str) -> str:
    """Sonnet: structured writing, not code. "chiffrage_models" ({"step":
    "model"}) and "chiffrage_model" in config/api_keys.json override it."""
    cfg = _config()
    custom = cfg.get("chiffrage_models")
    if isinstance(custom, dict) and custom.get(step):
        return str(custom[step])
    return str(cfg.get("chiffrage_model") or "sonnet")


# ── The pack and the calculator ──────────────────────────────────────────────

def install(path: Path) -> None:
    """The skills, the agents' copy of the calculator and chiffrage/, as this
    version of the app ships them. Done before every run, like the Scrum pack."""
    skills = path / ".claude" / "skills"
    skills.mkdir(parents=True, exist_ok=True)
    for d in sorted(_PACK.glob("chiffrage-*")):
        shutil.copytree(d, skills / d.name, dirs_exist_ok=True)
    kit = path / ".claude" / "chiffrage-kit"
    kit.mkdir(exist_ok=True)
    shutil.copy2(_PACK / "chiffrage.py", kit / "chiffrage.py")
    (path / "chiffrage").mkdir(exist_ok=True)


def calc(path: Path, check: bool = False) -> dict:
    """The reviewed chiffrage.py on the workspace: {errors, warnings, written,
    summary}, or {'error': …} when it could not run. Without `check` it also
    writes chiffrage/synthese.json and livrables/chiffrage.md (when there is
    no error left)."""
    cmd = [sys.executable, "-I", str(_PACK / "chiffrage.py"), str(path), "--json"]
    if check:
        cmd.append("--check")
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
        f"\n\nYou are working for {_assistant_name()}, a voice assistant, on the chiffrage "
        f"(estimate and costing) of \"{name}\" in the current directory; its brief is in "
        f"CLAUDE.md, its Scrum deliverables are in scrum/ and its domain model, when there "
        f"is one, in ddd/. Nobody can answer questions while you work: make reasonable "
        f"choices, note each one in chiffrage/decisions.md, and finish.\n"
        f"Write only in chiffrage/: the file of your skill and chiffrage/decisions.md. Never "
        f"edit scrum/, ddd/ or .claude/chiffrage-kit/chiffrage.py, and never do the arithmetic "
        f"yourself: chiffrage.py computes every figure.\n"
        f"Keep token use low. Read only the files this step needs; do not re-read a file "
        f"you already have; do not paste file contents into your messages.\n"
        f"Run the calculator with these exact commands, each on its own: "
        f"`python3 .claude/chiffrage-kit/chiffrage.py . --check` to check, "
        f"`python3 .claude/chiffrage-kit/chiffrage.py .` to compute (`python` on Windows). "
        f"The assistant runs the same check after you, sends any error back to be fixed "
        f"and computes livrables/chiffrage.md itself.\n"
        f"{lang_line}{final}")


def _step_task(step: str, chain: tuple) -> str:
    task = f"Run the chiffrage-{step} skill."
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
        prompt = (f"The assistant ran `chiffrage.py --check` on the workspace and found these "
                  f"errors in chiffrage/{STEP_FILES[step]}. Fix exactly them; keep every id and "
                  f"everything else:\n" + "\n".join(f"- {e}" for e in errors[:40]))
        if warnings:
            prompt += ("\n\nRemarks from the same check: act on them too unless you have a "
                       "reason, and write the reason in chiffrage/decisions.md.\n"
                       + "\n".join(f"- {w}" for w in warnings[:15]))
        try:
            res = claude.agent(prompt, model=model, cwd=path,
                               append_system=_agent_system(name, language, ""),
                               timeout=_FIX_TIMEOUT, on_event=on_event)
            spent += res.tokens_in + res.tokens_out
        except claude.ClaudeError as e:
            print(f"[Chiffrage] correction run failed: {e}")
            break
    return _problems(path, step)[0], spent


def run_step(path: Path, name: str, step: str, language: str, progress,
             chain: tuple = ()) -> dict:
    """One step: the agent run, the assistant's check and corrections, then
    the figures computed. Its record, also saved in .jarvis/chiffrage.json.
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
                               f"and it carries on from the chiffrage/ files")
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
    elif not (path / "chiffrage" / STEP_FILES[step]).is_file():
        status, remains = "partial", f"chiffrage/{STEP_FILES[step]} was not written"
    calc(path)                         # synthese.json and livrables/chiffrage.md, for the next step
    rec.update(status=status, remains=remains, report=report[:2000],
               tokens=res.tokens_in + res.tokens_out + fix_tokens,
               cached=res.tokens_cached, minutes=round(res.duration_s / 60, 1),
               checked=not left)
    if _denied(res):
        rec["denied"] = _denied(res)
    _record(path, step, rec)
    return rec


def headline(path: Path) -> str:
    """'Charge P50 … · prix HT … · TCO …' from the computed summary, or ''."""
    found = calc(path, check=True)
    s = found.get("summary") or {}
    parts = []
    e, b, t = s.get("estimation") or {}, s.get("budget") or {}, s.get("tco") or {}
    if e.get("expected"):
        parts.append(f"charge P50 {round(float(e['expected']))} j·h")
    if b.get("price_ht"):
        parts.append(f"prix {round(float(b['price_ht'])):,} € HT".replace(",", " "))
    if t.get("tco"):
        parts.append(f"TCO {t.get('years', '?')} ans {round(float(t['tco'])):,} €".replace(",", " "))
    return " · ".join(parts)
