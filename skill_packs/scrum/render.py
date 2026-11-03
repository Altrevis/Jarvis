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
    cahier-des-charges.json the specification: context, objectives, scope,
                            requirements, constraints, acceptance... assembled
                            with the files above into one document (NF EN 16271)
    product-backlog.json    epics, user stories, DoR, DoD
    sprints.json            sprint goals, committed stories, tasks, burndown
    risques.json            risk register, probability x impact, after treatment;
                            drawn as three pages: register, risk matrix, heat map
    planning.json           Gantt items, milestones, ceremonies
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import math
import re
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
    ("cahier-des-charges", "cahier-des-charges"),
    ("cadre-scrum", "backlog"),
    ("product-backlog", "backlog"),
    ("priorisation", "backlog"),
    ("sprints", "sprint"),
    ("risques", "risques"),
    ("matrice-risques", "risques"),
    ("carte-chaleur", "risques"),
    ("planning", "planning"),
)
# Pages drawn from another page's file: one risk register, three pages; the
# Scrum framework and the value / effort matrix read the product backlog.
VIEWS = {"matrice-risques": "risques", "carte-chaleur": "risques",
         "cadre-scrum": "product-backlog", "priorisation": "product-backlog"}


def source(stem: str) -> str:
    """The JSON stem a page is drawn from."""
    return VIEWS.get(stem, stem)

FIB = {0, 0.5, 1, 2, 3, 5, 8, 13, 20, 40, 100}
PRIORITIES = ("must", "should", "could", "wont")
STORY_STATUS = ("todo", "ready", "doing", "done")
ITEM_TYPES = ("story", "bug", "tech", "spike")      # the product backlog is not only user stories
TYPE_COLOR = {"story": "#2563eb", "bug": "#dc2626", "tech": "#7c3aed", "spike": "#0891b2"}
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
        "cahier-des-charges": "Cahier des charges",
        "product-backlog": "Product backlog", "sprints": "Sprint backlog",
        "risques": "Registre des risques", "matrice-risques": "Matrice des risques",
        "carte-chaleur": "Carte de chaleur des risques", "planning": "Planning",
        "lead.bete-a-cornes": "Expression du besoin — méthode APTE",
        "lead.pieuvre": "Analyse fonctionnelle — fonctions principales (FP) et contraintes (FC)",
        "lead.swot": "Analyse stratégique — facteurs internes et externes",
        "lead.parties-prenantes": "Cartographie pouvoir / intérêt (Mendelow)",
        "lead.raci": "Qui réalise, qui approuve, qui est consulté, qui est informé",
        "lead.discovery": "Ce qu'il faut apprendre avant de construire",
        "lead.cahier-des-charges": "Cahier des charges fonctionnel — besoin, fonctions, exigences et conditions de réalisation",
        "lead.product-backlog": "Epics, user stories et priorités",
        "lead.sprints": "Objectif, engagement et tâches du sprint",
        "lead.risques": "Chaque risque : cause, conséquence, criticité, responsable et réponse",
        "lead.matrice-risques": "Criticité = probabilité × impact — la place de chaque risque, avant et après traitement",
        "lead.carte-chaleur": "Où se concentre l'exposition — nombre de risques par case, avant et après traitement",
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
        "inherent": "Avant traitement", "residual": "Après traitement", "now": "Exposition actuelle",
        "residual_col": "Résiduel", "exposure": "Exposition", "by_category": "Exposition par catégorie",
        "total": "Total", "other": "Autre",
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
        "cahier-des-charges": "Specification",
        "product-backlog": "Product backlog", "sprints": "Sprint backlog",
        "risques": "Risk register", "matrice-risques": "Risk matrix",
        "carte-chaleur": "Risk heat map", "planning": "Schedule",
        "lead.bete-a-cornes": "Need statement — APTE method",
        "lead.pieuvre": "Functional analysis — main functions (FP) and constraints (FC)",
        "lead.swot": "Strategic analysis — internal and external factors",
        "lead.parties-prenantes": "Power / interest grid (Mendelow)",
        "lead.raci": "Who does it, who approves, who is consulted, who is informed",
        "lead.discovery": "What must be learned before building",
        "lead.cahier-des-charges": "Functional specification — need, functions, requirements and delivery terms",
        "lead.product-backlog": "Epics, user stories and priorities",
        "lead.sprints": "Sprint goal, commitment and tasks",
        "lead.risques": "Each risk: cause, consequence, score, owner and response",
        "lead.matrice-risques": "Score = probability × impact — where each risk stands, before and after treatment",
        "lead.carte-chaleur": "Where the exposure concentrates — risks per cell, before and after treatment",
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
        "inherent": "Before treatment", "residual": "After treatment", "now": "Current exposure",
        "residual_col": "Residual", "exposure": "Exposure", "by_category": "Exposure by category",
        "total": "Total", "other": "Other",
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

