"""
Find a file or folder from a name that was SPOKEN, not typed.

A voice request reaches the tool as whatever the transcription heard, and the
plain substring test that used to run here failed on nearly all of it:
"projets ynov" against "Projet et cours Ynov", "telechargement" against
"Téléchargements", "dosier foto" against "Dossier Photos". One capital, one
plural "s", one accent or one typo and the folder did not exist.

So instead of trying a list of spellings one after another, every name on disk
is compared against the request in several forms at once:

    normalised   lower case, accents stripped, "_-. " treated as one separator,
                 letters and digits split ("projet2" -> "projet 2")
    singular     a trailing s / x dropped from every word ("cours" -> "cour")
    phonetic     a light French/English sound key ("photo" == "foto",
                 "bateau" == "bato", "dossier" == "dosier")
    fuzzy        difflib similarity, so one or two wrong letters still match
    by word      "ynov projet" finds "Projet et cours Ynov": every word asked
                 for must be present, in any order, among the name's words

The walk is breadth-first, so the shallowest matches come first, and it has a
time budget: a home folder holding a million files returns its best results in
a few seconds instead of hanging the conversation.
"""
from __future__ import annotations

import os
import re
import time
import unicodedata
from collections import deque
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path

# Folders never descended into: huge, machine-generated, and never what a
# person means. They can still MATCH themselves — only their content is skipped.
_SKIP_DESCEND = {
    "node_modules", "__pycache__", "site-packages", "dist-packages",
    "venv", "env", ".venv", "snap", "AppData", "Library", "$RECYCLE.BIN",
    "System Volume Information",
}

# Words a person says around the name that are not part of it.
_NOISE = {"dossier", "dossiers", "fichier", "fichiers", "repertoire", "folder",
          "folders", "file", "files", "directory", "le", "la", "les", "l", "de",
          "du", "des", "d", "mon", "ma", "mes", "the", "my", "a", "an", "un",
          "une"}

MIN_SCORE = 0.75


