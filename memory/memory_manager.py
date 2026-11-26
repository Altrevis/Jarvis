import json
import re
from datetime import datetime
from threading import Lock
from pathlib import Path
import sys


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR         = get_base_dir()
MEMORY_PATH      = BASE_DIR / "memory" / "long_term.json"
_lock            = Lock()
MAX_VALUE_LENGTH = 380

# ── Why there are two very different numbers here ────────────────────────────
#
# There used to be one: MEMORY_MAX_CHARS = 2200, applied to the whole store. It
# was a *storage* limit, and it existed only because the entire memory was
# pasted into the system prompt on every connect — so growing the memory grew
# every single request. When it filled, _trim_to_limit() deleted the oldest
# entries and printed one line to a console nobody reads. A memory described as
# "deeply remembers projects, preferences and personal context" was in practice
# two pages long, and quietly forgot your sister's name after a few weeks.
#
# Storage and prompt budget are now separate concerns:
#
#   MEMORY_MAX_CHARS  — a runaway guard, not a feature limit. Nothing normal
#                       reaches it; a bug writing in a loop does.
#   PROMPT_CORE_CHARS — what actually rides in the system prompt every session.
#                       Smaller than the old whole-memory dump, so sessions
#                       start *faster* than before, not slower.
#
# Everything above the core stays on disk and is fetched on demand by the
# recall_memory tool — see search_memory() and format_memory_for_prompt().
MEMORY_MAX_CHARS  = 200_000
PROMPT_CORE_CHARS = 900
PROMPT_INDEX_CHARS = 420
# Most entries any one category may contribute to the core block, so a person
# with forty stored preferences still gets their sister into the prompt.
PROMPT_MAX_PER_CATEGORY = 6

def _empty_memory() -> dict:
    return {
        "identity":      {},
        "preferences":   {},
        "projects":      {},
        "relationships": {},
        "wishes":        {},
        "notes":         {},
    }


# The fields a new memory starts with, which save_memory's description names
# to the model. Any other dict at the top of long_term.json is a field the
# user made in the MEMORY panel; "sessions" is a list, not a field.
BUILTIN_FIELDS = tuple(_empty_memory())
# The built-in fields the user deleted in the panel, kept as a list under this
# key — without it load_memory would put them straight back, as it does for a
# file written by an older version. RESET ALL brings them all back.
_REMOVED_KEY = "_removed"
_RESERVED_FIELDS = {"sessions", _REMOVED_KEY}
# How the MEMORY panel names them (the user's own fields show their key).
FIELD_LABELS = {"identity": "Identité", "preferences": "Préférences", "projects": "Projets",
                "relationships": "Relations", "wishes": "Envies", "notes": "Notes"}


def field_label(key: str) -> str:
    return FIELD_LABELS.get(key) or key.replace("_", " ").capitalize()


def _removed(memory: dict) -> list[str]:
    found = memory.get(_REMOVED_KEY)
    return [k for k in found if k in BUILTIN_FIELDS] if isinstance(found, list) else []

def load_memory() -> dict:
    if not MEMORY_PATH.exists():
        return _empty_memory()
    with _lock:
        try:
            data = json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                base = _empty_memory()
                removed = _removed(data)
                for key in base:
                    if key not in data and key not in removed:
                        data[key] = {}
                return data
            return _empty_memory()
        except Exception as e:
            print(f"[Memory] ⚠️ Load error: {e}")
            return _empty_memory()

def _all_entries(memory: dict) -> list[tuple]:
    entries = []
    for cat, items in memory.items():
        if not isinstance(items, dict):
            continue
        for key, entry in items.items():
            if isinstance(entry, dict) and "value" in entry:
                entries.append((cat, key, entry))
    return entries


# Set by main.py so a trim can reach the activity log. Deleting something a
# person told you and mentioning it only on stdout is how a memory loses trust.
_trim_notifier = None


