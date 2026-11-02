---
name: scrum-parties-prenantes
description: >-
  Maps everyone who touches the project, inside and outside the team, on a
  power / interest grid (Mendelow) with their expectations and how to
  communicate with each, then builds the RACI matrix of who is Responsible,
  Accountable, Consulted and Informed for each activity. Writes JSON the
  assistant draws. Use when the user says "parties prenantes", "stakeholders",
  "personnes internes", "personnes externes", "acteurs du projet", "RACI",
  "matrice des responsabilités", "qui fait quoi".
---

# scrum-parties-prenantes

Two deliverables:

1. `scrum/parties-prenantes.json` — who has a stake in the project
2. `scrum/raci.json` — who does what

Read `CLAUDE.md` (the team, if given) and `scrum/bete-a-cornes.json` /
`scrum/pieuvre.json` if they exist (the users and external systems are
there). Write only JSON. If the task asks for one deliverable, write that file
only.

## 1. Stakeholders

**Internal** (`"side": "internal"`): the Scrum team — Product Owner, Scrum
Master, developers — and anyone in the organisation that runs the project
(manager, sponsor, other teams).

**External** (`"side": "external"`): end users, customers, jury or
evaluators, suppliers and platforms, regulators, partners, competitors when
they matter.

For each, two scores from 1 to 5:

- **power**: how much they can change the project (budget, go/no-go, grade,
  access).
- **interest**: how much the outcome affects them.

The grid has four quadrants, and the quadrant decides the strategy:

| power | interest | quadrant | strategy |
|---|---|---|---|
| high | high | Gérer étroitement | involve in reviews, decide with them |
| high | low | Satisfaire | short, regular updates on what they care about |
| low | high | Tenir informé | demos, newsletters, user tests |
| low | low | Surveiller | minimal effort, watch for changes |

**3 sits on the line between quadrants: do not use it.** The grid is a
decision — choose 2.5 or 3.5 if you hesitate.

`attitude` is `supporter`, `neutral` or `resistant`. A resistant stakeholder
with high power is a risk: say so in `strategy`.

```json
{
  "stakeholders": [
    {"id": "po", "name": "Léo", "role": "Product Owner", "side": "internal",
     "power": 5, "interest": 5, "attitude": "supporter",
     "expectations": "Un produit démontrable aux Ydays",
     "strategy": "Sprint review, backlog partagé"},
    {"id": "jury", "name": "Jury Ydays", "role": "Évaluateurs", "side": "external",
     "power": 5, "interest": 2, "attitude": "neutral",
     "expectations": "Livrables complets, soutenance claire",
     "strategy": "Dossier PDF et soutenance finale"}
  ]
}
```

Use real names when the brief gives them, roles otherwise. 6 to 15
stakeholders; group people who play the same role ("Équipe de dev (3)").

## 2. RACI

**Roles** are columns: the Scrum roles plus the stakeholders who take part in
activities (référent, client, jury). **Activities** are rows, grouped by
`phase` (Cadrage, Backlog, Sprint, Livraison… — whatever fits the project),
8 to 20 rows.

Rules, checked by the renderer:

- **Exactly one A** per activity — the person who answers for the result.
  Two A's means nobody does.
- **At least one R** — the person or people who do the work.
- A and R can be the same person: write `"A/R"`.
- C = consulted before (two-way), I = informed after (one-way). Leave a cell
  out when the role is not involved.

Scrum sanity checks: the PO is A on the backlog and its priorities; the
developers are A/R on how the work is done and on estimates being theirs;
the SM is A on the ceremonies happening and on removing impediments — not
on the content of the work.

```json
{
  "roles": [
    {"id": "po", "label": "Product Owner", "name": "Léo"},
    {"id": "sm", "label": "Scrum Master", "name": "Inès"},
    {"id": "dev", "label": "Développeurs", "name": "Équipe"}
  ],
  "activities": [
    {"phase": "Backlog", "task": "Prioriser le product backlog",
     "raci": {"po": "A/R", "dev": "C", "sm": "I"}},
    {"phase": "Sprint", "task": "Estimer les user stories",
     "raci": {"po": "C", "sm": "A", "dev": "R"}}
  ]
}
```

Role ids are the keys of `raci`; they must exist in `roles`.

## Finish

```bash
python3 .claude/scrum-kit/render.py . --check
```

Fix every ERROR. Note assumptions (an invented name, a guessed power) in
`scrum/decisions.md`.
