---
name: scrum-discovery
description: >-
  Builds the discovery backlog: personas, and the hypotheses, open questions,
  research, experiments and spikes the team must work through before
  committing to build, each with a status and what it led to. Writes JSON the
  assistant draws as a board. Use when the user says "discovery backlog",
  "discovery", "personas", "hypothèses", "ce qu'on doit valider", "dual-track",
  "avant le product backlog", or before writing user stories on a vague idea.
---

# scrum-discovery

One deliverable: `scrum/discovery.json`.

Discovery is the track that decides **what is worth building**; delivery (the
product backlog) builds it. Its backlog holds things to *learn*, not features
to ship. Read `CLAUDE.md`, `sources/`, and the cadrage files if they exist —
the SWOT weaknesses and threats and the bête à cornes "what could make it
disappear" are where the riskiest assumptions hide.

## Personas

2 or 3, built from what the brief says about the users. Each one: a name and
age, a role, a short quote in their voice, 2–3 goals, 2–3 pains. A persona
that could be anyone is useless: tie each goal and pain to this product.

## Items

Each item has a `type`:

- `hypothesis` — a belief that, if false, sinks the product. Write it
  falsifiable: "Les étudiants passent plus de 3 h par livrable", not "Les
  étudiants manquent de temps".
- `question` — something the team does not know and must find out.
- `research` — desk research, benchmark, interviews to run.
- `experiment` — a test with a measure and a threshold (prototype, fake door,
  survey, landing page).
- `spike` — a time-boxed technical investigation ("Peut-on dessiner un Gantt
  sans librairie ?").

For `research` and `experiment` items, say how in `method`: entretiens,
observation, questionnaire, atelier, analyse documentaire, benchmark,
prototype, test utilisateur, A/B test. Needs are gathered all along the
project, not once: pick the technique that answers the question cheapest —
watch users for friction, interview for the why, survey for numbers, a
prototype to validate a requirement before building it.

And a `status`: `todo`, `doing`, `validated`, `invalidated`. A new project
starts mostly in `todo`; mark something validated or invalidated only when the
brief or sources actually settle it, and write the evidence in `outcome`.

Order matters: put the riskiest assumptions first. `leads_to` lists the epics
or stories (by id) a validated item justifies — fill it once the product
backlog exists.

```json
{
  "goal": "Vérifier que les étudiants préfèrent dicter leurs livrables plutôt que les remplir dans un outil.",
  "personas": [
    {"name": "Camille, 22 ans", "role": "Étudiante M1 chef de projet",
     "quote": "« Je passe plus de temps sur PowerPoint que sur le projet. »",
     "goals": ["Rendre des livrables propres"], "pains": ["Mise en forme interminable"]}
  ],
  "items": [
    {"id": "D1", "type": "hypothesis", "title": "Les étudiants passent plus de 3 h par livrable",
     "detail": "Mesurer sur 10 équipes", "method": "questionnaire", "status": "todo", "outcome": "", "leads_to": []},
    {"id": "D2", "type": "spike", "title": "Dessiner un Gantt en SVG sans librairie",
     "detail": "Time-box : 1 jour", "status": "todo"}
  ]
}
```

8 to 15 items. Ids D1, D2… and keep them stable across runs.

## Finish

```bash
python3 .claude/scrum-kit/render.py . --check
```

Fix every ERROR. Note assumptions in `scrum/decisions.md`; questions only the
user can answer go in `scrum/questions.md`.
