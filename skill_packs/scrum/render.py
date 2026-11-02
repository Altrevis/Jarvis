#!/usr/bin/env python3
"""Scrum deliverables renderer. Standard library only, no network.

Reads the JSON files the scrum-* skills write in <project>/scrum/ and draws
every deliverable as self-contained HTML with inline SVG in <project>/livrables/:

    python3 render.py <project>            # draw everything that exists
    python3 render.py <project> --check    # validate only: exit 1 on any error
    python3 render.py <project> --json     # draw, then print counts as JSON

Why a renderer instead of letting the agent write the HTML: an SVG diagram is
ten times the tokens of the JSON it shows, it would look different on every
run, and moving one story would mean redrawing the page. The agent writes the
data; this draws it, the same way every time, in a few milliseconds.

Files (all optional; each skill's SKILL.md holds the shape of what it writes):

    meta.json               name, description, vision, lang (fr | en)
    bete-a-cornes.json      need statement, APTE method
    pieuvre.json            interaction diagram: elements, FP and FC functions
    swot.json               strengths, weaknesses, opportunities, threats
    parties-prenantes.json  internal and external stakeholders, power/interest
    raci.json               roles x activities
    discovery.json          personas, hypotheses, questions, experiments
    product-backlog.json    epics, user stories, DoR, DoD
    sprints.json            sprint goals, committed stories, tasks, burndown
    risques.json            risk register, probability x impact
    planning.json           Gantt items, milestones, ceremonies
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import math
import sys
from pathlib import Path

# (page stem = json stem, the step of the pipeline that writes it)
ORDER = (
    ("bete-a-cornes", "cadrage"),
    ("pieuvre", "cadrage"),
    ("swot", "cadrage"),
    ("parties-prenantes", "parties-prenantes"),
    ("raci", "parties-prenantes"),
    ("discovery", "discovery"),
    ("product-backlog", "backlog"),
    ("sprints", "sprint"),
    ("risques", "risques"),
    ("planning", "planning"),
)

FIB = {0, 0.5, 1, 2, 3, 5, 8, 13, 20, 40, 100}
PRIORITIES = ("must", "should", "could", "wont")
STORY_STATUS = ("todo", "ready", "doing", "done")
TASK_STATUS = ("todo", "doing", "done")
DISCOVERY_STATUS = ("todo", "doing", "validated", "invalidated")
DISCOVERY_TYPES = ("hypothesis", "question", "research", "experiment", "spike")
PALETTE = ("#2563eb", "#7c3aed", "#db2777", "#ea580c", "#16a34a", "#0891b2",
           "#ca8a04", "#4f46e5", "#be123c", "#0d9488")

LABELS = {
    "fr": {
        "bete-a-cornes": "Bête à cornes", "pieuvre": "Diagramme pieuvre",
        "swot": "Matrice SWOT", "parties-prenantes": "Parties prenantes",
        "raci": "Matrice RACI", "discovery": "Discovery backlog",
        "product-backlog": "Product backlog", "sprints": "Sprint backlog",
        "risques": "Gestion des risques", "planning": "Planning",
        "lead.bete-a-cornes": "Expression du besoin — méthode APTE",
        "lead.pieuvre": "Analyse fonctionnelle — fonctions principales (FP) et contraintes (FC)",
        "lead.swot": "Analyse stratégique — facteurs internes et externes",
        "lead.parties-prenantes": "Cartographie pouvoir / intérêt (Mendelow)",
        "lead.raci": "Qui réalise, qui approuve, qui est consulté, qui est informé",
        "lead.discovery": "Ce qu'il faut apprendre avant de construire",
        "lead.product-backlog": "Epics, user stories et priorités",
        "lead.sprints": "Objectif, engagement et tâches du sprint",
        "lead.risques": "Registre des risques — probabilité × impact",
        "lead.planning": "Phases, sprints, jalons et cérémonies",
        "serves": "À qui le produit rend-il service ?", "acts_on": "Sur quoi agit-il ?",
        "purpose": "Dans quel but ?", "statement": "Énoncé du besoin",
        "why": "Pourquoi ce besoin existe-t-il ?",
        "change": "Qu'est-ce qui pourrait le faire évoluer ?",
        "end": "Qu'est-ce qui pourrait le faire disparaître ?",
        "FP": "Fonction principale", "FC": "Fonction contrainte", "code": "Code",
        "type": "Type", "function": "Fonction", "criteria": "Critère",
        "level": "Niveau", "flex": "Flexibilité", "elements": "Éléments du milieu extérieur",
        "S": "Forces", "W": "Faiblesses", "O": "Opportunités", "T": "Menaces",
        "internal_origin": "Origine interne", "external_origin": "Origine externe",
        "helpful": "Positif", "harmful": "Négatif",
        "strategies": "Stratégies croisées (TOWS)", "SO": "Forces × Opportunités",
        "ST": "Forces × Menaces", "WO": "Faiblesses × Opportunités",
        "WT": "Faiblesses × Menaces",
        "internal": "Internes", "external": "Externes", "power": "Influence",
        "interest": "Intérêt", "q_manage": "Gérer étroitement", "q_satisfy": "Satisfaire",
        "q_inform": "Tenir informé", "q_monitor": "Surveiller", "name": "Nom",
        "role": "Rôle", "expectations": "Attentes", "strategy": "Communication",
        "attitude": "Attitude", "supporter": "Favorable", "neutral": "Neutre",
        "resistant": "Réticent",
        "R": "Réalise", "A": "Approuve — rend des comptes", "C": "Consulté",
        "I": "Informé", "activity": "Activité", "control": "Contrôle",
        "one_a": "un seul A requis", "no_r": "aucun R",
        "goal": "Objectif de la discovery", "personas": "Personas", "goals": "Objectifs",
        "pains": "Frustrations", "d.todo": "À explorer", "d.doing": "En cours",
        "d.validated": "Validé", "d.invalidated": "Invalidé",
        "hypothesis": "Hypothèse", "question": "Question", "research": "Recherche",
        "experiment": "Expérience", "spike": "Spike", "outcome": "Résultat",
        "leads_to": "Mène à",
        "product_goal": "Objectif produit", "epics": "Epics", "story_map": "Story map",
        "stories": "User stories", "as": "En tant que", "want": "je veux",
        "so_that": "afin de", "acceptance": "Critères d'acceptation",
        "priority": "Priorité", "value": "Valeur", "points": "Points", "status": "Statut",
        "sprint": "Sprint", "dor": "Definition of Ready", "dod": "Definition of Done",
        "must": "Must", "should": "Should", "could": "Could", "wont": "Won't",
        "s.todo": "À faire", "s.ready": "Prête", "s.doing": "En cours", "s.done": "Terminée",
        "no_epic": "Sans epic", "done_pct": "fait",
        "sprint_goal": "Objectif du sprint", "dates": "Dates", "capacity": "Capacité",
        "committed": "Engagé", "tasks": "Tâches", "t.todo": "À faire", "t.doing": "En cours",
        "t.done": "Terminé", "burndown": "Burndown", "ideal": "Idéal", "actual": "Réel",
        "remaining": "Points restants", "day": "Jour", "overview": "Vue d'ensemble des sprints",
        "velocity": "Vélocité", "over": "au-dessus de la capacité", "owner": "Responsable",
        "other_sprints": "Sprints suivants",
        "risk": "Risque", "category": "Catégorie", "cause": "Cause",
        "consequence": "Conséquence", "probability": "Probabilité", "impact": "Impact",
        "criticality": "Criticité", "prevention": "Prévention", "contingency": "Plan de secours",
        "c.low": "Faible", "c.medium": "Moyen", "c.high": "Élevé", "c.critical": "Critique",
        "p1": "Très rare", "p2": "Rare", "p3": "Possible", "p4": "Probable", "p5": "Quasi certain",
        "i1": "Négligeable", "i2": "Mineur", "i3": "Modéré", "i4": "Majeur", "i5": "Critique",
        "milestones": "Jalons", "ceremonies": "Cérémonies", "ceremony": "Cérémonie",
        "when": "Fréquence", "duration": "Durée", "who": "Participants",
        "purpose_col": "Objectif", "today": "Aujourd'hui", "week": "S",
        "sprints_group": "Sprints", "item": "Tâche", "start": "Début", "end_col": "Fin",
        "dashboard": "Tableau de bord", "generated": "Généré le",
        "missing": "Pas encore produit", "step": "étape", "back": "← Tableau de bord",
        "k.epics": "Epics", "k.stories": "User stories", "k.points": "Story points",
        "k.sprints": "Sprints", "k.critical": "Risques critiques",
        "k.stakeholders": "Parties prenantes", "vision": "Vision produit",
        "deliverables": "Livrables", "error": "Ce livrable n'a pas pu être dessiné",
    },
    "en": {
        "bete-a-cornes": "Horned beast diagram", "pieuvre": "Octopus diagram",
        "swot": "SWOT matrix", "parties-prenantes": "Stakeholders",
        "raci": "RACI matrix", "discovery": "Discovery backlog",
        "product-backlog": "Product backlog", "sprints": "Sprint backlog",
        "risques": "Risk management", "planning": "Schedule",
        "lead.bete-a-cornes": "Need statement — APTE method",
        "lead.pieuvre": "Functional analysis — main functions (FP) and constraints (FC)",
        "lead.swot": "Strategic analysis — internal and external factors",
        "lead.parties-prenantes": "Power / interest grid (Mendelow)",
        "lead.raci": "Who does it, who approves, who is consulted, who is informed",
        "lead.discovery": "What must be learned before building",
        "lead.product-backlog": "Epics, user stories and priorities",
        "lead.sprints": "Sprint goal, commitment and tasks",
        "lead.risques": "Risk register — probability × impact",
        "lead.planning": "Phases, sprints, milestones and ceremonies",
        "serves": "Whom does it serve?", "acts_on": "What does it act on?",
        "purpose": "For what purpose?", "statement": "Need statement",
        "why": "Why does this need exist?", "change": "What could make it change?",
        "end": "What could make it disappear?",
        "FP": "Main function", "FC": "Constraint", "code": "Code", "type": "Type",
        "function": "Function", "criteria": "Criterion", "level": "Level",
        "flex": "Flexibility", "elements": "Elements of the environment",
        "S": "Strengths", "W": "Weaknesses", "O": "Opportunities", "T": "Threats",
        "internal_origin": "Internal", "external_origin": "External",
        "helpful": "Helpful", "harmful": "Harmful",
        "strategies": "Cross strategies (TOWS)", "SO": "Strengths × Opportunities",
        "ST": "Strengths × Threats", "WO": "Weaknesses × Opportunities",
        "WT": "Weaknesses × Threats",
        "internal": "Internal", "external": "External", "power": "Power",
        "interest": "Interest", "q_manage": "Manage closely", "q_satisfy": "Keep satisfied",
        "q_inform": "Keep informed", "q_monitor": "Monitor", "name": "Name", "role": "Role",
        "expectations": "Expectations", "strategy": "Communication", "attitude": "Attitude",
        "supporter": "Supporter", "neutral": "Neutral", "resistant": "Resistant",
        "R": "Responsible", "A": "Accountable", "C": "Consulted", "I": "Informed",
        "activity": "Activity", "control": "Check", "one_a": "exactly one A needed",
        "no_r": "no R",
        "goal": "Discovery goal", "personas": "Personas", "goals": "Goals",
        "pains": "Pains", "d.todo": "To explore", "d.doing": "In progress",
        "d.validated": "Validated", "d.invalidated": "Invalidated",
        "hypothesis": "Hypothesis", "question": "Question", "research": "Research",
        "experiment": "Experiment", "spike": "Spike", "outcome": "Outcome",
        "leads_to": "Leads to",
        "product_goal": "Product goal", "epics": "Epics", "story_map": "Story map",
        "stories": "User stories", "as": "As", "want": "I want", "so_that": "so that",
        "acceptance": "Acceptance criteria", "priority": "Priority", "value": "Value",
        "points": "Points", "status": "Status", "sprint": "Sprint",
        "dor": "Definition of Ready", "dod": "Definition of Done",
        "must": "Must", "should": "Should", "could": "Could", "wont": "Won't",
        "s.todo": "To do", "s.ready": "Ready", "s.doing": "In progress", "s.done": "Done",
        "no_epic": "No epic", "done_pct": "done",
        "sprint_goal": "Sprint goal", "dates": "Dates", "capacity": "Capacity",
        "committed": "Committed", "tasks": "Tasks", "t.todo": "To do",
        "t.doing": "In progress", "t.done": "Done", "burndown": "Burndown",
        "ideal": "Ideal", "actual": "Actual", "remaining": "Points remaining",
        "day": "Day", "overview": "All sprints", "velocity": "Velocity",
        "over": "over capacity", "owner": "Owner", "other_sprints": "Next sprints",
        "risk": "Risk", "category": "Category", "cause": "Cause",
        "consequence": "Consequence", "probability": "Probability", "impact": "Impact",
        "criticality": "Score", "prevention": "Prevention", "contingency": "Contingency",
        "c.low": "Low", "c.medium": "Medium", "c.high": "High", "c.critical": "Critical",
        "p1": "Very rare", "p2": "Rare", "p3": "Possible", "p4": "Likely",
        "p5": "Almost certain", "i1": "Negligible", "i2": "Minor", "i3": "Moderate",
        "i4": "Major", "i5": "Severe",
        "milestones": "Milestones", "ceremonies": "Ceremonies", "ceremony": "Ceremony",
        "when": "When", "duration": "Duration", "who": "Who", "purpose_col": "Purpose",
        "today": "Today", "week": "W", "sprints_group": "Sprints", "item": "Item",
        "start": "Start", "end_col": "End",
        "dashboard": "Dashboard", "generated": "Generated on",
        "missing": "Not produced yet", "step": "step", "back": "← Dashboard",
        "k.epics": "Epics", "k.stories": "User stories", "k.points": "Story points",
        "k.sprints": "Sprints", "k.critical": "Critical risks",
        "k.stakeholders": "Stakeholders", "vision": "Product vision",
        "deliverables": "Deliverables", "error": "This deliverable could not be drawn",
    },
}

CSS = """
:root{--ink:#172033;--muted:#5b6b7d;--line:#dde3ec;--bg:#f4f6fa;--panel:#fff;--accent:#2563eb;--soft:#eef3fb}
*{box-sizing:border-box}
html,body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 "Inter","Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;-webkit-print-color-adjust:exact;print-color-adjust:exact}
a{color:var(--accent);text-decoration:none}
.top{background:#0f172a;color:#e2e8f0;padding:20px 36px;display:flex;gap:24px;align-items:flex-end;justify-content:space-between}
.top h1{margin:0;font-size:22px;color:#fff}
.top .sub{color:#94a3b8;font-size:13px;margin-top:2px}
.top .back{color:#93c5fd;font-size:13px;white-space:nowrap}
nav.pills{display:flex;flex-wrap:wrap;gap:8px;padding:12px 36px;background:#fff;border-bottom:1px solid var(--line);position:sticky;top:0;z-index:2}
nav.pills a{padding:4px 12px;border-radius:999px;background:var(--soft);font-size:13px;color:#1e3a8a}
nav.pills a.off{background:#f1f5f9;color:#94a3b8}
main{padding:4px 0 30px}
.art{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:24px 30px;margin:22px 36px}
.art>h2{margin:0;font-size:20px}
.art>.lead{margin:2px 0 18px;color:var(--muted);font-size:13px}
.figure{background:#fff}
svg.diagram{display:block;width:100%;height:auto;max-height:80vh;margin:0 auto;font-family:inherit}
h3{font-size:15px;margin:24px 0 10px}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{border-bottom:1px solid var(--line);padding:7px 9px;text-align:left;vertical-align:top}
th{background:#f8fafc;color:#334155;font-weight:600;font-size:11.5px;text-transform:uppercase;letter-spacing:.3px}
.chip{display:inline-block;padding:0 8px;border-radius:999px;font-size:11.5px;font-weight:600;line-height:19px;white-space:nowrap}
.grid{display:grid;gap:14px}
.cards{grid-template-columns:repeat(auto-fit,minmax(240px,1fr))}
.card{border:1px solid var(--line);border-radius:12px;padding:14px 16px;background:#fff}
.card h4{margin:0 0 6px;font-size:12px;color:var(--muted);font-weight:600;text-transform:uppercase;letter-spacing:.4px}
.muted{color:var(--muted)}.small{font-size:12px}
ul.tight{margin:4px 0 0;padding-left:18px}ul.tight li{margin:2px 0}
.banner{background:var(--soft);border-radius:12px;padding:12px 16px;margin-bottom:16px}
.banner b{color:#1e3a8a}
.swot{display:grid;grid-template-columns:30px 1fr 1fr;gap:10px}
.swot .ax{font-size:11.5px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.6px;text-align:center;align-self:end}
.swot .side{writing-mode:vertical-rl;transform:rotate(180deg);align-self:center}
.swot .q{border-radius:14px;padding:16px 18px;min-height:180px}
.swot .q h3{margin:0 0 6px;font-size:17px;display:flex;align-items:center;gap:10px}
.swot .q h3 b{display:inline-grid;place-items:center;width:30px;height:30px;border-radius:8px;color:#fff;font-size:16px}
.q.s{background:#ecfdf3;border:1px solid #bbf7d0}.q.s h3 b{background:#16a34a}
.q.w{background:#fff7ed;border:1px solid #fed7aa}.q.w h3 b{background:#ea580c}
.q.o{background:#eff6ff;border:1px solid #bfdbfe}.q.o h3 b{background:#2563eb}
.q.t{background:#fef2f2;border:1px solid #fecaca}.q.t h3 b{background:#dc2626}
.board{display:grid;grid-template-columns:repeat(var(--cols),minmax(200px,1fr));gap:12px;align-items:start;overflow-x:auto}
.col{background:#f1f5f9;border-radius:12px;padding:10px;min-height:80px}
.col>h4{margin:2px 4px 10px;font-size:11.5px;text-transform:uppercase;letter-spacing:.5px;color:#475569;display:flex;justify-content:space-between;gap:8px}
.col>h4 i{font-style:normal;color:#64748b}
.ticket{background:#fff;border:1px solid var(--line);border-left:4px solid var(--c,#94a3b8);border-radius:9px;padding:8px 11px;margin-bottom:8px;font-size:12.5px;box-shadow:0 1px 2px rgba(15,23,42,.05)}
.ticket .id{font-weight:700;font-size:11px;color:#475569;display:flex;justify-content:space-between;gap:6px;align-items:center}
.ticket .t{font-weight:600;margin:3px 0;line-height:1.35}
.ticket .meta{color:var(--muted);font-size:11.5px;display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin-top:4px}
.ticket.done{opacity:.55}
.raci td.c{text-align:center}.raci th.c{text-align:center}
.raci tr.phase td{background:#f8fafc;font-weight:700;color:#334155;font-size:12px;text-transform:uppercase;letter-spacing:.4px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:22px 36px}
.kpi{background:#fff;border:1px solid var(--line);border-radius:14px;padding:14px 16px}
.kpi b{display:block;font-size:26px;line-height:1.2}
.kpi span{color:var(--muted);font-size:11.5px;text-transform:uppercase;letter-spacing:.4px}
.bar{height:8px;background:#e2e8f0;border-radius:99px;overflow:hidden;margin-top:6px}.bar i{display:block;height:100%;background:var(--accent)}
.bar.over i{background:#dc2626}
.missing{border:1px dashed #cbd5e1;border-radius:12px;padding:18px;color:#64748b;background:#f8fafc}
.sprinthead{display:grid;grid-template-columns:2fr 1fr 1fr;gap:14px;margin-bottom:14px}
.split{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:18px}
footer{color:#94a3b8;font-size:12px;text-align:center;padding:6px 0 26px}
@page{size:A4 landscape;margin:9mm}
@media print{html,body{background:#fff}nav.pills,.top .back{display:none}.art{margin:0;border:none;padding:0 2mm;break-before:page}.kpis{margin:6mm 0}main{padding:0}svg.diagram{max-height:122mm}.board{overflow:visible}footer{display:none}
h2,h3,.lead,.banner{break-after:avoid}svg.diagram,.card,.ticket,.sprinthead,tr,.swot .q{break-inside:avoid}thead{display:table-header-group}}
"""


# ── Small helpers ────────────────────────────────────────────────────────────

def esc(v) -> str:
    return html.escape("" if v is None else str(v), quote=True)


def as_list(v) -> list:
    if isinstance(v, list):
        return v
    if v in (None, "", {}):
        return []
    return [v]


def txt(v) -> str:
    if isinstance(v, dict):
        return str(v.get("text") or v.get("title") or v.get("label") or "")
    return "" if v is None else str(v)


def num(v, default=None):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return int(f) if f.is_integer() else f


def pdate(v) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


def fmt_date(d: dt.date | None) -> str:
    return d.strftime("%d/%m/%Y") if d else ""


def wrap(text: str, width: int) -> list[str]:
    width = max(4, int(width))
    lines, cur = [], ""
    for w in str(text or "").split():
        while len(w) > width:
            if cur:
                lines.append(cur)
                cur = ""
            lines.append(w[:width - 1] + "-")
            w = w[width - 1:]
        if not cur:
            cur = w
        elif len(cur) + 1 + len(w) <= width:
            cur += " " + w
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def svg_text(x, y, text, width_px, size=14, anchor="middle", weight=400,
             fill="#172033", max_lines=4, valign="middle") -> str:
    """Wrapped SVG text. `y` is the centre of the block (valign middle) or the
    first line's centre (valign top)."""
    lines = wrap(text, width_px / (size * 0.56))
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(" .,;:")[: max(1, int(width_px / (size * 0.56)) - 1)] + "…"
    lh = size * 1.25
    y0 = y - (len(lines) - 1) * lh / 2 if valign == "middle" else y
    spans = "".join(f'<tspan x="{x:.1f}" y="{y0 + i * lh:.1f}">{esc(s)}</tspan>'
                    for i, s in enumerate(lines))
    return (f'<text text-anchor="{anchor}" dominant-baseline="central" font-size="{size}" '
            f'font-weight="{weight}" fill="{fill}">{spans}</text>')


def chip(text, bg, fg="#fff") -> str:
    return f'<span class="chip" style="background:{bg};color:{fg}">{esc(text)}</span>'


def ul(items) -> str:
    items = [txt(i) for i in as_list(items) if txt(i).strip()]
    return "<ul class=\"tight\">" + "".join(f"<li>{esc(i)}</li>" for i in items) + "</ul>" if items else ""


def working_days(a: dt.date, b: dt.date) -> list[dt.date]:
    out, d = [], a
    while d <= b and len(out) < 400:
        if d.weekday() < 5:
            out.append(d)
        d += dt.timedelta(days=1)
    return out


PRIO_COLOR = {"must": "#dc2626", "should": "#ea580c", "could": "#2563eb", "wont": "#94a3b8"}
STATUS_COLOR = {"todo": "#94a3b8", "ready": "#0891b2", "doing": "#ca8a04", "done": "#16a34a"}


def crit_class(score: float) -> tuple[str, str]:
    if score >= 15:
        return "c.critical", "#dc2626"
    if score >= 10:
        return "c.high", "#ea580c"
    if score >= 5:
        return "c.medium", "#eab308"
    return "c.low", "#16a34a"


# ── Context: what was read, what is wrong ────────────────────────────────────

class Ctx:
    def __init__(self, root: Path):
        self.root = root
        self.dir = root / "scrum"
        self.meta: dict = {}
        self.data: dict[str, dict] = {}
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.lang = "fr"

    def t(self, key: str) -> str:
        return LABELS[self.lang].get(key) or LABELS["en"].get(key) or key

    def err(self, stem: str, msg: str) -> None:
        self.errors.append(f"{stem}.json: {msg}")

    def warn(self, stem: str, msg: str) -> None:
        self.warnings.append(f"{stem}.json: {msg}")

    def _read(self, stem: str) -> dict | None:
        path = self.dir / f"{stem}.json"
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            self.err(stem, f"not valid JSON ({e})")
            return None
        if not isinstance(data, dict):
            self.err(stem, "must be a JSON object { ... }")
            return None
        return data

    def load(self) -> None:
        self.meta = self._read("meta") or {}
        # Labels exist in French and English; any other language reads English.
        self.lang = "fr" if str(self.meta.get("lang") or "fr").lower().startswith("fr") else "en"
        for stem, _ in ORDER:
            d = self._read(stem)
            if d is not None:
                self.data[stem] = d

    # Lookups other files rely on
    def stories(self) -> dict[str, dict]:
        return {str(s.get("id")): s for s in as_list(self.data.get("product-backlog", {}).get("stories"))
                if isinstance(s, dict) and s.get("id")}

    def epic_colors(self) -> dict[str, str]:
        epics = [e for e in as_list(self.data.get("product-backlog", {}).get("epics")) if isinstance(e, dict)]
        return {str(e.get("id")): str(e.get("color") or PALETTE[i % len(PALETTE)])
                for i, e in enumerate(epics)}


# ── Checks ───────────────────────────────────────────────────────────────────

def _ids(c: Ctx, stem: str, items: list, what: str) -> set[str]:
    seen: set[str] = set()
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            c.err(stem, f"{what}[{i}] must be an object")
            continue
        iid = str(it.get("id") or "").strip()
        if not iid:
            c.err(stem, f"{what}[{i}] has no id")
        elif iid in seen:
            c.err(stem, f"{what} id {iid!r} is used twice")
        seen.add(iid)
    return seen


def check_bete(d, c, s="bete-a-cornes"):
    for k in ("product", "serves", "acts_on", "purpose"):
        if not str(d.get(k) or "").strip():
            c.err(s, f"missing {k!r}")
    if not isinstance(d.get("validation"), dict):
        c.warn(s, "no 'validation' {why, change, end}: the need is not validated")


def check_pieuvre(d, c, s="pieuvre"):
    if not str(d.get("product") or "").strip():
        c.err(s, "missing 'product'")
    els = as_list(d.get("elements"))
    ids = _ids(c, s, els, "elements")
    if len(els) < 3:
        c.warn(s, "fewer than 3 elements of the environment")
    if len(els) > 12:
        c.warn(s, "more than 12 elements: the diagram gets unreadable, merge some")
    fns = as_list(d.get("functions"))
    _ids(c, s, fns, "functions")
    fp = 0
    for f in fns:
        if not isinstance(f, dict):
            continue
        kind = str(f.get("type") or "").upper()
        links = [str(x) for x in as_list(f.get("links"))]
        fid = f.get("id")
        if kind not in ("FP", "FC"):
            c.err(s, f"function {fid}: type must be FP or FC")
            continue
        fp += kind == "FP"
        need = 2 if kind == "FP" else 1
        if len(links) != need:
            c.err(s, f"function {fid}: an {kind} links exactly {need} element(s), not {len(links)}")
        for x in links:
            if x not in ids:
                c.err(s, f"function {fid}: unknown element {x!r}")
        if not str(f.get("text") or "").strip():
            c.err(s, f"function {fid}: missing 'text'")
    if not fp:
        c.err(s, "no FP: a product exists for at least one main function")


def check_swot(d, c, s="swot"):
    keys = ("strengths", "weaknesses", "opportunities", "threats")
    if not any(as_list(d.get(k)) for k in keys):
        c.err(s, "all four lists are empty")
    for k in keys:
        if not as_list(d.get(k)):
            c.warn(s, f"{k} is empty")


def check_stakeholders(d, c, s="parties-prenantes"):
    items = as_list(d.get("stakeholders"))
    if not items:
        c.err(s, "no 'stakeholders'")
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            c.err(s, f"stakeholders[{i}] must be an object")
            continue
        name = it.get("name") or f"#{i}"
        if not it.get("name"):
            c.err(s, f"stakeholders[{i}] has no name")
        if it.get("side") not in ("internal", "external"):
            c.err(s, f"{name}: side must be internal or external")
        for k in ("power", "interest"):
            v = num(it.get(k))
            if v is None or not 1 <= v <= 5:
                c.err(s, f"{name}: {k} must be a number from 1 to 5")
            elif v == 3:
                c.warn(s, f"{name}: {k} 3 sits on the quadrant line — pick a side (2.5 or 3.5 are fine)")


def _letters(v) -> str:
    return "".join(ch for ch in str(v or "").upper() if ch in "RACI")


def check_raci(d, c, s="raci"):
    roles = as_list(d.get("roles"))
    ids = _ids(c, s, roles, "roles")
    acts = as_list(d.get("activities"))
    if not acts:
        c.err(s, "no 'activities'")
    for i, a in enumerate(acts):
        if not isinstance(a, dict):
            c.err(s, f"activities[{i}] must be an object")
            continue
        name = a.get("task") or f"#{i}"
        cells = a.get("raci") if isinstance(a.get("raci"), dict) else {}
        if not cells:
            c.err(s, f"{name}: missing 'raci' {{role_id: letters}}")
        for rid, v in cells.items():
            if rid not in ids:
                c.err(s, f"{name}: unknown role {rid!r}")
            bad = [ch for ch in str(v).upper() if ch.isalpha() and ch not in "RACI"]
            if bad:
                c.err(s, f"{name}: {v!r} — only R, A, C, I are allowed")
        letters = "".join(_letters(v) for v in cells.values())
        if letters.count("A") != 1:
            c.err(s, f"{name}: exactly one A, found {letters.count('A')}")
        if "R" not in letters:
            c.err(s, f"{name}: nobody is R")


def check_discovery(d, c, s="discovery"):
    items = as_list(d.get("items"))
    if not items:
        c.err(s, "no 'items'")
    _ids(c, s, items, "items")
    for it in items:
        if not isinstance(it, dict):
            continue
        if it.get("type") not in DISCOVERY_TYPES:
            c.err(s, f"{it.get('id')}: type must be one of {', '.join(DISCOVERY_TYPES)}")
        if it.get("status", "todo") not in DISCOVERY_STATUS:
            c.err(s, f"{it.get('id')}: status must be one of {', '.join(DISCOVERY_STATUS)}")
        if not str(it.get("title") or "").strip():
            c.err(s, f"{it.get('id')}: missing 'title'")


def check_backlog(d, c, s="product-backlog"):
    epics = as_list(d.get("epics"))
    eids = _ids(c, s, epics, "epics")
    stories = as_list(d.get("stories"))
    if not stories:
        c.err(s, "no 'stories'")
    _ids(c, s, stories, "stories")
    for st in stories:
        if not isinstance(st, dict):
            continue
        sid = st.get("id")
        if st.get("epic") and str(st.get("epic")) not in eids:
            c.err(s, f"{sid}: unknown epic {st.get('epic')!r}")
        for k in ("as", "want", "so_that"):
            if not str(st.get(k) or "").strip():
                c.err(s, f"{sid}: missing {k!r} (En tant que / je veux / afin de)")
        p = num(st.get("points"))
        if st.get("points") is not None and p not in FIB:
            c.err(s, f"{sid}: points {st.get('points')!r} is not on the scale 0 ½ 1 2 3 5 8 13 20 40 100")
        if p is not None and p > 13:
            c.warn(s, f"{sid}: {p} points is too big for one sprint — split it")
        if st.get("priority") not in PRIORITIES:
            c.err(s, f"{sid}: priority must be one of {', '.join(PRIORITIES)}")
        if st.get("status", "todo") not in STORY_STATUS:
            c.err(s, f"{sid}: status must be one of {', '.join(STORY_STATUS)}")
        if not as_list(st.get("acceptance")):
            c.warn(s, f"{sid}: no acceptance criteria")


def check_sprints(d, c, s="sprints"):
    sprints = as_list(d.get("sprints"))
    if not sprints:
        c.err(s, "no 'sprints'")
    _ids(c, s, sprints, "sprints")
    known = c.stories()
    for sp in sprints:
        if not isinstance(sp, dict):
            continue
        sid = sp.get("id")
        a, b = sp.get("start"), sp.get("end")
        if (a and not pdate(a)) or (b and not pdate(b)):
            c.err(s, f"{sid}: dates must be YYYY-MM-DD")
        elif pdate(a) and pdate(b) and pdate(a) > pdate(b):
            c.err(s, f"{sid}: start is after end")
        for st in as_list(sp.get("stories")):
            if known and str(st) not in known:
                c.err(s, f"{sid}: story {st!r} is not in product-backlog.json")
        sp_stories = {str(x) for x in as_list(sp.get("stories"))}
        for t in as_list(sp.get("tasks")):
            if not isinstance(t, dict):
                c.err(s, f"{sid}: every task must be an object")
                continue
            if t.get("status", "todo") not in TASK_STATUS:
                c.err(s, f"{sid}: task {t.get('title')!r} status must be todo, doing or done")
            if t.get("story") and str(t.get("story")) not in sp_stories:
                c.warn(s, f"{sid}: task {t.get('title')!r} belongs to {t.get('story')}, not in this sprint")
        committed = sum(num(known.get(str(x), {}).get("points"), 0) or 0 for x in sp_stories)
        cap = num(sp.get("capacity"))
        if cap and committed > cap:
            c.warn(s, f"{sid}: {committed} points committed for a capacity of {cap}")


def check_risks(d, c, s="risques"):
    risks = as_list(d.get("risks"))
    if not risks:
        c.err(s, "no 'risks'")
    _ids(c, s, risks, "risks")
    for r in risks:
        if not isinstance(r, dict):
            continue
        rid = r.get("id")
        for k in ("probability", "impact"):
            v = num(r.get(k))
            if v is None or not 1 <= v <= 5:
                c.err(s, f"{rid}: {k} must be a number from 1 to 5")
        if not r.get("owner"):
            c.warn(s, f"{rid}: no owner")
        score = (num(r.get("probability"), 0) or 0) * (num(r.get("impact"), 0) or 0)
        if score >= 10 and not r.get("prevention"):
            c.warn(s, f"{rid}: score {score} and no prevention")


def check_planning(d, c, s="planning"):
    items = as_list(d.get("items"))
    if not items and not as_list(d.get("milestones")):
        c.err(s, "no 'items' and no 'milestones'")
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            c.err(s, f"items[{i}] must be an object")
            continue
        a, b = pdate(it.get("start")), pdate(it.get("end"))
        if not a or not b:
            c.err(s, f"{it.get('label') or i}: start and end must be YYYY-MM-DD")
        elif a > b:
            c.err(s, f"{it.get('label') or i}: start is after end")
    for m in as_list(d.get("milestones")):
        if not isinstance(m, dict) or not pdate(m.get("date")):
            c.err(s, f"milestone {txt(m)!r}: date must be YYYY-MM-DD")


CHECKS = {"bete-a-cornes": check_bete, "pieuvre": check_pieuvre, "swot": check_swot,
          "parties-prenantes": check_stakeholders, "raci": check_raci,
          "discovery": check_discovery, "product-backlog": check_backlog,
          "sprints": check_sprints, "risques": check_risks, "planning": check_planning}


# ── Drawings. Each returns (figure html, details html) ───────────────────────

def _arrow_defs(mid: str, color="#334155") -> str:
    return (f'<defs><marker id="{mid}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
            f'markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" '
            f'fill="{color}"/></marker></defs>')


def draw_bete(d, c):
    W, H = 900, 530
    s = [f'<svg viewBox="0 0 {W} {H}" class="diagram" role="img">', _arrow_defs("arr-bete")]
    s.append('<path d="M190,152 C190,392 710,392 710,152" fill="none" stroke="#334155" stroke-width="3"/>')
    s.append('<line x1="450" y1="332" x2="450" y2="402" stroke="#334155" stroke-width="3" marker-end="url(#arr-bete)"/>')
    for x, key, val in ((40, "serves", d.get("serves")), (560, "acts_on", d.get("acts_on"))):
        s.append(f'<text x="{x + 150}" y="22" text-anchor="middle" font-size="13" font-weight="600" fill="#5b6b7d">{esc(c.t(key))}</text>')
        s.append(f'<rect x="{x}" y="36" width="300" height="116" rx="14" fill="#eff6ff" stroke="#93c5fd" stroke-width="2"/>')
        s.append(svg_text(x + 150, 94, val, 270, size=16, weight=600))
    s.append('<ellipse cx="450" cy="240" rx="180" ry="54" fill="#1d4ed8"/>')
    s.append(svg_text(450, 240, d.get("product"), 300, size=18, weight=700, fill="#fff", max_lines=2))
    s.append(f'<text x="464" y="372" font-size="13" font-weight="600" fill="#5b6b7d">{esc(c.t("purpose"))}</text>')
    s.append('<rect x="190" y="410" width="520" height="104" rx="14" fill="#fef3c7" stroke="#fbbf24" stroke-width="2"/>')
    s.append(svg_text(450, 462, d.get("purpose"), 490, size=16, weight=600))
    s.append("</svg>")

    v = d.get("validation") if isinstance(d.get("validation"), dict) else {}
    details = ""
    if d.get("statement"):
        details += f'<div class="banner"><b>{esc(c.t("statement"))} —</b> {esc(d["statement"])}</div>'
    cards = "".join(f'<div class="card"><h4>{esc(c.t(k))}</h4>{esc(v.get(k))}</div>'
                    for k in ("why", "change", "end") if v.get(k))
    if cards:
        details += f'<div class="grid cards">{cards}</div>'
    return "".join(s), details


def draw_pieuvre(d, c):
    els = [e for e in as_list(d.get("elements")) if isinstance(e, dict) and e.get("id")]
    fns = [f for f in as_list(d.get("functions")) if isinstance(f, dict)]
    W, H, cx, cy, rx, ry = 1000, 660, 500, 330, 125, 52
    n = max(1, len(els))
    pos = {}
    for i, e in enumerate(els):
        a = -math.pi / 2 + 2 * math.pi * i / n
        pos[str(e["id"])] = (cx + 385 * math.cos(a), cy + 255 * math.sin(a))

    def near_product(x, y, margin=16):
        return ((x - cx) / (rx + margin)) ** 2 + ((y - cy) / (ry + margin)) ** 2 < 1

    placed: list[tuple[float, float]] = []

    def free(x, y):
        return not near_product(x, y) and all(math.hypot(x - px, y - py) > 40 for px, py in placed)

    lines, labels, seen_pairs = [], [], {}
    for f in fns:
        kind = str(f.get("type") or "").upper()
        links = [str(x) for x in as_list(f.get("links"))]
        code = esc(f.get("id") or "")
        if kind == "FP" and len(links) == 2 and all(x in pos for x in links):
            (ax, ay), (bx, by) = pos[links[0]], pos[links[1]]
            key = tuple(sorted(links))
            k = seen_pairs[key] = seen_pairs.get(key, -1) + 1
            # An FP goes from one element to the other THROUGH the product:
            # both control points sit close to its centre. A second FP between
            # the same pair is pushed aside so the two stay distinguishable.
            nx, ny = -(by - ay), bx - ax
            norm = math.hypot(nx, ny) or 1
            ox, oy = nx / norm * 34 * k, ny / norm * 34 * k
            c1 = (cx + (ax - cx) * 0.22 + ox, cy + (ay - cy) * 0.22 + oy)
            c2 = (cx + (bx - cx) * 0.22 + ox, cy + (by - cy) * 0.22 + oy)
            lines.append(f'<path d="M{ax:.0f},{ay:.0f} C{c1[0]:.0f},{c1[1]:.0f} {c2[0]:.0f},{c2[1]:.0f} '
                         f'{bx:.0f},{by:.0f}" fill="none" stroke="#2563eb" stroke-width="2.6"/>')

            def at(t):
                u = 1 - t
                return (u ** 3 * ax + 3 * u * u * t * c1[0] + 3 * u * t * t * c2[0] + t ** 3 * bx,
                        u ** 3 * ay + 3 * u * u * t * c1[1] + 3 * u * t * t * c2[1] + t ** 3 * by)
            # Label just outside the product, on whichever side is free.
            exits = [t / 100 for t in range(50, 95, 3) if not near_product(*at(t / 100))][:1]
            exits += [t / 100 for t in range(50, 5, -3) if not near_product(*at(t / 100))][:1]
            spot = next((at(t) for t in exits + [0.8, 0.2, 0.7, 0.3, 0.88, 0.12] if free(*at(t))),
                        at(exits[0]) if exits else at(0.25))
            placed.append(spot)
            labels.append((*spot, code, "#2563eb"))
        elif kind == "FC" and len(links) == 1 and links[0] in pos:
            ex, ey = pos[links[0]]
            lines.append(f'<line x1="{cx}" y1="{cy}" x2="{ex:.0f}" y2="{ey:.0f}" stroke="#ea580c" '
                         f'stroke-width="2.2" stroke-dasharray="7 5"/>')
            spot = next(((cx + (ex - cx) * t, cy + (ey - cy) * t) for t in (0.6, 0.5, 0.7)
                         if free(cx + (ex - cx) * t, cy + (ey - cy) * t)),
                        (cx + (ex - cx) * 0.6, cy + (ey - cy) * 0.6))
            placed.append(spot)
            labels.append((*spot, code, "#ea580c"))
    s = [f'<svg viewBox="0 0 {W} {H}" class="diagram" role="img">', *lines]
    s.append(f'<ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry}" fill="#1d4ed8"/>')
    s.append(svg_text(cx, cy, d.get("product"), 210, size=17, weight=700, fill="#fff", max_lines=2))
    for e in els:
        ex, ey = pos[str(e["id"])]
        s.append(f'<rect x="{ex - 92:.0f}" y="{ey - 32:.0f}" width="184" height="64" rx="32" '
                 f'fill="#fff" stroke="#334155" stroke-width="2"/>')
        s.append(svg_text(ex, ey, e.get("label") or e["id"], 160, size=13, weight=600, max_lines=3))
    for lx, ly, code, color in labels:
        w = 12 + 8 * len(code)
        s.append(f'<rect x="{lx - w / 2:.0f}" y="{ly - 11:.0f}" width="{w}" height="22" rx="11" fill="{color}"/>')
        s.append(f'<text x="{lx:.0f}" y="{ly:.0f}" text-anchor="middle" dominant-baseline="central" '
                 f'font-size="12" font-weight="700" fill="#fff">{code}</text>')
    s.append(f'<g font-size="12" fill="#5b6b7d"><line x1="24" y1="{H - 40}" x2="64" y2="{H - 40}" stroke="#2563eb" stroke-width="2.6"/>'
             f'<text x="72" y="{H - 36}">FP — {esc(c.t("FP"))}</text>'
             f'<line x1="24" y1="{H - 18}" x2="64" y2="{H - 18}" stroke="#ea580c" stroke-width="2.2" stroke-dasharray="7 5"/>'
             f'<text x="72" y="{H - 14}">FC — {esc(c.t("FC"))}</text></g>')
    s.append("</svg>")
    label_of = {str(e["id"]): str(e.get("label") or e["id"]) for e in els}
    rows = []
    for f in sorted(fns, key=lambda f: (str(f.get("type", "")).upper() != "FP", str(f.get("id", "")))):
        kind = str(f.get("type") or "").upper()
        between = " ↔ ".join(label_of.get(str(x), str(x)) for x in as_list(f.get("links")))
        color = "#2563eb" if kind == "FP" else "#ea580c"
        rows.append(f"<tr><td>{chip(f.get('id', ''), color)}</td><td>{esc(f.get('text'))}"
                    f"<div class='small muted'>{esc(between)}</div></td><td>{esc(f.get('criteria'))}</td>"
                    f"<td>{esc(f.get('level'))}</td><td>{esc(f.get('flexibility'))}</td></tr>")
    details = (f"<table><thead><tr><th>{esc(c.t('code'))}</th><th>{esc(c.t('function'))}</th>"
               f"<th>{esc(c.t('criteria'))}</th><th>{esc(c.t('level'))}</th>"
               f"<th>{esc(c.t('flex'))}</th></tr></thead>{''.join(rows)}</table>") if rows else ""
    return "".join(s), details


def draw_swot(d, c):
    def quad(cls, letter, key):
        return (f'<div class="q {cls}"><h3><b>{letter}</b>{esc(c.t(letter))}</h3>'
                f'{ul(d.get(key))}</div>')
    fig = (f'<div class="swot"><div></div><div class="ax">{esc(c.t("helpful"))}</div>'
           f'<div class="ax">{esc(c.t("harmful"))}</div>'
           f'<div class="ax side">{esc(c.t("internal_origin"))}</div>'
           f'{quad("s", "S", "strengths")}{quad("w", "W", "weaknesses")}'
           f'<div class="ax side">{esc(c.t("external_origin"))}</div>'
           f'{quad("o", "O", "opportunities")}{quad("t", "T", "threats")}</div>')
    st = d.get("strategies") if isinstance(d.get("strategies"), dict) else {}
    cards = "".join(f'<div class="card"><h4>{esc(c.t(k))}</h4>{ul(st.get(k))}</div>'
                    for k in ("SO", "ST", "WO", "WT") if as_list(st.get(k)))
    details = f'<h3>{esc(c.t("strategies"))}</h3><div class="grid cards">{cards}</div>' if cards else ""
    return fig, details


def draw_stakeholders(d, c):
    items = [s for s in as_list(d.get("stakeholders")) if isinstance(s, dict)]
    W, H, x0, y0, pw, ph = 760, 560, 70, 20, 660, 480

    def place(v):
        v = max(1.0, min(5.0, float(num(v, 3) or 3)))
        return 0.07 + (v - 1) / 4 * 0.86
    s = [f'<svg viewBox="0 0 {W} {H}" class="diagram" role="img">']
    quads = (("q_satisfy", x0, y0, "#fff7ed"), ("q_manage", x0 + pw / 2, y0, "#fef2f2"),
             ("q_monitor", x0, y0 + ph / 2, "#f8fafc"), ("q_inform", x0 + pw / 2, y0 + ph / 2, "#eff6ff"))
    for key, qx, qy, fill in quads:
        s.append(f'<rect x="{qx}" y="{qy}" width="{pw / 2}" height="{ph / 2}" fill="{fill}" stroke="#dde3ec"/>')
        s.append(f'<text x="{qx + pw / 4}" y="{qy + 22}" text-anchor="middle" font-size="13" '
                 f'font-weight="700" fill="#64748b" letter-spacing="1">{esc(c.t(key).upper())}</text>')
    s.append(f'<text x="{x0 + pw / 2}" y="{y0 + ph + 30}" text-anchor="middle" font-size="13" '
             f'font-weight="600" fill="#334155">{esc(c.t("interest"))} →</text>')
    s.append(f'<text transform="translate({x0 - 30},{y0 + ph / 2}) rotate(-90)" text-anchor="middle" '
             f'font-size="13" font-weight="600" fill="#334155">{esc(c.t("power"))} →</text>')
    groups: dict[tuple, list] = {}
    for it in items:
        groups.setdefault((num(it.get("power"), 3), num(it.get("interest"), 3)), []).append(it)
    dots, boxes = [], []                      # boxes: (x1, y1, x2, y2) of placed labels
    for (pw_v, in_v), members in groups.items():
        bx = x0 + place(in_v) * pw
        by = y0 + ph - place(pw_v) * ph
        for k, it in enumerate(members):
            if len(members) > 1:
                a = 2 * math.pi * k / len(members)
                dots.append((bx + 22 * math.cos(a), by + 22 * math.sin(a), it))
            else:
                dots.append((bx, by, it))
    taken = [(px - 9, py - 9, px + 9, py + 9) for px, py, _ in dots]
    for px, py, it in dots:
        color = "#2563eb" if it.get("side") == "internal" else "#ea580c"
        name = str(it.get("name", ""))[:26]
        w = 6.9 * len(name) + 4
        # Right, left, above, below: the first spot that hits no dot, no label
        # and stays inside the grid.
        options = ((px + 12, py, "start", (px + 12, py - 8, px + 12 + w, py + 8)),
                   (px - 12, py, "end", (px - 12 - w, py - 8, px - 12, py + 8)),
                   (px, py - 18, "middle", (px - w / 2, py - 26, px + w / 2, py - 10)),
                   (px, py + 18, "middle", (px - w / 2, py + 10, px + w / 2, py + 26)))

        def clear(b):
            return (b[0] >= x0 and b[2] <= x0 + pw and b[1] >= y0 and b[3] <= y0 + ph
                    and not any(b[0] < o[2] and o[0] < b[2] and b[1] < o[3] and o[1] < b[3]
                                for o in taken + boxes if o != (px - 9, py - 9, px + 9, py + 9)))
        lx, ly, anchor, box = next((o for o in options if clear(o[3])), options[0])
        boxes.append(box)
        s.append(f'<circle cx="{px:.0f}" cy="{py:.0f}" r="8" fill="{color}" stroke="#fff" stroke-width="2"/>')
        s.append(f'<text x="{lx:.0f}" y="{ly:.0f}" dominant-baseline="central" text-anchor="{anchor}" '
                 f'font-size="12" font-weight="600" fill="#172033">{esc(name)}</text>')
    s.append(f'<g font-size="12" fill="#334155"><circle cx="{x0 + 8}" cy="{H - 14}" r="6" fill="#2563eb"/>'
             f'<text x="{x0 + 20}" y="{H - 10}">{esc(c.t("internal"))}</text>'
             f'<circle cx="{x0 + 110}" cy="{H - 14}" r="6" fill="#ea580c"/>'
             f'<text x="{x0 + 122}" y="{H - 10}">{esc(c.t("external"))}</text></g>')
    s.append("</svg>")
    att_color = {"supporter": "#16a34a", "neutral": "#64748b", "resistant": "#dc2626"}
    details = ""
    for side in ("internal", "external"):
        rows = [it for it in items if it.get("side") == side]
        if not rows:
            continue
        rows.sort(key=lambda it: -((num(it.get("power"), 0) or 0) + (num(it.get("interest"), 0) or 0)))
        body = "".join(
            f"<tr><td><b>{esc(it.get('name'))}</b></td><td>{esc(it.get('role'))}</td>"
            f"<td>{esc(it.get('power'))}/5</td><td>{esc(it.get('interest'))}/5</td>"
            f"<td>{chip(c.t(str(it.get('attitude'))), att_color[it['attitude']]) if it.get('attitude') in att_color else ''}</td>"
            f"<td>{esc(it.get('expectations'))}</td><td>{esc(it.get('strategy'))}</td></tr>" for it in rows)
        details += (f"<h3>{esc(c.t(side))}</h3><table><thead><tr><th>{esc(c.t('name'))}</th><th>{esc(c.t('role'))}</th>"
                    f"<th>{esc(c.t('power'))}</th><th>{esc(c.t('interest'))}</th><th>{esc(c.t('attitude'))}</th>"
                    f"<th>{esc(c.t('expectations'))}</th><th>{esc(c.t('strategy'))}</th></tr></thead>{body}</table>")
    return "".join(s), details


RACI_COLOR = {"R": "#2563eb", "A": "#dc2626", "C": "#ca8a04", "I": "#64748b"}


def draw_raci(d, c):
    roles = [r for r in as_list(d.get("roles")) if isinstance(r, dict) and r.get("id")]
    acts = [a for a in as_list(d.get("activities")) if isinstance(a, dict)]
    head = "".join(f"<th class='c'>{esc(r.get('label') or r['id'])}"
                   f"<div class='small muted' style='text-transform:none;letter-spacing:0'>{esc(r.get('name') or '')}</div></th>"
                   for r in roles)
    rows, phase = [], None
    for a in acts:
        if a.get("phase") and a.get("phase") != phase:
            phase = a.get("phase")
            rows.append(f"<tr class='phase'><td colspan='{len(roles) + 2}'>{esc(phase)}</td></tr>")
        cells = a.get("raci") if isinstance(a.get("raci"), dict) else {}
        tds = "".join("<td class='c'>" + " ".join(chip(ch, RACI_COLOR[ch]) for ch in _letters(cells.get(r["id"])))
                      + "</td>" for r in roles)
        letters = "".join(_letters(v) for v in cells.values())
        problems = []
        if letters.count("A") != 1:
            problems.append(c.t("one_a"))
        if "R" not in letters:
            problems.append(c.t("no_r"))
        ok = "<span style='color:#16a34a'>✓</span>" if not problems else \
            f"<span class='small' style='color:#dc2626'>⚠ {esc(', '.join(problems))}</span>"
        rows.append(f"<tr><td>{esc(a.get('task'))}</td>{tds}<td class='c'>{ok}</td></tr>")
    legend = " &nbsp; ".join(f"{chip(k, v)} {esc(c.t(k))}" for k, v in RACI_COLOR.items())
    fig = (f"<table class='raci'><thead><tr><th>{esc(c.t('activity'))}</th>{head}<th class='c'>{esc(c.t('control'))}</th></tr></thead>"
           f"{''.join(rows)}</table><p class='small muted' style='margin-top:12px'>{legend}</p>")
    return fig, ""


def draw_discovery(d, c):
    items = [i for i in as_list(d.get("items")) if isinstance(i, dict)]
    type_color = {"hypothesis": "#7c3aed", "question": "#0891b2", "research": "#2563eb",
                  "experiment": "#db2777", "spike": "#ca8a04"}
    cols = []
    for st in DISCOVERY_STATUS:
        cards = []
        for it in (i for i in items if i.get("status", "todo") == st):
            color = type_color.get(it.get("type"), "#64748b")
            extra = ""
            if it.get("outcome"):
                extra += f"<div class='meta'><b>{esc(c.t('outcome'))} :</b> {esc(it['outcome'])}</div>"
            if as_list(it.get("leads_to")):
                extra += f"<div class='meta'>{esc(c.t('leads_to'))} → {esc(', '.join(map(str, as_list(it['leads_to']))))}</div>"
            cards.append(f"<div class='ticket{' done' if st == 'invalidated' else ''}' style='--c:{color}'>"
                         f"<div class='id'>{esc(it.get('id'))} {chip(c.t(str(it.get('type'))), color)}</div>"
                         f"<div class='t'>{esc(it.get('title'))}</div>"
                         f"<div class='small muted'>{esc(it.get('detail') or '')}</div>{extra}</div>")
        cols.append(f"<div class='col'><h4>{esc(c.t('d.' + st))}<i>{len(cards)}</i></h4>{''.join(cards)}</div>")
    goal = f"<div class='banner'><b>{esc(c.t('goal'))} —</b> {esc(d['goal'])}</div>" if d.get("goal") else ""
    fig = f"{goal}<div class='board' style='--cols:4'>{''.join(cols)}</div>"
    personas = [p for p in as_list(d.get("personas")) if isinstance(p, dict)]
    details = ""
    if personas:
        cards = "".join(
            f"<div class='card'><b style='font-size:15px'>{esc(p.get('name'))}</b>"
            f"<div class='small muted'>{esc(p.get('role') or '')}</div>"
            f"{'<p class=small>' + esc(p['quote']) + '</p>' if p.get('quote') else ''}"
            f"<h4 style='margin-top:10px'>{esc(c.t('goals'))}</h4>{ul(p.get('goals'))}"
            f"<h4 style='margin-top:10px'>{esc(c.t('pains'))}</h4>{ul(p.get('pains'))}</div>" for p in personas)
        details = f"<h3>{esc(c.t('personas'))}</h3><div class='grid cards'>{cards}</div>"
    return fig, details


def _story_line(st, c) -> str:
    return (f"<b>{esc(c.t('as'))}</b> {esc(st.get('as'))}, <b>{esc(c.t('want'))}</b> "
            f"{esc(st.get('want'))} <b>{esc(c.t('so_that'))}</b> {esc(st.get('so_that'))}")


def draw_backlog(d, c):
    epics = [e for e in as_list(d.get("epics")) if isinstance(e, dict)]
    stories = [s for s in as_list(d.get("stories")) if isinstance(s, dict)]
    colors = c.epic_colors()
    order = {p: i for i, p in enumerate(PRIORITIES)}
    columns = [(str(e.get("id")), e.get("title") or e.get("id"), colors.get(str(e.get("id")), "#64748b"))
               for e in epics]
    if any(str(s.get("epic") or "") not in colors for s in stories):
        columns.append(("", c.t("no_epic"), "#64748b"))
    cols = []
    for eid, title, color in columns:
        mine = [s for s in stories if str(s.get("epic") or "") == eid
                or (eid == "" and str(s.get("epic") or "") not in colors)]
        mine.sort(key=lambda s: order.get(s.get("priority"), 9))
        pts = sum(num(s.get("points"), 0) or 0 for s in mine)
        cards = "".join(
            f"<div class='ticket{' done' if s.get('status') == 'done' else ''}' style='--c:{color}'>"
            f"<div class='id'>{esc(s.get('id'))}{'<span>✓</span>' if s.get('status') == 'done' else ''}</div>"
            f"<div class='t'>{esc(s.get('title') or s.get('want'))}</div><div class='meta'>"
            f"{chip(c.t(str(s.get('priority'))), PRIO_COLOR.get(s.get('priority'), '#64748b'))}"
            f"{chip(str(num(s.get('points'), '?')) + ' pts', '#e2e8f0', '#172033')}"
            f"{chip(s['sprint'], '#f1f5f9', '#334155') if s.get('sprint') else ''}</div></div>" for s in mine)
        cols.append(f"<div class='col' style='border-top:4px solid {color}'><h4>{esc(title)}<i>{pts} pts</i></h4>{cards}</div>")
    goal = (f"<div class='banner'><b>{esc(c.t('product_goal'))} —</b> {esc(d['product_goal'])}</div>"
            if d.get("product_goal") else "")
    fig = (f"{goal}<div class='board' style='--cols:{max(1, len(cols))}'>{''.join(cols)}</div>")

    ecards = []
    for e in epics:
        mine = [s for s in stories if str(s.get("epic")) == str(e.get("id"))]
        pts = sum(num(s.get("points"), 0) or 0 for s in mine)
        done = sum(num(s.get("points"), 0) or 0 for s in mine if s.get("status") == "done")
        pct = round(100 * done / pts) if pts else 0
        color = colors.get(str(e.get("id")), "#64748b")
        ecards.append(f"<div class='card' style='border-left:5px solid {color}'>"
                      f"<div class='small muted'><b>{esc(e.get('id'))}</b></div><b style='font-size:15px'>{esc(e.get('title'))}</b>"
                      f"<div class='small'>{esc(e.get('description') or '')}</div>"
                      f"<div class='small muted' style='margin-top:6px'>{len(mine)} stories · {pts} pts · {pct}% {esc(c.t('done_pct'))}</div>"
                      f"<div class='bar'><i style='width:{pct}%;background:{color}'></i></div></div>")
    rows = "".join(
        f"<tr><td><b>{esc(s.get('id'))}</b><div class='small muted'>{esc(s.get('epic') or '')}</div></td>"
        f"<td><div style='font-weight:600'>{esc(s.get('title') or '')}</div><div class='small'>{_story_line(s, c)}</div></td>"
        f"<td class='small'>{ul(s.get('acceptance'))}</td>"
        f"<td>{chip(c.t(str(s.get('priority'))), PRIO_COLOR.get(s.get('priority'), '#64748b'))}</td>"
        f"<td>{esc(s.get('value') if s.get('value') is not None else '')}</td><td><b>{esc(num(s.get('points'), ''))}</b></td>"
        f"<td>{chip(c.t('s.' + str(s.get('status', 'todo'))), STATUS_COLOR.get(s.get('status', 'todo'), '#64748b'))}</td>"
        f"<td>{esc(s.get('sprint') or '')}</td></tr>" for s in stories)
    details = (f"<h3>{esc(c.t('epics'))}</h3><div class='grid cards'>{''.join(ecards)}</div>" if ecards else "")
    details += (f"<h3>{esc(c.t('stories'))}</h3><table><thead><tr><th>ID</th><th>User story</th>"
                f"<th>{esc(c.t('acceptance'))}</th><th>{esc(c.t('priority'))}</th><th>{esc(c.t('value'))}</th>"
                f"<th>{esc(c.t('points'))}</th><th>{esc(c.t('status'))}</th><th>{esc(c.t('sprint'))}</th></tr></thead>{rows}</table>")
    dor, dod = as_list(d.get("definition_of_ready")), as_list(d.get("definition_of_done"))
    if dor or dod:
        details += (f"<div class='split' style='margin-top:18px'><div class='card'><h4>{esc(c.t('dor'))}</h4>{ul(dor)}</div>"
                    f"<div class='card'><h4>{esc(c.t('dod'))}</h4>{ul(dod)}</div></div>")
    return fig, details


def _burndown(sp, committed, c) -> str:
    a, b = pdate(sp.get("start")), pdate(sp.get("end"))
    actual = [num(v) for v in as_list(sp.get("burndown")) if num(v) is not None]
    days = len(working_days(a, b)) if a and b and a <= b else max(len(actual), 10)
    days = max(days, len(actual), 2)
    W, H, x0, y0, pw, ph = 560, 260, 46, 14, 494, 200
    step = max(1, math.ceil(max([committed] + actual + [1]) / 4))   # whole-point ticks
    top = step * 4
    X = lambda i: x0 + pw * i / max(1, days - 1)
    Y = lambda v: y0 + ph - ph * v / top
    s = [f'<svg viewBox="0 0 {W} {H}" class="diagram" role="img" style="max-width:560px">']
    for k in range(5):
        v = step * k
        s.append(f'<line x1="{x0}" x2="{x0 + pw}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="#e2e8f0"/>'
                 f'<text x="{x0 - 8}" y="{Y(v):.1f}" text-anchor="end" dominant-baseline="central" font-size="11" fill="#64748b">{v}</text>')
    for i in range(days):
        if days <= 15 or i % 2 == 0:
            s.append(f'<text x="{X(i):.1f}" y="{y0 + ph + 16}" text-anchor="middle" font-size="11" fill="#64748b">{i + 1}</text>')
    s.append(f'<line x1="{X(0):.1f}" y1="{Y(committed):.1f}" x2="{X(days - 1):.1f}" y2="{Y(0):.1f}" '
             f'stroke="#94a3b8" stroke-width="2" stroke-dasharray="6 5"/>')
    if actual:
        pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(actual))
        s.append(f'<polyline points="{pts}" fill="none" stroke="#2563eb" stroke-width="3"/>')
        s += [f'<circle cx="{X(i):.1f}" cy="{Y(v):.1f}" r="3.5" fill="#2563eb"/>' for i, v in enumerate(actual)]
    s.append(f'<g font-size="11.5" fill="#334155"><line x1="{x0 + 8}" x2="{x0 + 32}" y1="{H - 12}" y2="{H - 12}" stroke="#94a3b8" stroke-width="2" stroke-dasharray="6 5"/>'
             f'<text x="{x0 + 38}" y="{H - 8}">{esc(c.t("ideal"))}</text>'
             f'<line x1="{x0 + 110}" x2="{x0 + 134}" y1="{H - 12}" y2="{H - 12}" stroke="#2563eb" stroke-width="3"/>'
             f'<text x="{x0 + 140}" y="{H - 8}">{esc(c.t("actual"))}</text>'
             f'<text x="{x0 + pw}" y="{H - 8}" text-anchor="end" fill="#64748b">{esc(c.t("remaining"))} / {esc(c.t("day"))}</text></g>')
    s.append("</svg>")
    return "".join(s)


def _sprint_block(sp, c, stories, colors) -> str:
    ids = [str(x) for x in as_list(sp.get("stories"))]
    committed = sum(num(stories.get(x, {}).get("points"), 0) or 0 for x in ids) or (num(sp.get("committed"), 0) or 0)
    cap = num(sp.get("capacity"), 0) or 0
    pct = min(100, round(100 * committed / cap)) if cap else 0
    over = cap and committed > cap
    a, b = pdate(sp.get("start")), pdate(sp.get("end"))
    head = (f"<div class='sprinthead'><div class='card'><h4>{esc(c.t('sprint_goal'))}</h4>"
            f"<b style='font-size:15px'>{esc(sp.get('goal') or '—')}</b></div>"
            f"<div class='card'><h4>{esc(c.t('dates'))}</h4>{fmt_date(a)} → {fmt_date(b)}</div>"
            f"<div class='card'><h4>{esc(c.t('committed'))} / {esc(c.t('capacity'))}</h4>"
            f"<b style='font-size:18px'>{committed}</b> / {cap or '?'} pts"
            f"{' <span class=small style=color:#dc2626>' + esc(c.t('over')) + '</span>' if over else ''}"
            f"<div class='bar{' over' if over else ''}'><i style='width:{pct}%'></i></div></div></div>")
    tasks = [t for t in as_list(sp.get("tasks")) if isinstance(t, dict)]
    cols = []
    for st in TASK_STATUS:
        mine = [t for t in tasks if t.get("status", "todo") == st]
        hours = sum(num(t.get("hours"), 0) or 0 for t in mine)
        cards = []
        for t in mine:
            sid = str(t.get("story") or "")
            color = colors.get(str(stories.get(sid, {}).get("epic")), "#64748b")
            cards.append(f"<div class='ticket{' done' if st == 'done' else ''}' style='--c:{color}'>"
                         f"<div class='id'>{esc(sid)}<span>{esc(num(t.get('hours'), ''))}{'h' if t.get('hours') else ''}</span></div>"
                         f"<div class='t'>{esc(t.get('title'))}</div>"
                         f"<div class='meta'>{('👤 ' + esc(t['owner'])) if t.get('owner') else ''}</div></div>")
        cols.append(f"<div class='col'><h4>{esc(c.t('t.' + st))}<i>{len(mine)} · {hours}h</i></h4>{''.join(cards)}</div>")
    stories_list = "".join(
        f"<div class='ticket' style='--c:{colors.get(str(stories.get(x, {}).get('epic')), '#64748b')}'>"
        f"<div class='id'>{esc(x)}<span>{esc(num(stories.get(x, {}).get('points'), '?'))} pts</span></div>"
        f"<div class='t'>{esc(stories.get(x, {}).get('title') or stories.get(x, {}).get('want') or '')}</div></div>"
        for x in ids)
    stories_col = (f"<div class='col' style='background:#eef3fb'><h4>{esc(c.t('stories'))}<i>{len(ids)}</i></h4>"
                   f"{stories_list}</div>")
    board = f"<div class='board' style='--cols:4'>{stories_col}{''.join(cols)}</div>"
    burn = (f"<h3>{esc(c.t('burndown'))}</h3>{_burndown(sp, committed, c)}" if committed else "")
    return head + board + burn


def _current_sprint(sprints: list) -> dict | None:
    today = dt.date.today()
    for sp in sprints:
        a, b = pdate(sp.get("start")), pdate(sp.get("end"))
        if a and b and a <= today <= b:
            return sp
    for sp in sprints:
        b = pdate(sp.get("end"))
        if b and b >= today:
            return sp
    return sprints[0] if sprints else None


def draw_sprints(d, c):
    sprints = [s for s in as_list(d.get("sprints")) if isinstance(s, dict)]
    stories, colors = c.stories(), c.epic_colors()
    cur = _current_sprint(sprints)
    if cur is None:
        return f"<div class='missing'>{esc(c.t('missing'))}</div>", ""
    fig = (f"<h3 style='margin-top:0'>{esc(cur.get('name') or cur.get('id'))}</h3>"
           + _sprint_block(cur, c, stories, colors))
    rows = []
    for sp in sprints:
        ids = [str(x) for x in as_list(sp.get("stories"))]
        committed = sum(num(stories.get(x, {}).get("points"), 0) or 0 for x in ids)
        rows.append(f"<tr><td><b>{esc(sp.get('name') or sp.get('id'))}</b></td>"
                    f"<td>{fmt_date(pdate(sp.get('start')))} → {fmt_date(pdate(sp.get('end')))}</td>"
                    f"<td>{esc(sp.get('goal') or '')}</td><td>{esc(', '.join(ids))}</td>"
                    f"<td><b>{committed}</b> / {esc(sp.get('capacity') or '?')}</td></tr>")
    vel = f" — {esc(c.t('velocity'))} : {esc(d['velocity'])} pts" if d.get("velocity") else ""
    details = (f"<h3>{esc(c.t('overview'))}{vel}</h3><table><thead><tr><th>{esc(c.t('sprint'))}</th><th>{esc(c.t('dates'))}</th>"
               f"<th>{esc(c.t('sprint_goal'))}</th><th>{esc(c.t('stories'))}</th>"
               f"<th>{esc(c.t('committed'))} / {esc(c.t('capacity'))}</th></tr></thead>{''.join(rows)}</table>")
    others = [sp for sp in sprints if sp is not cur and (as_list(sp.get("tasks")) or as_list(sp.get("stories")))]
    for sp in others:
        details += (f"<h3>{esc(sp.get('name') or sp.get('id'))}</h3>" + _sprint_block(sp, c, stories, colors))
    return fig, details


def draw_risks(d, c):
    risks = [r for r in as_list(d.get("risks")) if isinstance(r, dict)]
    W, H, x0, y0, cell = 640, 560, 150, 16, 92
    s = [f'<svg viewBox="0 0 {W} {H}" class="diagram" role="img" style="max-width:680px">']
    for p in range(1, 6):
        for i in range(1, 6):
            _, color = crit_class(p * i)
            x, y = x0 + (i - 1) * cell, y0 + (5 - p) * cell
            s.append(f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" fill="{color}" fill-opacity="0.18" stroke="#fff" stroke-width="3" rx="8"/>')
            s.append(f'<text x="{x + cell - 8}" y="{y + 14}" text-anchor="end" font-size="10" fill="#64748b">{p * i}</text>')
            here = [r for r in risks if num(r.get("probability")) == p and num(r.get("impact")) == i]
            for k, r in enumerate(here[:6]):
                cx = x + 26 + (k % 2) * 40
                cy = y + 30 + (k // 2) * 22
                s.append(f'<rect x="{cx - 18}" y="{cy - 9}" width="36" height="18" rx="9" fill="{color}"/>'
                         f'<text x="{cx}" y="{cy}" text-anchor="middle" dominant-baseline="central" font-size="10.5" '
                         f'font-weight="700" fill="#fff">{esc(str(r.get("id", ""))[:5])}</text>')
        s.append(f'<text x="{x0 - 10}" y="{y0 + (5 - p) * cell + cell / 2 - 7}" text-anchor="end" font-size="13" font-weight="700" fill="#334155">{p}</text>'
                 f'<text x="{x0 - 10}" y="{y0 + (5 - p) * cell + cell / 2 + 9}" text-anchor="end" font-size="11" fill="#64748b">{esc(c.t("p" + str(p)))}</text>')
    for i in range(1, 6):
        x = x0 + (i - 1) * cell + cell / 2
        s.append(f'<text x="{x}" y="{y0 + 5 * cell + 18}" text-anchor="middle" font-size="13" font-weight="700" fill="#334155">{i}</text>'
                 f'<text x="{x}" y="{y0 + 5 * cell + 34}" text-anchor="middle" font-size="11" fill="#64748b">{esc(c.t("i" + str(i)))}</text>')
    s.append(f'<text x="{x0 + 2.5 * cell}" y="{H - 8}" text-anchor="middle" font-size="13" font-weight="600" fill="#334155">{esc(c.t("impact"))} →</text>'
             f'<text transform="translate(18,{y0 + 2.5 * cell}) rotate(-90)" text-anchor="middle" font-size="13" font-weight="600" fill="#334155">{esc(c.t("probability"))} →</text>')
    s.append("</svg>")
    legend = " &nbsp; ".join(f"{chip(c.t(k), col)} {rng}" for k, col, rng in
                             (("c.low", "#16a34a", "1–4"), ("c.medium", "#eab308", "5–9"),
                              ("c.high", "#ea580c", "10–14"), ("c.critical", "#dc2626", "15–25")))
    fig = "".join(s) + f"<p class='small muted' style='text-align:center'>{legend}</p>"
    ranked = sorted(risks, key=lambda r: -((num(r.get("probability"), 0) or 0) * (num(r.get("impact"), 0) or 0)))
    rows = []
    for r in ranked:
        score = (num(r.get("probability"), 0) or 0) * (num(r.get("impact"), 0) or 0)
        key, color = crit_class(score)
        rows.append(f"<tr><td><b>{esc(r.get('id'))}</b></td><td><b>{esc(r.get('title'))}</b>"
                    f"<div class='small muted'>{esc(r.get('category') or '')}</div></td>"
                    f"<td class='small'>{esc(r.get('cause') or '')}{' → ' if r.get('cause') and r.get('consequence') else ''}{esc(r.get('consequence') or '')}</td>"
                    f"<td>{esc(r.get('probability'))}</td><td>{esc(r.get('impact'))}</td>"
                    f"<td>{chip(f'{score} · {c.t(key)}', color)}</td><td>{esc(r.get('owner') or '')}</td>"
                    f"<td class='small'>{esc(r.get('prevention') or '')}</td><td class='small'>{esc(r.get('contingency') or '')}</td>"
                    f"<td class='small'>{esc(r.get('status') or '')}</td></tr>")
    details = (f"<table><thead><tr><th>ID</th><th>{esc(c.t('risk'))}</th><th>{esc(c.t('cause'))} → {esc(c.t('consequence'))}</th>"
               f"<th>P</th><th>I</th><th>{esc(c.t('criticality'))}</th><th>{esc(c.t('owner'))}</th>"
               f"<th>{esc(c.t('prevention'))}</th><th>{esc(c.t('contingency'))}</th><th>{esc(c.t('status'))}</th></tr></thead>"
               f"{''.join(rows)}</table>")
    return fig, details


def draw_planning(d, c):
    rows = []                                # (group, id, label, start, end, owner)
    for it in as_list(d.get("items")):
        if not isinstance(it, dict):
            continue
        a, b = pdate(it.get("start")), pdate(it.get("end"))
        if a and b and a <= b:
            rows.append((str(it.get("group") or ""), str(it.get("id") or ""), str(it.get("label") or it.get("id") or ""),
                         a, b, str(it.get("owner") or "")))
    if d.get("include_sprints", True):
        have = {r[1] for r in rows} | {r[2] for r in rows}
        for sp in as_list(c.data.get("sprints", {}).get("sprints")):
            if not isinstance(sp, dict):
                continue
            a, b = pdate(sp.get("start")), pdate(sp.get("end"))
            name = str(sp.get("name") or sp.get("id") or "")
            if a and b and a <= b and str(sp.get("id")) not in have and name not in have:
                rows.append((c.t("sprints_group"), str(sp.get("id")), name, a, b, ""))
    miles = [(pdate(m.get("date")), txt(m)) for m in as_list(d.get("milestones"))
             if isinstance(m, dict) and pdate(m.get("date"))]
    dates = [r[3] for r in rows] + [r[4] for r in rows] + [m[0] for m in miles]
    if not dates:
        return f"<div class='missing'>{esc(c.t('missing'))}</div>", ""
    lo, hi = min(dates), max(dates)
    lo -= dt.timedelta(days=lo.weekday())
    hi += dt.timedelta(days=6 - hi.weekday())
    days = (hi - lo).days + 1
    px = max(3.0, min(36.0, 900 / days))
    LW, row_h = 250, 30
    groups: list[str] = []
    for r in rows:
        if r[0] not in groups:
            groups.append(r[0])
    head_h = 46
    mile_h = 44 if miles else 0
    body = sum(1 + sum(1 for r in rows if r[0] == g) for g in groups) - (1 if groups == [""] else 0)
    W = LW + days * px + 24
    H = head_h + mile_h + body * row_h + 26        # the last 16px hold the "today" label
    X = lambda day: LW + (day - lo).days * px
    s = [f'<svg viewBox="0 0 {W:.0f} {H:.0f}" class="diagram" role="img" style="max-height:none">']
    weeks_mode = px * 7 >= 34
    d0 = lo
    while d0 <= hi:
        if weeks_mode and d0.weekday() == 0:
            x = X(d0)
            s.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{head_h - 6}" y2="{H}" stroke="#e2e8f0"/>')
            s.append(f'<text x="{x + 3:.1f}" y="16" font-size="11" font-weight="700" fill="#334155">{esc(c.t("week"))}{d0.isocalendar()[1]}</text>'
                     f'<text x="{x + 3:.1f}" y="31" font-size="10" fill="#64748b">{d0.strftime("%d/%m")}</text>')
        elif not weeks_mode and d0.day == 1:
            x = X(d0)
            s.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{head_h - 6}" y2="{H}" stroke="#e2e8f0"/>'
                     f'<text x="{x + 3:.1f}" y="24" font-size="11" font-weight="700" fill="#334155">{d0.strftime("%m/%Y")}</text>')
        d0 += dt.timedelta(days=1)
    y = head_h
    if miles:
        s.append(f'<text x="8" y="{y + 22}" font-size="12" font-weight="700" fill="#334155">◆ {esc(c.t("milestones"))}</text>')
        last_x, level = -999.0, 0
        for md, label in sorted(miles):
            x = X(md) + px / 2
            level = 1 - level if x - last_x < 150 else 0
            last_x = x
            s.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{y + 8}" y2="{H}" stroke="#7c3aed" stroke-width="1.2" stroke-dasharray="3 4"/>')
            ly = y + 12 + level * 18
            text = label[:34]
            # A milestone near the right edge writes its label to the left.
            left = x + 10 + 6.6 * len(text) > W
            s.append(f'<path d="M{x:.1f},{ly - 7} l7,7 l-7,7 l-7,-7 z" fill="#7c3aed"/>'
                     f'<text x="{x - 10 if left else x + 10:.1f}" y="{ly}" text-anchor="{"end" if left else "start"}" '
                     f'dominant-baseline="central" font-size="11" font-weight="600" fill="#5b21b6">{esc(text)}</text>')
        y += mile_h
    for gi, g in enumerate(groups):
        color = PALETTE[gi % len(PALETTE)]
        if g or groups != [""]:
            s.append(f'<rect x="0" y="{y}" width="{W:.0f}" height="{row_h}" fill="#f8fafc"/>'
                     f'<text x="8" y="{y + row_h / 2}" dominant-baseline="central" font-size="12" font-weight="700" fill="{color}">{esc((g or "—").upper()[:36])}</text>')
            y += row_h
        for r in (r for r in rows if r[0] == g):
            _, rid, label, a, b, owner = r
            x1, x2 = X(a), X(b) + px
            s.append(f'<text x="18" y="{y + row_h / 2}" dominant-baseline="central" font-size="12" fill="#172033">{esc(label[:34])}</text>')
            s.append(f'<rect x="{x1:.1f}" y="{y + 6}" width="{max(3, x2 - x1):.1f}" height="{row_h - 12}" rx="5" fill="{color}"/>')
            tag = owner or f"{a.strftime('%d/%m')} → {b.strftime('%d/%m')}"
            if x2 - x1 > 8 * len(tag):
                s.append(f'<text x="{x1 + 6:.1f}" y="{y + row_h / 2}" dominant-baseline="central" font-size="10.5" fill="#fff">{esc(tag)}</text>')
            else:
                s.append(f'<text x="{x2 + 5:.1f}" y="{y + row_h / 2}" dominant-baseline="central" font-size="10.5" fill="#64748b">{esc(tag)}</text>')
            y += row_h
    today = dt.date.today()
    if lo <= today <= hi:
        x = X(today) + px / 2
        s.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{head_h - 8}" y2="{H - 16}" stroke="#dc2626" stroke-width="1.6"/>'
                 f'<text x="{x:.1f}" y="{H - 4}" text-anchor="middle" font-size="10.5" font-weight="700" fill="#dc2626">{esc(c.t("today"))}</text>')
    s.append("</svg>")
    cer = [x for x in as_list(d.get("ceremonies")) if isinstance(x, dict)]
    details = ""
    if cer:
        body = "".join(f"<tr><td><b>{esc(x.get('name'))}</b></td><td>{esc(x.get('when') or '')}</td>"
                       f"<td>{esc(x.get('duration') or '')}</td><td>{esc(x.get('who') or '')}</td>"
                       f"<td>{esc(x.get('purpose') or '')}</td></tr>" for x in cer)
        details += (f"<h3>{esc(c.t('ceremonies'))}</h3><table><thead><tr><th>{esc(c.t('ceremony'))}</th><th>{esc(c.t('when'))}</th>"
                    f"<th>{esc(c.t('duration'))}</th><th>{esc(c.t('who'))}</th><th>{esc(c.t('purpose_col'))}</th></tr></thead>{body}</table>")
    if miles:
        body = "".join(f"<tr><td>{fmt_date(md)}</td><td>{esc(label)}</td></tr>" for md, label in sorted(miles))
        details += f"<h3>{esc(c.t('milestones'))}</h3><table>{body}</table>"
    return "".join(s), details


DRAW = {"bete-a-cornes": draw_bete, "pieuvre": draw_pieuvre, "swot": draw_swot,
        "parties-prenantes": draw_stakeholders, "raci": draw_raci, "discovery": draw_discovery,
        "product-backlog": draw_backlog, "sprints": draw_sprints, "risques": draw_risks,
        "planning": draw_planning}


# ── Pages ────────────────────────────────────────────────────────────────────

def _section(stem: str, c: Ctx, figure_id: bool) -> str:
    title = c.t(stem)
    d = c.data.get(stem)
    if d is None:
        step = dict(ORDER)[stem]
        inner = f"<div class='missing'>{esc(c.t('missing'))} — {esc(c.t('step'))} « {esc(step)} »</div>"
    else:
        try:
            fig, details = DRAW[stem](d, c)
        except Exception as e:                     # never let one file sink the dashboard
            fig, details = f"<div class='missing'>{esc(c.t('error'))} ({esc(type(e).__name__)}: {esc(e)})</div>", ""
        fid = " id='figure'" if figure_id else ""
        inner = f"<div class='figure'{fid}>{fig}</div>{details}"
    return (f"<section class='art' id='{stem}'><h2>{esc(title)}</h2>"
            f"<p class='lead'>{esc(c.t('lead.' + stem))}</p>{inner}</section>")


def _page(title: str, body: str, c: Ctx, back: bool, nav: str = "") -> str:
    name = c.meta.get("name") or c.root.name
    sub = c.meta.get("description") or ""
    link = f"<a class='back' href='index.html'>{esc(c.t('back'))}</a>" if back else ""
    return (f"<!DOCTYPE html><html lang='{c.lang}'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<title>{esc(title)} — {esc(name)}</title><style>{CSS}</style></head><body>"
            f"<header class='top'><div><h1>{esc(name)} · {esc(title)}</h1>"
            f"<div class='sub'>{esc(str(sub)[:160])}</div></div>{link}</header>{nav}"
            f"<main>{body}</main><footer>{esc(c.t('generated'))} {dt.date.today().strftime('%d/%m/%Y')}</footer></body></html>")


def summary(c: Ctx) -> dict:
    stories = list(c.stories().values())
    risks = [r for r in as_list(c.data.get("risques", {}).get("risks")) if isinstance(r, dict)]
    return {
        "artefacts": {stem: stem in c.data for stem, _ in ORDER},
        "epics": len(as_list(c.data.get("product-backlog", {}).get("epics"))),
        "stories": len(stories),
        "points": sum(num(s.get("points"), 0) or 0 for s in stories),
        "points_done": sum(num(s.get("points"), 0) or 0 for s in stories if s.get("status") == "done"),
        "sprints": len(as_list(c.data.get("sprints", {}).get("sprints"))),
        "risks": len(risks),
        "critical_risks": sum(1 for r in risks
                              if (num(r.get("probability"), 0) or 0) * (num(r.get("impact"), 0) or 0) >= 15),
        "stakeholders": len(as_list(c.data.get("parties-prenantes", {}).get("stakeholders"))),
        "errors": c.errors, "warnings": c.warnings,
    }


def dashboard(c: Ctx) -> str:
    sm = summary(c)
    nav = "<nav class='pills'>" + "".join(
        f"<a href='#{stem}'{'' if stem in c.data else ' class=off'}>{esc(c.t(stem))}</a>"
        for stem, _ in ORDER) + "</nav>"
    kpis = [("k.epics", sm["epics"]), ("k.stories", sm["stories"]),
            ("k.points", f"{sm['points_done']}/{sm['points']}" if sm["points"] else 0),
            ("k.sprints", sm["sprints"]), ("k.critical", sm["critical_risks"]),
            ("k.stakeholders", sm["stakeholders"])]
    tiles = "".join(f"<div class='kpi'><b>{esc(v)}</b><span>{esc(c.t(k))}</span></div>" for k, v in kpis)
    vision = (f"<section class='art'><h2>{esc(c.t('vision'))}</h2><p style='font-size:15px;margin:8px 0 0'>"
              f"{esc(c.meta['vision'])}</p></section>") if c.meta.get("vision") else ""
    body = f"<div class='kpis'>{tiles}</div>{vision}" + "".join(_section(stem, c, False) for stem, _ in ORDER)
    return _page(c.t("dashboard"), body, c, back=False, nav=nav)


def render(c: Ctx, out: Path) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for stem, _ in ORDER:
        target = out / f"{stem}.html"
        if stem in c.data:
            target.write_text(_page(c.t(stem), _section(stem, c, True), c, back=True), encoding="utf-8")
            written.append(target)
        elif target.exists():
            target.unlink()                      # a deleted JSON takes its page with it
    index = out / "index.html"
    index.write_text(dashboard(c), encoding="utf-8")
    written.append(index)
    return written


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Draw the Scrum deliverables of a project folder.")
    ap.add_argument("project", nargs="?", default=".", help="folder that contains scrum/")
    ap.add_argument("--check", action="store_true", help="validate only; exit 1 on any error")
    ap.add_argument("--json", action="store_true", help="print a JSON summary")
    ap.add_argument("--out", help="output folder (default <project>/livrables)")
    a = ap.parse_args(argv)
    c = Ctx(Path(a.project).resolve())
    if not c.dir.is_dir():
        print(f"no scrum/ folder in {c.root}", file=sys.stderr)
        return 2
    c.load()
    for stem, d in c.data.items():
        try:
            CHECKS[stem](d, c)
        except Exception as e:
            c.err(stem, f"could not be checked ({type(e).__name__}: {e})")
    if a.check:
        for e in c.errors:
            print(f"ERROR   {e}")
        for w in c.warnings:
            print(f"warning {w}")
        done = [stem for stem, _ in ORDER if stem in c.data]
        print(f"{len(c.errors)} error(s), {len(c.warnings)} warning(s) in {len(done)} file(s): {', '.join(done) or 'none'}")
        return 1 if c.errors else 0
    written = render(c, Path(a.out) if a.out else c.root / "livrables")
    if a.json:
        print(json.dumps(summary(c), ensure_ascii=False))
    else:
        print(f"{len(written)} page(s) in {written[-1].parent}")
        for e in c.errors:
            print(f"ERROR   {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