def set_trim_notifier(fn) -> None:
    """Register a callable(str) that surfaces trims to the user."""
    global _trim_notifier
    _trim_notifier = fn


def _trim_to_limit(memory: dict) -> dict:
    if len(json.dumps(memory, ensure_ascii=False)) <= MEMORY_MAX_CHARS:
        return memory
    entries = _all_entries(memory)
    entries.sort(key=lambda t: t[2].get("updated", "0000-00-00"))
    dropped = []
    for cat, key, _ in entries:
        if len(json.dumps(memory, ensure_ascii=False)) <= MEMORY_MAX_CHARS:
            break
        del memory[cat][key]
        dropped.append(f"{cat}/{key}")
        print(f"[Memory] 🗑️  Trimmed {cat}/{key}")
    if dropped and _trim_notifier:
        try:
            _trim_notifier(
                f"SYS: Memory full — forgot {len(dropped)} oldest entries "
                f"({', '.join(dropped[:3])}{'…' if len(dropped) > 3 else ''})"
            )
        except Exception:
            pass
    return memory

def save_memory(memory: dict) -> None:
    if not isinstance(memory, dict):
        return
    memory = _trim_to_limit(memory)
    MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        MEMORY_PATH.write_text(
            json.dumps(memory, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


def _truncate_value(val: str) -> str:
    if isinstance(val, str) and len(val) > MAX_VALUE_LENGTH:
        return val[:MAX_VALUE_LENGTH].rstrip() + "…"
    return val


def _recursive_update(target: dict, updates: dict) -> bool:
    changed = False
    for key, value in updates.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, dict) and "value" not in value:
            if key not in target or not isinstance(target[key], dict):
                target[key] = {}
                changed = True
            if _recursive_update(target[key], value):
                changed = True
        else:
            new_val  = _truncate_value(str(value["value"] if isinstance(value, dict) else value))
            entry    = {"value": new_val, "updated": datetime.now().strftime("%Y-%m-%d")}
            existing = target.get(key, {})
            if not isinstance(existing, dict) or existing.get("value") != new_val:
                target[key] = entry
                changed = True
    return changed


def update_memory(memory_update: dict) -> dict:
    if not isinstance(memory_update, dict) or not memory_update:
        return load_memory()
    memory = load_memory()
    if _recursive_update(memory, memory_update):
        save_memory(memory)
        print(f"[Memory] 💾 Saved: {list(memory_update.keys())}")
    return memory

def _entry_value(entry) -> str:
    """Accept both the {'value': ..., 'updated': ...} shape and a bare string,
    because early versions of the store wrote plain strings."""
    if isinstance(entry, dict):
        return str(entry.get("value", "") or "").strip()
    return str(entry or "").strip()


def _pretty(key: str) -> str:
    return key.replace("_", " ").strip()


# Identity is always in the prompt; these categories compete for the remaining
# budget by recency.
_CATEGORY_LABELS = {
    "preferences":   "Preferences",
    "projects":      "Active projects / goals",
    "relationships": "People in their life",
    "wishes":        "Wishes / plans",
    "notes":         "Notes",
}

_IDENTITY_FIELDS = ["name", "age", "birthday", "city", "job",
                    "language", "school", "nationality"]


def custom_fields(memory: dict | None = None) -> list[str]:
    """The fields the user made in the MEMORY panel, alphabetical."""
    memory = load_memory() if memory is None else memory
    return sorted(k for k, v in memory.items()
                  if isinstance(v, dict) and k not in BUILTIN_FIELDS
                  and k not in _RESERVED_FIELDS)


def _prompt_labels(memory: dict) -> dict[str, str]:
    """The categories that compete for the prompt: the built-in ones, then the
    user's own fields under a readable label. Without the second half a fact
    filed in a new field would never reach the prompt or its index."""
    labels = dict(_CATEGORY_LABELS)
    for key in custom_fields(memory):
        labels[key] = _pretty(key).capitalize()
    return labels


def format_memory_for_prompt(memory: dict | None) -> str:
    """Build the memory block that goes into the system prompt.

    This used to dump everything. It now sends three things:

      1. IDENTITY  - always, in full. It is small, and it is wrong for the
         assistant to have to look up your name.
      2. RECENT    - the most recently updated entries from every other
         category, up to PROMPT_CORE_CHARS. Recency is the cheapest useful
         relevance signal available without embeddings.
      3. AN INDEX  - the *keys* of everything else, values omitted.

    Point 3 is what makes recall work at all. A model cannot decide to look
    something up if it does not know the thing exists: with only points 1 and 2,
    "who is Ayse?" would get "I don't know" while ayse_sister sat on disk
    unread. The index costs a few hundred characters and turns recall from a
    gamble into a lookup.

    Net effect on latency: this block is SMALLER than the old full dump, so
    every session connects with fewer tokens. Occasionally the model spends one
    extra round trip on recall_memory - covered by the acknowledgment it
    already speaks before any slow step."""
    if not memory:
        return ""

    labels  = _prompt_labels(memory)
    customs = custom_fields(memory)
    core_lines: list[str] = []

    # 1. Identity - always, in full
    identity = memory.get("identity", {}) or {}
    for field in _IDENTITY_FIELDS:
        val = _entry_value(identity.get(field))
        if not val:
            continue
        if field == "language":
            # Labelled as an observation, not a setting. A bare "Language:
            # English" line written months ago reads like a standing order and
            # was one of the reasons a Turkish question came back in English.
            core_lines.append(
                f"Has spoken to you in: {val} (an observation about the past — "
                f"always answer in the language of their CURRENT message)")
        else:
            core_lines.append(f"{field.title()}: {val}")
    for key, entry in identity.items():
        if key in _IDENTITY_FIELDS:
            continue
        val = _entry_value(entry)
        if val:
            core_lines.append(f"{_pretty(key).title()}: {val}")

    # 2. Everything else, most recently updated first
    rest: list[tuple[str, str, str, str]] = []   # (updated, cat, key, value)
    for cat in labels:
        for key, entry in (memory.get(cat, {}) or {}).items():
            val = _entry_value(entry)
            if not val:
                continue
            updated = (entry.get("updated", "") if isinstance(entry, dict) else "") or "0000-00-00"
            rest.append((updated, cat, key, val))
    rest.sort(key=lambda t: t[0], reverse=True)

    used    = sum(len(l) + 1 for l in core_lines)
    shown: dict[str, list[str]] = {}
    overflow: dict[str, list[str]] = {}

    # Recency decides order, but no single category may take the whole budget.
    # Without the cap, someone with forty stored preferences gets a prompt that
    # is forty preferences and not one person's name — the categories that
    # matter most in conversation are also the ones that change least often, so
    # pure recency systematically buries them.
    per_cat_used: dict[str, int] = {}
    for _updated, cat, key, val in rest:
        line = f"  - {_pretty(key).title()}: {val}"
        if (per_cat_used.get(cat, 0) < PROMPT_MAX_PER_CATEGORY
                and used + len(line) + 1 <= PROMPT_CORE_CHARS):
            shown.setdefault(cat, []).append(line)
            per_cat_used[cat] = per_cat_used.get(cat, 0) + 1
            used += len(line) + 1
        else:
            overflow.setdefault(cat, []).append(_pretty(key))

    # The index is a table of contents, so it is interleaved across categories
    # rather than continuing in recency order. Sorted by recency it would list
    # twenty-four preferences before the first relationship, and the one entry
    # the index exists for — the old fact the model has no other way to know
    # about — would fall off the end.
    indexed: list[str] = []
    if overflow:
        cats  = [c for c in labels if overflow.get(c)]
        cursor = {c: 0 for c in cats}
        while cats:
            for cat in list(cats):
                i = cursor[cat]
                if i >= len(overflow[cat]):
                    cats.remove(cat)
                    continue
                indexed.append(overflow[cat][i])
                cursor[cat] = i + 1

    for cat, label in labels.items():
        if shown.get(cat):
            core_lines.append("")
            core_lines.append(f"{label}:")
            core_lines.extend(shown[cat])

    if not core_lines and not indexed and not customs:
        return ""

    out = [
        "[WHAT YOU KNOW ABOUT THIS PERSON — use naturally, never recite like a list]",
        *core_lines,
    ]

    # 3. The index of what is on disk but not in this prompt
    if indexed:
        budget, names = PROMPT_INDEX_CHARS, []
        for n in indexed:
            if budget - len(n) - 2 < 0:
                break
            names.append(n)
            budget -= len(n) + 2
        if names:
            out.append("")
            out.append(
                "[ALSO REMEMBERED — values not shown here. Call recall_memory "
                "with a keyword to read any of these before saying you do not know]"
            )
            out.append(", ".join(names)
                       + (f" (+{len(indexed) - len(names)} more)"
                          if len(indexed) > len(names) else ""))

    # 4. The fields the user made, by name, even empty: a field the model does
    #    not know about is one it never files anything in.
    if customs:
        out.append("")
        out.append("[MEMORY FIELDS THE USER CREATED — when a fact belongs in one, "
                   "pass its name as save_memory's category: " + ", ".join(customs) + "]")

    return "\n".join(out) + "\n"


# ── Recall ────────────────────────────────────────────────────────────────────

def _score(query_words: list[str], cat: str, key: str, value: str) -> int:
    """Cheap lexical relevance. No embeddings, no network, no model call - this
    runs in well under a millisecond, which is the entire point: recall must
    cost one model round trip, never two."""
    hay_key = _pretty(key).lower()
    hay_val = value.lower()
    score   = 0
    for w in query_words:
        if not w:
            continue
        if w == hay_key:
            score += 10
        elif w in hay_key:
            score += 6
        if w in hay_val:
            score += 3
        if w in cat:
            score += 1
    return score


def search_memory(query: str, limit: int = 8) -> str:
    """Find stored facts matching `query`. Backs the recall_memory tool.

    An empty query is treated as "show me everything you know", capped - the
    model asks that when the user says "what do you remember about me?"."""
    memory = load_memory()
    words  = [w for w in re.split(r"[^\w]+", (query or "").lower()) if len(w) > 1]

    rows: list[tuple[int, str, str, str]] = []
    for cat, items in memory.items():
        if not isinstance(items, dict):
            continue                     # skip 'sessions', which is a list
        for key, entry in items.items():
            val = _entry_value(entry)
            if not val:
                continue
            s = _score(words, cat, key, val) if words else 1
            if s > 0:
                rows.append((s, cat, key, val))

    if not rows:
        return (f"Nothing stored about '{query}'." if query
                else "I have not stored anything about this person yet.")

    rows.sort(key=lambda r: (-r[0], r[2]))
    lines = [f"{cat}/{_pretty(key)}: {val}" for _s, cat, key, val in rows[:max(1, limit)]]
    head  = (f"Stored facts matching '{query}':" if query
             else "Everything currently stored:")
    more  = (f"\n(+{len(rows) - len(lines)} more — search with a narrower keyword)"
             if len(rows) > len(lines) else "")
    return head + "\n" + "\n".join(lines) + more


def all_entries_for_ui() -> list[dict]:
    """Flat list for the memory panel: what JARVIS knows, and when it learned it.
    Sorted newest first so the panel opens on what changed most recently."""
    memory = load_memory()
    rows = []
    for cat, items in memory.items():
        if not isinstance(items, dict):
            continue
        for key, entry in items.items():
            val = _entry_value(entry)
            if not val:
                continue
            rows.append({
                "category": cat,
                "key":      key,
                "value":    val,
                "updated":  (entry.get("updated", "") if isinstance(entry, dict) else ""),
            })
    rows.sort(key=lambda r: (r["updated"] or "0000-00-00"), reverse=True)
    return rows

def file_category(category: str, memory: dict | None = None) -> str:
    """Where a fact saved by the model (or a tool) goes: its category when
    that field exists, else Notes. A field the user deleted is not brought
    back by the next fact the model files in it, and a category the model
    made up does not become a field: fields are the user's to make."""
    memory = load_memory() if memory is None else memory
    if category not in _RESERVED_FIELDS and isinstance(memory.get(category), dict):
        return category
    return "notes"


def remember(key: str, value: str, category: str = "notes") -> str:
    category = file_category(category)
    update_memory({category: {key: {"value": value}}})
    return f"Remembered: {category}/{key} = {value}"


def forget(key: str, category: str = "notes") -> str:
    memory = load_memory()
    cat    = memory.get(category, {})
    if key in cat:
        del cat[key]
        memory[category] = cat
        save_memory(memory)
        return f"Forgotten: {category}/{key}"
    return f"Not found: {category}/{key}"


forget_memory = forget


BACKUP_PATH = MEMORY_PATH.with_name("long_term.backup.json")


def reset_memory() -> int:
    """Forget everything: every fact and every session summary. Returns how
    many facts were stored.

    Only ever called from the MEMORY panel's button, never by the model — a
    voice misheard as "forget everything" must not be able to wipe a person's
    history. The previous file is kept as long_term.backup.json, overwritten by
    the next reset, so one mistaken click can still be undone by hand."""
    with _lock:
        count = 0
        if MEMORY_PATH.exists():
            try:
                old = json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
                if isinstance(old, dict):
                    count = len(_all_entries(old))
            except Exception:
                pass
            BACKUP_PATH.write_bytes(MEMORY_PATH.read_bytes())
        MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        MEMORY_PATH.write_text(json.dumps(_empty_memory(), indent=2, ensure_ascii=False),
                               encoding="utf-8")
    print(f"[Memory] 🧹 Reset — {count} facts forgotten (backup: {BACKUP_PATH.name})")
    return count


# ── Fields, for the MEMORY panel ─────────────────────────────────────────────
#
# What the panel can do besides RESET ALL: pick a field, make a new one, empty
# or remove one, add or correct a fact by hand. Messages are in French: the
# panel shows them as they are.

def field_key(name: str) -> str:
    """'Cours Ynov' -> 'cours_ynov': how a field, or a fact, is stored."""
    return re.sub(r"[^\w]+", "_", str(name or "").strip().lower()).strip("_")[:40]


def _count(items) -> int:
    return sum(1 for e in (items or {}).values() if _entry_value(e))


def list_fields() -> list[dict]:
    """Every field and how many facts it holds: the built-in ones still there,
    in their usual order, then the user's own."""
    memory = load_memory()
    keys = [k for k in BUILTIN_FIELDS if isinstance(memory.get(k), dict)]
    return [{"key": key, "count": _count(memory.get(key)), "builtin": key in BUILTIN_FIELDS}
            for key in (*keys, *custom_fields(memory))]


def create_field(name: str) -> str:
    """A new, empty field. Returns its key; raises ValueError. The name of a
    built-in field that was deleted (« Envies », « wishes ») brings that
    field back rather than making a look-alike."""
    key = field_key(name)
    if not key:
        raise ValueError("Donne un nom au champ.")
    if key in _RESERVED_FIELDS or name.strip() == _REMOVED_KEY:
        raise ValueError(f"« {key} » est réservé : choisis un autre nom.")
    memory = load_memory()
    removed = _removed(memory)
    back = next((k for k in removed if key in (k, field_key(field_label(k)))), "")
    key = back or key
    if isinstance(memory.get(key), dict) or any(
            key == field_key(field_label(k)) for k in BUILTIN_FIELDS if k in memory):
        raise ValueError(f"Le champ « {field_label(key) if back else name.strip()} » existe déjà.")
    memory[key] = {}
    if back:
        memory[_REMOVED_KEY] = [k for k in removed if k != back]
    save_memory(memory)
    print(f"[Memory] ➕ Field {'restored' if back else 'created'}: {key}")
    return key


def delete_field(key: str, keep: bool = False) -> int:
    """Erase every fact of a field, and the field with them unless `keep`
    (« vider »: it stays, empty). Any field can go, built-in ones included:
    those are listed under _REMOVED_KEY so they stay gone. Returns how many
    facts were erased. The file before is kept as long_term.backup.json, as a
    full reset keeps it."""
    memory = load_memory()
    items = memory.get(key)
    if not isinstance(items, dict) or key in _RESERVED_FIELDS:
        return 0
    count = _count(items)
    with _lock:
        if MEMORY_PATH.exists():
            BACKUP_PATH.write_bytes(MEMORY_PATH.read_bytes())
    if keep:
        memory[key] = {}
    else:
        del memory[key]
        if key in BUILTIN_FIELDS:
            memory[_REMOVED_KEY] = sorted({*_removed(memory), key})
    save_memory(memory)
    print(f"[Memory] 🧹 Field {key} {'emptied' if keep else 'deleted'}: {count} facts "
          f"(backup: {BACKUP_PATH.name})")
    return count


def set_fact(category: str, key: str, value: str,
             old: tuple[str, str] | None = None) -> str:
    """Add or correct one fact by hand. `old` is the (category, key) it
    replaces when an existing fact was edited — renamed, or moved to another
    field. Returns the key it is stored under; raises ValueError."""
    key = field_key(key)
    value = " ".join(str(value or "").split())
    if not key:
        raise ValueError("Donne un nom à ce fait (ex. : prénom de ma sœur).")
    if not value:
        raise ValueError("Écris ce que Jarvis doit retenir.")
    memory = load_memory()
    if not category:
        raise ValueError("Il n'y a plus aucun champ : crée-en un avec ＋ NOUVEAU CHAMP.")
    if not isinstance(memory.get(category), dict) or category in _RESERVED_FIELDS:
        raise ValueError(f"Le champ « {field_label(category)} » n'existe pas.")
    if old and tuple(old) != (category, key) and isinstance(memory.get(old[0]), dict):
        memory[old[0]].pop(old[1], None)
    memory[category][key] = {"value": _truncate_value(value),
                             "updated": datetime.now().strftime("%Y-%m-%d")}
    save_memory(memory)
    print(f"[Memory] ✎ {category}/{key} set by hand")
    return key


# ── Session memory ─────────────────────────────────────────────────────────────

_SESSION_MAX = 3   # safety cap — in practice 0-1 entries after pop


def save_session_summary(summary: str, language: str = "") -> None:
    """Append a 1-2 sentence session summary to long_term.json['sessions']."""
    summary = (summary or "").strip()
    if not summary:
        return
    memory   = load_memory()
    sessions = memory.get("sessions", [])
    if not isinstance(sessions, list):
        sessions = []
    entry: dict = {
        "date":    datetime.now().strftime("%Y-%m-%d"),
        "summary": summary[:280],
    }
    if language:
        entry["language"] = language
    sessions.append(entry)
    memory["sessions"] = sessions[-_SESSION_MAX:]
    with _lock:
        MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        MEMORY_PATH.write_text(
            json.dumps(memory, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    print(f"[Memory] 📝 Session saved ({entry['date']}): {summary[:60]}…")


def pop_last_session() -> dict | None:
    """
    Return AND remove the most recent session entry.
    Calling this consumes the entry so it is never repeated in future briefings.
    """
    with _lock:
        if not MEMORY_PATH.exists():
            return None
        try:
            memory   = json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
            sessions = memory.get("sessions", [])
            if not isinstance(sessions, list) or not sessions:
                return None
            entry = sessions.pop()          # remove the last entry
            memory["sessions"] = sessions
            MEMORY_PATH.write_text(
                json.dumps(memory, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            return entry
        except Exception as e:
            print(f"[Memory] ⚠️ pop_last_session error: {e}")
            return None