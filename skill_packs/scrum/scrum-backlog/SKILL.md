---
name: scrum-backlog
description: >-
  Writes the product backlog the Scrum Guide 2020 way: an ordered, emergent
  list under one Product Goal — epics, user stories in the "En tant que / je
  veux / afin de" form with Given/When/Then acceptance criteria, plus bugs,
  technical items and time-boxed spikes — sized in Fibonacci points, with
  MoSCoW priority and business value, refined from the top, and the
  Definition of Ready and Definition of Done. Drawn as a story map, a backlog
  health panel, a value / effort matrix and the Scrum framework page. Use
  when the user says "product backlog", "user stories", "epics", "rédige
  les stories", "story map", "estimation", "priorisation", "MoSCoW",
  "matrice valeur effort", "affinage", "refinement", "DoR", "DoD",
  "critères d'acceptation".
---

# scrum-backlog

One deliverable: `scrum/product-backlog.json`.

Read `CLAUDE.md` and, when they exist, `scrum/pieuvre.json` (every FP should
be covered by at least one epic), `scrum/discovery.json` (validated items
justify stories; invalidated ones kill them) and `scrum/parties-prenantes.json`
(the "as" of each story is one of these users).

When `scrum/cahier-des-charges.json` exists it is the reference: the backlog
implements its functional requirements, nothing outside its scope. Every
story names the requirement(s) it implements in `requirements` (["EF-03"]),
every `must` requirement is implemented by at least one story, and an
out-of-scope item never becomes a story.

**Do not convert the specification requirement by requirement** (Mike Cohn):
a specification is good at saying *what*, bad at planning — its numbered
items depend on each other and cannot be ordered or delivered one at a time.
Write stories as **vertical slices** a user can try at the end of a sprint;
one story may implement several requirements, and one requirement may take
several stories. The `requirements` links are what makes sure nothing falls
through the cracks: the checker lists every must-have no story implements.

If the file already exists, **update it**: keep ids, statuses and sprint
assignments; add, split or reword stories; never renumber.

## Product goal

The commitment of the Product Backlog (Scrum Guide 2020): **a future state of
the product**, the long-term target the team plans towards, measurable — "Une
équipe produit tous ses livrables à la voix en moins d'une heure". One at a
time: the team reaches it (or drops it) before taking the next. The rest of
the backlog emerges to say *what* gets there.

## What goes in the backlog

The backlog is the single source of work — nothing is worked on that is not
in it — so it holds more than user stories (`type`):

- `story` (default) — user value, written as below.
- `bug` — a defect found in a review or a test: `title`, `description`
  (what happens, what should), acceptance criteria. Ordered by impact.
- `tech` — technical debt, refactoring, infrastructure, an enabler a later
  story needs: `title`, `description` saying why it matters to the product.
  Left out of the backlog, debt piles up and slows every sprint.
- `spike` — a time-boxed investigation that buys knowledge, not a feature:
  `title`, `description` (the question), `timebox` ("2 jours"), and as
  acceptance the answer expected at the end.

The Product Owner **orders** the backlog and is the only one who changes the
order; stakeholders feed it, they do not prioritise it. The **Developers
size** the items (Planning Poker, relative points) — they do the work.

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
  involved ("Étant donné …, quand …, alors …"). Cover the main path **and**
  an alternative or error case. Testable, no "should be fast". They are
  specific to the story — what every item needs goes in the DoD.
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
- `requirements`: ids of the cahier des charges requirements it implements,
  when there is one.
- `type`: `story` unless it is a `bug`, `tech` or `spike` (see above);
  a spike also has `timebox`.

Check every story against **INVEST**: Independent, Negotiable, Valuable,
Estimable, Small, Testable. A story that is a task ("Créer la table users")
is not a story: fold it into the story it serves.

**Order** the `stories` array as the Product Owner would: must before should
before could, then higher value / smaller size first. The array order *is*
the backlog order.

Must-haves should total no more than about 60% of the points: if everything
is a must, nothing is. The **value / effort** page plots `value` against
`points`: quick wins (high value, small) should sit near the top of the
order, big low-value items should be questioned or become `wont`. Managing
a backlog is as much saying no as ordering.

## Refinement: detailed at the top, coarse below

Refinement is continuous (about 10 % of the team's capacity, not an official
event): split, clarify, add acceptance criteria, estimate. Keep the backlog
**emergent and appropriately detailed**:

- the top items are `ready` (they meet the DoR) and add up to **at least one
  sprint of velocity** — the checker warns when the next Sprint Planning
  would starve;
- below, refined items (estimated, with criteria, not yet ready);
- at the bottom, coarse items and epics. As a guide: about 20 % ready, 30 %
  refined, 50 % to refine. Do not detail what will change before it is built.

Past 150 items nobody reads it: merge, archive, keep the far future as epics.

## DoR and DoD

- `definition_of_ready`: 4–6 conditions for an item to enter a sprint
  (format, criteria written, estimated by the Developers, dependencies known,
  ≤ 8 points). It is checked at refinement, upstream.
- `definition_of_done`: the commitment of the **Increment** (Scrum Guide
  2020) — the quality every item must reach to count as done, the same for
  all items. **5 to 15 criteria, each checkable yes or no** ("Code relu par un
  pair", "Tests automatisés verts", "Testé sur Windows et Linux") — never
  "code propre". Include the non-functional requirements of the cahier des
  charges that apply to every item, by id ("Temps d'affichage ≤ 5 s
  (ENF-01)"). Adapt to the project: a report-writing project has no
  "déployé en production". An item that does not meet it is not shown at the
  Sprint Review and goes back to the backlog. The team revisits it at each
  retrospective.

```json
{
  "product_goal": "...",
  "epics": [{"id": "E1", "title": "Cadrage du projet", "description": "Bête à cornes, pieuvre, SWOT"}],
  "stories": [
    {"id": "US-01", "epic": "E1", "title": "Bête à cornes vocale",
     "as": "chef de projet", "want": "décrire mon projet à la voix",
     "so_that": "obtenir la bête à cornes sans la dessiner",
     "acceptance": ["Étant donné un projet décrit, quand je demande la bête à cornes, alors le diagramme s'affiche"],
     "points": 3, "priority": "must", "value": 80, "status": "todo", "requirements": ["EF-01"]},
    {"id": "BUG-01", "type": "bug", "epic": "E1", "title": "Le Gantt déborde de la page PDF",
     "description": "Au-delà de 12 semaines la dernière colonne est coupée",
     "acceptance": ["Étant donné 16 semaines, quand j'exporte, alors tout le Gantt tient sur la page"],
     "points": 2, "priority": "should", "value": 60, "status": "todo"},
    {"id": "SPK-01", "type": "spike", "epic": "E1", "title": "Reconnaissance vocale hors ligne",
     "description": "Vosk ou Whisper local tiennent-ils sur un poste étudiant ?", "timebox": "2 jours",
     "acceptance": ["Une recommandation écrite, avec le taux mesuré sur 20 commandes"],
     "points": 2, "priority": "could", "value": 35, "status": "todo"}
  ],
  "definition_of_ready": ["..."],
  "definition_of_done": ["..."]
}
```

15 to 40 items for a first backlog. Ids US-01… for stories, BUG-01…,
TECH-01…, SPK-01… for the others.

When the discovery file exists, fill its items' `leads_to` with the epics or
stories they justify.

## Finish

```bash
python3 .claude/scrum-kit/render.py . --check
```

Fix every ERROR. A story above 13 points is a warning you should act on.
Note assumptions in `scrum/decisions.md`.
