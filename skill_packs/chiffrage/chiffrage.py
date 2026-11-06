#!/usr/bin/env python3
"""Chiffrage calculator and checker. Standard library only, no network.

Reads the JSON files the chiffrage-* skills write in <project>/chiffrage/ and
does every calculation of the estimate, so no agent does arithmetic by hand:

    python3 chiffrage.py <project>            # compute, write chiffrage/synthese.json
                                              # and livrables/chiffrage.md
    python3 chiffrage.py <project> --check    # validate only: exit 1 on any error
    python3 chiffrage.py <project> --json     # compute, print the summary as JSON

Why a calculator instead of letting the agent do the sums: a language model
adding forty three-point estimates, a square root of a sum of squares, a
Monte Carlo run and a three-year cost table gets a digit wrong sooner or
later, and a wrong figure in front of a jury costs more than the whole
estimate. The agent writes the inputs and the reasons; this computes them the
same way every time.

Files (all in chiffrage/; each skill's SKILL.md holds the shape it writes):

    wbs.json         work breakdown structure: lots, work packages, deliverables,
                     dependencies, assumptions, exclusions, phase on the cone
    estimation.json  three points per work package, proportional overheads,
                     cross-checks (function points, COCOMO, velocity, analogy,
                     expert), engagement percentile
    budget.json      profiles and daily rates, allocation, other costs,
                     contingency, reserve, margin, VAT, payment schedule
    tco.json         run costs over 3 to 5 years, end of life, alternatives, gains
    pitch.md         the oral defence (only its sections are checked)

Also read when present: scrum/product-backlog.json (story coverage, points).

Sources of the constants: cone of uncertainty — Boehm (1981), McConnell,
Software Estimation (2006); PERT — Malcolm et al. (1959); function point
weights — IFPUG CPM 4.x; COCOMO 81 basic — Boehm (1981); COCOMO II.2000 —
Boehm et al. (2000).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import random
import re
import sys
import unicodedata
from pathlib import Path
from statistics import NormalDist

# Multipliers of a single-point estimate, by phase (low, high).
CONE = {
    "concept": (0.25, 4.0),
    "besoins": (0.5, 2.0),
    "specs": (0.67, 1.5),
    "conception": (0.8, 1.25),
    "code": (1.0, 1.0),
}
PHASES = {
    "concept": "Concept initial",
    "besoins": "Besoins définis & validés",
    "specs": "Spécifications complètes",
    "conception": "Conception terminée",
    "code": "Code terminé",
}
# IFPUG unadjusted weights (low, average, high).
FP_WEIGHTS = {"EI": (3, 4, 6), "EO": (4, 5, 7), "EQ": (3, 4, 6), "ILF": (7, 10, 15), "EIF": (5, 7, 10)}
# COCOMO 81 basic: effort = a * KLOC^b person-months, duration = 2.5 * effort^d months.
COCOMO81 = {"organique": (2.4, 1.05, 0.38), "semi-detache": (3.0, 1.12, 0.35), "embarque": (3.6, 1.20, 0.32)}
COCOMO81_ALIASES = {"organic": "organique", "semi-detached": "semi-detache", "semidetache": "semi-detache",
                    "embedded": "embarque"}
# COCOMO II.2000 nominal scale factors: PREC, FLEX, RESL, TEAM, PMAT.
COCOMO2_NOMINAL_SF = (3.72, 3.04, 4.24, 3.29, 4.68)
PM_HOURS = 152          # one COCOMO person-month
RUNS = 10_000
SEED = 2026
COST_CATEGORIES = ("licences", "infra", "outils", "sous-traitance", "materiel", "formation", "juridique",
                   "securite", "autre")
RUN_CATEGORIES = ("hebergement", "maintenance", "evolutions", "licences", "services", "support", "exploitation",
                  "securite", "conformite", "formation", "autre")
PRICING = ("forfait", "regie", "interne")
# Sections a pitch must have: any of the words, in a heading.
PITCH_SECTIONS = (
    ("decision", "la décision demandée"),
    ("perimetre hypothese", "le périmètre et les hypothèses"),
    ("methode", "la méthode d'estimation"),
    ("fourchette chiffre estimation", "le chiffre en fourchette"),
    ("budget", "le budget"),
    ("tco cout-complet cout-total", "le TCO"),
    ("risque", "les risques"),
    ("option scenario", "les options"),
    ("question objection", "les questions préparées"),
)
ID_RE = re.compile(r"^\d+(\.\d+)*$")


def key(s) -> str:
    """Lower case, no accents, dashes: "Semi-détaché" -> "semi-detache"."""
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def num(v):
    """A finite number, or None. Strings are refused: "12" is a typo waiting to happen."""
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    return float(v)


def g(x: float, dec: int | None = None) -> str:
    """A number for French text: 1,05 not 1.05."""
    return (f"{x:g}" if dec is None else f"{x:.{dec}f}").replace(".", ",")


def idkey(i: str):
    return tuple(int(x) for x in i.split("."))


def pct(sorted_values: list, q: float) -> float:
    if not sorted_values:
        return 0.0
    return sorted_values[min(len(sorted_values) - 1, max(0, round(q * (len(sorted_values) - 1))))]


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


# ── WBS ─────────────────────────────────────────────────────────────────────

def read_wbs(w, backlog, c: Check) -> dict | None:
    F = "wbs.json"
    if not isinstance(w, dict):
        c.err(F, "must be a JSON object")
        return None
    nodes: dict[str, dict] = {}
    for n in w.get("nodes") or []:
        if not isinstance(n, dict):
            c.err(F, "every node must be an object")
            continue
        i = str(n.get("id", "")).strip()
        if not ID_RE.match(i):
            c.err(F, f"node id {i!r}: use 1, 1.1, 1.1.1 …")
            continue
        if i in nodes:
            c.err(F, f"{i}: duplicate id")
            continue
        if not str(n.get("title", "")).strip():
            c.err(F, f"{i}: no title")
        nodes[i] = n
    if not nodes:
        c.err(F, "no nodes")
        return None

    ids = sorted(nodes, key=idkey)
    parent = {i: i.rsplit(".", 1)[0] if "." in i else None for i in ids}
    has_children = {p for p in parent.values() if p}
    leaves = [i for i in ids if i not in has_children]
    for i in ids:
        if parent[i] and parent[i] not in nodes:
            c.err(F, f"{i}: its parent {parent[i]} is missing")
        if i.count(".") > 2:
            c.warn(F, f"{i}: more than 3 levels — a WBS this deep is hard to read and to estimate")

    def under(x: str) -> list[str]:
        return [leaf for leaf in leaves if leaf == x or leaf.startswith(x + ".")]

    kinds = {}
    for i in leaves:
        k = nodes[i].get("kind", "dev")
        if k not in ("dev", "indirect"):
            c.err(F, f"{i}: kind must be \"dev\" or \"indirect\"")
            k = "dev"
        kinds[i] = k
        if not str(nodes[i].get("deliverable", "")).strip():
            c.warn(F, f"{i}: no deliverable — a work package ends with something you can check")
    if "indirect" not in kinds.values():
        c.warn(F, "no indirect work package (recette, mise en production, CI/CD, documentation, formation…)")

    deps: dict[str, set] = {i: set() for i in leaves}
    for i in ids:
        for x in nodes[i].get("depends_on") or []:
            x = str(x).strip()
            if x not in nodes:
                c.err(F, f"{i}: depends on {x}, which is not in the WBS")
                continue
            src, dst = under(x), under(i)
            if set(src) & set(dst):
                c.err(F, f"{i}: depends on {x}, which contains it or is inside it")
                continue
            for d in dst:
                deps[d].update(src)

    users: dict[str, list] = {i: [] for i in leaves}
    for i in leaves:
        for d in deps[i]:
            users[d].append(i)
    indeg = {i: len(deps[i]) for i in leaves}
    ready = [i for i in leaves if not indeg[i]]
    order: list[str] = []
    while ready:
        i = ready.pop(0)
        order.append(i)
        for u in users[i]:
            indeg[u] -= 1
            if not indeg[u]:
                ready.append(u)
    if len(order) < len(leaves):
        loop = sorted(set(leaves) - set(order), key=idkey)
        c.err(F, f"the dependencies form a cycle through {', '.join(loop)}")
        deps = {i: set() for i in leaves}
        users = {i: [] for i in leaves}
        order = list(leaves)

    phase = key(w.get("phase"))
    if phase not in CONE:
        c.err(F, f"phase must be one of {', '.join(CONE)} (where the project is on the cone of uncertainty)")
        phase = None
    if len(w.get("assumptions") or []) < 3:
        c.warn(F, "fewer than 3 assumptions — « une estimation sans fourchette ni hypothèses est une "
                  "promesse déguisée »")
    if not w.get("exclusions"):
        c.warn(F, "no exclusions — say what the price does not include")
    hpd = num(w.get("hours_per_day", 7))
    if hpd is None or not 1 <= hpd <= 12:
        c.err(F, "hours_per_day must be a number between 1 and 12")
        hpd = 7.0
    start = None
    if w.get("start"):
        try:
            start = dt.date.fromisoformat(str(w["start"]))
        except ValueError:
            c.err(F, "start must be a date, YYYY-MM-DD")

    if isinstance(backlog, dict):
        items = {str(s.get("id")): s for s in backlog.get("stories") or [] if isinstance(s, dict)}
        seen: dict[str, str] = {}
        for i in ids:
            stories = nodes[i].get("stories") or []
            if stories and i not in leaves:
                c.warn(F, f"{i}: put its stories on its work packages, not on the lot")
            for s in stories:
                s = str(s)
                if s not in items:
                    c.err(F, f"{i}: {s} is not in scrum/product-backlog.json")
                    continue
                if items[s].get("priority") == "wont":
                    c.warn(F, f"{i}: {s} is \"wont\" in the backlog — out of scope, move it to the exclusions")
                if s in seen:
                    c.warn(F, f"{s} is in both {seen[s]} and {i} — one work package per backlog item")
                seen.setdefault(s, i)
        missing = [s for s, v in items.items() if v.get("priority") != "wont" and s not in seen]
        if missing:
            more = " …" if len(missing) > 12 else ""
            c.warn(F, f"{len(missing)} backlog item(s) in no work package (règle des 100 %): "
                      f"{', '.join(missing[:12])}{more}")

    return {"nodes": nodes, "ids": ids, "leaves": leaves, "kinds": kinds, "deps": deps, "users": users,
            "order": order, "phase": phase, "hpd": hpd, "start": start, "under": under}


# ── Estimation ──────────────────────────────────────────────────────────────

def beta_params(o: float, m: float, p: float):
    """PERT-Beta shape parameters; its mean is (o + 4m + p) / 6."""
    if p - o < 1e-9:
        return None
    return 1 + 4 * (m - o) / (p - o), 1 + 4 * (p - m) / (p - o)


def cpm(W: dict, dur: dict) -> tuple[float, list[str], dict]:
    """Critical path with these durations (unlimited resources)."""
    es, ef = {}, {}
    for i in W["order"]:
        es[i] = max((ef[d] for d in W["deps"][i]), default=0.0)
        ef[i] = es[i] + dur.get(i, 0.0)
    length = max(ef.values(), default=0.0)
    ls, lf = {}, {}
    for i in reversed(W["order"]):
        lf[i] = min((ls[u] for u in W["users"][i]), default=length)
        ls[i] = lf[i] - dur.get(i, 0.0)
    critical = [i for i in W["order"] if lf[i] - ef[i] < 1e-6]
    slack = {i: lf[i] - ef[i] for i in W["order"]}
    return length, critical, slack


def finish_date(start: dt.date, days: float) -> dt.date:
    """The working day (Mon–Fri, public holidays not counted) on which `days` of work end."""
    d = start
    while d.weekday() >= 5:
        d += dt.timedelta(days=1)
    left = max(0, math.ceil(days - 1e-9) - 1)
    while left:
        d += dt.timedelta(days=1)
        if d.weekday() < 5:
            left -= 1
    return d


def backlog_points(backlog) -> float | None:
    if not isinstance(backlog, dict):
        return None
    pts = [num(s.get("points")) for s in backlog.get("stories") or []
           if isinstance(s, dict) and s.get("priority") != "wont"]
    pts = [p for p in pts if p is not None]
    return sum(pts) if pts else None


def cross_check(cc, W: dict, backlog, c: Check) -> dict | None:
    F = "estimation.json"
    if not isinstance(cc, dict):
        c.err(F, "every cross_check must be an object")
        return None
    m = key(cc.get("method"))
    hpd = W["hpd"]

    if m in ("points-de-fonction", "function-points", "fp", "ifpug"):
        counts = cc.get("counts") or {}
        if not isinstance(counts, dict) or not counts:
            c.err(F, "points-de-fonction: counts is required, e.g. {\"EI\": 6, \"EO\": 4, …}")
            return None
        for t in set(counts) - set(FP_WEIGHTS):
            c.err(F, f"points-de-fonction: unknown type {t} (EI, EO, EQ, ILF, EIF)")
        ufp = 0.0
        for t, w in FP_WEIGHTS.items():
            v = counts.get(t, 0)
            if isinstance(v, dict):
                n = [num(v.get(k, 0)) for k in ("low", "avg", "high")]
                if any(x is None or x < 0 for x in n):
                    c.err(F, f"points-de-fonction: {t} low / avg / high must be counts ≥ 0")
                    return None
                ufp += sum(a * b for a, b in zip(n, w))
            else:
                n = num(v)
                if n is None or n < 0:
                    c.err(F, f"points-de-fonction: {t} must be a count ≥ 0 or {{low, avg, high}}")
                    return None
                ufp += n * w[1]
        gsc = cc.get("gsc")
        if gsc is not None:
            if (not isinstance(gsc, list) or len(gsc) != 14
                    or any(num(g) is None or not 0 <= g <= 5 for g in gsc)):
                c.err(F, "points-de-fonction: gsc must be the 14 general system characteristics, each 0 to 5")
                return None
            vaf = 0.65 + 0.01 * sum(gsc)
        else:
            vaf = num(cc.get("vaf", 1.0))
            if vaf is None or not 0.65 <= vaf <= 1.35:
                c.err(F, "points-de-fonction: vaf must be between 0.65 and 1.35")
                return None
        hpf = num(cc.get("hours_per_fp", 10))
        if hpf is None or hpf <= 0:
            c.err(F, "points-de-fonction: hours_per_fp must be a positive number")
            return None
        fp = ufp * vaf
        return {"method": "Points de fonction (IFPUG)", "effort": fp * hpf / hpd,
                "detail": f"{g(ufp)} UFP × {g(vaf, 2)} = {fp:.0f} FP × {g(hpf)} h/FP = {fp * hpf:.0f} h"}

    if m in ("cocomo", "cocomo-81", "cocomo81"):
        kloc = num(cc.get("kloc"))
        mode = key(cc.get("mode", "organique"))
        mode = COCOMO81_ALIASES.get(mode, mode)
        if kloc is None or kloc <= 0 or mode not in COCOMO81:
            c.err(F, "cocomo: kloc > 0 and mode organique | semi-detache | embarque are required")
            return None
        a, b, d = COCOMO81[mode]
        pm = a * kloc ** b
        months = 2.5 * pm ** d
        return {"method": f"COCOMO 81 ({mode})", "effort": pm * PM_HOURS / hpd, "months": months,
                "detail": f"{g(a)} × {g(kloc)}^{g(b)} = {g(pm, 1)} personnes-mois · durée 2,5 × PM^{g(d)} = "
                          f"{g(months, 1)} mois · équipe ≈ {g(pm / months, 1)}"}

    if m in ("cocomo-2", "cocomo2", "cocomo-ii"):
        kloc = num(cc.get("kloc"))
        sf = cc.get("scale_factors", list(COCOMO2_NOMINAL_SF))
        em = cc.get("effort_multipliers", [])
        if (kloc is None or kloc <= 0 or not isinstance(sf, list) or len(sf) != 5
                or any(num(x) is None or x < 0 for x in sf)
                or not isinstance(em, list) or any(num(x) is None or x <= 0 for x in em)):
            c.err(F, "cocomo2: kloc > 0, scale_factors (5 numbers) and effort_multipliers (numbers > 0)")
            return None
        e = 0.91 + 0.01 * sum(sf)
        pm = 2.94 * math.prod(em) * kloc ** e
        months = 3.67 * pm ** (0.28 + 0.2 * (e - 0.91))
        return {"method": "COCOMO II", "effort": pm * PM_HOURS / hpd, "months": months,
                "detail": f"2,94 × EM {g(math.prod(em), 2)} × {g(kloc)}^{g(e, 3)} = {g(pm, 1)} personnes-mois · "
                          f"durée {g(months, 1)} mois"}

    if m in ("velocite", "velocity", "planning-poker", "story-points"):
        pts = num(cc.get("points")) if "points" in cc else backlog_points(backlog)
        source = "saisis" if "points" in cc else "du backlog"
        vel = cc.get("velocity")
        vel = [vel, vel] if num(vel) is not None else vel
        sd = num(cc.get("sprint_days", 10))
        team = num(cc.get("team"))
        if (pts is None or pts <= 0 or not isinstance(vel, list) or len(vel) != 2
                or any(num(v) is None or v <= 0 for v in vel) or not sd or sd <= 0 or not team or team <= 0):
            c.err(F, "velocite: points (or a backlog with points), velocity (a number or [low, high]), "
                     "sprint_days and team are required")
            return None
        lo_v, hi_v = sorted(vel)
        s_lo, s_hi = math.ceil(pts / hi_v), math.ceil(pts / lo_v)
        e_lo, e_hi = s_lo * sd * team, s_hi * sd * team
        return {"method": "Vélocité (story points)", "effort": (e_lo + e_hi) / 2, "range": [e_lo, e_hi],
                "detail": f"{g(pts)} points {source} ÷ {g(lo_v)}–{g(hi_v)} pts/sprint = {s_lo}–{s_hi} sprints "
                          f"× {g(sd)} j × {g(team)} pers."}

    if m in ("analogie", "analogy", "expert", "jugement-d-expert", "jugement-expert"):
        effort = num(cc.get("effort"))
        factor = num(cc.get("factor", 1))
        if effort is None or effort <= 0 or factor is None or factor <= 0:
            c.err(F, f"{m}: effort (jours-homme) > 0 is required, factor > 0 if given")
            return None
        ref = str(cc.get("reference", "")).strip()
        if not ref:
            c.warn(F, f"{m}: no reference — name the past project or the expert")
        label = "Analogie" if m.startswith("analog") else "Jugement d'expert"
        return {"method": label, "effort": effort * factor,
                "detail": f"{ref or '?'} : {g(effort)} jh" + (f" × {g(factor)}" if factor != 1 else "")}

    c.err(F, f"unknown cross_check method {cc.get('method')!r} (points-de-fonction, cocomo, cocomo2, "
             "velocite, analogie, expert)")
    return None


def compute_estimation(e, W: dict, backlog, c: Check) -> dict | None:
    F = "estimation.json"
    if not isinstance(e, dict):
        c.err(F, "must be a JSON object")
        return None
    leaves = W["leaves"]
    est: dict[str, tuple] = {}
    basis_missing = 0
    for x in e.get("estimates") or []:
        if not isinstance(x, dict):
            c.err(F, "every estimate must be an object")
            continue
        i = str(x.get("id", "")).strip()
        if i not in W["nodes"]:
            c.err(F, f"{i}: not in wbs.json")
            continue
        if i not in leaves:
            c.err(F, f"{i}: has work packages under it — estimate those, not the lot")
            continue
        if i in est:
            c.err(F, f"{i}: estimated twice")
            continue
        o, m, p = num(x.get("o")), num(x.get("m")), num(x.get("p"))
        people = num(x.get("people", 1))
        if o is None or m is None or p is None or o < 0 or not o <= m <= p or p <= 0:
            c.err(F, f"{i}: o, m, p must be numbers with 0 ≤ o ≤ m ≤ p and p > 0")
            continue
        if people is None or people <= 0:
            c.err(F, f"{i}: people must be a number > 0")
            continue
        if m > 10:
            c.warn(F, f"{i}: m = {m:g} jh — above 10 jh (règle 8/80 h), split it: decomposing reduces "
                      "uncertainty")
        if p == o and m >= 1:
            c.warn(F, f"{i}: o = p, no uncertainty at all — is that true?")
        if p > 3 * m and m > 0:
            c.warn(F, f"{i}: p is more than 3 × m — that much uncertainty calls for a spike first")
        if not str(x.get("basis", "")).strip():
            basis_missing += 1
        est[i] = (o, m, p, people)
    missing = [i for i in leaves if i not in est]
    if missing:
        c.err(F, f"work package(s) with no estimate: {', '.join(missing)}")
    if basis_missing:
        c.warn(F, f"{basis_missing} estimate(s) with no basis — say why each figure")
    if not est:
        return None

    overheads, rate_total = [], 0.0
    for oh in e.get("overheads") or []:
        r = num(oh.get("rate")) if isinstance(oh, dict) else None
        label = str(oh.get("label", "")).strip() if isinstance(oh, dict) else ""
        if not label or r is None or not 0 < r <= 0.5:
            c.err(F, "every overhead needs a label and a rate between 0 and 0.5 (0.12 = 12 %)")
            continue
        overheads.append({"label": label, "rate": r})
        rate_total += r
    if rate_total > 0.6:
        c.warn(F, f"overheads add {rate_total:.0%} on top of the work packages — double counting?")

    conf = num(e.get("confidence", 0.8))
    if conf is None or not 0.5 <= conf <= 0.99:
        c.err(F, "confidence must be between 0.5 and 0.99 (0.8 = commit at P80)")
        conf = 0.8
    team = num(e.get("team")) if "team" in e else None
    if "team" in e and (team is None or team <= 0):
        c.err(F, "team must be the number of people working on the packages at the same time")
        team = None

    rows, s_leaf, var, s_dev = [], 0.0, 0.0, 0.0
    for i in leaves:
        if i not in est:
            continue
        o, m, p, people = est[i]
        exp, sd = (o + 4 * m + p) / 6, (p - o) / 6
        s_leaf += exp
        var += sd * sd
        if W["kinds"][i] == "dev":
            s_dev += exp
        rows.append({"id": i, "title": W["nodes"][i].get("title", ""), "kind": W["kinds"][i],
                     "deliverable": W["nodes"][i].get("deliverable", ""), "o": o, "m": m, "p": p,
                     "people": people, "expected": exp, "sigma": sd})
    for oh in overheads:
        oh["effort"] = s_leaf * oh["rate"]
    total = s_leaf * (1 + rate_total)
    sigma = math.sqrt(var) * (1 + rate_total)
    nd = NormalDist()
    commit = total + nd.inv_cdf(conf) * sigma
    dev_share = s_dev / total if total else 0.0
    if total and dev_share > 0.7:
        c.warn(F, f"pure development is {dev_share:.0%} of the effort — usually 50–60 %: tests, recette, "
                  "DevOps, ceremonies or project management forgotten?")
    elif total and dev_share < 0.4:
        c.warn(F, f"pure development is only {dev_share:.0%} of the effort — overheads counted twice?")

    # Monte Carlo: PERT-Beta per work package, critical path per run.
    rng = random.Random(SEED)
    params = {i: (est[i][0], est[i][2] - est[i][0], beta_params(*est[i][:3]), est[i][3]) for i in est}
    efforts, lengths = [], []
    for _ in range(RUNS):
        fin: dict[str, float] = {}
        work = 0.0
        for i in W["order"]:
            start = max((fin[d] for d in W["deps"][i]), default=0.0)
            if i not in params:
                fin[i] = start
                continue
            o, span, ab, people = params[i]
            x = o if ab is None else o + span * rng.betavariate(*ab)
            work += x
            fin[i] = start + x / people
        length = max(fin.values(), default=0.0)
        if team:
            length = max(length, work / team)
        efforts.append(work * (1 + rate_total))
        lengths.append(length)
    efforts.sort()
    lengths.sort()

    dur = {r["id"]: r["expected"] / r["people"] for r in rows}
    length, critical, slack = cpm(W, dur)
    workload = s_leaf / team if team else None
    expected_days = max(length, workload or 0.0)
    duration = {"critical_path": critical, "cpm_days": length, "workload_days": workload,
                "expected_days": expected_days,
                "monte_carlo": {"p50": pct(lengths, .5), "p80": pct(lengths, .8), "p90": pct(lengths, .9)},
                "slack": {i: s for i, s in slack.items() if s > 1e-6}}
    if W["start"]:
        duration["start"] = W["start"].isoformat()
        duration["finish_p50"] = finish_date(W["start"], duration["monte_carlo"]["p50"]).isoformat()
        duration["finish_p80"] = finish_date(W["start"], duration["monte_carlo"]["p80"]).isoformat()

    checks = [r for r in (cross_check(cc, W, backlog, c) for cc in e.get("cross_checks") or []) if r]
    if not e.get("cross_checks"):
        c.warn(F, "no cross_check — « croiser 2 méthodes fiabilise, jamais une seule à l'aveugle »")
    for r in checks:
        r["ratio"] = r["effort"] / total if total else 0.0
        if not 0.67 <= r["ratio"] <= 1.5:
            c.warn(F, f"{r['method']} gives {r['effort']:.0f} jh, {r['ratio']:.2f} × the PERT estimate "
                      f"({total:.0f} jh) — find out why (scope forgotten? optimism? wrong productivity?) "
                      "and write it in decisions.md")

    cone = None
    if W["phase"]:
        lo, hi = CONE[W["phase"]]
        cone = {"phase": W["phase"], "label": PHASES[W["phase"]], "low": lo, "high": hi,
                "range": [total * lo, total * hi]}

    return {"unit": "jours-homme", "hours_per_day": W["hpd"], "packages": rows, "leaves_expected": s_leaf,
            "dev_expected": s_dev, "overheads": overheads, "overhead_rate": rate_total, "expected": total,
            "sigma": sigma, "confidence": conf, "commit": commit,
            "p80": total + nd.inv_cdf(0.8) * sigma, "p90": total + nd.inv_cdf(0.9) * sigma,
            "monte_carlo": {"runs": RUNS, "p10": pct(efforts, .1), "p50": pct(efforts, .5),
                            "p80": pct(efforts, .8), "p90": pct(efforts, .9)},
            "dev_share": dev_share, "team": team, "duration": duration, "cone": cone, "cross_checks": checks}


# ── Budget ──────────────────────────────────────────────────────────────────

def compute_budget(b, E: dict, W: dict, c: Check) -> dict | None:
    F = "budget.json"
    if not isinstance(b, dict):
        c.err(F, "must be a JSON object")
        return None
    pricing = key(b.get("pricing", "forfait"))
    if pricing not in PRICING:
        c.err(F, f"pricing must be one of {', '.join(PRICING)}")
        pricing = "forfait"

    profiles: dict[str, dict] = {}
    for p in b.get("profiles") or []:
        if not isinstance(p, dict):
            c.err(F, "every profile must be an object")
            continue
        pid = str(p.get("id", "")).strip()
        if not pid or pid in profiles:
            c.err(F, f"profile id {pid!r} missing or duplicated")
            continue
        tjm, salary = num(p.get("tjm")), num(p.get("salary"))
        if tjm is not None and tjm > 0:
            rate = tjm
        elif salary is not None and salary > 0:
            charges, days = num(p.get("charges", 0.45)), num(p.get("days", 218))
            if charges is None or not 0 <= charges <= 1 or not days or days <= 0:
                c.err(F, f"{pid}: charges (0.45 = 45 %) and days (218) must be numbers")
                continue
            rate = salary * (1 + charges) / days
        else:
            c.err(F, f"{pid}: give a daily rate (tjm) or a gross yearly salary (salary)")
            continue
        if not str(p.get("basis", "")).strip():
            c.warn(F, f"{pid}: no basis — where does this rate come from?")
        if not 150 <= rate <= 2000:
            c.warn(F, f"{pid}: {rate:.0f} €/day is unusual for France")
        profiles[pid] = {"id": pid, "title": p.get("title", pid), "rate": rate,
                         "kind": "tjm" if tjm is not None and tjm > 0 else "salary"}
    if len({p["kind"] for p in profiles.values()}) > 1:
        c.warn(F, "profiles mix selling rates (tjm) and internal costs (salary) — pick one basis, then "
                  "add the margin only to costs")
    if not profiles:
        c.err(F, "no profile")
        return None

    alloc = b.get("allocation") or {}
    if not isinstance(alloc, dict):
        c.err(F, "allocation must be an object")
        alloc = {}
    default = alloc.get("default") or (next(iter(profiles)) if len(profiles) == 1 else None)
    labels = {oh["label"] for oh in E["overheads"]}
    for k in alloc:
        if k != "default" and k not in W["nodes"] and k not in labels:
            c.warn(F, f"allocation {k!r} is neither a WBS id nor an overhead label")

    def split(target: str) -> dict:
        v, t = alloc.get(target), target
        while v is None and "." in t:
            t = t.rsplit(".", 1)[0]
            v = alloc.get(t)
        v = v if v is not None else default
        if isinstance(v, str):
            v = {v: 1}
        if not isinstance(v, dict) or not v:
            c.err(F, f"{target}: no profile — set allocation.default or allocate it")
            return {}
        bad = [k for k in v if k not in profiles]
        shares = [num(s) for s in v.values()]
        if bad or any(s is None or s < 0 for s in shares) or abs(sum(shares) - 1) > 0.001:
            c.err(F, f"{target}: allocation must name existing profiles with shares adding up to 1")
            return {}
        return v

    per_profile = {pid: {"jh": 0.0, "cost": 0.0} for pid in profiles}
    lines = [(r["id"], r["expected"]) for r in E["packages"]] + [(oh["label"], oh["effort"]) for oh in E["overheads"]]
    for target, jh in lines:
        for pid, share in split(target).items():
            per_profile[pid]["jh"] += jh * share
            per_profile[pid]["cost"] += jh * share * profiles[pid]["rate"]
    labour = sum(v["cost"] for v in per_profile.values())

    costs, by_cat = [], {}
    for x in b.get("costs") or []:
        amt = num(x.get("amount")) if isinstance(x, dict) else None
        cat = key(x.get("category", "autre")) if isinstance(x, dict) else ""
        if amt is None or amt < 0 or not str(x.get("label", "")).strip():
            c.err(F, "every cost needs a label and an amount ≥ 0")
            continue
        if cat not in COST_CATEGORIES:
            c.err(F, f"{x['label']}: category must be one of {', '.join(COST_CATEGORIES)}")
            cat = "autre"
        if not str(x.get("basis", "")).strip():
            c.warn(F, f"{x['label']}: no basis — how was the amount found?")
        costs.append({"label": x["label"], "category": cat, "amount": amt, "basis": x.get("basis", "")})
        by_cat[cat] = by_cat.get(cat, 0.0) + amt
    other = sum(by_cat.values())
    if not costs:
        c.warn(F, "no cost outside the team — licences, environments, tools, legal, security audit?")

    cont_def = b.get("contingency") or {"method": "percentile"}
    method = key(cont_def.get("method", "percentile")) if isinstance(cont_def, dict) else ""
    avg_rate = labour / E["expected"] if E["expected"] else 0.0
    risks = []
    if method in ("percentile", "p80", "pert"):
        contingency = max(0.0, E["commit"] - E["expected"]) * avg_rate
        cont_label = f"P{round(E['confidence'] * 100)} − P50 de la charge × TJM moyen"
    elif method == "rate":
        r = num(cont_def.get("rate"))
        if r is None or not 0 <= r <= 0.5:
            c.err(F, "contingency.rate must be between 0 and 0.5")
            r = 0.0
        contingency = (labour + other) * r
        cont_label = f"{pc(r)} du coût"
    elif method == "risks":
        for x in cont_def.get("risks") or []:
            pr, cost = num(x.get("probability")), num(x.get("cost"))
            if pr is None or not 0 < pr < 1 or cost is None or cost < 0:
                c.err(F, "every contingency risk needs probability (0 to 1) and cost (€)")
                continue
            risks.append({"id": x.get("id", ""), "label": x.get("label", ""), "probability": pr,
                          "cost": cost, "exposure": pr * cost})
        contingency = sum(x["exposure"] for x in risks)
        cont_label = "Σ probabilité × coût des risques identifiés"
        if not risks:
            c.warn(F, "contingency by risks with no risk listed")
    else:
        c.err(F, "contingency.method must be percentile, rate or risks")
        contingency, cont_label = 0.0, "?"
    if pricing == "forfait" and contingency <= 0:
        c.warn(F, "fixed price with no contingency — at a forfait, the risk is yours")

    reserve_rate = num(b.get("management_reserve", 0))
    if reserve_rate is None or not 0 <= reserve_rate <= 0.3:
        c.err(F, "management_reserve must be between 0 and 0.3")
        reserve_rate = 0.0
    reserve = (labour + other) * reserve_rate
    margin = num(b.get("margin", 0))
    if margin is None or not 0 <= margin <= 1:
        c.err(F, "margin must be between 0 and 1 (0.15 = 15 %)")
        margin = 0.0
    if pricing == "interne" and margin > 0:
        c.warn(F, "internal project with a margin — an internal budget is at cost")
    if margin > 0.35:
        c.warn(F, f"a {margin:.0%} margin is hard to defend")
    vat = num(b.get("vat", 0 if pricing == "interne" else 0.2))
    if vat is None or not 0 <= vat <= 0.3:
        c.err(F, "vat must be between 0 and 0.3")
        vat = 0.2

    cost_total = labour + other + contingency + reserve
    price = cost_total * (1 + margin)
    price_p50 = (labour + other + reserve) * (1 + margin)

    schedule = []
    sched = b.get("schedule") or []
    if sched:
        shares = [num(s.get("share")) if isinstance(s, dict) else None for s in sched]
        if any(s is None or s <= 0 for s in shares) or abs(sum(shares) - 1) > 0.001:
            c.err(F, "schedule shares must be > 0 and add up to 1")
        else:
            schedule = [{"label": s.get("label", ""), "share": sh, "amount": price * sh}
                        for s, sh in zip(sched, shares)]
    elif pricing == "forfait":
        c.warn(F, "fixed price with no payment schedule (acompte, jalons, VSR)")

    return {"currency": b.get("currency", "EUR"), "pricing": pricing,
            "profiles": [{**profiles[p], **per_profile[p]} for p in profiles],
            "labour": labour, "labour_jh": E["expected"], "average_rate": avg_rate,
            "costs": costs, "costs_by_category": by_cat, "other": other,
            "contingency": contingency, "contingency_basis": cont_label, "risks": risks,
            "management_reserve": reserve, "management_reserve_rate": reserve_rate,
            "cost_total": cost_total, "margin_rate": margin, "margin": price - cost_total,
            "price_p50_ht": price_p50, "price_ht": price, "vat_rate": vat, "vat": price * vat,
            "price_ttc": price * (1 + vat), "schedule": schedule}


# ── TCO ─────────────────────────────────────────────────────────────────────

def yearly_series(item: dict, years: int, build: float, idx: float, F: str, c: Check) -> list[float] | None:
    g = num(item.get("growth")) if "growth" in item else idx
    if g is None or not -0.5 <= g <= 2:
        c.err(F, f"{item.get('label')}: growth must be a yearly rate (0.1 = +10 %/an)")
        return None
    modes = [k for k in ("monthly", "yearly", "rate_of_build", "amount") if k in item]
    if len(modes) != 1:
        c.err(F, f"{item.get('label')}: give exactly one of monthly, yearly, rate_of_build, amount")
        return None
    mode = modes[0]
    v = num(item[mode])
    if v is None or v < 0:
        c.err(F, f"{item.get('label')}: {mode} must be a number ≥ 0")
        return None
    if mode == "rate_of_build" and v > 0.5:
        c.warn(F, f"{item.get('label')}: {v:.0%} of the build every year is a lot")
    first = int(num(item.get("from_year", 1)) or 1)
    out = [0.0] * (years + 1)
    if mode == "amount":
        y = int(num(item.get("year", 1)) or 1)
        if not 1 <= y <= years:
            c.err(F, f"{item.get('label')}: year must be between 1 and {years}")
            return None
        out[y] = v
        return out
    base = {"monthly": v * 12, "yearly": v, "rate_of_build": v * build}[mode]
    for y in range(max(1, first), years + 1):
        out[y] = base * (1 + g) ** (y - max(1, first))
    return out


def compute_tco(t, B: dict | None, c: Check) -> dict | None:
    F = "tco.json"
    if not isinstance(t, dict):
        c.err(F, "must be a JSON object")
        return None
    years = num(t.get("years", 3))
    if years is None or years != int(years) or not 1 <= years <= 10:
        c.err(F, "years must be a whole number between 1 and 10")
        return None
    years = int(years)
    if not 3 <= years <= 5:
        c.warn(F, "a TCO is usually computed over 3 to 5 years")
    build = t.get("build", "budget")
    if build == "budget":
        if not B:
            c.err(F, "build is \"budget\" but budget.json gives no total")
            return None
        build = B["price_ht"]
    else:
        build = num(build)
        if build is None or build < 0:
            c.err(F, "build must be \"budget\" or an amount ≥ 0")
            return None
    idx = num(t.get("indexation", 0))
    if idx is None or not 0 <= idx <= 0.2:
        c.err(F, "indexation must be a yearly rate between 0 and 0.2")
        idx = 0.0

    rows, cats = [], set()
    for item in t.get("run") or []:
        if not isinstance(item, dict) or not str(item.get("label", "")).strip():
            c.err(F, "every run item needs a label")
            continue
        cat = key(item.get("category", "autre"))
        if cat not in RUN_CATEGORIES:
            c.err(F, f"{item['label']}: category must be one of {', '.join(RUN_CATEGORIES)}")
            cat = "autre"
        if not str(item.get("basis", "")).strip():
            c.warn(F, f"{item['label']}: no basis — how was the amount found?")
        s = yearly_series(item, years, build, idx, F, c)
        if s is not None:
            rows.append({"label": item["label"], "category": cat, "years": s, "total": sum(s)})
            cats.add(cat)
    if "maintenance" not in cats:
        c.warn(F, "no maintenance item — corrective and adaptive maintenance is often 15–20 % of the build "
                  "a year")
    if "hebergement" not in cats:
        c.warn(F, "no hosting item")

    eol = t.get("end_of_life")
    eol_amount = 0.0
    if eol:
        eol_amount = num(eol.get("amount")) if isinstance(eol, dict) else None
        if eol_amount is None or eol_amount < 0:
            c.err(F, "end_of_life needs an amount ≥ 0")
            eol_amount = 0.0
    per_year = [build] + [sum(r["years"][y] for r in rows) for y in range(1, years + 1)]
    per_year[-1] += eol_amount
    run_total = sum(per_year[1:]) - eol_amount
    tco = sum(per_year)
    if build and run_total / build < 0.1 * years:
        c.warn(F, f"run is {run_total / build:.0%} of the build over {years} years — under-estimated?")

    alternatives = []
    for a in t.get("alternatives") or []:
        if not isinstance(a, dict) or not str(a.get("label", "")).strip():
            c.err(F, "every alternative needs a label")
            continue
        setup = num(a.get("setup", 0))
        s = yearly_series({k: v for k, v in a.items() if k not in ("setup",)}, years, build, idx, F, c)
        if s is None or setup is None or setup < 0:
            continue
        s[0] = setup
        alternatives.append({"label": a["label"], "years": s, "total": sum(s), "basis": a.get("basis", "")})

    gains = [0.0] * (years + 1)
    for gn in t.get("gains") or []:
        if not isinstance(gn, dict) or not str(gn.get("label", "")).strip():
            c.err(F, "every gain needs a label")
            continue
        s = yearly_series(gn, years, build, 0.0, F, c)
        if s is not None:
            gains = [a + b for a, b in zip(gains, s)]
    payback = None
    cum = 0.0
    cumulative = []
    for y in range(years + 1):
        cum += gains[y] - per_year[y]
        cumulative.append(cum)
        if payback is None and any(gains) and cum >= 0:
            payback = y
    return {"years": years, "build": build, "indexation": idx, "run": rows, "end_of_life": eol_amount,
            "per_year": per_year, "run_total": run_total, "tco": tco,
            "run_share": run_total / tco if tco else 0.0, "alternatives": alternatives,
            "gains": gains if any(gains) else None, "cumulative_net": cumulative if any(gains) else None,
            "payback_year": payback,
            "roi": (sum(gains) - tco) / tco if any(gains) and tco else None}


# ── Pitch ───────────────────────────────────────────────────────────────────

def check_pitch(text: str, c: Check):
    heads = [key(line.lstrip("#")) for line in text.splitlines() if line.startswith("#")]
    for words, label in PITCH_SECTIONS:
        if not any(w in h for h in heads for w in words.split()):
            c.warn("pitch.md", f"no heading for {label}")
    words = len(text.split())
    if words > 2500:
        c.warn("pitch.md", f"{words} words — too long for a 10-minute defence and its Q&A")


# ── Report ──────────────────────────────────────────────────────────────────

def fr(x: float, dec: int = 1) -> str:
    return f"{x:,.{dec}f}".replace(",", " ").replace(".", ",")


def pc(x: float) -> str:
    return f"{round(x * 100)} %"


def eur(x: float) -> str:
    return fr(x, 0) + " €"


def report(S: dict, W: dict, wbs: dict) -> str:
    E, B, T = S.get("estimation"), S.get("budget"), S.get("tco")
    out = [f"# Chiffrage — {wbs.get('project', '')}".rstrip(" —"), "",
           f"_Calculé par chiffrage.py le {dt.date.today().isoformat()} à partir de chiffrage/*.json. "
           "Ne pas modifier ce fichier : corriger les JSON et relancer._", ""]
    if E:
        d = E["duration"]
        out += ["## En bref", "", "| | |", "|---|---|",
                f"| Charge attendue (P50) | {fr(E['expected'])} jh |",
                f"| Engagement (P{round(E['confidence'] * 100)}) | {fr(E['commit'])} jh |",
                f"| Délai P80 | {fr(d['monte_carlo']['p80'])} jours ouvrés"
                + (f", fin le {d['finish_p80']}" if d.get("finish_p80") else "") + " |"]
        if B:
            out.append(f"| Prix {B['pricing']} HT | {eur(B['price_ht'])} (sans provision : {eur(B['price_p50_ht'])}) |")
        if T:
            out.append(f"| TCO {T['years']} ans | {eur(T['tco'])} (run : {pc(T['run_share'])}) |")
        out.append("")

        out += ["## 1. WBS et estimation PERT (jours-homme)", "",
                "| Lot | Livrable | O | M | P | Dp | σ |", "|---|---|--:|--:|--:|--:|--:|"]
        for r in E["packages"]:
            tag = " *(indirect)*" if r["kind"] == "indirect" else ""
            out.append(f"| {r['id']} {r['title']}{tag} | {r['deliverable']} | {fr(r['o'])} | {fr(r['m'])} | "
                       f"{fr(r['p'])} | **{fr(r['expected'])}** | {fr(r['sigma'], 2)} |")
        out.append(f"| **Lots de travaux** | | | | | **{fr(E['leaves_expected'])}** | "
                   f"{fr(math.sqrt(sum(r['sigma'] ** 2 for r in E['packages'])), 2)} |")
        for oh in E["overheads"]:
            out.append(f"| {oh['label']} ({pc(oh['rate'])}) | | | | | {fr(oh['effort'])} | |")
        out += [f"| **Total** | | | | | **{fr(E['expected'])}** | {fr(E['sigma'], 2)} |", "",
                f"Dp = (O + 4M + P) / 6 · σ = (P − O) / 6 · σ total = √Σσ² · développement pur : "
                f"{pc(E['dev_share'])} de la charge.", ""]

        mc = E["monte_carlo"]
        out += ["## 2. Une estimation est une probabilité", "",
                f"| | Loi normale (PERT) | Monte Carlo ({fr(mc['runs'], 0)} tirages, loi bêta) |",
                "|---|--:|--:|",
                f"| P50 | {fr(E['expected'])} jh | {fr(mc['p50'])} jh |",
                f"| P80 | {fr(E['p80'])} jh | {fr(mc['p80'])} jh |",
                f"| P90 | {fr(E['p90'])} jh | {fr(mc['p90'])} jh |", ""]
        if E["cone"]:
            cn = E["cone"]
            out += [f"Cône d'incertitude, phase « {cn['label']} » : × {fr(cn['low'], 2)} à × {fr(cn['high'], 2)}, "
                    f"soit {fr(cn['range'][0])} à {fr(cn['range'][1])} jh autour du P50. Les lots sont supposés "
                    "indépendants : en réalité leurs erreurs vont dans le même sens, la vraie fourchette est "
                    "plus large que le PERT.", ""]

        if E["cross_checks"]:
            out += ["## 3. Méthodes croisées", "", "| Méthode | Charge | Écart / PERT | Calcul |",
                    "|---|--:|--:|---|"]
            for r in E["cross_checks"]:
                rng = f" ({fr(r['range'][0], 0)}–{fr(r['range'][1], 0)})" if r.get("range") else ""
                out.append(f"| {r['method']} | {fr(r['effort'])} jh{rng} | × {fr(r['ratio'], 2)} | {r['detail']} |")
            out.append("")

        out += ["## 4. Délai et chemin critique", "",
                f"- Chemin critique (ressources illimitées) : {' → '.join(d['critical_path'])} — "
                f"{fr(d['cpm_days'])} jours ouvrés."]
        if d["workload_days"]:
            out.append(f"- Charge des lots ÷ équipe de {fr(E['team'], 0)} : {fr(d['workload_days'])} jours ouvrés.")
        out.append(f"- Délai Monte Carlo : P50 {fr(d['monte_carlo']['p50'])} j · P80 {fr(d['monte_carlo']['p80'])} j"
                   f" · P90 {fr(d['monte_carlo']['p90'])} j.")
        if d.get("start"):
            out.append(f"- Début le {d['start']} → fin P50 le {d['finish_p50']}, P80 le {d['finish_p80']} "
                       "(jours fériés non comptés).")
        if d["slack"]:
            out.append("- Marges : " + ", ".join(f"{i} {fr(s)} j" for i, s in sorted(
                d["slack"].items(), key=lambda kv: idkey(kv[0]))) + ".")
        out.append("")

    if B:
        out += [f"## 5. Budget ({B['pricing']})", "", "| Poste | Jours | Taux | Montant |", "|---|--:|--:|--:|"]
        for p in B["profiles"]:
            if p["jh"]:
                out.append(f"| {p['title']} | {fr(p['jh'])} | {eur(p['rate'])} | {eur(p['cost'])} |")
        out.append(f"| **Équipe** | {fr(B['labour_jh'])} | {eur(B['average_rate'])} | **{eur(B['labour'])}** |")
        for x in B["costs"]:
            out.append(f"| {x['label']} ({x['category']}) | | | {eur(x['amount'])} |")
        out += [f"| Provision pour risques — {B['contingency_basis']} | | | {eur(B['contingency'])} |",
                f"| Réserve de gestion ({pc(B['management_reserve_rate'])}) | | | {eur(B['management_reserve'])} |",
                f"| **Coût total** | | | **{eur(B['cost_total'])}** |",
                f"| Marge ({pc(B['margin_rate'])}) | | | {eur(B['margin'])} |",
                f"| **Prix HT** | | | **{eur(B['price_ht'])}** |",
                f"| TVA ({pc(B['vat_rate'])}) | | | {eur(B['vat'])} |",
                f"| **Prix TTC** | | | **{eur(B['price_ttc'])}** |", ""]
        if B["schedule"]:
            out += ["Échéancier : " + " · ".join(f"{s['label']} {pc(s['share'])} = {eur(s['amount'])} HT"
                                                 for s in B["schedule"]), ""]

    if T:
        ys = range(T["years"] + 1)
        out += [f"## 6. TCO sur {T['years']} ans", "",
                "| Poste | " + " | ".join(f"An {y}" for y in ys) + " | Total |",
                "|---|" + "--:|" * (T["years"] + 2),
                f"| Build | {eur(T['build'])} | " + " | ".join("" for _ in range(T["years"])) + f" | {eur(T['build'])} |"]
        for r in T["run"]:
            out.append(f"| {r['label']} | | " + " | ".join(eur(r["years"][y]) for y in ys if y)
                       + f" | {eur(r['total'])} |")
        if T["end_of_life"]:
            out.append(f"| Fin de vie / réversibilité | " + " | ".join("" for _ in range(T["years"]))
                       + f" | {eur(T['end_of_life'])} | {eur(T['end_of_life'])} |")
        out += ["| **Total** | " + " | ".join(f"**{eur(v)}**" for v in T["per_year"]) + f" | **{eur(T['tco'])}** |",
                "", f"Run : {eur(T['run_total'])} sur {T['years']} ans, {pc(T['run_share'])} du TCO.", ""]
        for a in T["alternatives"]:
            diff = a["total"] - T["tco"]
            out.append(f"- Alternative « {a['label']} » : {eur(a['total'])} sur {T['years']} ans "
                       f"({'+' if diff >= 0 else '−'}{eur(abs(diff))} par rapport au projet).")
        if T["gains"]:
            out.append(f"- Gains : {eur(sum(T['gains']))} sur {T['years']} ans · ROI {pc(T['roi'])} · "
                       + (f"retour sur investissement l'année {T['payback_year']}." if T["payback_year"] is not None
                          else f"pas rentabilisé en {T['years']} ans."))
        out.append("")

    for title, k in (("Hypothèses", "assumptions"), ("Exclusions", "exclusions")):
        if wbs.get(k):
            out += [f"## {title}", ""] + [f"- {x}" for x in wbs[k]] + [""]
    return "\n".join(out)


# ── Main ────────────────────────────────────────────────────────────────────

def rounded(x):
    if isinstance(x, float):
        return round(x, 2)
    if isinstance(x, dict):
        return {k: rounded(v) for k, v in x.items()}
    if isinstance(x, list):
        return [rounded(v) for v in x]
    return x


def compute(root: Path, c: Check) -> tuple[dict, dict | None, dict | None]:
    d = root / "chiffrage"
    files = {n: load(d / f"{n}.json", c) for n in ("wbs", "estimation", "budget", "tco")}
    backlog = load(root / "scrum" / "product-backlog.json", c)
    S: dict = {}
    W = read_wbs(files["wbs"], backlog, c) if files["wbs"] is not None else None
    if files["wbs"] is None and any(files[n] is not None for n in ("estimation", "budget", "tco")):
        c.err("wbs.json", "missing — every other file is built on the WBS")
    E = B = T = None
    if W and files["estimation"] is not None:
        E = compute_estimation(files["estimation"], W, backlog, c)
    elif files["budget"] is not None:
        c.err("budget.json", "needs estimation.json")
    if E and files["budget"] is not None:
        B = compute_budget(files["budget"], E, W, c)
    if files["tco"] is not None:
        T = compute_tco(files["tco"], B, c)
    if (d / "pitch.md").is_file():
        check_pitch((d / "pitch.md").read_text(encoding="utf-8"), c)
    for k, v in (("estimation", E), ("budget", B), ("tco", T)):
        if v:
            S[k] = v
    return S, W, files["wbs"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Compute and check the chiffrage of a project folder.")
    ap.add_argument("project", help="folder holding chiffrage/")
    ap.add_argument("--check", action="store_true", help="validate only; exit 1 on any error")
    ap.add_argument("--json", action="store_true", help="print the computed summary as JSON")
    a = ap.parse_args(argv)
    root = Path(a.project).resolve()
    if not (root / "chiffrage").is_dir():
        print(f"ERROR   no chiffrage/ folder in {root}")
        return 1
    c = Check()
    S, W, wbs = compute(root, c)
    written = []
    if not a.check and not c.errors and W:
        (root / "chiffrage" / "synthese.json").write_text(
            json.dumps(rounded(S), ensure_ascii=False, indent=1), encoding="utf-8")
        (root / "livrables").mkdir(exist_ok=True)
        (root / "livrables" / "chiffrage.md").write_text(report(S, W, wbs), encoding="utf-8")
        written = ["chiffrage/synthese.json", "livrables/chiffrage.md"]
    if a.json:
        print(json.dumps({"errors": c.errors, "warnings": c.warnings, "written": written,
                          "summary": rounded(S)}, ensure_ascii=False, indent=1))
        return 1 if c.errors else 0
    for e in c.errors:
        print(f"ERROR   {e}")
    for w in c.warnings:
        print(f"WARN    {w}")
    E, B, T = S.get("estimation"), S.get("budget"), S.get("tco")
    if E and not a.check:
        print(f"Charge P50 {fr(E['expected'])} jh · engagement P{round(E['confidence'] * 100)} "
              f"{fr(E['commit'])} jh · délai P80 {fr(E['duration']['monte_carlo']['p80'])} j ouvrés")
    if B and not a.check:
        print(f"Prix HT {eur(B['price_ht'])} (sans provision {eur(B['price_p50_ht'])})")
    if T and not a.check:
        print(f"TCO {T['years']} ans {eur(T['tco'])}")
    if written:
        print("Written: " + ", ".join(written))
    elif not a.check and c.errors:
        print("Nothing written: fix the errors first.")
    print(f"{len(c.errors)} error(s), {len(c.warnings)} warning(s)")
    return 1 if c.errors else 0


if __name__ == "__main__":
    sys.exit(main())
