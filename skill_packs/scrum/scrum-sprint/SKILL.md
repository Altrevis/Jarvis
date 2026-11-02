---
name: scrum-sprint
description: >-
  Plans sprints from the product backlog: sprint goal, dates, team capacity,
  the stories committed against velocity, the sprint backlog broken into
  tasks with owners and hours, and the burndown. Also updates task statuses
  and the burndown during a sprint. Writes JSON the assistant draws as a
  board and a burndown chart. Use when the user says "sprint backlog",
  "sprint planning", "planifie le sprint", "objectif de sprint", "burndown",
  "vélocité", "capacité", "tâches du sprint", "mets à jour le sprint".
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

1. **Sprint goal first**: one sentence on the value the increment brings
   ("Produire le cadrage complet à la voix"). The stories serve the goal, not
   the other way round.
2. Take stories **in backlog order** that are `ready` (or could be) and serve
   the goal, until the next one would exceed capacity. Never commit beyond
   capacity: the renderer warns.
3. Set each committed story's `sprint` to the sprint id and its `status` to
   `ready` (or keep `doing`/`done`) **in product-backlog.json**.
4. Break each committed story into **tasks** of 1 to 8 hours: design, build,
   test, review, document — what the DoD requires. Give each an `owner` and
   `hours`. Status starts at `todo`.

Plan the first sprint in full detail. Plan the following ones (2 to 4) at
story level only — goal, dates, stories, no tasks yet. That is how Scrum
works: detail arrives just in time.

## During a sprint

When the task is an update ("US-02 est terminée", "Marc a fini le dessin
SVG"), change task and story statuses and append today's remaining points to
`burndown`: one number per working day since the sprint started, the points
of committed stories not yet `done`.

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
     "burndown": [10]},
    {"id": "S2", "name": "Sprint 2", "goal": "...", "start": "2026-11-09", "end": "2026-11-20",
     "capacity": 14, "stories": ["US-04", "US-05"], "tasks": []}
  ]
}
```

Dates are YYYY-MM-DD; sprints follow each other with no gap and no overlap.
`burndown` is optional: leave it out until the sprint has started.

## Finish

```bash
python3 .claude/scrum-kit/render.py . --check
```

Fix every ERROR (a story id that is not in the backlog, a bad date). Note
assumptions — velocity above all — in `scrum/decisions.md`.
