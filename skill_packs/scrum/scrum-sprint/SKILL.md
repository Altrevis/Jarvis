---
name: scrum-sprint
description: >-
  Plans sprints from the product backlog the Scrum Guide 2020 way — the
  Sprint Goal (why), the items selected against velocity (what), the plan in
  tasks of a day or less (how) — updates tasks and the burndown during the
  sprint, and records the Sprint Review and the Sprint Retrospective at its
  end. Drawn as a board, a burndown, the Increment, a velocity chart and a
  product burn-up. Use when the user says "sprint backlog", "sprint
  planning", "planifie le sprint", "objectif de sprint", "burndown",
  "vélocité", "capacité", "tâches du sprint", "mets à jour le sprint",
  "sprint review", "rétrospective", "fin du sprint", "increment".
---

# scrum-sprint

One deliverable: `scrum/sprints.json`. It needs `scrum/product-backlog.json`:
if that file is missing, stop and say the backlog step comes first.

Read the backlog (stories, points, priorities, DoR) and `CLAUDE.md` (team
size, availability, project dates). If `scrum/raci.json` exists, task owners
are the people in its roles.

## Capacity and velocity

- **velocity**: points the team finishes per sprint. Known → use it. Unknown
  (first sprint) → estimate it from capacity: roughly 1 point per person per
  2 days of focused work, then take 70–80% of that for a first sprint. State
  the assumption in `scrum/decisions.md`.
- **capacity** per sprint: the points the team can take *this* sprint —
  velocity adjusted for holidays, exams, part-time members.
- **Sprint length**: 1 to 4 weeks, the same for every sprint; default 2.

## Planning a sprint

Sprint Planning answers three questions (Scrum Guide 2020); together the
answers are the **Sprint Backlog**, a plan by and for the Developers:

1. **Why is this sprint valuable? — the Sprint Goal**, the Sprint Backlog's
   commitment: one sentence on the value the Increment brings ("Produire le
   cadrage complet à la voix"). The stories serve the goal, not the other way
   round. During the sprint nothing may endanger it and quality is never
   lowered; the scope can be renegotiated with the Product Owner, the goal
   stays.
2. **What can be done? — the items.** The Developers select them with the
   Product Owner, **in backlog order**, `ready` (or nearly), serving the
   goal, until the next one would exceed capacity. Never commit beyond
   capacity: the renderer warns.
3. Set each committed story's `sprint` to the sprint id and its `status` to
   `ready` (or keep `doing`/`done`) **in product-backlog.json**.
4. **How will it be done? — the plan**: break each committed story into
   **tasks of a day or less** (1 to 8 hours; the checker flags longer ones):
   design, build, test, review, document — what the DoD requires. Give each
   an `owner` and `hours`. Status starts at `todo`. When the previous
   retrospective decided improvement actions, add the most important one as
   a task too.

Plan the first sprint in full detail. Plan the following ones (2 to 4) at
story level only — goal, dates, stories, no tasks yet. That is how Scrum
works: detail arrives just in time.

## During a sprint

When the task is an update ("US-02 est terminée", "Marc a fini le dessin
SVG"), change task and story statuses and append today's remaining points to
`burndown`: one number per working day since the sprint started, the points
of committed stories not yet `done`. A story is `done` only when it meets the
Definition of Done — not when its code is written.

## At the end of a sprint

When the user says the sprint is over, or reports the review or the retro:

- **Increment**: the stories that meet the DoD stay `done`. The others are
  not shown at the review and go back to the product backlog: status back to
  `ready` or `todo`, `sprint` set to the next sprint if they carry over.
- **Sprint Review** — a working session with the stakeholders, not a demo:
  `review.feedback` (what they said) and `review.backlog_changes` (what it
  changes in the product backlog — and make those changes in
  product-backlog.json).
- **Sprint Retrospective**: `retrospective.went_well`, `to_improve`, and
  `actions` [{action, owner}] — few, concrete, owned. The checker warns
  about a sprint that is over with no retrospective.
- **Velocity**: the points actually done; update `velocity` as the average
  of the last sprints and use it for the next capacity.

```json
{
  "velocity": 12,
  "sprints": [
    {"id": "S1", "name": "Sprint 1", "goal": "Produire le cadrage complet à la voix",
     "start": "2026-10-26", "end": "2026-11-06", "capacity": 12,
     "stories": ["US-01", "US-02", "US-03"],
     "tasks": [
       {"story": "US-01", "title": "Schéma JSON de la bête à cornes", "owner": "Léo", "hours": 2, "status": "todo"}
     ],
     "burndown": [10, 10, 8],
     "review": {"feedback": ["Le référent veut voir la flexibilité F0–F3"],
                "backlog_changes": ["US-03 reportée au sprint 2", "Ajout de BUG-01"]},
     "retrospective": {"went_well": ["Daily tenu chaque jour"], "to_improve": ["Revue de code tardive"],
                       "actions": [{"action": "Revue de code avant 17 h", "owner": "Marc"}]}},
    {"id": "S2", "name": "Sprint 2", "goal": "...", "start": "2026-11-09", "end": "2026-11-20",
     "capacity": 14, "stories": ["US-04", "US-05"], "tasks": []}
  ]
}
```

Dates are YYYY-MM-DD; sprints follow each other with no gap and no overlap,
all of the same length, one month at most. `burndown`, `review` and
`retrospective` are optional: leave them out until they happen.

## Finish

```bash
python3 .claude/scrum-kit/render.py . --check
```

Fix every ERROR (a story id that is not in the backlog, a bad date). Note
assumptions — velocity above all — in `scrum/decisions.md`.
