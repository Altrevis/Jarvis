---
name: scrum-cadrage
description: >-
  Frames a project before any backlog exists: the need statement (bête à
  cornes, APTE method), the interaction diagram (diagramme pieuvre) with its
  main functions and constraints, the SWOT matrix with cross strategies, and
  the product vision. Writes JSON the assistant draws. Use when the user says
  "bête à cornes", "pieuvre", "diagramme des interactions", "analyse
  fonctionnelle", "SWOT", "cadrage", "vision produit", "expression du besoin",
  or when a Scrum workspace starts.
---

# scrum-cadrage

Three deliverables, in this order, because each one feeds the next:

1. `scrum/bete-a-cornes.json` — what need the product answers
2. `scrum/pieuvre.json` — what it must do in its environment, and under which constraints
3. `scrum/swot.json` — whether the project is worth it, and how to play it

Plus the `vision` field of `scrum/meta.json`.

The source is the brief in `CLAUDE.md` and any file in `sources/`. Write only
JSON, never HTML: the assistant draws every diagram from these files. If the
task asks for one deliverable only, write that file only and leave the others
untouched.

## 1. Bête à cornes (APTE)

Three questions, answered about the **user's need**, not about features:

- **À qui le produit rend-il service ?** The user or customer, specific enough
  to picture ("étudiants de M1 en gestion de projet", not "les gens").
- **Sur quoi agit-il ?** The thing the product changes: matter, data, a state,
  a person. Not the product itself.
- **Dans quel but ?** The need, as a verb phrase: "Produire ... sans ...".
  The purpose is what remains if the product disappears and the need does not.

Then validate the need — a need nobody can explain is not one:

- **why**: why does the need exist?
- **change**: what could make it evolve?
- **end**: what could make it disappear? (If the honest answer is "next
  month", say so: it is a finding.)

```json
{
  "product": "Jarvis",
  "serves": "Les étudiants chefs de projet d'une équipe Ydays",
  "acts_on": "Les livrables de gestion de projet",
  "purpose": "Produire des livrables Scrum présentables sans heures de mise en forme",
  "statement": "Jarvis rend service aux étudiants en agissant sur leurs livrables pour les produire à la voix.",
  "validation": {"why": "...", "change": "...", "end": "..."}
}
```

Keep each box under ~90 characters: it is drawn in a box, not a paragraph.

## 2. Diagramme pieuvre (interaction diagram)

List the **elements of the environment** the product deals with during its
use: users, other systems, data, regulations, budget, energy, physical
surroundings. 5 to 10 is right; more than 12 is unreadable.

Then the functions, each written as **"Permettre à <A> de <verbe> <B>"** or
**"<Verbe> ..."** for a constraint:

- **FP (fonction principale)**: the reason the product exists. It links
  **exactly two** elements *through* the product ("permettre à l'utilisateur
  de produire ses livrables" links `user` and `docs`). Every FP must trace
  back to the bête à cornes purpose.
- **FC (fonction contrainte)**: an adaptation the product must make to **one**
  element (a law, a budget, a platform, a standard). It links exactly one.

For each function, give the cahier des charges columns when you can:
`criteria` (what is measured), `level` (the target value) and `flexibility`
(F0 = imperative, F1 = little negotiable, F2 = negotiable, F3 = very
negotiable).

```json
{
  "product": "Jarvis",
  "elements": [
    {"id": "user", "label": "Utilisateur"},
    {"id": "docs", "label": "Livrables"},
    {"id": "law", "label": "RGPD"}
  ],
  "functions": [
    {"id": "FP1", "type": "FP", "links": ["user", "docs"],
     "text": "Permettre à l'utilisateur de produire ses livrables à la voix",
     "criteria": "Temps pour un SWOT", "level": "< 3 min", "flexibility": "F1"},
    {"id": "FC1", "type": "FC", "links": ["law"],
     "text": "Garder les données personnelles en local",
     "criteria": "Données envoyées", "level": "Texte de la requête seulement", "flexibility": "F0"}
  ]
}
```

Element ids are short, lowercase, no spaces; labels are what is drawn.
Number FP1, FP2… then FC1, FC2… If `scrum/cahier-des-charges.json` exists,
its requirements point to these ids: keep every existing id and its meaning,
add new functions with new numbers.

## 3. SWOT

- **strengths / weaknesses**: internal — the team, the product, the
  resources, what the project controls.
- **opportunities / threats**: external — market, users, competitors,
  technology, law, calendar. Nothing the team controls.

3 to 6 items each, one line each, concrete and specific to this project
("Équipe de 4 à temps partiel", not "Manque de ressources"). An item that
would fit any project is filler: replace it.

Then **strategies** (TOWS): how to use strengths to seize opportunities (SO),
strengths against threats (ST), opportunities to fix weaknesses (WO), and how
to limit the weaknesses × threats exposure (WT). One or two each.

```json
{
  "strengths": ["..."], "weaknesses": ["..."],
  "opportunities": ["..."], "threats": ["..."],
  "strategies": {"SO": ["..."], "ST": ["..."], "WO": ["..."], "WT": ["..."]}
}
```

## 4. Vision

Add or update `"vision"` in `scrum/meta.json` (keep its other keys), in the
elevator-pitch form: *Pour <cible> qui <besoin>, <produit> est un <catégorie>
qui <bénéfice clé>. Contrairement à <alternative>, il <différence>.*
Two sentences at most.

## Finish

```bash
python3 .claude/scrum-kit/render.py . --check
```

Fix every ERROR. Warnings are judgement calls: fix them or leave them on
purpose. Note assumptions you made in `scrum/decisions.md` (one line each).
