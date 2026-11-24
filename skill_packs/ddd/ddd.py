#!/usr/bin/env python3
"""Domain model checker and report. Standard library only, no network.

Reads the JSON files the ddd-* skills write in <project>/ddd/, checks them
against the rules of Domain-Driven Design and against the project file they
come from (cahier des charges, product backlog), and writes the readable
model the code is built on:

    python3 ddd.py <project>              # check, write livrables/ddd.md
    python3 ddd.py <project> --check      # validate only: exit 1 on any error
    python3 ddd.py <project> --json       # same as the first, summary as JSON
    python3 ddd.py <project> --code DIR   # also: does the code in DIR speak
                                          # the model's language?

Why a checker: the rules that make a domain model worth having are easy to
state and easy to break without noticing — a story owned by two contexts, a
reference to an entity inside another aggregate, a repository for something
that is not a root, a class named "Booking" where the whole team says
"Réservation". A language model writing forty elements breaks one sooner or
later; this finds it the same way every time.

Files (all in ddd/; each skill's SKILL.md holds the shape it writes):

    domaine.json    the domain vision statement, the subdomains (core,
                    supporting, generic) and how each is built, the
                    ubiquitous language (glossary), questions for the experts
    contextes.json  the bounded contexts, what each owns of the backlog and the
                    cahier des charges, the external systems, the context map
    modele.json     per context: aggregates (root, entities, invariants),
                    value objects, services, specifications, domain events,
                    modules

Also read when present: scrum/cahier-des-charges.json and
scrum/product-backlog.json (or the same names in docs/, in a code project).

Source: Eric Evans, Domain-Driven Design — Tackling Complexity in the Heart of
Software (Addison-Wesley, 2003). Domain events and the partnership
relationship are from his later Domain-Driven Design Reference (2015).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

SUBDOMAIN_TYPES = {"core": "cœur", "supporting": "support", "generic": "générique"}
APPROACHES = {
    "model-driven": "conception pilotée par le modèle",
    "transaction-script": "script de transaction",
    "smart-ui": "Smart UI (CRUD direct)",
    "buy": "solution du marché",
    "open-source": "brique open source",
}
# Context map patterns (Evans, ch. 14). "partnership" is from the 2015 Reference.
PATTERNS = {
    "shared-kernel": "noyau partagé",
    "customer-supplier": "client / fournisseur",
    "conformist": "conformiste",
    "anticorruption-layer": "couche anticorruption",
    "open-host-service": "service hôte ouvert",
    "published-language": "langage publié",
    "separate-ways": "chemins séparés",
    "partnership": "partenariat",
}
SERVICE_LAYERS = {"domain": "domaine", "application": "application", "infrastructure": "infrastructure"}
# The three uses of a specification (Evans, ch. 9).
SPEC_KINDS = {"validation": "validation", "selection": "sélection", "building": "construction"}

SD_RE = re.compile(r"^SD\d+$")
BC_RE = re.compile(r"^BC\d+$")
CODE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
PACKAGE_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
RULE_RE = re.compile(r"\bRG-\d+\b")

# What the code check reads, and what it never walks into.
SRC_EXT = {".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".java", ".kt", ".cs", ".php",
           ".go", ".rb", ".rs", ".swift", ".dart", ".vue", ".svelte", ".sql", ".prisma"}
SKIP_DIRS = {"node_modules", "dist", "build", "out", "coverage", "venv", "env", "__pycache__",
             "vendor", "target", "bin", "obj", "Pods", "DerivedData"}
MAX_FILES = 4000
MAX_BYTES = 300_000
WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
CAMEL_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")


# ── Helpers ─────────────────────────────────────────────────────────────────

def key(s) -> str:
    """Lower case, no accents, dashes: "Open Host Service" -> "open-host-service"."""
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def flat(s) -> str:
    """For matching a name in any spelling: "Créneau horaire", "CreneauHoraire"
    and "creneau_horaire" are all "creneauhoraire"."""
    return key(s).replace("-", "")


def text(v) -> str:
    return " ".join(str(v).split()) if isinstance(v, (str, int, float)) and not isinstance(v, bool) else ""


def strs(v) -> list[str]:
    """The non-empty strings of a list (anything else is an empty list)."""
    return [text(x) for x in v if text(x)] if isinstance(v, list) else []


def short(items, n: int = 12) -> str:
    items = list(items)
    return ", ".join(items[:n]) + (" …" if len(items) > n else "")


class Check:
    def __init__(self):
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def err(self, file: str, msg: str):
        self.errors.append(f"{file}: {msg}")

    def warn(self, file: str, msg: str):
        self.warnings.append(f"{file}: {msg}")


def load(path: Path, c: Check):
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        c.err(path.name, f"not valid JSON ({e})")
        return None


def project_file(root: Path, name: str, c: Check):
    """A Scrum deliverable: scrum/ in a Scrum workspace, docs/ in a code project."""
    for folder in ("scrum", "docs"):
        if (root / folder / name).is_file():
            return load(root / folder / name, c)
    return None


def backlog_items(backlog) -> dict[str, dict]:
    if not isinstance(backlog, dict):
        return {}
    return {text(s.get("id")): s for s in backlog.get("stories") or []
            if isinstance(s, dict) and text(s.get("id"))}


def cdc_index(cdc) -> dict:
    """What the checks need from the cahier des charges."""
    out = {"requirements": {}, "modules": {}, "rules": set(), "interfaces": [], "data": []}
    if not isinstance(cdc, dict):
        return out
    for r in cdc.get("requirements") or []:
        if isinstance(r, dict) and text(r.get("id")):
            out["requirements"][text(r["id"])] = r
            for rule in r.get("rules") or []:
                out["rules"].update(RULE_RE.findall(str(rule)))
    for rule in cdc.get("rules") or []:
        out["rules"].update(RULE_RE.findall(json.dumps(rule, ensure_ascii=False)))
    for m in cdc.get("modules") or []:
        if isinstance(m, dict) and text(m.get("id")):
            out["modules"][text(m["id"])] = m
    tech = cdc.get("technical") if isinstance(cdc.get("technical"), dict) else {}
    out["interfaces"] = [text(i.get("system")) for i in tech.get("interfaces") or []
                         if isinstance(i, dict) and text(i.get("system"))]
    out["data"] = [text(i.get("entity")) for i in tech.get("data") or []
                   if isinstance(i, dict) and text(i.get("entity"))]
    return out


def in_language(name: str, D: dict | None) -> bool:
    return bool(D) and (flat(name) in D["terms"] or flat(name) in D["codes"])


def code_name(name: str, D: dict | None) -> str:
    """The identifier the glossary gives a model element, else its own name."""
    if D:
        entry = D["terms"].get(flat(name))
        if entry and text(entry.get("code")):
            return text(entry["code"])
    return name


# ── domaine.json ────────────────────────────────────────────────────────────

def read_domaine(d, cdc, c: Check) -> dict | None:
    F = "domaine.json"
    if not isinstance(d, dict):
        c.err(F, "must be a JSON object")
        return None
    vision = text(d.get("vision"))
    if not vision:
        c.err(F, "no vision — the domain vision statement: in one paragraph, what the core "
                 "domain is and why it is worth building (Evans, ch. 15)")
    elif len(vision) > 1500:
        c.warn(F, "vision longer than 1500 characters — a vision statement fits in a page and "
                  "says what is special, not how it works")

    subdomains: dict[str, dict] = {}
    for s in d.get("subdomains") or []:
        if not isinstance(s, dict):
            c.err(F, "every subdomain must be an object")
            continue
        i = text(s.get("id"))
        if not SD_RE.match(i):
            c.err(F, f"subdomain id {i!r}: use SD1, SD2 …")
            continue
        if i in subdomains:
            c.err(F, f"{i}: duplicate id")
            continue
        if not text(s.get("name")):
            c.err(F, f"{i}: no name")
        t = key(s.get("type"))
        if t not in SUBDOMAIN_TYPES:
            c.err(F, f"{i}: type must be core, supporting or generic")
            t = "supporting"
        a = key(s.get("approach"))
        if a not in APPROACHES:
            c.err(F, f"{i}: approach must be one of {', '.join(APPROACHES)}")
            a = "model-driven"
        if not text(s.get("why")):
            c.warn(F, f"{i}: no why — say why it is {t} and why it is built this way")
        if t == "generic" and a == "model-driven":
            c.warn(F, f"{i}: a generic subdomain modelled in house — everyone needs it, nobody "
                      f"wins with it: buy, take open source, or keep it minimal (Generic Subdomains)")
        if t == "core" and a in ("smart-ui", "buy", "open-source"):
            c.warn(F, f"{i}: the core built as {a} — the core is where the product differs, "
                      f"so it is where the best modelling goes")
        subdomains[i] = {**s, "id": i, "type": t, "approach": a}
    cores = [i for i, s in subdomains.items() if s["type"] == "core"]
    if not subdomains:
        c.err(F, "no subdomains")
    elif not cores:
        c.err(F, "no core subdomain — which part makes this product worth building rather "
                 "than buying? That is the core domain")
    elif len(cores) > 2:
        c.warn(F, f"{len(cores)} core subdomains — the core is the small part that makes the "
                  f"product worth it (Evans, ch. 15); the rest is supporting or generic")
    if cores and not strs(d.get("highlighted_core")):
        c.warn(F, "no highlighted_core — 3 to 7 lines naming the elements of the core model "
                  "everyone on the team must know")

    terms: dict[str, dict] = {}
    codes: dict[str, str] = {}
    avoid: dict[str, str] = {}
    for g in d.get("glossary") or []:
        if not isinstance(g, dict):
            c.err(F, "every glossary entry must be an object")
            continue
        term = text(g.get("term"))
        if not term:
            c.err(F, "a glossary entry has no term")
            continue
        k = flat(term)
        if k in terms:
            c.err(F, f"{term}: twice in the glossary — one word, one meaning (a word that "
                     f"means two things in two contexts goes in the homonyms of contextes.json)")
            continue
        if not text(g.get("definition")):
            c.err(F, f"{term}: no definition")
        code = text(g.get("code"))
        if code:
            if not CODE_RE.match(code):
                c.warn(F, f"{term}: code {code!r} is not an identifier — the name of the class "
                          f"or type in the code, e.g. CreneauHoraire")
            elif flat(code) in codes:
                c.warn(F, f"{term}: code {code} is already the code of {codes[flat(code)]}")
            else:
                codes[flat(code)] = term
        terms[k] = {**g, "term": term}
        for w in strs(g.get("avoid")):
            avoid[flat(w)] = term
    for w, term in avoid.items():
        if w == flat(term):
            c.err(F, f"{term}: lists itself in avoid")
        elif w in terms:
            c.err(F, f"{terms[w]['term']} is a term and also a word to avoid for {term} — pick one")
    if len(terms) < 5:
        c.warn(F, f"only {len(terms)} glossary term(s) — the ubiquitous language of even a small "
                  f"domain has 10 to 30: the nouns of the stories, the rules, the states")
    if isinstance(cdc, dict):
        missing = [text(g.get("term")) for g in cdc.get("glossary") or []
                   if isinstance(g, dict) and text(g.get("term"))
                   and flat(g["term"]) not in terms and flat(g["term"]) not in avoid
                   and flat(g["term"]) not in codes]
        if missing:
            c.warn(F, f"{len(missing)} term(s) of the cahier des charges glossary missing from "
                      f"the language: {short(missing)} — add them, or put them in a term's "
                      f"avoid when the team chose another word")
    return {"project": text(d.get("project")), "vision": vision, "subdomains": subdomains,
            "cores": cores, "highlighted": strs(d.get("highlighted_core")), "terms": terms,
            "codes": codes, "avoid": avoid, "questions": strs(d.get("questions"))}


# ── contextes.json ──────────────────────────────────────────────────────────

def read_contextes(x, D: dict | None, idx: dict, items: dict, c: Check) -> dict | None:
    F = "contextes.json"
    if not isinstance(x, dict):
        c.err(F, "must be a JSON object")
        return None
    if D is None:
        c.err(F, "needs domaine.json — the contexts are drawn on its subdomains and language")

    contexts: dict[str, dict] = {}
    for b in x.get("contexts") or []:
        if not isinstance(b, dict):
            c.err(F, "every context must be an object")
            continue
        i = text(b.get("id"))
        if not BC_RE.match(i):
            c.err(F, f"context id {i!r}: use BC1, BC2 …")
            continue
        if i in contexts:
            c.err(F, f"{i}: duplicate id")
            continue
        if not text(b.get("name")):
            c.err(F, f"{i}: no name")
        kind = key(b.get("kind") or "internal")
        if kind not in ("internal", "external"):
            c.err(F, f"{i}: kind must be internal or external")
            kind = "internal"
        sds = strs(b.get("subdomains"))
        for s in sds:
            if D and s not in D["subdomains"]:
                c.err(F, f"{i}: subdomain {s} is not in domaine.json")
        if kind == "internal":
            if not sds:
                c.warn(F, f"{i}: no subdomains — which part of the domain does it model?")
            if not text(b.get("responsibility")):
                c.warn(F, f"{i}: no responsibility — one sentence on what this context decides "
                          f"and what it leaves to the others")
            if D:
                unknown = [t for t in strs(b.get("terms")) if not in_language(t, D)]
                if unknown:
                    c.warn(F, f"{i}: terms not in the glossary of domaine.json: {short(unknown)}")
            code = text(b.get("code"))
            if code and not PACKAGE_RE.match(code):
                c.warn(F, f"{i}: code {code!r} — the package or folder name in the code, lower "
                          f"case, e.g. reservation")
        elif strs(b.get("stories")) or strs(b.get("requirements")):
            c.err(F, f"{i}: an external system owns no story — put them on the internal "
                     f"context that talks to it")
        contexts[i] = {**b, "id": i, "kind": kind}
    internal = [i for i, b in contexts.items() if b["kind"] == "internal"]
    external = [i for i, b in contexts.items() if b["kind"] == "external"]
    if not internal:
        c.err(F, "no internal context — at least the one the product's core lives in")

    approach: dict[str, tuple[str, str]] = {}
    for i in internal:
        sds = [D["subdomains"][s] for s in strs(contexts[i].get("subdomains"))
               if D and s in D["subdomains"]]
        core = [s for s in sds if s["type"] == "core"]
        pick = core[0] if core else (sds[0] if sds else None)
        approach[i] = (pick["approach"], pick["type"]) if pick else ("model-driven", "supporting")
        types = {s["type"] for s in sds}
        if "core" in types and "generic" in types:
            c.warn(F, f"{i}: holds a core and a generic subdomain — keep the generic one in a "
                      f"context of its own, so the core stays small (Segregated Core)")
    if D:
        # A generic subdomain bought or taken open source is carried by its
        # external system: Stripe carries "Paiement".
        covered = {s for i in contexts for s in strs(contexts[i].get("subdomains"))}
        inside = {s for i in internal for s in strs(contexts[i].get("subdomains"))}
        for s in D["cores"]:
            if s not in inside:
                c.err(F, f"the core subdomain {s} is in no internal context")
        others = [s for s in D["subdomains"] if s not in covered and s not in D["cores"]]
        if others:
            c.warn(F, f"subdomain(s) in no context: {', '.join(others)}")

    story_ctx: dict[str, str] = {}
    for i in internal:
        for s in strs(contexts[i].get("stories")):
            if items and s not in items:
                c.err(F, f"{i}: {s} is not in the product backlog")
                continue
            if items and key(items[s].get("priority")) == "wont":
                c.warn(F, f"{i}: {s} is \"wont\" in the backlog — out of scope, leave it out")
            if s in story_ctx and story_ctx[s] != i:
                c.err(F, f"{s} is in {story_ctx[s]} and {i} — a story belongs to the context "
                         f"whose language it speaks; split it in the backlog if it spans two")
                continue
            story_ctx[s] = i
    if items:
        missing = [s for s, v in items.items() if key(v.get("priority")) != "wont" and s not in story_ctx]
        if missing:
            c.warn(F, f"{len(missing)} backlog item(s) in no context: {short(missing)}")

    req_ctx: dict[str, str] = {}
    for i in internal:
        for r in strs(contexts[i].get("requirements")):
            if idx["requirements"] and r not in idx["requirements"]:
                c.err(F, f"{i}: {r} is not a requirement of the cahier des charges")
                continue
            if r in req_ctx and req_ctx[r] != i:
                c.warn(F, f"{r} is in {req_ctx[r]} and {i} — fine if both really carry it; "
                          f"say which one decides")
            req_ctx.setdefault(r, i)
        for m in strs(contexts[i].get("modules")):
            if idx["modules"] and m not in idx["modules"]:
                c.warn(F, f"{i}: module {m} is not in the cahier des charges")
    if idx["requirements"]:
        missing = [r for r in idx["requirements"] if r not in req_ctx]
        if missing:
            c.warn(F, f"{len(missing)} requirement(s) of the cahier des charges in no context: "
                      f"{short(missing)}")

    relations, pairs, linked = [], set(), set()
    for r in x.get("relations") or []:
        if not isinstance(r, dict):
            c.err(F, "every relation must be an object")
            continue
        u, dn = text(r.get("upstream")), text(r.get("downstream"))
        label = f"relation {u or '?'} → {dn or '?'}"
        if u not in contexts or dn not in contexts:
            c.err(F, f"{label}: upstream and downstream must both be contexts of this file")
            continue
        if u == dn:
            c.err(F, f"{label}: a context is not related to itself")
            continue
        pats = [key(p) for p in strs(r.get("patterns"))]
        unknown = [p for p in pats if p not in PATTERNS]
        if unknown:
            c.err(F, f"{label}: unknown pattern(s) {', '.join(unknown)} — use {', '.join(PATTERNS)}")
            pats = [p for p in pats if p in PATTERNS]
        if not pats:
            c.err(F, f"{label}: no pattern — e.g. customer-supplier, conformist, anticorruption-layer")
            continue
        if "separate-ways" in pats and len(pats) > 1:
            c.err(F, f"{label}: separate-ways means no integration at all — it goes alone")
        if "conformist" in pats and "anticorruption-layer" in pats:
            c.err(F, f"{label}: conformist or anticorruption-layer, not both")
        if frozenset((u, dn)) in pairs:
            c.warn(F, f"{label}: these two contexts are already related — one relation per pair, "
                      f"with all its patterns")
        pairs.add(frozenset((u, dn)))
        up, down = contexts[u], contexts[dn]
        if down["kind"] == "external" and up["kind"] == "internal":
            c.warn(F, f"{label}: an external system downstream of the app — the app is usually "
                      f"downstream of what it does not control; check the direction")
        if up["kind"] == "external" and not {"conformist", "anticorruption-layer", "separate-ways"} & set(pats):
            c.warn(F, f"{label}: downstream of an external system — say conformist (take its "
                      f"model as it is) or anticorruption-layer (translate it at the border)")
        if "anticorruption-layer" in pats and not text(r.get("translation")):
            c.warn(F, f"{label}: anticorruption layer without translation — say which of their "
                      f"concepts become which of ours")
        if "shared-kernel" in pats and not strs(r.get("shared")):
            c.warn(F, f"{label}: shared kernel without shared — list the few model elements "
                      f"both sides own, and keep it small")
        if "conformist" in pats and approach.get(dn, ("", ""))[1] == "core":
            c.warn(F, f"{label}: the core conforms to another model — an anticorruption layer "
                      f"would keep the core's language its own")
        if not text(r.get("why")):
            c.warn(F, f"{label}: no why")
        linked.update((u, dn))
        relations.append({**r, "upstream": u, "downstream": dn, "patterns": pats})
    if len(contexts) > 1:
        alone = [i for i in contexts if i not in linked]
        if alone:
            c.warn(F, f"context(s) in no relation: {', '.join(alone)} — say separate-ways if one "
                      f"truly needs nothing from the others")

    if idx["interfaces"]:
        names = set()
        for i in external:
            names.update({flat(contexts[i].get("name")), flat(contexts[i].get("system"))})
        missing = [s for s in idx["interfaces"] if flat(s) not in names]
        if missing:
            c.warn(F, f"interface(s) of the cahier des charges with no external context: "
                      f"{short(missing)} — each system the app talks to is on the map, with its relation")

    homonyms = []
    for h in x.get("homonyms") or []:
        if not isinstance(h, dict) or not text(h.get("term")):
            c.err(F, "every homonym needs a term")
            continue
        meanings = h.get("meanings") if isinstance(h.get("meanings"), dict) else {}
        for b in meanings:
            if b not in contexts:
                c.err(F, f"homonym {text(h['term'])}: {b} is not a context")
        if len(meanings) < 2:
            c.warn(F, f"homonym {text(h['term'])}: give its meaning in at least two contexts")
        homonyms.append({"term": text(h["term"]), "meanings": {b: text(v) for b, v in meanings.items()}})

    return {"contexts": contexts, "internal": internal, "external": external, "approach": approach,
            "relations": relations, "pairs": pairs, "story_ctx": story_ctx, "req_ctx": req_ctx,
            "homonyms": homonyms}


# ── modele.json ─────────────────────────────────────────────────────────────

def read_context_model(b: str, e: dict, D: dict | None, X: dict, idx: dict, items: dict,
                       c: Check) -> dict:
    F = "modele.json"
    appr = X["approach"][b][0]
    mine = {s for s, ctx in X["story_ctx"].items() if ctx == b}

    vos: dict[str, dict] = {}
    for v in e.get("value_objects") or []:
        n = text(v.get("name")) if isinstance(v, dict) else ""
        if not n:
            c.err(F, f"{b}: a value object has no name")
            continue
        if n in vos:
            c.err(F, f"{b}.{n}: two value objects with this name")
            continue
        if "identity" in v or "id" in {key(a) for a in strs(v.get("attributes"))}:
            c.warn(F, f"{b}.{n}: a value object has no identity — if it needs one, it is an entity")
        vos[n] = v

    aggs: dict[str, dict] = {}
    entities: dict[str, str] = {}               # entity -> its aggregate
    for a in e.get("aggregates") or []:
        n = text(a.get("name")) if isinstance(a, dict) else ""
        if not n:
            c.err(F, f"{b}: an aggregate has no name")
            continue
        if n in aggs:
            c.err(F, f"{b}.{n}: two aggregates with this name")
            continue
        ents: dict[str, dict] = {}
        for en in a.get("entities") or []:
            en_name = text(en.get("name")) if isinstance(en, dict) else ""
            if not en_name:
                c.err(F, f"{b}.{n}: every entity needs a name")
                continue
            if en_name in entities:
                c.err(F, f"{b}.{en_name}: in aggregates {entities[en_name]} and {n} — an entity "
                         f"belongs to one aggregate")
                continue
            if not text(en.get("identity")):
                c.warn(F, f"{b}.{en_name}: no identity — say what makes two of them the same one "
                          f"(a number, a natural key)")
            entities[en_name] = n
            ents[en_name] = en
        root = text(a.get("root"))
        if not root:
            c.err(F, f"{b}.{n}: no root — the one entity the outside world holds on to")
        elif root not in ents:
            c.err(F, f"{b}.{n}: its root {root} must be one of its entities")
        for en_name, en in ents.items():
            if en.get("repository") and en_name != root:
                c.err(F, f"{b}.{en_name}: a repository is for an aggregate root only — reach "
                         f"{en_name} through {root or 'the root'}")
        for v in strs(a.get("value_objects")):
            if v not in vos:
                c.err(F, f"{b}.{n}: value object {v} is not in the value_objects of {b}")
        invs = [i for i in a.get("invariants") or [] if isinstance(i, dict) and text(i.get("rule"))]
        if not invs:
            c.warn(F, f"{b}.{n}: no invariant — an aggregate exists to keep rules true inside its "
                      f"boundary; without one it may just be an entity of another aggregate")
        for inv in invs:
            for rg in RULE_RE.findall(text(inv.get("source"))):
                if idx["rules"] and rg not in idx["rules"]:
                    c.warn(F, f"{b}.{n}: {rg} is not a rule of the cahier des charges")
        for s in strs(a.get("stories")):
            if s not in mine:
                c.warn(F, f"{b}.{n}: {s} is not a story of {b} in contextes.json")
        aggs[n] = {**a, "name": n, "root": root, "entities": ents, "invariants": invs,
                   "refs": strs(a.get("references")), "refs_out": []}
    roots = {a["root"]: n for n, a in aggs.items() if a["root"]}

    for n, a in aggs.items():
        for r in a["refs"]:
            if "." in r:
                ctx, name = r.split(".", 1)
                if ctx not in X["contexts"]:
                    c.err(F, f"{b}.{n}: refers to {r}, but {ctx} is not a context")
                elif ctx == b:
                    c.err(F, f"{b}.{n}: write {name}, not {r}, inside its own context")
                else:
                    a["refs_out"].append((ctx, name))
            elif r in roots or r in aggs:
                if (roots.get(r) or r) == n:
                    c.err(F, f"{b}.{n}: refers to itself")
            elif r in entities:
                c.err(F, f"{b}.{n}: refers to {r}, which is inside {entities[r]} — hold the "
                         f"identity of the root {aggs[entities[r]]['root'] or entities[r]} and go through it")
            else:
                c.err(F, f"{b}.{n}: refers to {r}, which is not an aggregate of {b} "
                         f"(write BCx.Name for another context)")

    services: dict[str, dict] = {}
    for s in e.get("services") or []:
        n = text(s.get("name")) if isinstance(s, dict) else ""
        if not n:
            c.err(F, f"{b}: a service has no name")
            continue
        layer = key(s.get("layer") or "domain")
        if layer not in SERVICE_LAYERS:
            c.err(F, f"{b}.{n}: layer must be domain, application or infrastructure")
            layer = "domain"
        if not text(s.get("does")):
            c.warn(F, f"{b}.{n}: no does — the operation, in the language of the domain")
        services[n] = {**s, "layer": layer}

    specs: dict[str, dict] = {}
    for s in e.get("specifications") or []:
        n = text(s.get("name")) if isinstance(s, dict) else ""
        if not n:
            c.err(F, f"{b}: a specification has no name")
            continue
        kind = key(s.get("kind") or "validation")
        if kind not in SPEC_KINDS:
            c.err(F, f"{b}.{n}: kind must be validation, selection or building")
            kind = "validation"
        if not text(s.get("rule")):
            c.warn(F, f"{b}.{n}: no rule — the predicate, in a sentence")
        for src in strs(s.get("from")):
            if src not in items and src not in idx["requirements"] and not RULE_RE.fullmatch(src):
                if items or idx["requirements"]:
                    c.warn(F, f"{b}.{n}: {src} is neither a story nor a requirement nor a rule")
        specs[n] = {**s, "kind": kind}

    events: dict[str, dict] = {}
    for ev in e.get("events") or []:
        n = text(ev.get("name")) if isinstance(ev, dict) else ""
        if not n:
            c.err(F, f"{b}: an event has no name")
            continue
        src = text(ev.get("raised_by"))
        if src not in aggs:
            c.err(F, f"{b}.{n}: raised_by must be an aggregate of {b}")
        for ctx in strs(ev.get("consumed_by")):
            if ctx not in X["contexts"]:
                c.err(F, f"{b}.{n}: consumed by {ctx}, which is not a context")
            elif ctx != b and frozenset((b, ctx)) not in X["pairs"]:
                c.warn(F, f"{b}.{n}: consumed by {ctx}, but contextes.json has no relation "
                          f"between {b} and {ctx}")
        events[n] = ev

    modules = []
    known = set(aggs) | set(vos) | set(services) | set(specs) | set(events)
    placed = set()
    for m in e.get("modules") or []:
        n = text(m.get("name")) if isinstance(m, dict) else ""
        if not n:
            c.err(F, f"{b}: a module has no name")
            continue
        inside = strs(m.get("contains"))
        unknown = [x for x in inside if x not in known]
        if unknown:
            c.warn(F, f"{b}: module {n} holds {short(unknown)}, not in the model of {b}")
        placed.update(inside)
        modules.append({"name": n, "contains": inside})
    if modules:
        loose = [a for a in aggs if a not in placed]
        if loose:
            c.warn(F, f"{b}: aggregate(s) in no module: {short(loose)}")

    if appr == "model-driven" and not aggs:
        c.err(F, f"{b}: a model-driven context with no aggregate")
    if appr != "model-driven" and not aggs and not text(e.get("note")):
        c.warn(F, f"{b}: no aggregate — fine for a {APPROACHES[appr]} context; say so in note")
    if D:
        names = list(aggs) + list(entities) + list(vos)
        off = sorted({x for x in names if not in_language(x, D)})
        if off:
            c.warn(F, f"{b}: names not in the ubiquitous language: {short(off)} — add each to "
                      f"the glossary of domaine.json (term, definition, code), or rename it")
        for x in names + list(services) + list(events):
            if flat(x) in D["avoid"]:
                c.err(F, f"{b}.{x}: a word to avoid — the language says {D['avoid'][flat(x)]}")
    return {"aggregates": aggs, "roots": roots, "entities": entities, "value_objects": vos,
            "services": services, "specifications": specs, "events": events, "modules": modules,
            "note": text(e.get("note"))}


def read_modele(m, D: dict | None, X: dict | None, idx: dict, items: dict, c: Check) -> dict | None:
    F = "modele.json"
    if not isinstance(m, dict):
        c.err(F, "must be a JSON object")
        return None
    if X is None:
        c.err(F, "needs contextes.json — the model is drawn per bounded context")
        return None
    models: dict[str, dict] = {}
    for e in m.get("contexts") or []:
        if not isinstance(e, dict):
            c.err(F, "every entry of contexts must be an object")
            continue
        b = text(e.get("context"))
        if b not in X["contexts"]:
            c.err(F, f"context {b!r} is not in contextes.json")
            continue
        if X["contexts"][b]["kind"] != "internal":
            c.err(F, f"{b}: an external system is not modelled here — its model is translated "
                     f"at the border (contextes.json)")
            continue
        if b in models:
            c.err(F, f"{b}: twice")
            continue
        models[b] = read_context_model(b, e, D, X, idx, items, c)
    for b in X["internal"]:
        if b not in models and X["approach"][b][0] == "model-driven":
            c.warn(F, f"{b}: no model — a model-driven context gets its aggregates here")

    for b, M in models.items():
        for n, a in M["aggregates"].items():
            for ctx, name in a["refs_out"]:
                if frozenset((b, ctx)) not in X["pairs"]:
                    c.err(F, f"{b}.{n}: refers to {ctx}.{name}, but contextes.json has no "
                             f"relation between {b} and {ctx}")
                elif (ctx in models and models[ctx]["aggregates"] and name not in models[ctx]["roots"]
                      and name not in models[ctx]["aggregates"]):
                    c.warn(F, f"{b}.{n}: {ctx}.{name} is not an aggregate root of {ctx} — refer "
                              f"to roots only, by identity")
    if idx["data"]:
        seen = {flat(x) for M in models.values()
                for x in list(M["aggregates"]) + list(M["entities"]) + list(M["value_objects"])}
        if D:
            seen |= set(D["terms"]) | set(D["codes"])
        missing = [x for x in idx["data"] if flat(x) not in seen]
        if missing:
            c.warn(F, f"data of the cahier des charges in no model element: {short(missing)} — "
                      f"an aggregate, an entity or a value object, or say in a note why not")
    return models


# ── The code check ──────────────────────────────────────────────────────────

def code_words(folder: Path) -> tuple[set, set, set, int]:
    """(identifiers, their words, folder names, files read), all flattened."""
    idents, parts, dirs, files = set(), set(), set(), 0
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        dirs.update(flat(d) for d in dirnames)
        for f in sorted(filenames):
            p = Path(dirpath) / f
            if p.suffix.lower() not in SRC_EXT or files >= MAX_FILES:
                continue
            try:
                if p.stat().st_size > MAX_BYTES:
                    continue
                body = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            files += 1
            idents.add(flat(p.stem))
            for w in WORD_RE.findall(body):
                idents.add(flat(w))
                for piece in w.split("_"):
                    parts.update(x.lower() for x in CAMEL_RE.findall(piece))
    return idents, parts, dirs, files


def conformance(D: dict | None, X: dict | None, M: dict | None, folder: Path, c: Check) -> dict:
    F = "code"
    if not folder.is_dir():
        c.warn(F, f"{folder} is not a folder")
        return {}
    idents, parts, dirs, files = code_words(folder)
    if not files:
        c.warn(F, f"no source file in {folder}")
        return {"files": 0}
    expected = []
    for b, mm in (M or {}).items():
        if X["approach"][b][0] != "model-driven":
            continue
        names = (list(mm["entities"]) + list(mm["value_objects"]) + list(mm["events"])
                 + [s for s, v in mm["services"].items() if v["layer"] == "domain"])
        expected += [(b, n, code_name(n, D)) for n in names]
    missing = [f"{b}.{code}" for b, _n, code in expected if flat(code) not in idents]
    avoid_used = []
    for w, term in (D or {}).get("avoid", {}).items():
        if w and (w in idents or w in parts):
            avoid_used.append((w, term))
    packages = [(i, text(X["contexts"][i].get("code"))) for i in (X or {}).get("internal", [])
                if text(X["contexts"][i].get("code"))]
    no_package = [f"{i} ({code})" for i, code in packages if flat(code) not in dirs]
    if expected and missing:
        c.warn(F, f"{len(missing)} of {len(expected)} model name(s) not found in the code: "
                  f"{short(missing)} — not built yet, or named otherwise than the language says")
    for w, term in avoid_used:
        c.warn(F, f"the code says {w!r} where the language says {term}")
    if no_package:
        c.warn(F, f"no folder for the context(s) {short(no_package)}")
    return {"files": files, "names": len(expected), "found": len(expected) - len(missing),
            "missing": missing, "avoid_used": [f"{w} → {t}" for w, t in avoid_used],
            "packages_missing": no_package}


# ── The report ──────────────────────────────────────────────────────────────

def cell(v) -> str:
    return text(v).replace("|", "\\|") or "—"


def row(*cells) -> str:
    return "| " + " | ".join(cell(x) for x in cells) + " |"


def ctx_label(X: dict, i: str) -> str:
    b = X["contexts"].get(i) or {}
    return f"{i} {text(b.get('name'))}".strip()


def mermaid_map(X: dict) -> list[str]:
    """The context map as a Mermaid flowchart: upstream on the left."""
    def node(i):
        b = X["contexts"][i]
        name = text(b.get("name")).replace('"', "'") or i
        if b["kind"] == "external":
            return f'    {i}[["{name}<br/>(externe)"]]:::externe'
        core = X["approach"].get(i, ("", ""))[1] == "core"
        return f'    {i}["{name}{"<br/>(cœur)" if core else ""}"]' + (":::coeur" if core else "")
    lines = ["```mermaid", "flowchart LR"]
    lines += [node(i) for i in X["contexts"]]
    for r in X["relations"]:
        lab = " + ".join(PATTERNS[p] for p in r["patterns"])
        arrow = "-.-" if "separate-ways" in r["patterns"] else "-->"
        lines.append(f'    {r["upstream"]} {arrow}|"{lab}"| {r["downstream"]}')
    lines += ["    classDef coeur fill:#fde68a,stroke:#b45309,color:#111;",
              "    classDef externe fill:#e5e7eb,stroke:#6b7280,color:#111;", "```"]
    return lines


def _report_domaine(D: dict) -> list[str]:
    out = ["## 1. Vision du domaine", "", D["vision"] or "—", ""]
    if D["highlighted"]:
        out += ["**Le cœur en bref** (*Highlighted Core*) :", ""]
        out += [f"- {h}" for h in D["highlighted"]] + [""]
    out += ["## 2. Sous-domaines", "", row("Id", "Sous-domaine", "Type", "Approche", "Pourquoi"),
            "|---|---|---|---|---|"]
    for s in D["subdomains"].values():
        out.append(row(s["id"], s.get("name"), SUBDOMAIN_TYPES[s["type"]], APPROACHES[s["approach"]],
                       s.get("why")))
    out += ["", "## 3. Langage omniprésent", "",
            "Un mot par concept, le même dans les stories, les échanges, le code et les tests. "
            "Un terme qui manque ici manque au modèle.", "",
            row("Terme", "Définition", "Dans le code", "À éviter"), "|---|---|---|---|"]
    for t in sorted(D["terms"].values(), key=lambda g: key(g["term"])):
        code = text(t.get("code"))
        out.append(row(t["term"], t.get("definition"), f"`{code}`" if code else "",
                       ", ".join(strs(t.get("avoid")))))
    return out + [""]


def _report_contextes(X: dict, items: dict) -> list[str]:
    out = ["## 4. Contextes délimités", "",
           row("Id", "Contexte", "Sous-domaines", "Responsabilité", "Stories", "Exigences"),
           "|---|---|---|---|---|---|"]
    for i in X["internal"]:
        b = X["contexts"][i]
        stories = [s for s, ctx in X["story_ctx"].items() if ctx == i]
        reqs = [r for r, ctx in X["req_ctx"].items() if ctx == i]
        out.append(row(i, b.get("name"), ", ".join(strs(b.get("subdomains"))), b.get("responsibility"),
                       ", ".join(stories), ", ".join(reqs)))
    if X["external"]:
        out += ["", "**Systèmes externes** :", ""]
        for i in X["external"]:
            b = X["contexts"][i]
            out.append(f"- **{i} {text(b.get('name'))}** — {text(b.get('responsibility')) or '—'}")
    if X["homonyms"]:
        out += ["", "**Homonymes** — le même mot, un sens par contexte :", "",
                row("Terme", "Sens"), "|---|---|"]
        for h in X["homonyms"]:
            out.append(row(h["term"], " · ".join(f"{ctx_label(X, b)} : {v}" for b, v in h["meanings"].items())))
    out += ["", "## 5. Carte des contextes", ""] + mermaid_map(X) + [""]
    if X["relations"]:
        out += [row("Amont", "Aval", "Relation", "Traduction / partagé", "Pourquoi"), "|---|---|---|---|---|"]
        for r in X["relations"]:
            out.append(row(ctx_label(X, r["upstream"]), ctx_label(X, r["downstream"]),
                           " + ".join(PATTERNS[p] for p in r["patterns"]),
                           text(r.get("translation")) or ", ".join(strs(r.get("shared"))), r.get("why")))
        out.append("")
    return out


def _report_aggregate(a: dict) -> list[str]:
    head = f"- **{a['name']}** — racine `{a['root'] or '?'}`"
    inner = [x for x in a["entities"] if x != a["root"]]
    if inner:
        head += f" · entités {', '.join(inner)}"
    if strs(a.get("value_objects")):
        head += f" · objets-valeurs {', '.join(strs(a['value_objects']))}"
    head += " · dépôt" if a.get("repository", True) else " · sans dépôt"
    out = [head]
    for inv in a["invariants"]:
        src = text(inv.get("source"))
        out.append(f"  - Invariant : {text(inv['rule'])}" + (f" ({src})" if src else ""))
    if strs(a.get("commands")):
        out.append(f"  - Commandes : {', '.join(strs(a['commands']))}")
    if a["refs"]:
        out.append(f"  - Références (par identité) : {', '.join(a['refs'])}")
    if text(a.get("factory")):
        out.append(f"  - Fabrique : {text(a['factory'])}")
    if strs(a.get("stories")):
        out.append(f"  - Stories : {', '.join(strs(a['stories']))}")
    return out


def _report_modele(X: dict, M: dict) -> list[str]:
    out = ["## 6. Modèle par contexte", ""]
    for b in X["internal"]:
        ctx = X["contexts"][b]
        appr, kind = X["approach"][b]
        out += [f"### {ctx_label(X, b)} — {SUBDOMAIN_TYPES[kind]}, {APPROACHES[appr]}", ""]
        mm = M.get(b)
        if not mm:
            out += ["Pas de modèle détaillé.", ""]
            continue
        if mm["note"]:
            out += [mm["note"], ""]
        if mm["aggregates"]:
            out += ["**Agrégats**", ""]
            for a in mm["aggregates"].values():
                out += _report_aggregate(a)
            out.append("")
        if mm["value_objects"]:
            out += ["**Objets-valeurs**", "", row("Nom", "Attributs", "Règles"), "|---|---|---|"]
            for n, v in mm["value_objects"].items():
                out.append(row(n, ", ".join(strs(v.get("attributes"))), "; ".join(strs(v.get("rules")))))
            out.append("")
        if mm["services"]:
            out += ["**Services**", "", row("Nom", "Couche", "Rôle"), "|---|---|---|"]
            for n, s in mm["services"].items():
                out.append(row(n, SERVICE_LAYERS[s["layer"]], s.get("does")))
            out.append("")
        if mm["specifications"]:
            out += ["**Spécifications**", "", row("Nom", "Usage", "Règle", "Vient de"), "|---|---|---|---|"]
            for n, s in mm["specifications"].items():
                out.append(row(n, SPEC_KINDS[s["kind"]], s.get("rule"), ", ".join(strs(s.get("from")))))
            out.append("")
        if mm["events"]:
            out += ["**Événements du domaine**", "", row("Événement", "Levé par", "Écouté par", "Données"),
                    "|---|---|---|---|"]
            for n, ev in mm["events"].items():
                out.append(row(n, ev.get("raised_by"), ", ".join(strs(ev.get("consumed_by"))),
                               ", ".join(strs(ev.get("data")))))
            out.append("")
        if mm["modules"]:
            out += ["**Modules** : " + " · ".join(f"`{m['name']}` ({', '.join(m['contains'])})"
                                                  for m in mm["modules"]), ""]
    return out


def _report_trace(X: dict, M: dict, items: dict) -> list[str]:
    if not items:
        return []
    by_story = {}
    for b, mm in M.items():
        for a in mm["aggregates"].values():
            for s in strs(a.get("stories")):
                by_story.setdefault(s, []).append(a["name"])
    out = ["## 7. Traçabilité backlog → modèle", "", row("Story", "Titre", "Contexte", "Agrégat"),
           "|---|---|---|---|"]
    for s, v in items.items():
        if key(v.get("priority")) == "wont":
            continue
        ctx = X["story_ctx"].get(s)
        out.append(row(s, v.get("title"), ctx_label(X, ctx) if ctx else "**aucun**",
                       ", ".join(by_story.get(s, []))))
    return out + [""]


CODE_RULES = (
    "- Le code parle le langage omniprésent : classes, méthodes, tables, routes et tests "
    "portent les noms du glossaire (colonne « Dans le code »), jamais un mot « à éviter ».",
    "- Une transaction modifie **un seul agrégat**. Les autres suivent par un événement du "
    "domaine ou par le service d'application, jamais par un accès direct.",
    "- Hors de l'agrégat, on ne garde que l'**identité de la racine** ; on ne tient jamais une "
    "entité interne.",
    "- Un **dépôt** (repository) par racine d'agrégat, et pour elles seulement : son interface "
    "dans `domain/`, son implémentation dans `infrastructure/`.",
    "- Les **objets-valeurs** sont immuables et se comparent par leurs attributs ; les règles "
    "de validation vivent dedans.",
    "- Le domaine ne dépend de rien : ni framework web, ni ORM, ni API externe. Ce sont "
    "l'application et l'infrastructure qui dépendent de lui (architecture en couches).",
    "- Un système externe passe par sa **couche anticorruption** (un adaptateur qui traduit) "
    "quand la carte des contextes en prévoit une ; son modèle n'entre pas dans le domaine.",
    "- Les **spécifications** deviennent des prédicats nommés, et les critères d'acceptation "
    "des stories des tests nommés dans le langage du domaine.",
)


def _report_code(X: dict, M: dict) -> list[str]:
    out = ["## 8. Pour le code", "", "Règles que le code suit (Evans, ch. 4 à 6) :", ""]
    out += list(CODE_RULES) + [""]
    for b in X["internal"]:
        ctx = X["contexts"][b]
        appr = X["approach"][b][0]
        pkg = text(ctx.get("code")) or key(ctx.get("name")) or b.lower()
        if appr == "model-driven":
            mm = M.get(b) or {}
            aggs = ", ".join(mm.get("aggregates", {})) or "…"
            out += [f"**{ctx_label(X, b)}** — `{pkg}/` :", "", "```text",
                    f"{pkg}/",
                    f"  domain/          {aggs} ; objets-valeurs, événements, services du domaine,",
                    "                   interfaces des dépôts",
                    "  application/     un cas d'usage par commande (une transaction = un agrégat)",
                    "  infrastructure/  dépôts, persistance, adaptateurs et couches anticorruption",
                    "  interface/       API, écrans", "```", ""]
        else:
            out += [f"**{ctx_label(X, b)}** — `{pkg}/` : {APPROACHES[appr]}, sans couche domaine "
                    f"séparée : écrans et accès aux données directs, au plus simple.", ""]
    return out


def report(root: Path, D: dict, X: dict | None, M: dict | None, items: dict, conf: dict | None) -> str:
    project = D["project"] or root.name
    n_aggs = sum(len(mm["aggregates"]) for mm in (M or {}).values())
    lines = [f"# Modèle du domaine — {project}", "",
             "> Conception pilotée par le domaine (Eric Evans, *Domain-Driven Design*, 2003). "
             "Écrit par les skills ddd-\\*, vérifié et mis en page par `ddd.py` : les données "
             "sont dans `ddd/`, c'est là qu'on les corrige.", "", "## Synthèse", ""]
    cores = [text(D["subdomains"][s].get("name")) for s in D["cores"]]
    lines.append(f"- **Cœur du domaine** : {', '.join(cores) or '—'}")
    if X:
        lines.append(f"- **Contextes délimités** : {len(X['internal'])} interne(s), "
                     f"{len(X['external'])} système(s) externe(s), {len(X['relations'])} relation(s)")
    lines.append(f"- **Langage omniprésent** : {len(D['terms'])} termes")
    if M is not None:
        lines.append(f"- **Agrégats** : {n_aggs}")
    if X and items:
        todo = [s for s, v in items.items() if key(v.get("priority")) != "wont"]
        done = sum(1 for s in todo if s in X["story_ctx"])
        lines.append(f"- **Backlog** : {done}/{len(todo)} stories rattachées à un contexte")
    lines.append("")
    lines += _report_domaine(D)
    if X:
        lines += _report_contextes(X, items)
        if M is not None:
            lines += _report_modele(X, M)
            lines += _report_trace(X, M, items)
            lines += _report_code(X, M)
    if D["questions"]:
        lines += ["## 9. Questions pour les experts du domaine", "",
                  "Ce que la modélisation n'a pas pu trancher seule (*knowledge crunching*) :", ""]
        lines += [f"- {q}" for q in D["questions"]] + [""]
    if conf and conf.get("files"):
        lines += ["## 10. Conformité du code", "",
                  f"- {conf['found']}/{conf['names']} noms du modèle retrouvés dans le code "
                  f"({conf['files']} fichiers lus)"]
        if conf["missing"]:
            lines.append(f"- Absents : {short(conf['missing'], 30)}")
        for a in conf["avoid_used"]:
            lines.append(f"- Mot à éviter dans le code : {a}")
        for p in conf["packages_missing"]:
            lines.append(f"- Pas de dossier pour {p}")
        lines.append("")
    lines += ["---", "",
              "Sources : E. Evans, *Domain-Driven Design — Tackling Complexity in the Heart of "
              "Software*, Addison-Wesley, 2003 ; événements du domaine et partenariat : "
              "E. Evans, *Domain-Driven Design Reference*, 2015.", ""]
    return "\n".join(lines)


# ── Main ────────────────────────────────────────────────────────────────────

def compute(root: Path, c: Check):
    d = root / "ddd"
    files = {n: load(d / f"{n}.json", c) for n in ("domaine", "contextes", "modele")}
    cdc = project_file(root, "cahier-des-charges.json", c)
    items = backlog_items(project_file(root, "product-backlog.json", c))
    idx = cdc_index(cdc)
    D = read_domaine(files["domaine"], cdc, c) if files["domaine"] is not None else None
    if files["domaine"] is None and (files["contextes"] is not None or files["modele"] is not None):
        c.err("domaine.json", "missing — the contexts and the model are built on the domain")
    X = read_contextes(files["contextes"], D, idx, items, c) if files["contextes"] is not None else None
    M = read_modele(files["modele"], D, X, idx, items, c) if files["modele"] is not None else None
    return D, X, M, items


def summary(D, X, M, items, conf) -> dict:
    s: dict = {}
    if D:
        s.update(project=D["project"], terms=len(D["terms"]), subdomains=len(D["subdomains"]),
                 core=[text(D["subdomains"][i].get("name")) for i in D["cores"]])
    if X:
        todo = [k for k, v in items.items() if key(v.get("priority")) != "wont"]
        s.update(contexts=len(X["internal"]), external=len(X["external"]),
                 relations=len(X["relations"]),
                 stories={"total": len(todo), "mapped": sum(1 for k in todo if k in X["story_ctx"])})
    if M is not None:
        s["aggregates"] = sum(len(mm["aggregates"]) for mm in M.values())
    if conf:
        s["conformance"] = conf
    return s


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Check a domain model and write livrables/ddd.md.")
    ap.add_argument("project", help="folder holding ddd/")
    ap.add_argument("--check", action="store_true", help="validate only; exit 1 on any error")
    ap.add_argument("--json", action="store_true", help="print the summary as JSON")
    ap.add_argument("--code", metavar="DIR", help="also check that the code in DIR speaks the model")
    a = ap.parse_args(argv)
    root = Path(a.project).resolve()
    if not (root / "ddd").is_dir():
        print(f"ERROR   no ddd/ folder in {root}")
        return 1
    c = Check()
    D, X, M, items = compute(root, c)
    conf = conformance(D, X, M, Path(a.code).resolve(), c) if a.code and X else None
    written = []
    if not a.check and not c.errors and D:
        (root / "livrables").mkdir(exist_ok=True)
        (root / "livrables" / "ddd.md").write_text(report(root, D, X, M, items, conf), encoding="utf-8")
        written = ["livrables/ddd.md"]
    s = summary(D, X, M, items, conf)
    if a.json:
        print(json.dumps({"errors": c.errors, "warnings": c.warnings, "written": written,
                          "summary": s}, ensure_ascii=False, indent=1))
        return 1 if c.errors else 0
    for e in c.errors:
        print(f"ERROR   {e}")
    for w in c.warnings:
        print(f"WARN    {w}")
    if s.get("contexts") is not None:
        print(f"{s['contexts']} contexte(s), {s.get('aggregates', 0)} agrégat(s), "
              f"{s.get('terms', 0)} termes · cœur : {', '.join(s.get('core') or ['—'])}")
    if written:
        print("Written: " + ", ".join(written))
    elif not a.check and c.errors:
        print("Nothing written: fix the errors first.")
    print(f"{len(c.errors)} error(s), {len(c.warnings)} warning(s)")
    return 1 if c.errors else 0


if __name__ == "__main__":
    sys.exit(main())