def normalize(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().replace("œ", "oe").replace("æ", "ae")
    s = re.sub(r"(?<=[a-z])(?=\d)|(?<=\d)(?=[a-z])", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return s.strip()


def _singular(t: str) -> str:
    return t[:-1] if len(t) > 3 and t[-1] in "sx" else t


_PHON_RULES = [
    (r"ph", "f"), (r"qu", "k"), (r"ck", "k"), (r"ch", "sh"), (r"eau", "o"),
    (r"au", "o"), (r"y", "i"), (r"z", "s"),
    (r"w", "v"), (r"c(?=[aou])", "k"), (r"c(?=[eiy])", "s"), (r"c$", "k"),
    (r"g(?=[ei])", "j"), (r"h", ""), (r"(er|ez|et)$", "e"), (r"(.)\1+", r"\1"),
]


@lru_cache(maxsize=50_000)
def _phon(t: str) -> str:
    """Rough sound key: two spellings of the same spoken word collapse to one."""
    for pat, rep in _PHON_RULES:
        t = re.sub(pat, rep, t)
    return t


def _tok_sim(q: str, t: str) -> float:
    """How well one asked-for word matches one word of a name, 0..1."""
    if q == t:
        return 1.0
    if len(q) <= 2:
        return 0.0                       # "ia" must not match "via"
    if t.startswith(q) or (len(t) >= 4 and q.startswith(t)):
        return 0.88
    sm = SequenceMatcher(None, q, t)
    if sm.real_quick_ratio() < 0.5:
        return 0.0
    raw = sm.ratio()
    # Short words get less slack: one letter off "foto" is already "foo".
    need = 0.88 if len(q) <= 4 else (0.8 if len(q) <= 5 else 0.75)
    if raw >= need:
        return min(raw, 0.97)
    # Spelled differently, sounds the same ("foto"/"photo", "ydais"/"ydays").
    # Only between words that already share half their letters, or a short
    # sound key ends up matching anything.
    if raw >= 0.6:
        pq, pt = _phon(q), _phon(t)
        if len(pq) >= 3:
            if pq == pt:
                return 0.92
            r2 = SequenceMatcher(None, pq, pt).ratio()
            if r2 >= 0.9:
                return 0.9
    return 0.0


def _is_noise(w: str) -> bool:
    """A filler word, even misspelt: "dosier" is still "dossier"."""
    if w in _NOISE:
        return True
    return len(w) >= 5 and any(len(n) >= 5 and _tok_sim(w, n) >= 0.85
                               for n in _NOISE)


class Query:
    def __init__(self, text: str):
        norm = normalize(text)
        words = [w for w in norm.split()]
        kept = [w for w in words if not _is_noise(w)]
        words = kept or words
        self.tokens = [_singular(w) for w in words]
        self.compact = "".join(self.tokens)
        self.wants_hidden = text.strip().startswith(".")
        # A name with an extension asked for explicitly ("rapport.pdf")
        # should rank that exact file first.
        self.raw = text.strip().lower()

    def __bool__(self) -> bool:
        return bool(self.compact)


@lru_cache(maxsize=200_000)
def _score_name(q_tokens: tuple, q_compact: str, raw: str, name: str) -> float:
    if name.lower() == raw:
        return 1.0
    forms = {name}
    stem, dot, _ext = name.rpartition(".")
    if dot and stem:
        forms.add(stem)
    best = 0.0
    for form in forms:
        ct = [_singular(t) for t in normalize(form).split()]
        if not ct:
            continue
        comp = "".join(ct)
        if comp == q_compact:
            return 0.99
        s = 0.0
        # The request is part of the name ("ynov" in "projetynov2025").
        if len(q_compact) >= 3 and q_compact in comp:
            s = 0.82 + 0.15 * len(q_compact) / len(comp)
        # Same name with a typo or two, spaces ignored.
        if len(q_compact) >= 5:
            sm = SequenceMatcher(None, q_compact, comp)
            if sm.real_quick_ratio() >= 0.8:
                r = sm.ratio()
                if r >= 0.8:
                    s = max(s, r)
        # Every asked-for word appears among the name's words, in any order.
        sims = []
        for qt in q_tokens:
            b = 0.0
            for t in ct:
                b = max(b, _tok_sim(qt, t))
                if b == 1.0:
                    break
            if b == 0.0:
                sims = []
                break
            sims.append(b)
        if sims:
            extra = max(0, len(ct) - len(q_tokens))
            s = max(s, 0.70 + 0.28 * (sum(sims) / len(sims)) - 0.015 * extra)
        elif len(q_tokens) > 1:
            # The other way round: the whole NAME is inside what was said
            # ("le projet ydays de l'école" -> "Ydays"). Ranked below a name
            # that matches every word.
            rev = []
            for t in ct:
                b = max(_tok_sim(t, qt) for qt in q_tokens) if len(t) > 2 else \
                    (1.0 if t in q_tokens else 0.0)
                if b == 0.0:
                    rev = []
                    break
                rev.append(b)
            if rev:
                s = max(s, 0.68 + 0.2 * (sum(rev) / len(rev)))
        best = max(best, s)
    return min(best, 0.99)


def score(q: Query, name: str) -> float:
    return _score_name(tuple(q.tokens), q.compact, q.raw, name)


def search(query: str, roots: list[Path], kind: str = "any",
           extension: str = "", max_results: int = 15,
           time_budget: float = 8.0, max_depth: int = 12) -> tuple[list[tuple], dict]:
    """Breadth-first search under `roots`.

    kind: "folder", "file" or "any". Returns ([(score, path, is_dir), ...] best
    first, stats). Never raises."""
    q = Query(query)
    ext = extension.lower().strip()
    if ext and not ext.startswith("."):
        ext = "." + ext
    if not q and not ext:
        return [], {"visited": 0, "truncated": False, "seconds": 0.0}

    t0 = time.monotonic()
    found: list[tuple[float, int, str, bool]] = []
    queue = deque((Path(r), 0) for r in roots)
    seen: set[str] = set()
    visited, truncated = 0, False

    while queue:
        if time.monotonic() - t0 > time_budget:
            truncated = True
            break
        d, depth = queue.popleft()
        key = str(d)
        if key in seen:
            continue
        seen.add(key)
        try:
            it = os.scandir(d)
        except OSError:
            continue
        with it:
            for e in it:
                visited += 1
                name = e.name
                try:
                    is_dir = e.is_dir(follow_symlinks=False)
                except OSError:
                    continue
                if name.startswith(".") and not q.wants_hidden:
                    continue
                if kind == "any" or (kind == "folder") == is_dir:
                    if ext and (is_dir or not name.lower().endswith(ext)):
                        pass
                    elif not q:
                        found.append((0.9, depth, e.path, is_dir))   # extension only
                    else:
                        s = score(q, name)
                        if s >= MIN_SCORE:
                            found.append((s, depth, e.path, is_dir))
                if is_dir and depth < max_depth and name not in _SKIP_DESCEND:
                    queue.append((Path(e.path), depth + 1))

    # Best score first, nudged towards shallow paths — the folder a person
    # means is rarely buried eight levels down, so ~/Images beats
    # .../sdk/os/image even though the latter is the exact spelling.
    found.sort(key=lambda r: (-(r[0] - 0.004 * r[1]), r[1], len(r[2])))
    out = [(s, Path(p), is_dir) for s, _d, p, is_dir in found[:max_results]]
    return out, {"visited": visited, "truncated": truncated,
                 "seconds": round(time.monotonic() - t0, 2)}


def resolve_path(raw: Path) -> Path | None:
    """`raw` as given if it exists; otherwise the same path with each missing
    component replaced by its closest-sounding sibling ("~/bureau/projet ynov"
    -> "~/Bureau/Projet et cours Ynov"). None when a component has no close
    enough match. Read-only callers only: never use it to pick what to delete."""
    if raw.exists():
        return raw
    parts = raw.parts
    if not parts:
        return None
    cur = Path(parts[0])
    for part in parts[1:]:
        nxt = cur / part
        if nxt.exists():
            cur = nxt
            continue
        q = Query(part)
        best, best_s = None, 0.0
        try:
            with os.scandir(cur) as it:
                for e in it:
                    s = score(q, e.name) if q else 0.0
                    if s > best_s:
                        best, best_s = e.path, s
        except OSError:
            return None
        if best is None or best_s < 0.8:
            return None
        cur = Path(best)
    return cur
