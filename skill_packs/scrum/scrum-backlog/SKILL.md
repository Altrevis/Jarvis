---
name: scrum-backlog
description: >-
  Writes the product backlog: the product goal, epics, and user stories in
  the "En tant que / je veux / afin de" form with Given/When/Then acceptance
  criteria, Fibonacci estimates, MoSCoW priority and business value, ordered
  by the Product Owner's priority, plus the Definition of Ready and the
  Definition of Done. Writes JSON the assistant draws as a story map. Use when
  the user says "product backlog", "user stories", "epics", "rédige les
  stories", "story map", "estimation", "priorisation", "MoSCoW", "DoR",
  "DoD", "critères d'acceptation".
---

# scrum-backlog

One deliverable: `scrum/product-backlog.json`.

Read `CLAUDE.md` and, when they exist, `scrum/pieuvre.json` (every FP should
be covered by at least one epic), `scrum/discovery.json` (validated items
justify stories; invalidated ones kill them) and `scrum/parties-prenantes.json`
(the "as" of each story is one of these users).

If the file already exists, **update it**: keep ids, statuses and sprint
assignments; add, split or reword stories; never renumber.

## Product goal

One sentence: the measurable outcome the backlog is ordered towards ("Une
équipe produit tous ses livrables à la voix en moins d'une heure").

## Epics

3 to 7. An epic is a large user-facing capability, named as an outcome
("Cadrage du projet", "Paiement en ligne"), not a technical layer
("Backend", "Base de données").

## User stories

**Card, Conversation, Confirmation.** Each story:

- `title`: 2–6 words, what the card shows.
- `as` / `want` / `so_that`: *En tant que <persona or role>, je veux
  <action>, afin de <benefit>*. The benefit is for the user, never "so that
  the feature exists".
- `acceptance`: 2–4 criteria, in Given/When/Then form when behaviour is
  involved ("Étant donné …, quand …, alors …"). Testable, no "should be fast".
- `points`: relative size on the Fibonacci scale 1, 2, 3, 5, 8, 13 (0 and ½
  for trivial ones; 20, 40, 100 only for epics-in-disguise you have not split
  yet). **Above 8, split** — by workflow step, by business rule, by data
  variation, by happy path vs edge cases.
- `priority`: MoSCoW — `must` (the product fails without it), `should`
  (important, a workaround exists), `could` (nice), `wont` (explicitly not
  this release — keep them, they record a decision).
- `value`: business value 1–100, relative across the backlog.
- `status`: `todo`, `ready` (meets the DoR), `doing`, `done`.
- `sprint`: the sprint id once planned, otherwise leave it out.

Check every story against **INVEST**: Independent, Negotiable, Valuable,
Estimable, Small, Testable. A story that is a task ("Créer la table users")
is not a story: fold it into the story it serves.

**Order** the `stories` array as the Product Owner would: must before should
before could, then higher value / smaller size first. The array order *is*
the backlog order.

Must-haves should total no more than about 60% of the points: if everything
is a must, nothing is.

## DoR and DoD

- `definition_of_ready`: 4–6 conditions for a story to enter a sprint
  (format, criteria written, estimated, dependencies known, ≤ 8 points).
- `definition_of_done`: 4–6 conditions for an increment to count as done
  (reviewed, tested, integrated, documented, accepted by the PO). Adapt to
  the project — a report-writing project does not have "deployed to prod".

```json
{
  "product_goal": "...",
  "epics": [{"id": "E1", "title": "Cadrage du projet", "description": "Bête à cornes, pieuvre, SWOT"}],
  "stories": [
    {"id": "US-01", "epic": "E1", "title": "Bête à cornes vocale",
     "as": "chef de projet", "want": "décrire mon projet à la voix",
     "so_that": "obtenir la bête à cornes sans la dessiner",
     "acceptance": ["Étant donné un projet décrit, quand je demande la bête à cornes, alors le diagramme s'affiche"],
     "points": 3, "priority": "must", "value": 80, "status": "todo"}
  ],
  "definition_of_ready": ["..."],
  "definition_of_done": ["..."]
}
```

15 to 40 stories for a first backlog. Ids US-01, US-02…

When the discovery file exists, fill its items' `leads_to` with the epics or
stories they justify.

## Finish

```bash
python3 .claude/scrum-kit/render.py . --check
```

Fix every ERROR. A story above 13 points is a warning you should act on.
Note assumptions in `scrum/decisions.md`.
