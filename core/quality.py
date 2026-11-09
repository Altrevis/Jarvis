"""
quality — what every agent that writes files must respect, and the
assistant's own check of it.

TWO KINDS OF WORK
    Agents write for one of two purposes, and they are told which:

        improving Jarvis   the folder is the assistant's own code (this
                           repository): a mission whose target is Jarvis
        another project    anything else: a mission's work folder, a target
                           that is the user's project, a project of
                           actions/project.py

    The rules below hold for both. SELF_RULES is added when the folder is
    Jarvis itself: its conventions, what must never be touched, what to tell
    the user to restart.

THE RULES
    Two short blocks go into the system prompt of every agent that writes
    files — the specialists of the agent team (core/orchestrator.py) and the
    steps of a project (actions/project.py):

        CODE_RULES   code and markup a person can open and maintain by hand
        LEGAL_RULES  nothing that exposes the user to a copyright, licence,
                     trademark or GDPR claim

    They cost a few hundred tokens, prompt-cached. The detail lives in the
    `legal` skill space, which only its specialist loads.

THE CHECK
    An agent can break a rule it was given, so the assistant checks after the
    run: it scans each folder the run could write in before and after, with
    the legal specialist's scanner — the reviewed copy in skill_spaces/,
    never the copy in a run folder, which an agent could edit — and keeps only
    the errors the run added. An agent working on an existing codebase (Jarvis
    or the user's project) answers for what it changed, not for what was
    there before it. The new errors go back to the agent in its correction
    run; what is left is reported as unfinished, never as done.
"""
from __future__ import annotations

import importlib.util
import sys
from collections import Counter
from pathlib import Path

if getattr(sys, "frozen", False):
    JARVIS_ROOT = Path(sys.executable).parent
else:
    JARVIS_ROOT = Path(__file__).resolve().parent.parent

SCANNER = JARVIS_ROOT / "skill_spaces" / "legal" / "licensing-copyright" / "legal_scan.py"

CODE_RULES = (
    "Code and markup are maintained by people after you: write them formatted the way the "
    "language's standard formatter would (Prettier, Black, gofmt…), one statement per line, HTML "
    "and SVG indented one element per line, CSS in stylesheets rather than long inline styles, "
    "clear names, a short comment where the reason is not obvious. Never minify or squeeze what "
    "you write onto one line: only build output may be minified."
)

LEGAL_RULES = (
    "Nothing you deliver may expose the user to a copyright, licence, trademark or GDPR claim:\n"
    "- Never copy, download or hotlink an image, icon, font, sound, video or text found online "
    "unless its licence allows commercial use (CC0, Unsplash, Pexels, CC BY with its credit, OFL, "
    "MIT…). Never another company's logo, name or look. Prefer drawing your own (SVG, CSS) or a "
    "neutral placeholder. Screenshots of another product, taken for research, stay in the research "
    "folder and never reach the product.\n"
    "- Record every asset you add in credits.json at the root of the folder you work in: path, "
    "source (URL or \"original\"), author, licence, attribution when the licence asks for one.\n"
    "- No private links: Drive, Dropbox, OneDrive, WeTransfer, signed or tokenised URLs, chat "
    "attachments.\n"
    "- Self-host fonts and libraries (no Google Fonts or public CDN links); no analytics, pixel "
    "or embed that loads before the visitor's consent.\n"
    "- Fake personal data only (example.com, Faker) in code, fixtures and seeds.\n"
    "- Code from the web only under a compatible licence, with its notice; no AGPL, SSPL, "
    "non-commercial or unlicensed dependency without saying so in your report.\n"
    "The assistant scans what you write for these and sends back what you added."
)

SELF_RULES = (
    f"{JARVIS_ROOT} is the assistant's own code (Jarvis): there you improve the assistant itself, "
    "you do not build a product for someone. Read readme.md and the docstring of each module you "
    "change, and follow their conventions: the token-saving design, the reviewed copies the "
    "assistant runs, the voice-first tool descriptions. Change only what the task needs and keep "
    "the app runnable. Never edit config/api_keys.json, config/certs/, memory/*.json or "
    "config/usage.json: they are the user's keys and data. A new skill goes in skill_spaces/<space>/ "
    "(a specialist's tools) or skill_packs/<pack>/ (a project method), as their README says. In "
    "your report, list what the user must restart or test."
)

_scanner = None


def is_jarvis(folder) -> bool:
    """True when the folder is the assistant's own code, or inside it."""
    try:
        f = Path(folder).resolve()
    except OSError:
        return False
    return f == JARVIS_ROOT or JARVIS_ROOT in f.parents


def describe(folder) -> str:
    """The folder as an agent is told about it: which kind of work it is."""
    kind = "Jarvis itself — improving the assistant" if is_jarvis(folder) else "another project"
    return f"{folder} ({kind})"


def _load_scanner():
    """The legal specialist's scanner, imported from the app's own copy."""
    global _scanner
    if _scanner is None and SCANNER.is_file():
        spec = importlib.util.spec_from_file_location("jarvis_legal_scan", SCANNER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _scanner = module
    return _scanner


def _errors(folder: Path, skip: tuple[str, ...]) -> list[dict] | None:
    """The scanner's errors for this folder, or None when it cannot run."""
    scanner = _load_scanner()
    if scanner is None or not Path(folder).is_dir():
        return None
    try:
        found, _summary = scanner.scan(Path(folder), list(skip))
    except Exception as e:                        # a scanner bug must never block a run
        print(f"[Quality] legal scan of {folder} failed: {e}")
        return None
    return found.errors


def _key(error: dict) -> tuple[str, str, str]:
    # Without the line number: lines move when an agent edits a file.
    return error["rule"], error["file"], error["message"]


def legal_baseline(folder: Path, skip: tuple[str, ...] = ()) -> Counter:
    """What the scanner already finds in the folder, before an agent runs."""
    return Counter(_key(e) for e in _errors(folder, skip) or ())


def new_legal_errors(folder: Path, baseline: Counter, skip: tuple[str, ...] = ()) -> list[str]:
    """The errors the run added, one line each: "file:line [rule] message"."""
    errors = _errors(folder, skip) or []
    now = Counter(_key(e) for e in errors)
    added = {k for k, n in now.items() if n > baseline.get(k, 0)}
    return [f"{e['file']}" + (f":{e['line']}" if e["line"] else "") + f" [{e['rule']}] {e['message']}"
            for e in errors if _key(e) in added]