# The specification's own words.
LABELS["fr"].update({
    "cadre-scrum": "Cadre Scrum", "priorisation": "Priorisation valeur / effort",
    "lead.cadre-scrum": "Les trois artefacts et leurs engagements, la Scrum Team et les événements — Scrum Guide 2020",
    "lead.priorisation": "Ce que rapporte chaque élément du backlog face à ce qu'il coûte",
    "type.story": "User story", "type.bug": "Bug", "type.tech": "Technique", "type.spike": "Spike",
    "health": "Santé du backlog", "h.items": "Éléments ouverts", "h.estimated": "Estimés",
    "h.accepted": "Avec critères d'acceptation", "h.ready_pts": "Points prêts",
    "h.covers": "sprint(s) d'avance", "h.shape": "Forme du backlog (éléments ouverts)", "h.ready": "Prêts",
    "h.refined": "Affinés", "h.rough": "À affiner", "h.target": "repère : ≈ 20 % prêts, 30 % affinés, 50 % à affiner",
    "q.quick": "Gains rapides", "q.major": "Gros chantiers", "q.fill": "Bouche-trous", "q.avoid": "À reconsidérer",
    "effort": "Effort (points)", "rank": "Rang", "ratio": "Valeur / point", "order_title": "Ordre du backlog",
    "quadrant": "Quadrant", "type": "Type",
    "c.pb": "Product Backlog", "c.sb": "Sprint Backlog", "c.inc": "Increment", "c.commit": "Engagement",
    "c.pg": "Objectif de produit", "c.sg": "Objectif de sprint", "c.dod": "Definition of Done",
    "c.items": "éléments", "c.ready": "prêts", "c.tasks": "tâches", "c.done": "finies", "c.criteria": "critères",
    "c.no_sprint": "Aucun sprint planifié", "c.no_goal": "Objectif à définir",
    "c.planning": "Sprint Planning", "c.during": "Sprint · Daily Scrum", "c.loop": "Sprint Review : inspecter l'Increment, adapter le Product Backlog",
    "c.retro_loop": "Sprint Retrospective : améliorer la façon de travailler",
    "team": "Scrum Team", "po": "Product Owner", "sm": "Scrum Master", "devs": "Developers",
    "po_acc": "Maximise la valeur du produit, formule l'objectif de produit, ordonne le Product Backlog. Une personne, pas un comité.",
    "sm_acc": "Met en place Scrum, accompagne l'équipe et l'organisation, lève les obstacles, veille aux événements et à leurs timeboxes.",
    "dev_acc": "Créent le Sprint Backlog, s'engagent sur la Definition of Done, adaptent leur plan chaque jour à l'objectif de sprint, dimensionnent les éléments.",
    "unassigned": "à désigner", "event": "Événement", "timebox": "Timebox Scrum Guide", "planned": "Prévu dans le planning",
    "e.sprint": "Sprint", "e.planning": "Sprint Planning", "e.daily": "Daily Scrum", "e.review": "Sprint Review",
    "e.retrospective": "Sprint Retrospective", "e.refinement": "Affinement du backlog",
    "tb.sprint": "≤ 1 mois — ici {w} sem.", "tb.refinement": "activité continue, ≈ 10 % de la capacité",
    "tb.weeks": "pour un sprint de {w} sem.", "pillars": "Piliers : transparence, inspection, adaptation",
    "values": "Valeurs : engagement, focus, ouverture, respect, courage", "not_planned": "non prévu",
    "increment": "Increment", "review": "Sprint Review", "retro": "Sprint Retrospective",
    "inc_lead": "Éléments finis selon la Definition of Done", "feedback": "Retours des parties prenantes",
    "backlog_changes": "Adaptations du Product Backlog", "went_well": "Ce qui a bien marché",
    "to_improve": "À améliorer", "actions": "Actions d'amélioration", "velocity_chart": "Vélocité par sprint",
    "burnup": "Burn-up du produit", "scope": "Périmètre", "done_pts": "Fini", "method": "Méthode", "pbi": "Élément",
 "cdc.version": "Version", "cdc.status": "Statut",
    "cdc.date": "Date", "cdc.client": "Maître d'ouvrage", "cdc.provider": "Maître d'œuvre",
    "cdc.authors": "Rédaction", "cdc.confidentiality": "Diffusion", "cdc.history": "Suivi des versions",
    "cdc.changes": "Modifications", "cdc.author": "Auteur", "cdc.approvals": "Validation du document",
    "cdc.decision": "Décision / visa", "cdc.toc": "Sommaire", "cdc.synthesis": "Synthèse",
    "cdc.s.overview": "Présentation du projet", "cdc.s.context": "Contexte", "cdc.stakes": "Enjeux",
    "cdc.s.current": "Existant et problèmes constatés", "cdc.s.objectives": "Objectifs",
    "cdc.objective": "Objectif", "cdc.indicator": "Indicateur", "cdc.target": "Cible",
    "cdc.deadline": "Échéance", "cdc.s.scope": "Périmètre", "cdc.in": "Dans le périmètre",
    "cdc.out": "Hors périmètre", "cdc.assumptions": "Hypothèses", "cdc.dependencies": "Dépendances",
    "cdc.s.stakeholders": "Parties prenantes", "cdc.side": "Interne / externe",
    "cdc.s.references": "Documents de référence", "cdc.s.need": "Expression du besoin",
    "cdc.s.statement": "Énoncé du besoin", "cdc.s.validation": "Validation du besoin",
    "cdc.question": "Question", "cdc.answer": "Réponse",
    "cdc.s.users": "Utilisateurs cibles", "cdc.profile": "Profil", "cdc.count": "Effectif",
    "cdc.frequency": "Fréquence d'usage", "cdc.skills": "Compétences",
    "cdc.s.fa": "Analyse fonctionnelle du besoin", "cdc.s.life": "Situations de vie du produit",
    "cdc.phase": "Situation de vie", "cdc.s.interactions": "Diagramme des interacteurs",
    "cdc.s.characterisation": "Caractérisation des fonctions de service",
    "cdc.F0": "F0 — impératif, flexibilité nulle", "cdc.F1": "F1 — peu négociable",
    "cdc.F2": "F2 — négociable", "cdc.F3": "F3 — très négociable",
    "cdc.s.functional": "Exigences fonctionnelles", "cdc.description": "Description",
    "cdc.actor": "Acteur", "cdc.functions": "Fonctions servies", "cdc.rules": "Règles de gestion",
    "cdc.acceptance": "Critères d'acceptation", "cdc.priority": "Priorité",
    "cdc.must": "Indispensable", "cdc.should": "Important", "cdc.could": "Souhaitable",
    "cdc.wont": "Hors de cette version", "cdc.other_reqs": "Autres exigences",
    "cdc.s.journeys": "Parcours utilisateurs", "cdc.s.nfr": "Exigences non fonctionnelles",
    "cdc.requirement": "Exigence", "cdc.criteria": "Critère", "cdc.level": "Niveau",
    "cdc.flex": "Flex.", "cdc.verification": "Vérification",
    "cdc.cat.performance": "Performance", "cdc.cat.security": "Sécurité",
    "cdc.cat.availability": "Disponibilité et fiabilité", "cdc.cat.usability": "Ergonomie et accessibilité",
    "cdc.cat.compatibility": "Compatibilité", "cdc.cat.maintainability": "Maintenabilité",
    "cdc.cat.portability": "Portabilité et réversibilité", "cdc.cat.compliance": "Conformité réglementaire",
    "cdc.cat.operability": "Exploitation", "cdc.cat.other": "Autres exigences",
    "cdc.v.test": "Test", "cdc.v.inspection": "Inspection", "cdc.v.analysis": "Analyse",
    "cdc.v.demonstration": "Démonstration",
    "cdc.s.technical": "Contraintes et environnement technique", "cdc.s.environment": "Environnement technique",
    "cdc.imposed": "Choix imposés", "cdc.hosting": "Hébergement",
    "cdc.s.interfaces": "Interfaces avec d'autres systèmes", "cdc.system": "Système", "cdc.direction": "Sens",
    "cdc.data": "Données échangées", "cdc.protocol": "Protocole", "cdc.freq": "Fréquence",
    "cdc.s.data": "Données", "cdc.entity": "Donnée", "cdc.volume": "Volume", "cdc.sensitivity": "Sensibilité",
    "cdc.retention": "Conservation", "cdc.migration": "Reprise des données existantes",
    "cdc.s.constraints": "Contraintes", "cdc.type": "Type", "cdc.constraint": "Contrainte",
    "cdc.s.organisation": "Organisation du projet", "cdc.s.method": "Méthode",
    "cdc.s.roles": "Rôles et responsabilités", "cdc.role": "Rôle", "cdc.responsibilities": "Responsabilités",
    "cdc.s.governance": "Instances de pilotage", "cdc.committee": "Instance", "cdc.participants": "Participants",
    "cdc.purpose": "Objet", "cdc.s.planning": "Planning et jalons", "cdc.milestone": "Jalon",
    "cdc.s.budget": "Budget", "cdc.item": "Poste", "cdc.amount": "Montant", "cdc.note": "Commentaire",
    "cdc.total": "Total", "cdc.envelope": "Enveloppe allouée", "cdc.s.deliverables": "Livrables",
    "cdc.deliverable": "Livrable", "cdc.format": "Format", "cdc.due": "Échéance",
    "cdc.s.acceptance": "Recette et validation", "cdc.process": "Déroulement de la recette",
    "cdc.acc_criteria": "Critères de validation", "cdc.severity": "Classification des anomalies",
    "cdc.sev_level": "Gravité", "cdc.definition": "Définition", "cdc.threshold": "Seuil accepté",
    "cdc.warranty": "Garantie", "cdc.s.support": "Maintenance, support et réversibilité",
    "cdc.maintenance": "Maintenance", "cdc.sla": "Niveaux de service", "cdc.sla_level": "Niveau",
    "cdc.response_time": "Prise en charge", "cdc.resolution": "Résolution", "cdc.training": "Formation",
    "cdc.documentation": "Documentation", "cdc.reversibility": "Réversibilité",
    "cdc.s.risks": "Risques", "cdc.s.response": "Cadre de réponse", "cdc.variants": "Variantes",
    "cdc.expected": "Contenu attendu de l'offre", "cdc.selection": "Critères de sélection des offres",
    "cdc.weight": "Pondération", "cdc.calendar": "Calendrier de la consultation", "cdc.contact": "Contact",
    "cdc.s.glossary": "Glossaire", "cdc.term": "Terme", "cdc.s.trace": "Matrice de traçabilité",
    "cdc.trace_lead": "Pour chaque fonction de service : les exigences qui la satisfont et les user stories qui les réalisent.",
    "cdc.requirements": "Exigences", "cdc.stories": "User stories",
    "cdc.unlinked": "Exigences rattachées à aucune fonction", "cdc.s.questions": "Questions ouvertes",
    "cdc.open": "Ouvrir le cahier des charges complet", "cdc.k.ef": "Exigences fonctionnelles",
    "cdc.k.enf": "Exigences non fonctionnelles", "cdc.k.cover": "Fonctions couvertes",
    "cdc.k.obj": "Objectifs", "cdc.elements": "Éléments du milieu extérieur", "cdc.fig": "Figure",
    "cdc.top_risks": "Risques principaux", "cdc.annex": "Annexe", "cdc.ceremonies": "Cérémonies Scrum",
    "cdc.persona": "Persona", "cdc.not_linked": "aucune", "cdc.internal": "Interne",
    "cdc.external": "Externe",
})
LABELS["en"].update({
    "cadre-scrum": "Scrum framework", "priorisation": "Value / effort prioritisation",
    "lead.cadre-scrum": "The three artefacts and their commitments, the Scrum Team and the events — Scrum Guide 2020",
    "lead.priorisation": "What each backlog item brings against what it costs",
    "type.story": "User story", "type.bug": "Bug", "type.tech": "Technical", "type.spike": "Spike",
    "health": "Backlog health", "h.items": "Open items", "h.estimated": "Estimated",
    "h.accepted": "With acceptance criteria", "h.ready_pts": "Ready points",
    "h.covers": "sprint(s) ahead", "h.shape": "Backlog shape (open items)", "h.ready": "Ready",
    "h.refined": "Refined", "h.rough": "To refine", "h.target": "guide: ≈ 20 % ready, 30 % refined, 50 % to refine",
    "q.quick": "Quick wins", "q.major": "Big bets", "q.fill": "Fill-ins", "q.avoid": "Reconsider",
    "effort": "Effort (points)", "rank": "Rank", "ratio": "Value / point", "order_title": "Backlog order",
    "quadrant": "Quadrant", "type": "Type",
    "c.pb": "Product Backlog", "c.sb": "Sprint Backlog", "c.inc": "Increment", "c.commit": "Commitment",
    "c.pg": "Product Goal", "c.sg": "Sprint Goal", "c.dod": "Definition of Done",
    "c.items": "items", "c.ready": "ready", "c.tasks": "tasks", "c.done": "done", "c.criteria": "criteria",
    "c.no_sprint": "No sprint planned", "c.no_goal": "Goal to be set",
    "c.planning": "Sprint Planning", "c.during": "Sprint · Daily Scrum", "c.loop": "Sprint Review: inspect the Increment, adapt the Product Backlog",
    "c.retro_loop": "Sprint Retrospective: improve the way of working",
    "team": "Scrum Team", "po": "Product Owner", "sm": "Scrum Master", "devs": "Developers",
    "po_acc": "Maximises the value of the product, sets the Product Goal, orders the Product Backlog. One person, not a committee.",
    "sm_acc": "Establishes Scrum, coaches the team and the organisation, removes impediments, keeps the events and their timeboxes.",
    "dev_acc": "Create the Sprint Backlog, commit to the Definition of Done, adapt their plan daily to the Sprint Goal, size the items.",
    "unassigned": "to be named", "event": "Event", "timebox": "Scrum Guide timebox", "planned": "In the schedule",
    "e.sprint": "Sprint", "e.planning": "Sprint Planning", "e.daily": "Daily Scrum", "e.review": "Sprint Review",
    "e.retrospective": "Sprint Retrospective", "e.refinement": "Backlog refinement",
    "tb.sprint": "≤ 1 month — here {w} wk", "tb.refinement": "ongoing, ≈ 10 % of capacity",
    "tb.weeks": "for a {w}-week sprint", "pillars": "Pillars: transparency, inspection, adaptation",
    "values": "Values: commitment, focus, openness, respect, courage", "not_planned": "not planned",
    "increment": "Increment", "review": "Sprint Review", "retro": "Sprint Retrospective",
    "inc_lead": "Items done to the Definition of Done", "feedback": "Stakeholder feedback",
    "backlog_changes": "Product Backlog adaptations", "went_well": "What went well",
    "to_improve": "To improve", "actions": "Improvement actions", "velocity_chart": "Velocity per sprint",
    "burnup": "Product burn-up", "scope": "Scope", "done_pts": "Done", "method": "Method", "pbi": "Item",
 "cdc.version": "Version", "cdc.status": "Status",
    "cdc.date": "Date", "cdc.client": "Client (project owner)", "cdc.provider": "Contractor",
    "cdc.authors": "Written by", "cdc.confidentiality": "Distribution", "cdc.history": "Revision history",
    "cdc.changes": "Changes", "cdc.author": "Author", "cdc.approvals": "Approval",
    "cdc.decision": "Decision / signature", "cdc.toc": "Contents", "cdc.synthesis": "Summary",
    "cdc.s.overview": "Project overview", "cdc.s.context": "Context", "cdc.stakes": "Stakes",
    "cdc.s.current": "Current situation and problems", "cdc.s.objectives": "Objectives",
    "cdc.objective": "Objective", "cdc.indicator": "Indicator", "cdc.target": "Target",
    "cdc.deadline": "Deadline", "cdc.s.scope": "Scope", "cdc.in": "In scope", "cdc.out": "Out of scope",
    "cdc.assumptions": "Assumptions", "cdc.dependencies": "Dependencies",
    "cdc.s.stakeholders": "Stakeholders", "cdc.side": "Internal / external",
    "cdc.s.references": "Reference documents", "cdc.s.need": "Expression of the need",
    "cdc.s.statement": "Need statement", "cdc.s.validation": "Validation of the need",
    "cdc.question": "Question", "cdc.answer": "Answer",
    "cdc.s.users": "Target users", "cdc.profile": "Profile", "cdc.count": "Number",
    "cdc.frequency": "Frequency of use", "cdc.skills": "Skills",
    "cdc.s.fa": "Functional analysis of the need", "cdc.s.life": "Life-cycle situations",
    "cdc.phase": "Situation", "cdc.s.interactions": "Interaction diagram",
    "cdc.s.characterisation": "Characterisation of the service functions",
    "cdc.F0": "F0 — mandatory, no flexibility", "cdc.F1": "F1 — hardly negotiable",
    "cdc.F2": "F2 — negotiable", "cdc.F3": "F3 — very negotiable",
    "cdc.s.functional": "Functional requirements", "cdc.description": "Description",
    "cdc.actor": "Actor", "cdc.functions": "Functions served", "cdc.rules": "Business rules",
    "cdc.acceptance": "Acceptance criteria", "cdc.priority": "Priority",
    "cdc.must": "Must have", "cdc.should": "Should have", "cdc.could": "Could have",
    "cdc.wont": "Not in this release", "cdc.other_reqs": "Other requirements",
    "cdc.s.journeys": "User journeys", "cdc.s.nfr": "Non-functional requirements",
    "cdc.requirement": "Requirement", "cdc.criteria": "Criterion", "cdc.level": "Level",
    "cdc.flex": "Flex.", "cdc.verification": "Verification",
    "cdc.cat.performance": "Performance", "cdc.cat.security": "Security",
    "cdc.cat.availability": "Availability and reliability", "cdc.cat.usability": "Usability and accessibility",
    "cdc.cat.compatibility": "Compatibility", "cdc.cat.maintainability": "Maintainability",
    "cdc.cat.portability": "Portability and reversibility", "cdc.cat.compliance": "Regulatory compliance",
    "cdc.cat.operability": "Operations", "cdc.cat.other": "Other requirements",
    "cdc.v.test": "Test", "cdc.v.inspection": "Inspection", "cdc.v.analysis": "Analysis",
    "cdc.v.demonstration": "Demonstration",
    "cdc.s.technical": "Constraints and technical environment", "cdc.s.environment": "Technical environment",
    "cdc.imposed": "Imposed choices", "cdc.hosting": "Hosting",
    "cdc.s.interfaces": "Interfaces with other systems", "cdc.system": "System", "cdc.direction": "Direction",
    "cdc.data": "Data exchanged", "cdc.protocol": "Protocol", "cdc.freq": "Frequency",
    "cdc.s.data": "Data", "cdc.entity": "Data", "cdc.volume": "Volume", "cdc.sensitivity": "Sensitivity",
    "cdc.retention": "Retention", "cdc.migration": "Migration of existing data",
    "cdc.s.constraints": "Constraints", "cdc.type": "Type", "cdc.constraint": "Constraint",
    "cdc.s.organisation": "Project organisation", "cdc.s.method": "Method",
    "cdc.s.roles": "Roles and responsibilities", "cdc.role": "Role", "cdc.responsibilities": "Responsibilities",
    "cdc.s.governance": "Governance", "cdc.committee": "Body", "cdc.participants": "Participants",
    "cdc.purpose": "Purpose", "cdc.s.planning": "Schedule and milestones", "cdc.milestone": "Milestone",
    "cdc.s.budget": "Budget", "cdc.item": "Item", "cdc.amount": "Amount", "cdc.note": "Note",
    "cdc.total": "Total", "cdc.envelope": "Allocated budget", "cdc.s.deliverables": "Deliverables",
    "cdc.deliverable": "Deliverable", "cdc.format": "Format", "cdc.due": "Due",
    "cdc.s.acceptance": "Acceptance", "cdc.process": "Acceptance process",
    "cdc.acc_criteria": "Acceptance criteria", "cdc.severity": "Defect classification",
    "cdc.sev_level": "Severity", "cdc.definition": "Definition", "cdc.threshold": "Accepted threshold",
    "cdc.warranty": "Warranty", "cdc.s.support": "Maintenance, support and reversibility",
    "cdc.maintenance": "Maintenance", "cdc.sla": "Service levels", "cdc.sla_level": "Level",
    "cdc.response_time": "Response", "cdc.resolution": "Resolution", "cdc.training": "Training",
    "cdc.documentation": "Documentation", "cdc.reversibility": "Reversibility",
    "cdc.s.risks": "Risks", "cdc.s.response": "Response framework", "cdc.variants": "Variants",
    "cdc.expected": "Expected content of the offer", "cdc.selection": "Selection criteria",
    "cdc.weight": "Weight", "cdc.calendar": "Consultation calendar", "cdc.contact": "Contact",
    "cdc.s.glossary": "Glossary", "cdc.term": "Term", "cdc.s.trace": "Traceability matrix",
    "cdc.trace_lead": "For each service function: the requirements that satisfy it and the user stories that implement them.",
    "cdc.requirements": "Requirements", "cdc.stories": "User stories",
    "cdc.unlinked": "Requirements linked to no function", "cdc.s.questions": "Open questions",
    "cdc.open": "Open the full specification", "cdc.k.ef": "Functional requirements",
    "cdc.k.enf": "Non-functional requirements", "cdc.k.cover": "Functions covered",
    "cdc.k.obj": "Objectives", "cdc.elements": "Elements of the environment", "cdc.fig": "Figure",
    "cdc.top_risks": "Main risks", "cdc.annex": "Appendix", "cdc.ceremonies": "Scrum ceremonies",
    "cdc.persona": "Persona", "cdc.not_linked": "none", "cdc.internal": "Internal",
    "cdc.external": "External",
})

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
.mx{display:grid;grid-template-columns:minmax(0,680px) minmax(260px,1fr);gap:26px;align-items:start}
ul.keys{list-style:none;margin:0 0 12px;padding:0}
ul.keys li{display:flex;gap:9px;align-items:baseline;padding:5px 0;border-bottom:1px solid var(--line);font-size:13px;break-inside:avoid}
ul.keys .chip{min-width:40px;text-align:center}ul.keys .sc{margin-left:auto;white-space:nowrap}
ul.keys.cols{columns:2 360px;column-gap:32px;margin-top:14px}
.pair{display:grid;grid-template-columns:repeat(auto-fit,minmax(380px,1fr));gap:24px;align-items:start}
.pair h4{margin:0 0 2px;font-size:14px;text-align:center}
.pair p{text-align:center;margin:4px 0 0}
td.hc,th.hc{text-align:center}td.hc{font-weight:700;border:2px solid #fff}
footer{color:#94a3b8;font-size:12px;text-align:center;padding:6px 0 26px}
@page{size:A4 landscape;margin:9mm}
@media print{html,body{background:#fff}nav.pills,.top .back{display:none}.art{margin:0;border:none;padding:0 2mm;break-before:page}.kpis{margin:6mm 0}main{padding:0}svg.diagram{max-height:122mm}.board{overflow:visible}footer{display:none}
h2,h3,.lead,.banner{break-after:avoid}svg.diagram,.card,.ticket,.sprinthead,tr,.swot .q,.health{break-inside:avoid}thead{display:table-header-group}
.pair svg.diagram{max-height:80mm}ul.keys li{padding:2px 0;font-size:12px}ul.keys.cols{columns:3 200px}table.heatcat td,table.heatcat th{padding:3px 8px}}
"""

# The specification is a document, not a dashboard: A4 portrait sheets.
DOC_CSS = """
body.doc{background:#e5e9f0}
.doc .back{display:inline-block;margin:16px 0 0 24px;font-size:13px}
.sheet{max-width:900px;margin:18px auto 40px;background:#fff;padding:56px 66px;box-shadow:0 2px 14px rgba(15,23,42,.12);border-radius:4px}
.sheet h2{font-size:21px;margin:38px 0 12px;color:#0f2a5a;border-bottom:2px solid #d6e0f0;padding-bottom:5px}
.sheet h3{font-size:16px;margin:26px 0 8px;color:#1e3a8a}
.sheet h4{font-size:14px;margin:18px 0 6px;color:#172033}
.sheet h2 .n,.sheet h3 .n,.sheet h4 .n{color:#2563eb;margin-right:10px}
.sheet p{margin:6px 0 10px;text-align:justify}
.sheet table{margin:8px 0 18px}
.sheet td,.sheet th{font-size:12.5px}
.sheet ul,.sheet ol{margin:4px 0 12px;padding-left:22px}.sheet li{margin:3px 0}
p.statement{background:var(--soft);border-left:4px solid var(--accent);padding:12px 16px;font-weight:600;text-align:left}
p.note{color:var(--muted);font-size:12.5px}
.cover{min-height:1060px;display:flex;flex-direction:column;gap:26px;padding:0 14px}
.cover .kicker{font-size:13px;letter-spacing:2.5px;text-transform:uppercase;color:#2563eb;font-weight:700;margin-top:120px}
.cover h1{font-size:40px;line-height:1.15;margin:6px 0 0;color:#0f172a}
.cover .subtitle{font-size:17px;color:var(--muted);max-width:640px}
.cover .bar{height:6px;width:120px;background:#2563eb;border-radius:3px}
.cover table.facts{width:auto;min-width:420px;margin-top:auto}
.cover table.facts td{border:none;padding:4px 18px 4px 0;font-size:13.5px}
.cover table.facts td:first-child{color:var(--muted);font-weight:600}
.cover .synth{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}
.cover .synth div{border:1px solid var(--line);border-radius:10px;padding:10px 12px}
.cover .synth b{display:block;font-size:22px}.cover .synth span{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.4px}
.toc ol{list-style:none;padding:0;margin:0}.toc li{margin:5px 0;font-size:14px}
.toc li.l2{margin-left:26px;font-size:13px}.toc .n{display:inline-block;min-width:40px;color:#2563eb;font-weight:600}
.req{border:1px solid var(--line);border-radius:10px;margin:12px 0 16px;overflow:hidden;break-inside:avoid}
.req .rh{display:flex;gap:10px;align-items:center;background:#f1f5fb;padding:8px 12px;font-weight:700;font-size:13.5px}
.req .rh .rid{color:#1e3a8a;min-width:58px}.req .rh .chip{margin-left:auto}
.req table{margin:0}.req td{border-bottom:1px solid #eef1f6}.req tr:last-child td{border-bottom:none}
.req td:first-child{width:23%;color:var(--muted);font-weight:600;font-size:12px}
.req ul{margin:0;padding-left:18px}
figure{margin:14px 0 20px;text-align:center}figcaption{font-size:12px;color:var(--muted);margin-top:6px}
.pb{break-after:page}
@page{size:A4 portrait;margin:16mm 15mm 18mm 15mm}
@media print{body.doc{background:#fff}.sheet{box-shadow:none;margin:0;padding:0;max-width:none;border-radius:0}.doc .back{display:none}
.cover{min-height:0;height:255mm}.sheet h2,.sheet h3,.sheet h4{break-after:avoid}.req,figure,tr{break-inside:avoid}
svg.diagram{max-height:150mm}}
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


# Criticality = probability x impact: (label, colour, lowest score, highest score)
ZONES = (("c.low", "#16a34a", 1, 4), ("c.medium", "#eab308", 5, 9),
         ("c.high", "#ea580c", 10, 14), ("c.critical", "#dc2626", 15, 25))


def crit_class(score: float) -> tuple[str, str]:
    if score >= 15:
        return "c.critical", "#dc2626"
    if score >= 10:
        return "c.high", "#ea580c"
    if score >= 5:
        return "c.medium", "#eab308"
    return "c.low", "#16a34a"


def mix(color: str, t: float) -> str:
    """`color` faded towards white: t=1 is the colour itself, t=0 white."""
    rgb = [int(color[k:k + 2], 16) for k in (1, 3, 5)]
    return "#" + "".join(f"{round(255 - (255 - v) * t):02x}" for v in rgb)


def ink(bg: str) -> str:
    """Dark or white text, whichever reads on `bg`."""
    r, g, b = (int(bg[k:k + 2], 16) / 255 for k in (1, 3, 5))
    return "#172033" if 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.6 else "#fff"


def _pi(r: dict, residual: bool = False) -> tuple:
    """(probability, impact) of a risk, before or after its treatment;
    (None, None) when not set or off the 1-5 scale."""
    pre = "residual_" if residual else ""
    p, i = num(r.get(pre + "probability")), num(r.get(pre + "impact"))
    return (p, i) if p in range(1, 6) and i in range(1, 6) else (None, None)


def _pos(r: dict, after: bool = False) -> tuple:
    """Where a risk stands. After treatment, a risk with none planned stays put."""
    return (after and _pi(r, True)[0] and _pi(r, True)) or _pi(r)


def _score(r: dict, after: bool = False) -> int:
    p, i = _pos(r, after)
    return (p or 0) * (i or 0)


# Scrum Guide 2020: the timebox of an event for a one-month sprint, in
# minutes; shorter sprints get proportionally shorter events.
TIMEBOX = {"planning": 480, "review": 240, "retrospective": 180}
CEREMONY_KINDS = (("planning", ("planning", "planification")),
                  ("daily", ("daily", "mêlée", "melee", "stand-up", "standup")),
                  ("review", ("review", "revue", "démo", "demo")),
                  ("retrospective", ("retro", "rétro")),
                  ("refinement", ("refinement", "affinage", "affinement", "grooming", "raffinement")))


def ceremony_kind(cer: dict) -> str:
    if cer.get("kind") in {k for k, _ in CEREMONY_KINDS}:
        return cer["kind"]
    name = txt(cer.get("name")).lower()
    return next((kind for kind, words in CEREMONY_KINDS if any(w in name for w in words)), "")


def minutes(v) -> float | None:
    """'15 min', '2 h', '1 h 30', '1h30' → minutes; None when it is not a duration."""
    t = txt(v).lower().replace(",", ".")
    m = re.search(r"(\d+(?:\.\d+)?)\s*h(?:eures?|ours?|rs?)?\.?\s*(\d+)?", t)
    if m:
        return float(m.group(1)) * 60 + (float(m.group(2)) if m.group(2) else 0)
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:min|mn)", t)
    return float(m.group(1)) if m else None


def fmt_minutes(m: float) -> str:
    h, mn = divmod(int(round(m)), 60)
    return f"{mn} min" if not h else (f"{h} h" if not mn else f"{h} h {mn:02d}")


def sprint_weeks(c) -> int | None:
    """Sprint length in weeks, from the first dated sprint."""
    for sp in as_list(c.data.get("sprints", {}).get("sprints")):
        if isinstance(sp, dict):
            a, b = pdate(sp.get("start")), pdate(sp.get("end"))
            if a and b and a <= b:
                return max(1, math.ceil(((b - a).days + 1) / 7))
    return None


def timebox(kind: str, weeks) -> float | None:
    if kind == "daily":
        return 15
    if kind in TIMEBOX:
        return TIMEBOX[kind] * min(weeks or 4, 4) / 4
    return None


def velocity(c) -> float | None:
    """Points per sprint: the stated velocity, else the capacity of the sprint to come."""
    d = c.data.get("sprints") if isinstance(c.data.get("sprints"), dict) else {}
    if num(d.get("velocity")):
        return num(d["velocity"])
    today = dt.date.today()
    for sp in as_list(d.get("sprints")):
        if isinstance(sp, dict) and pdate(sp.get("end")) and pdate(sp["end"]) >= today and num(sp.get("capacity")):
            return num(sp["capacity"])
    return None


def ready_ahead(c, stories) -> float:
    """Points ready for the next Sprint Planning: ready, not in a sprint already started."""
    today = dt.date.today()
    started = {str(sp.get("id")) for sp in as_list(c.data.get("sprints", {}).get("sprints"))
               if isinstance(sp, dict) and pdate(sp.get("start")) and pdate(sp["start"]) <= today}
    return sum(num(s.get("points"), 0) or 0 for s in stories
               if isinstance(s, dict) and s.get("status") == "ready" and str(s.get("sprint") or "") not in started)


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
            d = None if stem in VIEWS else self._read(stem)
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
        kind = st.get("type", "story")
        if kind not in ITEM_TYPES:
            c.err(s, f"{sid}: type must be one of {', '.join(ITEM_TYPES)}")
        if kind == "story":
            for k in ("as", "want", "so_that"):
                if not str(st.get(k) or "").strip():
                    c.err(s, f"{sid}: missing {k!r} (En tant que / je veux / afin de)")
        elif not txt(st.get("title")).strip():
            c.err(s, f"{sid}: missing 'title'")
        if kind == "spike" and not st.get("timebox"):
            c.warn(s, f"{sid}: a spike needs a 'timebox' (\"2 jours\"): it buys knowledge, not a feature")
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
        known = _cdc_ids(c)
        for rid in as_list(st.get("requirements")):
            if known is not None and str(rid) not in known:
                c.err(s, f"{sid}: requirement {rid!r} is not in cahier-des-charges.json")
    items = [st for st in stories if isinstance(st, dict)]
    first_wont = next((i for i, st in enumerate(items) if st.get("priority") == "wont"), None)
    if first_wont is not None:
        late = next((st for st in items[first_wont:] if st.get("priority") == "must"), None)
        if late:
            c.warn(s, f"{late.get('id')} (must) comes after {items[first_wont].get('id')} (wont): "
                      f"the array order is the backlog order")
    if len(items) > 150:
        c.warn(s, f"{len(items)} items: past 150 nobody reads it — archive, merge, keep epics coarse")
    dod = [txt(x) for x in as_list(d.get("definition_of_done"))]
    if not dod:
        c.warn(s, "no definition_of_done: the Increment has no commitment (Scrum Guide 2020)")
    elif not 5 <= len(dod) <= 15:
        c.warn(s, f"definition_of_done has {len(dod)} criteria: aim for 5 to 15, each checkable yes or no")
    for x in dod:
        m = VAGUE.search(x) or re.search(r"\b(propres?|clean|correcte?s?)\b", x, re.IGNORECASE)
        if m:
            c.warn(s, f"definition_of_done: {x!r} — {m.group(0)!r} cannot be checked yes or no")
    if not as_list(d.get("definition_of_ready")):
        c.warn(s, "no definition_of_ready: say when an item may enter a sprint")
    vel = velocity(c)
    ahead = ready_ahead(c, items)
    if vel and ahead < vel:
        c.warn(s, f"only {ahead} points are ready for a velocity of {vel}: refine the top of the "
                  f"backlog before the next Sprint Planning")


def check_sprints(d, c, s="sprints"):
    sprints = as_list(d.get("sprints"))
    if not sprints:
        c.err(s, "no 'sprints'")
    _ids(c, s, sprints, "sprints")
    known = c.stories()
    weeks: set[int] = set()
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
        if not txt(sp.get("goal")).strip():
            c.warn(s, f"{sid}: no sprint goal — it is the Sprint Backlog's commitment")
        for t in as_list(sp.get("tasks")):
            if isinstance(t, dict) and (num(t.get("hours"), 0) or 0) > 8:
                c.warn(s, f"{sid}: task {t.get('title')!r} is {t['hours']} h — split it into work of a day or less")
        start, end = pdate(a), pdate(b)
        if start and end and start <= end:
            days = (end - start).days + 1
            weeks.add(math.ceil(days / 7))
            if days > 31:
                c.warn(s, f"{sid}: {days} days — a sprint lasts one month or less")
            if end < dt.date.today() and not sp.get("retrospective"):
                c.warn(s, f"{sid} is over and has no retrospective recorded")
    if len(weeks) > 1:
        c.warn(s, f"sprints last {', '.join(map(str, sorted(weeks)))} weeks: keep one length for every sprint")


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
            if num(r.get(k)) not in range(1, 6):
                c.err(s, f"{rid}: {k} must be a whole number from 1 to 5")
        if not r.get("owner"):
            c.warn(s, f"{rid}: no owner")
        score = (num(r.get("probability"), 0) or 0) * (num(r.get("impact"), 0) or 0)
        if score >= 10 and not r.get("prevention"):
            c.warn(s, f"{rid}: score {score} and no prevention")
        if r.get("residual_probability") is None and r.get("residual_impact") is None:
            continue
        bad = [k for k in ("residual_probability", "residual_impact") if num(r.get(k)) not in range(1, 6)]
        for k in bad:
            c.err(s, f"{rid}: {k} must be a whole number from 1 to 5 (or leave both out)")
        if bad or not _pi(r)[0]:
            continue
        after = num(r["residual_probability"]) * num(r["residual_impact"])
        if after > score:
            c.warn(s, f"{rid}: residual score {after} is above the initial {score}")
        elif after < score and not r.get("prevention"):
            c.warn(s, f"{rid}: the score drops to {after} with no prevention to explain it")


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
    weeks = sprint_weeks(c)
    for cer in as_list(d.get("ceremonies")):
        if not isinstance(cer, dict):
            continue
        kind = ceremony_kind(cer)
        limit, got = timebox(kind, weeks), minutes(cer.get("duration"))
        if limit and got and got > limit:
            span = "" if kind == "daily" else f" for a {weeks or 4}-week sprint"
            c.warn(s, f"{cer.get('name')}: {fmt_minutes(got)} is over the Scrum Guide timebox of "
                      f"{fmt_minutes(limit)}{span}")


# Words that make a requirement impossible to verify unless a level says how much.
VAGUE = re.compile(r"\b(rapides?|rapidement|simples?|simplement|faciles?|facilement|intuitifs?|intuitives?"
                   r"|conviviale?s?|ergonomiques?|performante?s?|optimale?s?|efficaces?|modernes?"
                   r"|robustes?|fluides?|user-friendly|fast|easy|intuitive|efficient|robust|modern"
                   r"|seamless|etc)\b", re.IGNORECASE)
NFR_CATEGORIES = ("performance", "security", "availability", "usability", "compatibility",
                  "maintainability", "portability", "compliance", "operability", "other")
VERIFICATION = ("test", "inspection", "analysis", "demonstration")
FLEX = ("F0", "F1", "F2", "F3")
DOC_STATUS = ("brouillon", "en revue", "validé", "draft", "in review", "approved")
DIRECTIONS = ("entrant", "sortant", "bidirectionnel", "in", "out", "both")


def _cdc_ids(c) -> set[str] | None:
    """Requirement ids of the specification, or None when there is none."""
    d = c.data.get("cahier-des-charges")
    if not isinstance(d, dict):
        return None
    return {str(r.get("id")) for r in as_list(d.get("requirements")) + as_list(d.get("non_functional"))
            if isinstance(r, dict) and r.get("id")}


def _fn_ids(c) -> dict[str, dict]:
    return {str(f.get("id")): f for f in as_list(c.data.get("pieuvre", {}).get("functions"))
            if isinstance(f, dict) and f.get("id")}


def _actors(c, d) -> set[str]:
    """Everyone a requirement may name as its actor, lower-cased."""
    names = {txt(u.get("role")) for u in as_list(d.get("users")) if isinstance(u, dict)}
    for p in as_list(c.data.get("discovery", {}).get("personas")):
        if isinstance(p, dict):
            names |= {txt(p.get("role")), txt(p.get("name"))}
    for s in as_list(c.data.get("parties-prenantes", {}).get("stakeholders")):
        if isinstance(s, dict):
            names |= {txt(s.get("role")), txt(s.get("name"))}
    for r in as_list(c.data.get("raci", {}).get("roles")):
        if isinstance(r, dict):
            names |= {txt(r.get("label")), txt(r.get("name"))}
    names |= {txt(r.get("role")) for r in as_list((d.get("organisation") or {}).get("roles")) if isinstance(r, dict)}
    return {n.strip().lower() for n in names if n.strip()} | {"système", "system", "administrateur", "administrator"}


def check_cdc(d, c, s="cahier-des-charges"):
    doc = d.get("document") if isinstance(d.get("document"), dict) else {}
    if doc.get("status") and str(doc["status"]).lower() not in DOC_STATUS:
        c.warn(s, f"document.status should be one of {', '.join(DOC_STATUS[:3])}")
    ctx = d.get("context") if isinstance(d.get("context"), dict) else {}
    if not (txt(ctx.get("background")).strip() or txt(ctx.get("current")).strip()):
        c.err(s, "context: say why the project exists (background) and what exists today (current)")
    seen: set[str] = set()

    def unique(items, what):
        """Ids are unique across objectives and both kinds of requirement."""
        for i, it in enumerate(as_list(items)):
            if not isinstance(it, dict):
                c.err(s, f"{what}[{i}] must be an object")
            elif not str(it.get("id") or "").strip():
                c.err(s, f"{what}[{i}] has no id")
            elif str(it["id"]) in seen:
                c.err(s, f"id {it['id']!r} is used twice ({what})")
            else:
                seen.add(str(it["id"]))

    objectives = [o for o in as_list(d.get("objectives")) if isinstance(o, dict)]
    if not objectives:
        c.err(s, "no 'objectives': a specification states what success is")
    unique(d.get("objectives"), "objectives")
    for o in objectives:
        if not (o.get("indicator") and o.get("target")):
            c.warn(s, f"{o.get('id')}: an objective needs an indicator and a target to be measured")
    scope = d.get("scope") if isinstance(d.get("scope"), dict) else {}
    if not as_list(scope.get("in")):
        c.err(s, "scope.in is empty")
    if not as_list(scope.get("out")):
        c.warn(s, "scope.out is empty: write the exclusions, or they may be claimed as included")

    fns = _fn_ids(c)
    if not fns:
        c.warn(s, "no pieuvre.json: the functional analysis section is empty (run the cadrage step)")
    modules = {str(m.get("id")) for m in as_list(d.get("modules")) if isinstance(m, dict) and m.get("id")}
    actors = _actors(c, d)
    reqs = [r for r in as_list(d.get("requirements")) if isinstance(r, dict)]
    if not reqs:
        c.err(s, "no functional 'requirements'")
    unique(d.get("requirements"), "requirements")
    for r in reqs:
        rid = r.get("id")
        if not txt(r.get("title")).strip() or not txt(r.get("description")).strip():
            c.err(s, f"{rid}: needs a title and a description")
        if r.get("priority") not in PRIORITIES:
            c.err(s, f"{rid}: priority must be one of {', '.join(PRIORITIES)}")
        if r.get("module") and str(r["module"]) not in modules:
            c.err(s, f"{rid}: unknown module {r['module']!r}")
        for f in as_list(r.get("functions")):
            if fns and str(f) not in fns:
                c.err(s, f"{rid}: function {f!r} is not in pieuvre.json")
        if fns and not as_list(r.get("functions")):
            c.warn(s, f"{rid}: linked to no function of the pieuvre")
        if r.get("priority") == "must" and not as_list(r.get("acceptance")):
            c.err(s, f"{rid}: a must-have requirement needs acceptance criteria, or nobody can accept it")
        actor = txt(r.get("actor")).strip().lower()
        if actor and not any(actor == a or actor in a or a in actor for a in actors):
            c.warn(s, f"{rid}: actor {r.get('actor')!r} is not a user, persona or stakeholder of the project")
        m = VAGUE.search(f"{txt(r.get('title'))} {txt(r.get('description'))}")
        if m:
            c.warn(s, f"{rid}: {m.group(0)!r} cannot be verified — say how much, or move it to a non-functional requirement with a level")

    nfr = [r for r in as_list(d.get("non_functional")) if isinstance(r, dict)]
    if not nfr:
        c.err(s, "no 'non_functional' requirements (performance, security, accessibility...)")
    unique(d.get("non_functional"), "non_functional")
    for r in nfr:
        rid = r.get("id")
        if r.get("category") not in NFR_CATEGORIES:
            c.warn(s, f"{rid}: category should be one of {', '.join(NFR_CATEGORIES)}")
        if not txt(r.get("level")).strip():
            c.err(s, f"{rid}: no 'level' — a non-functional requirement without a level cannot be verified")
        elif VAGUE.search(txt(r.get("level"))):
            c.warn(s, f"{rid}: level {r.get('level')!r} is not measurable")
        if r.get("flexibility") is not None and r.get("flexibility") not in FLEX:
            c.err(s, f"{rid}: flexibility must be one of F0 F1 F2 F3")
        elif r.get("flexibility") is None:
            c.warn(s, f"{rid}: no flexibility (F0 to F3)")
        if r.get("verification") and r.get("verification") not in VERIFICATION:
            c.warn(s, f"{rid}: verification should be one of {', '.join(VERIFICATION)}")
        for f in as_list(r.get("functions")):
            if fns and str(f) not in fns:
                c.err(s, f"{rid}: function {f!r} is not in pieuvre.json")
    for x in as_list(d.get("extra_criteria")):
        if not isinstance(x, dict):
            continue
        if fns and str(x.get("function")) not in fns:
            c.err(s, f"extra_criteria: function {x.get('function')!r} is not in pieuvre.json")
        if x.get("flexibility") is not None and x.get("flexibility") not in FLEX:
            c.err(s, f"extra_criteria {x.get('function')}: flexibility must be one of F0 F1 F2 F3")

    linked = {str(f) for r in reqs + nfr for f in as_list(r.get("functions"))}
    for fid in fns:
        if fid not in linked:
            c.warn(s, f"function {fid} of the pieuvre is satisfied by no requirement")
    stories = [st for st in as_list(c.data.get("product-backlog", {}).get("stories")) if isinstance(st, dict)]
    if stories:
        done = {str(x) for st in stories for x in as_list(st.get("requirements"))}
        if not done:
            c.warn(s, "no user story names the requirement it implements: run the backlog step again")
        else:
            for r in reqs:
                if r.get("priority") == "must" and str(r.get("id")) not in done:
                    c.warn(s, f"{r.get('id')}: must-have requirement implemented by no user story")

    tech = d.get("technical") if isinstance(d.get("technical"), dict) else {}
    for it in as_list(tech.get("interfaces")):
        if isinstance(it, dict) and it.get("direction") and str(it["direction"]).lower() not in DIRECTIONS:
            c.warn(s, f"interface {it.get('system')!r}: direction should be one of {', '.join(DIRECTIONS[:3])}")
    for m in as_list(d.get("milestones")):
        if not isinstance(m, dict) or not pdate(m.get("date")):
            c.err(s, f"milestone {txt(m)!r}: date must be YYYY-MM-DD")
    budget = d.get("budget") if isinstance(d.get("budget"), dict) else {}
    amounts = [num(i.get("amount")) for i in as_list(budget.get("items")) if isinstance(i, dict)]
    if any(a is None for a in amounts):
        c.err(s, "budget.items: every amount must be a number")
    env = num(budget.get("envelope"))
    if env is not None and sum(a or 0 for a in amounts) > env:
        c.warn(s, f"budget: the items add up to {sum(a or 0 for a in amounts)}, above the envelope of {env}")
    resp = d.get("response") if isinstance(d.get("response"), dict) else {}
    weights = [num(x.get("weight")) for x in as_list(resp.get("criteria")) if isinstance(x, dict)]
    if weights and sum(w or 0 for w in weights) != 100:
        c.err(s, f"response.criteria: the weights add up to {sum(w or 0 for w in weights)}, not 100")
    if not as_list(d.get("glossary")):
        c.warn(s, "no glossary: define every acronym and business term the document uses")


CHECKS = {"bete-a-cornes": check_bete, "pieuvre": check_pieuvre, "swot": check_swot,
          "parties-prenantes": check_stakeholders, "raci": check_raci,
          "discovery": check_discovery, "cahier-des-charges": check_cdc,
          "product-backlog": check_backlog,
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
                         f"<div class='id'>{esc(it.get('id'))} {chip(c.t(str(it.get('type'))), color)}"
                         f"{chip(it['method'], '#f1f5f9', '#334155') if it.get('method') else ''}</div>"
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
    if st.get("type", "story") != "story":       # a bug, a technical item, a spike: no persona
        return esc(st.get("description") or "") + (f" <b>· {esc(st['timebox'])}</b>" if st.get("timebox") else "")
    return (f"<b>{esc(c.t('as'))}</b> {esc(st.get('as'))}, <b>{esc(c.t('want'))}</b> "
            f"{esc(st.get('want'))} <b>{esc(c.t('so_that'))}</b> {esc(st.get('so_that'))}")


def _type_chip(st, c) -> str:
    kind = st.get("type", "story")
    return chip(c.t("type." + kind), TYPE_COLOR.get(kind, "#64748b")) if kind != "story" else ""


def _health(d, c) -> str:
    """Is the backlog ready for the next Sprint Planning? Estimates, acceptance
    criteria, ready points against the velocity, and the shape of the backlog:
    detailed at the top, coarse below (roughly 20 / 30 / 50 %)."""
    items = [s for s in as_list(d.get("stories")) if isinstance(s, dict)]
    open_ = [s for s in items if s.get("status") != "done" and s.get("priority") != "wont"]
    if not open_:
        return ""
    n = len(open_)
    est = sum(1 for s in open_ if num(s.get("points")) is not None)
    acc = sum(1 for s in open_ if as_list(s.get("acceptance")))
    ready = [s for s in open_ if s.get("status") in ("ready", "doing")]
    refined = [s for s in open_ if s not in ready and num(s.get("points")) is not None and as_list(s.get("acceptance"))]
    rough = n - len(ready) - len(refined)
    vel, ahead = velocity(c), ready_ahead(c, items)
    tiles = [(n, c.t("h.items")), (f"{round(100 * est / n)} %", c.t("h.estimated")),
             (f"{round(100 * acc / n)} %", c.t("h.accepted")),
             (f"{ahead:g} pts", c.t("h.ready_pts") + (f" · {ahead / vel:.1f} {c.t('h.covers')}" if vel else ""))]
    segs = [(len(ready), "#16a34a", c.t("h.ready")), (len(refined), "#2563eb", c.t("h.refined")),
            (rough, "#94a3b8", c.t("h.rough"))]
    bar = "".join(f"<i style='width:{100 * k / n:.1f}%;background:{col}' title='{esc(label)}'></i>" for k, col, label in segs if k)
    legend = " &nbsp; ".join(f"{chip(f'{label} · {round(100 * k / n)} %', col)}" for k, col, label in segs)
    return (f"<div class='health'><h3>{esc(c.t('health'))}</h3><div class='kpis' style='margin:0 0 12px'>"
            + "".join(f"<div class='kpi'><b>{esc(v)}</b><span>{esc(label)}</span></div>" for v, label in tiles)
            + f"</div><div class='small muted'>{esc(c.t('h.shape'))}</div>"
            f"<div class='bar' style='height:14px;display:flex;margin:6px 0 8px'>{bar}</div>"
            f"<p class='small'>{legend} &nbsp; <span class='muted'>{esc(c.t('h.target'))}</span></p></div>")


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
            f"{_type_chip(s, c)}{chip(c.t(str(s.get('priority'))), PRIO_COLOR.get(s.get('priority'), '#64748b'))}"
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
        f"<td><div style='font-weight:600'>{_type_chip(s, c)} {esc(s.get('title') or '')}</div><div class='small'>{_story_line(s, c)}</div></td>"
        f"<td class='small'>{ul(s.get('acceptance'))}</td>"
        f"<td>{chip(c.t(str(s.get('priority'))), PRIO_COLOR.get(s.get('priority'), '#64748b'))}</td>"
        f"<td>{esc(s.get('value') if s.get('value') is not None else '')}</td><td><b>{esc(num(s.get('points'), ''))}</b></td>"
        f"<td>{chip(c.t('s.' + str(s.get('status', 'todo'))), STATUS_COLOR.get(s.get('status', 'todo'), '#64748b'))}</td>"
        f"<td>{esc(s.get('sprint') or '')}</td></tr>" for s in stories)
    details = _health(d, c)
    details += (f"<h3>{esc(c.t('epics'))}</h3><div class='grid cards'>{''.join(ecards)}</div>" if ecards else "")
    details += (f"<h3>{esc(c.t('stories'))}</h3><table><thead><tr><th>ID</th><th>User story</th>"
                f"<th>{esc(c.t('acceptance'))}</th><th>{esc(c.t('priority'))}</th><th>{esc(c.t('value'))}</th>"
                f"<th>{esc(c.t('points'))}</th><th>{esc(c.t('status'))}</th><th>{esc(c.t('sprint'))}</th></tr></thead>{rows}</table>")
    dor, dod = as_list(d.get("definition_of_ready")), as_list(d.get("definition_of_done"))
    if dor or dod:
        details += (f"<div class='split' style='margin-top:18px'><div class='card'><h4>{esc(c.t('dor'))}</h4>{ul(dor)}</div>"
                    f"<div class='card'><h4>{esc(c.t('dod'))}</h4>{ul(dod)}</div></div>")
    return fig, details


def _team(c) -> dict[str, str]:
    """Who holds each accountability, from the most explicit file that names it:
    the specification's roles, then the RACI, then the stakeholders."""
    words = {"po": ("product owner",), "sm": ("scrum master",), "devs": ("develop", "dévelop")}
    sources = [[(txt(r.get("role")), txt(r.get("name"))) for r in as_list(obj(c.data.get("cahier-des-charges", {}).get("organisation")).get("roles")) if isinstance(r, dict)],
               [(txt(r.get("label")), txt(r.get("name"))) for r in as_list(c.data.get("raci", {}).get("roles")) if isinstance(r, dict)],
               [(txt(x.get("role")), txt(x.get("name"))) for x in as_list(c.data.get("parties-prenantes", {}).get("stakeholders")) if isinstance(x, dict)]]
    found = {}
    for key, keys in words.items():
        for source in sources:
            names = [n for label, n in source if any(w in label.lower() for w in keys) and n and n.lower() not in label.lower()]
            if names:
                found[key] = ", ".join(names)
                break
    return found


def draw_framework(d, c):
    """The Scrum Guide 2020 on one page, filled with this project: the three
    artefacts and their commitments, the Scrum Team, the events and their timeboxes."""
    items = [s for s in as_list(d.get("stories")) if isinstance(s, dict)]
    stories = {str(s.get("id")): s for s in items}
    pts = lambda ss: sum(num(s.get("points"), 0) or 0 for s in ss)
    open_ = [s for s in items if s.get("status") != "done" and s.get("priority") != "wont"]
    done = [s for s in items if s.get("status") == "done"]
    sprints = [s for s in as_list(c.data.get("sprints", {}).get("sprints")) if isinstance(s, dict)]
    cur = _current_sprint(sprints)
    dod = [txt(x) for x in as_list(d.get("definition_of_done")) if txt(x).strip()]
    t = c.t

    boxes = [("c.pb", "#2563eb", "c.pg", txt(d.get("product_goal")) or t("c.no_goal"),
              f"{len(open_)} {t('c.items')} · {pts(open_):g} pts · {ready_ahead(c, items):g} pts {t('c.ready')}")]
    if cur:
        ids = [str(x) for x in as_list(cur.get("stories"))]
        tasks = [x for x in as_list(cur.get("tasks")) if isinstance(x, dict)]
        boxes.append(("c.sb", "#7c3aed", "c.sg", txt(cur.get("goal")) or t("c.no_goal"),
                      f"{cur.get('name') or cur.get('id')} · {len(ids)} stories · {pts(stories.get(i, {}) for i in ids):g} pts · "
                      f"{sum(1 for x in tasks if x.get('status') == 'done')}/{len(tasks)} {t('c.tasks')}"))
    else:
        boxes.append(("c.sb", "#7c3aed", "c.sg", t("c.no_sprint"), ""))
    boxes.append(("c.inc", "#16a34a", "c.dod", " · ".join(dod) or t("c.no_goal"),
                  f"{len(done)} stories {t('c.done')} · {pts(done):g} pts · DoD : {len(dod)} {t('c.criteria')}"))

    W, H, bw, bh, by = 1000, 400, 262, 252, 30
    xs = (20, 369, 718)
    s = [f'<svg viewBox="0 0 {W} {H}" class="diagram" role="img">', _arrow_defs("arr-scrum")]
    for x, (name, color, commit, text, stats) in zip(xs, boxes):
        s.append(f'<rect x="{x}" y="{by}" width="{bw}" height="{bh}" rx="14" fill="#fff" stroke="{color}" stroke-width="2"/>'
                 f'<path d="M{x},{by + 14} a14,14 0 0 1 14,-14 h{bw - 28} a14,14 0 0 1 14,14 v30 h-{bw} z" fill="{color}"/>'
                 f'<text x="{x + bw / 2}" y="{by + 23}" text-anchor="middle" dominant-baseline="central" font-size="17" '
                 f'font-weight="700" fill="#fff">{esc(t(name))}</text>'
                 f'<text x="{x + 16}" y="{by + 64}" font-size="11" font-weight="700" fill="{color}" letter-spacing=".6">'
                 f'{esc((t("c.commit") + " : " + t(commit)).upper())}</text>')
        s.append(svg_text(x + 16, by + 90, text, bw - 32, size=13.5, anchor="start", weight=600, max_lines=5, valign="top"))
        s.append(f'<line x1="{x + 16}" x2="{x + bw - 16}" y1="{by + bh - 52}" y2="{by + bh - 52}" stroke="#e2e8f0"/>')
        s.append(svg_text(x + 16, by + bh - 34, stats, bw - 32, size=11.5, anchor="start", fill="#5b6b7d", max_lines=2, valign="top"))
    for x, label in ((xs[0] + bw, "c.planning"), (xs[1] + bw, "c.during")):
        s.append(f'<line x1="{x + 6}" y1="{by + bh / 2}" x2="{x + 81}" y2="{by + bh / 2}" stroke="#334155" '
                 f'stroke-width="2.4" marker-end="url(#arr-scrum)"/>')
        s.append(svg_text(x + 44, by + bh / 2 - 30, t(label), 80, size=11.5, weight=600, fill="#334155", max_lines=3))
    loop_y = by + bh + 44
    s.append(f'<path d="M{xs[2] + bw / 2},{by + bh + 4} V{loop_y} H{xs[0] + bw / 2} V{by + bh + 8}" fill="none" '
             f'stroke="#16a34a" stroke-width="2.4" stroke-dasharray="7 5" marker-end="url(#arr-scrum)"/>')
    s.append(f'<text x="{W / 2}" y="{loop_y + 22}" text-anchor="middle" font-size="12.5" font-weight="600" fill="#166534">'
             f'↺ {esc(t("c.loop"))}</text>'
             f'<text x="{W / 2}" y="{loop_y + 44}" text-anchor="middle" font-size="12" fill="#5b6b7d">↻ {esc(t("c.retro_loop"))}</text>'
             f'<text x="{W / 2}" y="{H - 10}" text-anchor="middle" font-size="11.5" fill="#94a3b8">'
             f'{esc(t("pillars"))} · {esc(t("values"))}</text></svg>')

    team = _team(c)
    cards = "".join(f"<div class='card'><h4>{esc(t(k))}</h4><b>{esc(team.get(k) or t('unassigned'))}</b>"
                    f"<div class='small muted' style='margin-top:6px'>{esc(t(k + '_acc' if k != 'devs' else 'dev_acc'))}</div></div>"
                    for k in ("po", "sm", "devs"))
    weeks = sprint_weeks(c)
    planned = {}
    for cer in as_list(c.data.get("planning", {}).get("ceremonies")):
        if isinstance(cer, dict) and ceremony_kind(cer):
            planned.setdefault(ceremony_kind(cer), cer)
    rows = [f"<tr><td><b>{esc(t('e.sprint'))}</b></td><td>{esc(t('tb.sprint').format(w=weeks or '?'))}</td>"
            f"<td>{esc(f'{weeks} sem.' if weeks and c.lang == 'fr' else f'{weeks} wk' if weeks else t('not_planned'))}</td><td></td></tr>"]
    for kind in ("planning", "daily", "review", "retrospective", "refinement"):
        limit = timebox(kind, weeks)
        box = (f"≤ {fmt_minutes(limit)}" + ("" if kind == "daily" else f" — {t('tb.weeks').format(w=weeks or 4)}")
               if limit else t("tb.refinement"))
        cer = planned.get(kind)
        got = minutes(cer.get("duration")) if cer else None
        if not cer:
            state = chip(t("not_planned"), "#94a3b8")
        elif limit and got and got > limit:
            state = chip("⚠ > timebox", "#dc2626")
        else:
            state = chip("✓", "#16a34a")
        what = f"{txt(cer.get('duration'))} — {txt(cer.get('when'))}".strip(" —") if cer else ""
        rows.append(f"<tr><td><b>{esc(t('e.' + kind))}</b></td><td>{esc(box)}</td><td>{esc(what)}</td><td>{state}</td></tr>")
    details = (f"<h3>{esc(t('team'))}</h3><div class='grid cards'>{cards}</div>"
               f"<h3>{esc(t('ceremonies'))}</h3><table><thead><tr><th>{esc(t('event'))}</th><th>{esc(t('timebox'))}</th>"
               f"<th>{esc(t('planned'))}</th><th></th></tr></thead>{''.join(rows)}</table>")
    return "".join(s), details


def _quadrant(st) -> str:
    high = (num(st.get("value"), 0) or 0) >= 50
    small = (num(st.get("points"), 0) or 0) < 5
    return ("q.quick" if small else "q.major") if high else ("q.fill" if small else "q.avoid")


def draw_priority(d, c):
    """Value against effort: each open item placed by business value (1-100)
    and size (Fibonacci), coloured by its MoSCoW priority."""
    items = [s for s in as_list(d.get("stories")) if isinstance(s, dict)]
    placed = [s for s in items if num(s.get("points")) in FIB and num(s.get("value")) is not None
              and s.get("priority") != "wont"]
    pts = [num(s["points"]) for s in placed]
    axis = [v for v in sorted(FIB) if min([1] + pts) <= v <= max([13] + pts)]
    W, H, x0, y0, pw, ph = 940, 540, 70, 20, 840, 460
    col = pw / len(axis)
    X = lambda v: x0 + col * (axis.index(v) + 0.5)
    Y = lambda v: y0 + ph - ph * max(0, min(100, v)) / 100
    sx, sy = x0 + col * next((i for i, v in enumerate(axis) if v >= 5), len(axis)), Y(50)
    s = [f'<svg viewBox="0 0 {W} {H}" class="diagram" role="img">']
    for x1, y1, x2, y2, color, key, anchor, tx, ty in (
            (x0, y0, sx, sy, "#16a34a", "q.quick", "start", x0 + 12, y0 + 22),
            (sx, y0, x0 + pw, sy, "#2563eb", "q.major", "end", x0 + pw - 12, y0 + 22),
            (x0, sy, sx, y0 + ph, "#64748b", "q.fill", "start", x0 + 12, y0 + ph - 12),
            (sx, sy, x0 + pw, y0 + ph, "#dc2626", "q.avoid", "end", x0 + pw - 12, y0 + ph - 12)):
        s.append(f'<rect x="{x1:.1f}" y="{y1:.1f}" width="{x2 - x1:.1f}" height="{y2 - y1:.1f}" fill="{color}" fill-opacity=".07"/>'
                 f'<text x="{tx:.1f}" y="{ty:.1f}" text-anchor="{anchor}" font-size="14" font-weight="700" fill="{color}">{esc(c.t(key))}</text>')
    s.append(f'<rect x="{x0}" y="{y0}" width="{pw}" height="{ph}" fill="none" stroke="#cbd5e1"/>'
             f'<line x1="{sx:.1f}" x2="{sx:.1f}" y1="{y0}" y2="{y0 + ph}" stroke="#94a3b8" stroke-dasharray="5 4"/>'
             f'<line x1="{x0}" x2="{x0 + pw}" y1="{sy:.1f}" y2="{sy:.1f}" stroke="#94a3b8" stroke-dasharray="5 4"/>')
    for v in axis:
        s.append(f'<text x="{X(v):.1f}" y="{y0 + ph + 18}" text-anchor="middle" font-size="12" fill="#475569">{v:g}</text>')
    for v in (0, 25, 50, 75, 100):
        s.append(f'<text x="{x0 - 8}" y="{Y(v):.1f}" text-anchor="end" dominant-baseline="central" font-size="11" fill="#64748b">{v}</text>')
    s.append(f'<text x="{x0 + pw / 2}" y="{H - 6}" text-anchor="middle" font-size="13" font-weight="600" fill="#334155">{esc(c.t("effort"))} →</text>'
             f'<text transform="translate(18,{y0 + ph / 2}) rotate(-90)" text-anchor="middle" font-size="13" font-weight="600" fill="#334155">{esc(c.t("value"))} →</text>')
    by_col: dict = {}
    for st in placed:
        by_col.setdefault(num(st["points"]), []).append(st)
    for v, group in by_col.items():
        last = None
        for st in sorted(group, key=lambda st: -num(st["value"])):
            y = Y(num(st["value"]))
            y = y if last is None else max(y, last + 21)       # one under the other, never on top
            last = y = min(y, y0 + ph - 11)
            label = str(st.get("id", ""))[:7]
            w = 14 + 6.8 * len(label)
            fade = ' opacity=".45"' if st.get("status") == "done" else ""
            s.append(f'<g{fade}><rect x="{X(v) - w / 2:.1f}" y="{y - 9.5:.1f}" width="{w:.1f}" height="19" rx="9.5" '
                     f'fill="{PRIO_COLOR.get(st.get("priority"), "#64748b")}"/><text x="{X(v):.1f}" y="{y:.1f}" '
                     f'text-anchor="middle" dominant-baseline="central" font-size="10.5" font-weight="700" fill="#fff">'
                     f'{esc(label)}</text></g>')
    s.append("</svg>")
    legend = " &nbsp; ".join(chip(c.t(p), PRIO_COLOR[p]) for p in PRIORITIES[:3])
    fig = "".join(s) + f"<p class='small muted' style='text-align:center'>{legend}</p>"
    rows = []
    for k, st in enumerate(items, 1):
        p, v = num(st.get("points")), num(st.get("value"))
        ratio = f"{v / p:.1f}" if p and v is not None else "—"
        rows.append(f"<tr><td>{k}</td><td><b>{esc(st.get('id'))}</b></td><td>{_type_chip(st, c)} {esc(st.get('title') or '')}</td>"
                    f"<td>{chip(c.t(str(st.get('priority'))), PRIO_COLOR.get(st.get('priority'), '#64748b'))}</td>"
                    f"<td>{esc(v if v is not None else '')}</td><td>{esc(p if p is not None else '')}</td><td>{ratio}</td>"
                    f"<td>{esc(c.t(_quadrant(st))) if st in placed else '—'}</td></tr>")
    details = (f"<h3>{esc(c.t('order_title'))}</h3><table><thead><tr><th>{esc(c.t('rank'))}</th><th>ID</th>"
               f"<th>{esc(c.t('pbi'))}</th><th>{esc(c.t('priority'))}</th><th>{esc(c.t('value'))}</th>"
               f"<th>{esc(c.t('points'))}</th><th>{esc(c.t('ratio'))}</th><th>{esc(c.t('quadrant'))}</th></tr></thead>"
               f"{''.join(rows)}</table>")
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
    return head + board + burn + _inspect(sp, c, stories)


def _inspect(sp, c, stories) -> str:
    """Once a sprint has started: its Increment (the items done to the DoD),
    what the Sprint Review changed and what the retrospective decided."""
    a = pdate(sp.get("start"))
    if not a or a > dt.date.today():
        return ""
    ids = [str(x) for x in as_list(sp.get("stories"))]
    done = [f"{x} — {txt(stories.get(x, {}).get('title'))}" for x in ids if stories.get(x, {}).get("status") == "done"]
    rev, ret = obj(sp.get("review")), obj(sp.get("retrospective"))
    cards = [f"<div class='card' style='border-left:5px solid #16a34a'><h4>{esc(c.t('increment'))}</h4>"
             f"<div class='small muted'>{esc(c.t('inc_lead'))}</div>{ul(done) or '<p class=small>—</p>'}</div>"]
    if rev:
        cards.append(f"<div class='card' style='border-left:5px solid #2563eb'><h4>{esc(c.t('review'))}</h4>"
                     + (f"<div class='small muted'>{esc(c.t('feedback'))}</div>{ul(rev.get('feedback'))}" if as_list(rev.get("feedback")) else "")
                     + (f"<div class='small muted'>{esc(c.t('backlog_changes'))}</div>{ul(rev.get('backlog_changes'))}" if as_list(rev.get("backlog_changes")) else "")
                     + "</div>")
    if ret:
        actions = [f"{txt(x.get('action'))}" + (f" — {txt(x.get('owner'))}" if txt(x.get('owner')).strip() else "")
                   if isinstance(x, dict) else txt(x) for x in as_list(ret.get("actions"))]
        cards.append(f"<div class='card' style='border-left:5px solid #7c3aed'><h4>{esc(c.t('retro'))}</h4>"
                     + "".join(f"<div class='small muted'>{esc(c.t(k))}</div>{ul(v)}"
                               for k, v in (("went_well", ret.get("went_well")), ("to_improve", ret.get("to_improve")),
                                            ("actions", actions)) if as_list(v))
                     + "</div>")
    return f"<div class='grid cards' style='margin-top:16px'>{''.join(cards)}</div>"


def _progress(sprints, stories, c) -> str:
    """Velocity (committed against done, for the sprints that are over) and
    the product burn-up (points done against the scope, up to today)."""
    today = dt.date.today()
    started = [sp for sp in sprints if pdate(sp.get("start")) and pdate(sp["start"]) <= today]
    if not started:
        return ""
    pts = lambda ids, only_done=False: sum(num(stories.get(str(x), {}).get("points"), 0) or 0 for x in ids
                                           if not only_done or stories.get(str(x), {}).get("status") == "done")
    bars = [(str(sp.get("id")), pts(as_list(sp.get("stories"))), pts(as_list(sp.get("stories")), True))
            for sp in started if pdate(sp.get("end")) and pdate(sp["end"]) < today]
    W, H, x0, y0, pw, ph = 440, 240, 40, 14, 386, 180
    top = max([1] + [b[1] for b in bars])
    top = math.ceil(top / 5) * 5
    Y = lambda v: y0 + ph - ph * v / top
    slot = pw / max(1, len(bars))
    v = [f'<svg viewBox="0 0 {W} {H}" class="diagram" role="img" style="max-width:460px">']
    for k in range(6):
        val = top * k / 5
        v.append(f'<line x1="{x0}" x2="{x0 + pw}" y1="{Y(val):.1f}" y2="{Y(val):.1f}" stroke="#e2e8f0"/>'
                 f'<text x="{x0 - 6}" y="{Y(val):.1f}" text-anchor="end" dominant-baseline="central" font-size="10.5" fill="#64748b">{val:g}</text>')
    for i, (name, committed, done) in enumerate(bars):
        bx = x0 + slot * i + slot / 2
        bw = min(34, slot / 3)
        v.append(f'<rect x="{bx - bw - 2:.1f}" y="{Y(committed):.1f}" width="{bw:.1f}" height="{y0 + ph - Y(committed):.1f}" fill="#cbd5e1" rx="3"/>'
                 f'<rect x="{bx + 2:.1f}" y="{Y(done):.1f}" width="{bw:.1f}" height="{y0 + ph - Y(done):.1f}" fill="#2563eb" rx="3"/>'
                 f'<text x="{bx:.1f}" y="{y0 + ph + 16}" text-anchor="middle" font-size="11.5" fill="#334155">{esc(name)}</text>')
    v.append(f'<g font-size="11" fill="#334155"><rect x="{x0}" y="{H - 16}" width="12" height="10" fill="#cbd5e1"/>'
             f'<text x="{x0 + 16}" y="{H - 7}">{esc(c.t("committed"))}</text>'
             f'<rect x="{x0 + 90}" y="{H - 16}" width="12" height="10" fill="#2563eb"/>'
             f'<text x="{x0 + 106}" y="{H - 7}">{esc(c.t("done_pts"))}</text></g></svg>')
    scope = sum(num(s.get("points"), 0) or 0 for s in stories.values() if s.get("priority") != "wont")
    names = ["0"] + [str(sp.get("id")) for sp in sprints]
    cum, total = [0.0], 0.0
    for sp in started:
        total += pts(as_list(sp.get("stories")), True)
        cum.append(total)
    topb = max(1, math.ceil(max(scope, total) / 10) * 10)
    Yb = lambda val: y0 + ph - ph * val / topb
    Xb = lambda i: x0 + pw * i / max(1, len(names) - 1)
    b = [f'<svg viewBox="0 0 {W} {H}" class="diagram" role="img" style="max-width:460px">']
    for k in range(6):
        val = topb * k / 5
        b.append(f'<line x1="{x0}" x2="{x0 + pw}" y1="{Yb(val):.1f}" y2="{Yb(val):.1f}" stroke="#e2e8f0"/>'
                 f'<text x="{x0 - 6}" y="{Yb(val):.1f}" text-anchor="end" dominant-baseline="central" font-size="10.5" fill="#64748b">{val:g}</text>')
    for i, name in enumerate(names):
        b.append(f'<text x="{Xb(i):.1f}" y="{y0 + ph + 16}" text-anchor="middle" font-size="11.5" fill="#334155">{esc(name)}</text>')
    b.append(f'<line x1="{x0}" x2="{x0 + pw}" y1="{Yb(scope):.1f}" y2="{Yb(scope):.1f}" stroke="#dc2626" stroke-width="2" stroke-dasharray="7 5"/>')
    line = " ".join(f"{Xb(i):.1f},{Yb(val):.1f}" for i, val in enumerate(cum))
    b.append(f'<polyline points="{line}" fill="none" stroke="#16a34a" stroke-width="3"/>'
             + "".join(f'<circle cx="{Xb(i):.1f}" cy="{Yb(val):.1f}" r="3.5" fill="#16a34a"/>' for i, val in enumerate(cum)))
    b.append(f'<g font-size="11" fill="#334155"><line x1="{x0}" x2="{x0 + 22}" y1="{H - 11}" y2="{H - 11}" stroke="#16a34a" stroke-width="3"/>'
             f'<text x="{x0 + 28}" y="{H - 7}">{esc(c.t("done_pts"))}</text>'
             f'<line x1="{x0 + 90}" x2="{x0 + 112}" y1="{H - 11}" y2="{H - 11}" stroke="#dc2626" stroke-width="2" stroke-dasharray="7 5"/>'
             f'<text x="{x0 + 118}" y="{H - 7}">{esc(c.t("scope"))} ({scope:g} pts)</text></g></svg>')
    velocity_part = f"<div><h3>{esc(c.t('velocity_chart'))}</h3>{''.join(v)}</div>" if bars else ""
    return f"<div class='split'>{velocity_part}<div><h3>{esc(c.t('burnup'))}</h3>{''.join(b)}</div></div>"


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
    details = _progress(sprints, stories, c)
    details += (f"<h3>{esc(c.t('overview'))}{vel}</h3><table><thead><tr><th>{esc(c.t('sprint'))}</th><th>{esc(c.t('dates'))}</th>"
               f"<th>{esc(c.t('sprint_goal'))}</th><th>{esc(c.t('stories'))}</th>"
               f"<th>{esc(c.t('committed'))} / {esc(c.t('capacity'))}</th></tr></thead>{''.join(rows)}</table>")
    others = [sp for sp in sprints if sp is not cur and (as_list(sp.get("tasks")) or as_list(sp.get("stories")))]
    for sp in others:
        details += (f"<h3>{esc(sp.get('name') or sp.get('id'))}</h3>" + _sprint_block(sp, c, stories, colors))
    return fig, details


def _zone_legend(c) -> str:
    return " &nbsp; ".join(f"{chip(c.t(k), col)} {lo}–{hi}" for k, col, lo, hi in ZONES)


def _score_chip(score, c) -> str:
    key, color = crit_class(score)
    return chip(f"{score} · {c.t(key)}", color)


def _pi_frame(c, cell, fill, size=13):
    """The 5×5 probability × impact grid and its axes. fill(score) gives
    (colour, opacity, colour of the score in the corner).
    Returns (svg parts, x0, y0, width, height)."""
    x0, y0, small = round(cell * 1.63), 16, size - 2
    s = []
    for p in range(1, 6):
        y = y0 + (5 - p) * cell
        for i in range(1, 6):
            color, op, corner = fill(p * i)
            x = x0 + (i - 1) * cell
            s.append(f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" fill="{color}" fill-opacity="{op}" '
                     f'stroke="#fff" stroke-width="3" rx="8"/><text x="{x + cell - 8}" y="{y + 14}" '
                     f'text-anchor="end" font-size="10" fill="{corner}">{p * i}</text>')
        s.append(f'<text x="{x0 - 10}" y="{y + cell / 2 - 7}" text-anchor="end" font-size="{size}" font-weight="700" fill="#334155">{p}</text>'
                 f'<text x="{x0 - 10}" y="{y + cell / 2 + 9}" text-anchor="end" font-size="{small}" fill="#64748b">{esc(c.t("p" + str(p)))}</text>')
    bottom = y0 + 5 * cell
    for i in range(1, 6):
        x = x0 + (i - 1) * cell + cell / 2
        s.append(f'<text x="{x}" y="{bottom + 18}" text-anchor="middle" font-size="{size}" font-weight="700" fill="#334155">{i}</text>'
                 f'<text x="{x}" y="{bottom + 34}" text-anchor="middle" font-size="{small}" fill="#64748b">{esc(c.t("i" + str(i)))}</text>')
    H = bottom + 76
    s.append(f'<text x="{x0 + 2.5 * cell}" y="{H - 8}" text-anchor="middle" font-size="13" font-weight="600" fill="#334155">{esc(c.t("impact"))} →</text>'
             f'<text transform="translate(18,{y0 + 2.5 * cell}) rotate(-90)" text-anchor="middle" font-size="13" font-weight="600" fill="#334155">{esc(c.t("probability"))} →</text>')
    return s, x0, y0, x0 + 5 * cell + 16, H


def _placed(d) -> list[dict]:
    """The risks that can go on a grid: an object with P and I on the 1-5 scale."""
    return [r for r in as_list(d.get("risks")) if isinstance(r, dict) and _pi(r)[0]]


def draw_register(d, c):
    risks = [r for r in as_list(d.get("risks")) if isinstance(r, dict)]
    treated = any(_pi(r, True)[0] for r in risks)
    counts = " ".join(chip(f"{c.t(k)} · {sum(1 for r in risks if lo <= _score(r) <= hi)}", col)
                      for k, col, lo, hi in reversed(ZONES))
    rows = []
    for r in sorted(risks, key=lambda r: -_score(r)):
        after = _score_chip(_score(r, True), c) if _pi(r, True)[0] else "<span class='muted'>—</span>"
        rows.append(f"<tr><td><b>{esc(r.get('id'))}</b></td><td><b>{esc(r.get('title'))}</b>"
                    f"<div class='small muted'>{esc(r.get('category') or '')}</div></td>"
                    f"<td class='small'>{esc(r.get('cause') or '')}{' → ' if r.get('cause') and r.get('consequence') else ''}{esc(r.get('consequence') or '')}</td>"
                    f"<td>{esc(r.get('probability'))}</td><td>{esc(r.get('impact'))}</td>"
                    f"<td>{_score_chip(_score(r), c)}</td>{f'<td>{after}</td>' if treated else ''}"
                    f"<td>{esc(r.get('owner') or '')}</td>"
                    f"<td class='small'>{esc(r.get('prevention') or '')}</td><td class='small'>{esc(r.get('contingency') or '')}</td>"
                    f"<td class='small'>{esc(r.get('status') or '')}</td></tr>")
    residual = f"<th>{esc(c.t('residual_col'))}</th>" if treated else ""
    fig = (f"<p style='margin:0 0 12px'>{counts}</p>"
           f"<table><thead><tr><th>ID</th><th>{esc(c.t('risk'))}</th><th>{esc(c.t('cause'))} → {esc(c.t('consequence'))}</th>"
           f"<th>P</th><th>I</th><th>{esc(c.t('criticality'))}</th>{residual}<th>{esc(c.t('owner'))}</th>"
           f"<th>{esc(c.t('prevention'))}</th><th>{esc(c.t('contingency'))}</th><th>{esc(c.t('status'))}</th></tr></thead>"
           f"{''.join(rows)}</table>")
    return fig, ""


def _matrix_svg(risks, c, after: bool = False, cell: int = 92) -> str:
    """The P × I grid with every risk's id in its cell."""
    s, x0, y0, W, H = _pi_frame(c, cell, lambda sc: (crit_class(sc)[1], 0.18, "#64748b"))
    slots: dict[tuple, list] = {}
    for r in risks:
        slots.setdefault(_pos(r, after), []).append(r)
    for (p, i), here in slots.items():
        x, y = x0 + (i - 1) * cell, y0 + (5 - p) * cell
        color = crit_class(p * i)[1]
        for k, r in enumerate(here if len(here) <= 6 else here[:5]):
            cx, cy = x + cell / 2 + (k % 2 * 2 - 1) * 20, y + 26 + (k // 2) * 20
            s.append(f'<rect x="{cx - 17}" y="{cy - 8.5}" width="34" height="17" rx="8.5" fill="{color}"/>'
                     f'<text x="{cx}" y="{cy}" text-anchor="middle" dominant-baseline="central" font-size="10" '
                     f'font-weight="700" fill="#fff">{esc(str(r.get("id", ""))[:5])}</text>')
        if len(here) > 6:
            s.append(f'<text x="{x + cell / 2 + 20}" y="{y + 66}" text-anchor="middle" dominant-baseline="central" '
                     f'font-size="11" font-weight="700" fill="#334155">+{len(here) - 5}</text>')
    return (f'<svg viewBox="0 0 {W} {H}" class="diagram" role="img" style="max-width:{W + 40}px">'
            f'{"".join(s)}</svg>')


def draw_risk_matrix(d, c):
    risks = _placed(d)
    treated = any(_pi(r, True)[0] for r in risks)
    keys = "".join(
        f"<li>{chip(r.get('id'), crit_class(_score(r))[1])}<span>{esc(r.get('title'))}</span>"
        f"<span class='sc small muted'>{_score(r)}"
        f"{f' → {_score(r, True)}' if _score(r, True) != _score(r) else ''}</span></li>"
        for r in sorted(risks, key=lambda r: -_score(r)))
    legend = f"<p class='small muted' style='text-align:center'>{_zone_legend(c)}</p>"
    if not treated:
        return (f"<div class='mx'>{_matrix_svg(risks, c)}<div><ul class='keys'>{keys}</ul>{legend}</div></div>"), ""
    # Treatment planned: the matrix before it and the residual one after, side by side.
    panels = "".join(f"<div><h4>{esc(c.t('residual' if after else 'inherent'))}</h4>"
                     f"{_matrix_svg(risks, c, after, cell=80)}</div>" for after in (False, True))
    return f"<div class='pair'>{panels}</div>{legend}<ul class='keys cols'>{keys}</ul>", ""


def _heat_svg(risks, c, after: bool) -> str:
    def fill(score):
        for _, color, lo, hi in ZONES:
            if score <= hi:            # a shade deeper as the score climbs within its zone
                return mix(color, 0.84 + 0.16 * (score - lo) / (hi - lo)), 1, "rgba(15,23,42,.55)"
    cell = 70
    s, x0, y0, W, H = _pi_frame(c, cell, fill, size=12)
    count: dict[tuple, int] = {}
    for r in risks:
        count[_pos(r, after)] = count.get(_pos(r, after), 0) + 1
    for (p, i), n in count.items():
        cx, cy = x0 + (i - 0.5) * cell, y0 + (5.5 - p) * cell + 3
        s.append(f'<circle cx="{cx}" cy="{cy}" r="{min(30, 12 + 6 * math.sqrt(n)):.1f}" fill="#fff" fill-opacity=".93"/>'
                 f'<text x="{cx}" y="{cy}" text-anchor="middle" dominant-baseline="central" font-size="17" '
                 f'font-weight="800" fill="#0f172a">{n}</text>')
    return (f'<svg viewBox="0 0 {W} {H}" class="diagram" role="img" style="max-width:{W + 40}px">'
            f'{"".join(s)}</svg>')


def draw_heatmap(d, c):
    risks = _placed(d)
    treated = any(_pi(r, True)[0] for r in risks)
    before = sum(_score(r) for r in risks)
    panels = []
    for after in ((False, True) if treated else (False,)):
        scores = [_score(r, after) for r in risks]
        expo = sum(scores)
        drop = f" ({round(100 * (expo - before) / before):+d} %)".replace("-", "−") if after and before else ""
        title = c.t("residual" if after else "inherent") if treated else c.t("now")
        panels.append(
            f"<div><h4>{esc(title)}</h4>{_heat_svg(risks, c, after)}<p class='small'>"
            f"{chip(f'{c.t(ZONES[3][0])} · {sum(1 for x in scores if x >= 15)}', ZONES[3][1])} "
            f"{chip(f'{c.t(ZONES[2][0])} · {sum(1 for x in scores if 10 <= x < 15)}', ZONES[2][1])} "
            f"&nbsp; {esc(c.t('exposure'))} Σ P×I = <b>{expo}</b>{drop}</p></div>")
    fig = (f"<div class='pair'>{''.join(panels)}</div>"
           f"<p class='small muted' style='text-align:center'>{_zone_legend(c)}</p>")

    cats: dict[str, list] = {}
    for r in risks:
        cats.setdefault(str(r.get("category") or "").strip() or c.t("other"), []).append(r)
    rows = []
    for cat, rs in cats.items():
        n_by_zone = [sum(1 for r in rs if lo <= _score(r) <= hi) for _, _, lo, hi in ZONES]
        rows.append((cat, n_by_zone, sum(_score(r) for r in rs), sum(_score(r, True) for r in rs)))
    rows.sort(key=lambda row: -row[2])
    top = max((n for row in rows for n in row[1]), default=1) or 1
    body = ""
    for cat, n_by_zone, expo, expo_after in rows:
        cells = ""
        for (_, color, _, _), n in zip(ZONES, n_by_zone):
            bg = mix(color, 0.25 + 0.75 * n / top) if n else "#f8fafc"
            cells += f"<td class='hc' style='background:{bg};color:{ink(bg)}'>{n or ''}</td>"
        shift = f" → {expo_after}" if treated and expo_after != expo else ""
        body += (f"<tr><td><b>{esc(cat)}</b></td>{cells}<td class='hc'>{sum(n_by_zone)}</td>"
                 f"<td class='hc'>{expo}{shift}</td></tr>")
    head = "".join(f"<th class='hc'>{esc(c.t(k))} <span class='muted'>{lo}–{hi}</span></th>" for k, _, lo, hi in ZONES)
    details = (f"<h3>{esc(c.t('by_category'))}</h3><table class='heatcat'><thead><tr><th>{esc(c.t('category'))}</th>{head}"
               f"<th class='hc'>{esc(c.t('total'))}</th><th class='hc'>{esc(c.t('exposure'))} Σ P×I</th></tr></thead>"
               f"{body}</table>") if rows else ""
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


# ── Cahier des charges ───────────────────────────────────────────────────────
# The specification is assembled, not copied. Its own file holds what no other
# deliverable says (context, objectives, scope, requirements, acceptance...);
# the need, the functional analysis, the stakeholders, the RACI, the risks and
# the schedule are drawn from their own files. One source for every fact, so
# the document cannot contradict the diagrams.
#
# It is built as blocks so that the HTML page and the Word file
# (actions/scrum.py, python-docx) say exactly the same thing:
#   {"t": "cover", title, project, subtitle, version, facts: [[label, value]],
#    synthesis_title, synthesis: [[value, label]]}
#   {"t": "toc", title}                  contents, from the headings
#   {"t": "h", level 1-3, text, num, anchor, plain?, annex?}
#   {"t": "p", text, cls}                cls: "" | statement | note
#   {"t": "ul" | "ol", items}
#   {"t": "table", head, rows}           cell: text | [lines] | {"text", "color"} chip | {"strong", "text"}
#   {"t": "req", id, title, badge: {"text", "color"}, rows: [[label, text | [lines]]]}
#   {"t": "figure", svg, caption}
#   {"t": "break"}

def obj(v) -> dict:
    return v if isinstance(v, dict) else {}


def _money(v, currency, lang) -> str:
    n = num(v)
    if n is None:
        return txt(v)
    sym = {"EUR": "€", "USD": "$", "GBP": "£"}.get(str(currency or "EUR").upper(), str(currency or ""))
    if lang == "fr":
        return f"{n:,.0f}".replace(",", " ") + f" {sym}"
    return f"{sym}{n:,.0f}" if sym in ("€", "$", "£") else f"{n:,.0f} {sym}"


def _when(v) -> str:
    return fmt_date(pdate(v)) or txt(v)


def _svg_of(draw, *args) -> str:
    """A diagram for the document; '' when its file cannot be drawn."""
    try:
        out = draw(*args)
        return out[0] if isinstance(out, tuple) else out
    except Exception:
        return ""


def _cdc_stats(c) -> dict:
    d = obj(c.data.get("cahier-des-charges"))
    reqs = [r for r in as_list(d.get("requirements")) if isinstance(r, dict)]
    nfr = [r for r in as_list(d.get("non_functional")) if isinstance(r, dict)]
    fns = _fn_ids(c)
    linked = {str(f) for r in reqs + nfr for f in as_list(r.get("functions"))}
    return {"reqs": len(reqs), "nfr": len(nfr), "fn_total": len(fns),
            "fn_covered": sum(1 for f in fns if f in linked),
            "by_prio": {p: sum(1 for r in reqs if r.get("priority") == p) for p in PRIORITIES},
            "objectives": len([o for o in as_list(d.get("objectives")) if isinstance(o, dict)])}


def _fn_order(item):
    fid, f = item
    return (str(f.get("type", "")).upper() != "FP", fid)


def cdc_blocks(c) -> list[dict]:
    d = obj(c.data.get("cahier-des-charges"))
    t, lang = c.t, c.lang
    doc = obj(d.get("document"))
    B: list[dict] = []
    figs = [0]

    def head(level, text, annex=False):
        return {"t": "h", "level": level, "text": text, "annex": annex}

    def section(title, parts, annex=False):
        if parts:
            B.append(head(1, title, annex))
            B.extend(parts)

    def sub(title, parts, level=2):
        return [head(level, title), *parts] if parts else []

    def para(v, cls=""):
        return [{"t": "p", "text": txt(v), "cls": cls}] if txt(v).strip() else []

    def bullets(v, kind="ul"):
        items = [txt(i) for i in as_list(v) if txt(i).strip()]
        return [{"t": kind, "items": items}] if items else []

    def table(columns, rows):
        return [{"t": "table", "head": columns, "rows": rows}] if rows else []

    def figure(svg, caption):
        if not svg:
            return []
        figs[0] += 1
        return [{"t": "figure", "svg": svg, "caption": f"{t('cdc.fig')} {figs[0]} — {caption}"}]

    def colon(label):
        return f"{label} : " if lang == "fr" else f"{label}: "

    def dicts(v):
        return [x for x in as_list(v) if isinstance(x, dict)]

    # Cover, versions, contents
    st = _cdc_stats(c)
    facts = [[t("cdc.version"), txt(doc.get("version") or "1.0")],
             [t("cdc.status"), txt(doc.get("status") or ("brouillon" if lang == "fr" else "draft"))],
             [t("cdc.date"), _when(doc.get("date")) or dt.date.today().strftime("%d/%m/%Y")],
             [t("cdc.client"), txt(doc.get("client"))], [t("cdc.provider"), txt(doc.get("provider"))],
             [t("cdc.authors"), ", ".join(txt(a) for a in as_list(doc.get("authors")))],
             [t("cdc.confidentiality"), txt(doc.get("confidentiality"))]]
    B.append({"t": "cover", "title": txt(doc.get("title")) or t("cdc.title"),
              "project": txt(c.meta.get("name")) or c.root.name, "subtitle": txt(c.meta.get("description")),
              "version": facts[0][1], "synthesis_title": t("cdc.synthesis"),
              "facts": [f for f in facts if f[1].strip()],
              "synthesis": [[str(st["reqs"]), t("cdc.k.ef")], [str(st["nfr"]), t("cdc.k.enf")],
                            [f"{st['fn_covered']}/{st['fn_total']}", t("cdc.k.cover")],
                            [str(st["objectives"]), t("cdc.k.obj")]]})
    B.append({"t": "break"})
    hist = [[txt(h.get("version")), _when(h.get("date")), txt(h.get("author")), txt(h.get("changes"))]
            for h in dicts(doc.get("history"))]
    if hist:
        B += [{"t": "h", "level": 1, "text": t("cdc.history"), "plain": True},
              *table([t("cdc.version"), t("cdc.date"), t("cdc.author"), t("cdc.changes")], hist)]
    appr = [[txt(a.get("name")), txt(a.get("role")), _when(a.get("date")), txt(a.get("decision"))]
            for a in dicts(doc.get("approvals"))]
    if appr:
        B += [{"t": "h", "level": 1, "text": t("cdc.approvals"), "plain": True},
              *table([t("name"), t("cdc.role"), t("cdc.date"), t("cdc.decision")], appr)]
    B += [{"t": "toc", "title": t("cdc.toc")}, {"t": "break"}]

    # 1. The project
    ctx = obj(d.get("context"))
    part = sub(t("cdc.s.context"), para(ctx.get("organisation")) + para(ctx.get("background"))
               + sub(t("cdc.stakes"), bullets(ctx.get("stakes")), 3))
    part += sub(t("cdc.s.current"), para(ctx.get("current")) + bullets(ctx.get("problems")))
    part += sub(t("cdc.s.objectives"), table(
        ["ID", t("cdc.objective"), t("cdc.indicator"), t("cdc.target"), t("cdc.deadline")],
        [[txt(o.get("id")), txt(o.get("text")), txt(o.get("indicator")), txt(o.get("target")),
          _when(o.get("deadline"))] for o in dicts(d.get("objectives"))]))
    sc = obj(d.get("scope"))
    part += sub(t("cdc.s.scope"), sub(t("cdc.in"), bullets(sc.get("in")), 3)
                + sub(t("cdc.out"), bullets(sc.get("out")), 3)
                + sub(t("cdc.assumptions"), bullets(sc.get("assumptions")), 3)
                + sub(t("cdc.dependencies"), bullets(sc.get("dependencies")), 3))
    pp = c.data.get("parties-prenantes")
    if pp:
        rows = [[txt(x.get("name")), txt(x.get("role")),
                 t("cdc.internal") if x.get("side") == "internal" else t("cdc.external"),
                 txt(x.get("expectations")), txt(x.get("strategy"))] for x in dicts(pp.get("stakeholders"))]
        part += sub(t("cdc.s.stakeholders"), figure(_svg_of(draw_stakeholders, pp, c), t("lead.parties-prenantes"))
                    + table([t("name"), t("cdc.role"), t("cdc.side"), t("expectations"), t("strategy")], rows))
    part += sub(t("cdc.s.references"), bullets(d.get("references")))
    section(t("cdc.s.overview"), part)

    # 2. The need
    bete = obj(c.data.get("bete-a-cornes"))
    part = []
    if bete:
        part += sub(t("cdc.s.statement"), figure(_svg_of(draw_bete, bete, c), t("lead.bete-a-cornes"))
                    + para(bete.get("statement"), "statement"))
    v = obj(bete.get("validation"))
    part += sub(t("cdc.s.validation"), table([t("cdc.question"), t("cdc.answer")],
                                             [[t(k), txt(v.get(k))] for k in ("why", "change", "end") if txt(v.get(k)).strip()]))
    users = [[txt(u.get("role")), txt(u.get("description")), txt(u.get("count")), txt(u.get("frequency")),
              txt(u.get("skills"))] for u in dicts(d.get("users"))]
    personas = [[{"strong": txt(p.get("name")), "text": txt(p.get("role"))},
                 [txt(g) for g in as_list(p.get("goals"))], [txt(g) for g in as_list(p.get("pains"))]]
                for p in dicts(c.data.get("discovery", {}).get("personas"))]
    part += sub(t("cdc.s.users"), table([t("cdc.profile"), t("cdc.description"), t("cdc.count"),
                                         t("cdc.frequency"), t("cdc.skills")], users)
                + table([t("cdc.persona"), t("goals"), t("pains")], personas))
    section(t("cdc.s.need"), part)

    # 3. Functional analysis: life-cycle situations, interactions, characterisation
    pv = obj(c.data.get("pieuvre"))
    fns = _fn_ids(c)
    part = sub(t("cdc.s.life"), table([t("cdc.phase"), t("cdc.description")],
                                      [[txt(x.get("phase")), txt(x.get("description"))] for x in dicts(d.get("life_cycle"))]))
    if pv:
        els = [txt(e.get("label") or e.get("id")) for e in dicts(pv.get("elements"))]
        part += sub(t("cdc.s.interactions"), figure(_svg_of(draw_pieuvre, pv, c), t("lead.pieuvre"))
                    + sub(t("cdc.elements"), bullets(els), 3))
        extra: dict[str, list] = {}
        for x in dicts(d.get("extra_criteria")):
            extra.setdefault(str(x.get("function")), []).append(x)
        rows = []
        for fid, f in sorted(fns.items(), key=_fn_order):
            color = "#2563eb" if str(f.get("type", "")).upper() == "FP" else "#ea580c"
            crits = [f] if txt(f.get("criteria")).strip() or txt(f.get("level")).strip() else []
            for k, x in enumerate((crits + extra.get(fid, [])) or [{}]):
                rows.append([{"text": fid, "color": color} if k == 0 else "", txt(f.get("text")) if k == 0 else "",
                             txt(x.get("criteria")), txt(x.get("level")), txt(x.get("flexibility"))])
        part += sub(t("cdc.s.characterisation"), table(
            [t("code"), t("function"), t("cdc.criteria"), t("cdc.level"), t("cdc.flex")], rows)
            + bullets([t(f"cdc.{k}") for k in FLEX]))
    section(t("cdc.s.fa"), part)

    # 4. Functional requirements, by module
    fn_text = {fid: txt(f.get("text")) for fid, f in fns.items()}

    def req_block(r):
        rows = [[t("cdc.description"), txt(r.get("description"))]]
        if txt(r.get("actor")).strip():
            rows.append([t("cdc.actor"), txt(r.get("actor"))])
        served = [f"{x} — {fn_text[str(x)]}" if str(x) in fn_text else str(x) for x in as_list(r.get("functions"))]
        for label, val in ((t("cdc.functions"), served), (t("cdc.rules"), [txt(x) for x in as_list(r.get("rules"))]),
                           (t("cdc.acceptance"), [txt(x) for x in as_list(r.get("acceptance"))])):
            if val:
                rows.append([label, val])
        prio = r.get("priority")
        return {"t": "req", "id": txt(r.get("id")), "title": txt(r.get("title")), "rows": rows,
                "badge": {"text": t(f"cdc.{prio}") if prio in PRIORITIES else txt(prio),
                          "color": PRIO_COLOR.get(prio, "#64748b")}}

    reqs = dicts(d.get("requirements"))
    mods = dicts(d.get("modules"))
    part = []
    if mods:
        mod_ids = {str(m.get("id")) for m in mods}
        for m in mods:
            mine = [req_block(r) for r in reqs if str(r.get("module")) == str(m.get("id"))]
            part += sub(txt(m.get("name") or m.get("id")), para(m.get("description")) + mine)
        part += sub(t("cdc.other_reqs"), [req_block(r) for r in reqs if str(r.get("module")) not in mod_ids])
    else:
        part += [req_block(r) for r in reqs]
    journeys = []
    for j in dicts(d.get("journeys")):
        title = txt(j.get("name")) + (f" — {txt(j.get('actor'))}" if txt(j.get("actor")).strip() else "")
        journeys += sub(title, bullets(j.get("steps"), "ol"), 3)
    part += sub(t("cdc.s.journeys"), journeys)
    section(t("cdc.s.functional"), part)

    # 5. Non-functional requirements, by quality characteristic
    nfr = dicts(d.get("non_functional"))
    part = []
    for cat in NFR_CATEGORIES:
        mine = [r for r in nfr if (r.get("category") if r.get("category") in NFR_CATEGORIES else "other") == cat]
        rows = [[txt(r.get("id")), {"strong": txt(r.get("title")), "text": txt(r.get("description"))},
                 txt(r.get("criteria")), txt(r.get("level")), txt(r.get("flexibility")),
                 t(f"cdc.v.{r['verification']}") if r.get("verification") in VERIFICATION else txt(r.get("verification"))]
                for r in mine]
        part += sub(t(f"cdc.cat.{cat}"), table(["ID", t("cdc.requirement"), t("cdc.criteria"), t("cdc.level"),
                                                t("cdc.flex"), t("cdc.verification")], rows))
    section(t("cdc.s.nfr"), part + (bullets([t(f"cdc.{k}") for k in FLEX]) if part else []))

    # 6. Technical environment and constraints
    tech = obj(d.get("technical"))
    part = sub(t("cdc.s.environment"), bullets(tech.get("environment"))
               + sub(t("cdc.imposed"), bullets(tech.get("imposed")), 3)
               + sub(t("cdc.hosting"), para(tech.get("hosting")), 3))
    part += sub(t("cdc.s.interfaces"), table(
        [t("cdc.system"), t("cdc.direction"), t("cdc.data"), t("cdc.protocol"), t("cdc.freq")],
        [[txt(i.get("system")), txt(i.get("direction")), txt(i.get("data")), txt(i.get("protocol")),
          txt(i.get("frequency"))] for i in dicts(tech.get("interfaces"))]))
    part += sub(t("cdc.s.data"), table(
        [t("cdc.entity"), t("cdc.description"), t("cdc.volume"), t("cdc.sensitivity"), t("cdc.retention")],
        [[txt(x.get("entity")), txt(x.get("description")), txt(x.get("volume")), txt(x.get("sensitivity")),
          txt(x.get("retention"))] for x in dicts(tech.get("data"))])
        + sub(t("cdc.migration"), para(tech.get("migration")), 3))
    part += sub(t("cdc.s.constraints"), table([t("cdc.type"), t("cdc.constraint")],
                                              [[txt(x.get("type")), txt(x.get("text"))] for x in dicts(d.get("constraints"))]))
    section(t("cdc.s.technical"), part)

    # 7. Organisation: method, roles and RACI, governance and ceremonies
    org = obj(d.get("organisation"))
    part = sub(t("cdc.s.method"), para(org.get("method")))
    roles = table([t("cdc.role"), t("name"), t("cdc.responsibilities")],
                  [[txt(r.get("role")), txt(r.get("name")), txt(r.get("responsibilities"))] for r in dicts(org.get("roles"))])
    raci = obj(c.data.get("raci"))
    if raci:
        rl = [r for r in dicts(raci.get("roles")) if r.get("id")]
        acts = dicts(raci.get("activities"))
        phases = any(a.get("phase") for a in acts)
        color = {"A": "#dc2626", "R": "#2563eb", "C": "#ca8a04", "I": "#64748b"}
        rows = []
        for a in acts:
            cells = ([txt(a.get("phase"))] if phases else []) + [txt(a.get("task"))]
            for r in rl:
                raw = txt(obj(a.get("raci")).get(r["id"])).strip().upper()
                letters = _letters(raw)
                cells.append({"text": raw, "color": next(color[k] for k in "ARCI" if k in letters)} if letters else "")
            rows.append(cells)
        roles += table(([t("cdc.phase")] if phases else []) + [t("activity")]
                       + [txt(r.get("label") or r.get("id")) for r in rl], rows)
    part += sub(t("cdc.s.roles"), roles)
    cer = [[txt(x.get("name")), txt(x.get("when")), txt(x.get("duration")), txt(x.get("who")), txt(x.get("purpose"))]
           for x in dicts(c.data.get("planning", {}).get("ceremonies"))]
    part += sub(t("cdc.s.governance"), table(
        [t("cdc.committee"), t("cdc.frequency"), t("cdc.participants"), t("cdc.purpose")],
        [[txt(x.get("name")), txt(x.get("frequency")), txt(x.get("participants")), txt(x.get("purpose"))]
         for x in dicts(org.get("committees"))])
        + sub(t("cdc.ceremonies"), table([t("ceremony"), t("when"), t("duration"), t("who"), t("purpose_col")], cer), 3))
    section(t("cdc.s.organisation"), part)

    # 8. Schedule: the Gantt when the planning exists, milestones from both files
    pl = obj(c.data.get("planning"))
    part = figure(_svg_of(draw_planning, pl, c), t("lead.planning")) if pl else []
    miles = {}
    for m in dicts(pl.get("milestones")) + dicts(d.get("milestones")):
        day = pdate(m.get("date"))
        if day:
            miles.setdefault((day, txt(m.get("label")).strip().lower()), txt(m.get("label")))
    part += table([t("cdc.date"), t("cdc.milestone")], [[fmt_date(k[0]), label] for k, label in sorted(miles.items())])
    section(t("cdc.s.planning"), part)

    # 9. Budget
    bud = obj(d.get("budget"))
    cur = bud.get("currency") or "EUR"
    items = dicts(bud.get("items"))
    rows = [[txt(i.get("label")), _money(i.get("amount"), cur, lang), txt(i.get("note"))] for i in items]
    if rows:
        rows.append([{"strong": t("cdc.total")}, {"strong": _money(sum(num(i.get("amount"), 0) or 0 for i in items), cur, lang)}, ""])
    part = table([t("cdc.item"), t("cdc.amount"), t("cdc.note")], rows)
    if num(bud.get("envelope")) is not None:
        part += para(colon(t("cdc.envelope")) + _money(bud.get("envelope"), cur, lang))
    section(t("cdc.s.budget"), part + para(bud.get("notes"), "note"))

    # 10. Deliverables
    section(t("cdc.s.deliverables"), table(
        [t("cdc.deliverable"), t("cdc.description"), t("cdc.format"), t("cdc.due")],
        [[txt(x.get("name")), txt(x.get("description")), txt(x.get("format")), _when(x.get("due"))]
         for x in dicts(d.get("deliverables"))]))

    # 11. Acceptance
    acc = obj(d.get("acceptance"))
    section(t("cdc.s.acceptance"),
            sub(t("cdc.process"), bullets(acc.get("process"), "ol"))
            + sub(t("cdc.acc_criteria"), bullets(acc.get("criteria")))
            + sub(t("cdc.severity"), table([t("cdc.sev_level"), t("cdc.definition"), t("cdc.threshold")],
                                           [[txt(x.get("level")), txt(x.get("definition")), txt(x.get("threshold"))]
                                            for x in dicts(acc.get("severity"))]))
            + sub(t("cdc.warranty"), para(acc.get("warranty"))))

    # 12. Maintenance, support, reversibility
    sup = obj(d.get("support"))
    section(t("cdc.s.support"),
            sub(t("cdc.maintenance"), para(sup.get("maintenance")))
            + sub(t("cdc.sla"), table([t("cdc.sla_level"), t("cdc.response_time"), t("cdc.resolution")],
                                      [[txt(x.get("level")), txt(x.get("response")), txt(x.get("resolution"))]
                                       for x in dicts(sup.get("sla"))]))
            + sub(t("cdc.training"), para(sup.get("training")))
            + sub(t("cdc.documentation"), bullets(sup.get("documentation")))
            + sub(t("cdc.reversibility"), para(sup.get("reversibility"))))

    # 13. Risks, from the risk register
    rk = c.data.get("risques")
    if isinstance(rk, dict):
        risks = _placed(rk)
        rows = []
        for r in sorted(risks, key=lambda r: -_score(r))[:10]:
            key, col = crit_class(_score(r))
            after = crit_class(_score(r, True))
            rows.append([txt(r.get("id")), {"strong": txt(r.get("title")), "text": txt(r.get("category"))},
                         {"text": f"{_score(r)} · {t(key)}", "color": col},
                         {"text": f"{_score(r, True)} · {t(after[0])}", "color": after[1]} if _pi(r, True)[0] else "—",
                         txt(r.get("prevention")), txt(r.get("owner"))])
        section(t("cdc.s.risks"), figure(_svg_of(_matrix_svg, risks, c), t("matrice-risques"))
                + sub(t("cdc.top_risks"), table(["ID", t("risk"), t("criticality"), t("residual_col"),
                                                 t("prevention"), t("owner")], rows)))

    # 14. Response framework, when suppliers are consulted
    resp = obj(d.get("response"))
    weights = [[txt(x.get("criterion")), f"{txt(x.get('weight'))} %"] for x in dicts(resp.get("criteria"))]
    section(t("cdc.s.response"),
            sub(t("cdc.variants"), para(resp.get("variants")))
            + sub(t("cdc.expected"), bullets(resp.get("expected")))
            + sub(t("cdc.selection"), table([t("cdc.criteria"), t("cdc.weight")], weights))
            + sub(t("cdc.calendar"), table([t("cdc.date"), t("cdc.milestone")],
                                           [[_when(x.get("date")), txt(x.get("label"))] for x in dicts(resp.get("calendar"))]))
            + sub(t("cdc.contact"), para(resp.get("contact"))))

    # Appendices: glossary, traceability, open questions
    gloss = sorted(([txt(g.get("term")), txt(g.get("definition"))] for g in dicts(d.get("glossary"))),
                   key=lambda row: row[0].lower())
    section(t("cdc.s.glossary"), table([t("cdc.term"), t("cdc.definition")], gloss), annex=True)
    every = reqs + nfr
    stories = dicts(c.data.get("product-backlog", {}).get("stories"))
    rows = []
    for fid, f in sorted(fns.items(), key=_fn_order):
        rids = [txt(r.get("id")) for r in every if fid in {str(x) for x in as_list(r.get("functions"))}]
        row = [{"text": fid, "color": "#2563eb" if str(f.get("type", "")).upper() == "FP" else "#ea580c"},
               txt(f.get("text")), ", ".join(rids) or t("cdc.not_linked")]
        if stories:
            sids = sorted({txt(s.get("id")) for s in stories for x in as_list(s.get("requirements")) if str(x) in rids})
            row.append(", ".join(sids) or "—")
        rows.append(row)
    unlinked = [f"{txt(r.get('id'))} — {txt(r.get('title'))}" for r in every if not as_list(r.get("functions"))]
    if rows:
        section(t("cdc.s.trace"), para(t("cdc.trace_lead"), "note")
                + table([t("code"), t("function"), t("cdc.requirements")] + ([t("cdc.stories")] if stories else []), rows)
                + sub(t("cdc.unlinked"), bullets(unlinked)), annex=True)
    section(t("cdc.s.questions"), bullets(d.get("open_questions")), annex=True)

    # Numbers: 1, 1.2, 1.2.3; appendices A, B, C
    n1 = n2 = n3 = annexes = 0
    prefix = ""
    for b in B:
        if b["t"] != "h" or b.get("plain"):
            continue
        if b["level"] == 1:
            n2 = n3 = 0
            if b.get("annex"):
                annexes += 1
                prefix = chr(64 + annexes)
                b["text"] = f"{t('cdc.annex')} {prefix} — {b['text']}"
                b["num"] = ""
            else:
                n1 += 1
                prefix = b["num"] = str(n1)
        elif b["level"] == 2:
            n2, n3 = n2 + 1, 0
            b["num"] = f"{prefix}.{n2}"
        else:
            n3 += 1
            b["num"] = f"{prefix}.{n2}.{n3}"
        b["anchor"] = "s-" + (b["num"] or prefix).replace(".", "-")
    return B


def _cell_html(v) -> str:
    if isinstance(v, dict):
        if "color" in v:
            return chip(v.get("text", ""), v["color"])
        strong = f"<b>{esc(v.get('strong'))}</b>" if txt(v.get("strong")).strip() else ""
        rest = f"<div class='small muted'>{esc(v.get('text'))}</div>" if txt(v.get("text")).strip() else ""
        return strong + rest
    if isinstance(v, list):
        items = [txt(x) for x in v if txt(x).strip()]
        if len(items) == 1:
            return esc(items[0])
        return "<ul class='tight'>" + "".join(f"<li>{esc(x)}</li>" for x in items) + "</ul>"
    return esc(v)


def blocks_html(blocks: list[dict], c) -> str:
    heads = [b for b in blocks if b["t"] == "h" and not b.get("plain") and b["level"] <= 2]
    out = []
    for b in blocks:
        k = b["t"]
        if k == "cover":
            synth = "".join(f"<div><b>{esc(v)}</b><span>{esc(label)}</span></div>" for v, label in b["synthesis"])
            facts = "".join(f"<tr><td>{esc(a)}</td><td>{esc(v)}</td></tr>" for a, v in b["facts"])
            out.append(f"<section class='cover' id='figure'><div><div class='kicker'>{esc(b['title'])}</div>"
                       f"<h1>{esc(b['project'])}</h1></div><div class='bar'></div>"
                       f"<div class='subtitle'>{esc(b['subtitle'])}</div>"
                       f"<div><h4>{esc(c.t('cdc.synthesis'))}</h4><div class='synth'>{synth}</div></div>"
                       f"<table class='facts'>{facts}</table></section>")
        elif k == "toc":
            items = "".join(f"<li class='l{h['level']}'><a href='#{h['anchor']}'><span class='n'>{esc(h['num'])}</span>"
                            f"{esc(h['text'])}</a></li>" for h in heads)
            out.append(f"<nav class='toc'><h2>{esc(c.t('cdc.toc'))}</h2><ol>{items}</ol></nav>")
        elif k == "h":
            tag = f"h{min(4, b['level'] + 1)}"
            number = f"<span class='n'>{esc(b['num'])}</span>" if b.get("num") else ""
            anchor = f" id='{b['anchor']}'" if b.get("anchor") else ""
            out.append(f"<{tag}{anchor}>{number}{esc(b['text'])}</{tag}>")
        elif k == "p":
            out.append(f"<p class='{b.get('cls') or ''}'>{esc(b['text'])}</p>")
        elif k in ("ul", "ol"):
            out.append(f"<{k}>" + "".join(f"<li>{esc(i)}</li>" for i in b["items"]) + f"</{k}>")
        elif k == "table":
            th = "".join(f"<th>{esc(h)}</th>" for h in b["head"])
            rows = "".join("<tr>" + "".join(f"<td>{_cell_html(v)}</td>" for v in r) + "</tr>" for r in b["rows"])
            out.append(f"<table><thead><tr>{th}</tr></thead><tbody>{rows}</tbody></table>")
        elif k == "req":
            rows = "".join(f"<tr><td>{esc(a)}</td><td>{_cell_html(v)}</td></tr>" for a, v in b["rows"])
            out.append(f"<div class='req' id='{esc(b['id'])}'><div class='rh'><span class='rid'>{esc(b['id'])}</span>"
                       f"<span>{esc(b['title'])}</span>{chip(b['badge']['text'], b['badge']['color'])}</div>"
                       f"<table>{rows}</table></div>")
        elif k == "figure":
            out.append(f"<figure>{b['svg']}<figcaption>{esc(b['caption'])}</figcaption></figure>")
        elif k == "break":
            out.append("<div class='pb'></div>")
    return "".join(out)


def cdc_document(c) -> str:
    name = txt(c.meta.get("name")) or c.root.name
    try:
        body = blocks_html(cdc_blocks(c), c)
    except Exception as e:                       # one odd field never costs the whole document
        body = f"<div class='missing'>{esc(c.t('error'))} ({esc(type(e).__name__)}: {esc(e)})</div>"
    return (f"<!DOCTYPE html><html lang='{c.lang}'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<title>{esc(c.t('cdc.title'))} — {esc(name)}</title><style>{CSS}{DOC_CSS}</style></head>"
            f"<body class='doc'><a class='back' href='index.html'>{esc(c.t('back'))}</a>"
            f"<main class='sheet'>{body}</main></body></html>")


def draw_cdc(d, c):
    """The dashboard's view of the specification: where it stands, and a link."""
    st = _cdc_stats(c)
    doc = obj(d.get("document"))
    tiles = [(f"v{txt(doc.get('version') or '1.0')}", txt(doc.get("status") or ("brouillon" if c.lang == "fr" else "draft"))),
             (st["reqs"], c.t("cdc.k.ef")), (st["nfr"], c.t("cdc.k.enf")),
             (f"{st['fn_covered']}/{st['fn_total']}", c.t("cdc.k.cover")), (st["objectives"], c.t("cdc.k.obj"))]
    prio = " ".join(chip(f"{c.t('cdc.' + p)} · {st['by_prio'][p]}", PRIO_COLOR[p]) for p in PRIORITIES if st["by_prio"][p])
    fig = ("<div class='kpis' style='margin:0 0 12px'>"
           + "".join(f"<div class='kpi'><b>{esc(v)}</b><span>{esc(label)}</span></div>" for v, label in tiles)
           + f"</div><p>{prio}</p><p><a href='cahier-des-charges.html' style='font-weight:600'>{esc(c.t('cdc.open'))} →</a></p>")
    heads = [b for b in cdc_blocks(c) if b["t"] == "h" and b["level"] == 1 and not b.get("plain")]
    toc = "".join(f"<li><a href='cahier-des-charges.html#{b['anchor']}'>{esc((b['num'] + '. ') if b['num'] else '')}"
                  f"{esc(b['text'])}</a></li>" for b in heads)
    return fig, f"<h3>{esc(c.t('cdc.toc'))}</h3><ul class='tight' style='list-style:none;padding:0'>{toc}</ul>"


DRAW = {"bete-a-cornes": draw_bete, "pieuvre": draw_pieuvre, "swot": draw_swot,
        "parties-prenantes": draw_stakeholders, "raci": draw_raci, "discovery": draw_discovery,
        "cahier-des-charges": draw_cdc,
        "product-backlog": draw_backlog, "cadre-scrum": draw_framework, "priorisation": draw_priority,
        "sprints": draw_sprints, "risques": draw_register,
        "matrice-risques": draw_risk_matrix, "carte-chaleur": draw_heatmap, "planning": draw_planning}


# ── Pages ────────────────────────────────────────────────────────────────────

def _section(stem: str, c: Ctx, figure_id: bool) -> str:
    title = c.t(stem)
    d = c.data.get(source(stem))
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
        "artefacts": {stem: source(stem) in c.data for stem, _ in ORDER},
        "epics": len(as_list(c.data.get("product-backlog", {}).get("epics"))),
        "stories": len(stories),
        "points": sum(num(s.get("points"), 0) or 0 for s in stories),
        "points_done": sum(num(s.get("points"), 0) or 0 for s in stories if s.get("status") == "done"),
        "sprints": len(as_list(c.data.get("sprints", {}).get("sprints"))),
        "risks": len(risks),
        "critical_risks": sum(1 for r in risks
                              if (num(r.get("probability"), 0) or 0) * (num(r.get("impact"), 0) or 0) >= 15),
        "stakeholders": len(as_list(c.data.get("parties-prenantes", {}).get("stakeholders"))),
        "requirements": _cdc_stats(c)["reqs"], "nfr": _cdc_stats(c)["nfr"],
        "errors": c.errors, "warnings": c.warnings,
    }


def dashboard(c: Ctx) -> str:
    sm = summary(c)
    nav = "<nav class='pills'>" + "".join(
        f"<a href='#{stem}'{'' if source(stem) in c.data else ' class=off'}>{esc(c.t(stem))}</a>"
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
        if source(stem) in c.data:
            page = (cdc_document(c) if stem == "cahier-des-charges"
                    else _page(c.t(stem), _section(stem, c, True), c, back=True))
            target.write_text(page, encoding="utf-8")
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
    ap.add_argument("--blocks", action="store_true",
                    help="print the specification as document blocks (JSON), for the Word export")
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
    if a.blocks:
        if "cahier-des-charges" not in c.data:
            print("no scrum/cahier-des-charges.json", file=sys.stderr)
            return 1
        print(json.dumps(cdc_blocks(c), ensure_ascii=False))
        return 0
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
