---
name: scrum-planning
description: >-
  Builds the project schedule: phases and deliverables as a Gantt chart, the
  sprints on the same timeline, the milestones (kick-off, reviews, deadlines,
  defence), and the calendar of Scrum ceremonies with their frequency,
  duration, attendees and purpose. Use when the user says "planning",
  "Gantt", "calendrier", "roadmap", "jalons", "échéances", "release plan",
  "cérémonies", "rituels", "dates du projet".
---

# scrum-planning

One deliverable: `scrum/planning.json`.

Read `CLAUDE.md` (deadlines, start date, availability) and `scrum/sprints.json`
if it exists, and the `milestones` and deliverable dates of
`scrum/cahier-des-charges.json` if it exists — they were promised to the
client: keep them, or say in `scrum/decisions.md` why they move. **Do not
copy the sprints into `items`**: the renderer adds every
sprint of sprints.json to the Gantt by itself, in a "Sprints" group. Set
`"include_sprints": false` only if you really want them hidden.

No dates in the brief: start on the next Monday after today, say so in
`scrum/decisions.md`, and keep the plan consistent with the sprints.

## Items

Bars on the Gantt, grouped by `group` (drawn in the order groups first
appear):

- **Phases** — cadrage, discovery, réalisation, recette, livraison… Scrum
  does not have phases inside the delivery, but projects in a school or a
  company do have a frame around it: show it.
- **Livrables** — documents and events that are not sprints: dossier,
  soutenance, démo, formation, mise en production.
- Any other group the project needs (Communication, Recrutement, Marketing).

Each item: `id`, `label` (short, it is drawn on one line), `group`, `start`,
`end` (YYYY-MM-DD, inclusive), optional `owner` (drawn on the bar).
6 to 20 items; more and nobody reads it.

## Milestones

Points in time, no duration: kick-off, end of each release, reviews with the
référent or client, deadlines, the defence. Each: `label` and `date`.

## Ceremonies

The Scrum events, fitted to this team's rhythm. Give each a `kind`
(`planning`, `daily`, `review`, `retrospective`, `refinement`): the
renderer checks durations against the Scrum Guide timeboxes for the sprint
length and shows them on the Scrum framework page.

| name | when | duration (2-week sprint) |
|---|---|---|
| Sprint planning | first day of the sprint | ≤ 4 h |
| Daily scrum | every working day, same time | 15 min |
| Sprint review | last day of the sprint | ≤ 2 h |
| Sprint retrospective | after the review | ≤ 1 h 30 |
| Backlog refinement | mid-sprint (not an official event, but needed) | ≤ 10% of capacity |

Scale durations with sprint length (they are maxima for a 1-month sprint —
8 h, 4 h, 3 h — halved for 2 weeks). What each one is for (Scrum Guide 2020):

- **Sprint planning** — the Sprint Goal (why), the items (what), the plan
  (how).
- **Daily scrum** — for the Developers: progress towards the Sprint Goal and
  the plan for the next day. The three questions are gone since 2020; any
  format that serves the goal will do.
- **Sprint review** — a working session with the stakeholders on the
  Increment, which adapts the product backlog; not a slideshow.
- **Sprint retrospective** — how to improve quality and the way of working;
  ends with a few owned actions.
- **Backlog refinement** — an ongoing activity, not an official event.

For a part-time student team, a daily may be 3 times a week: say so rather
than pretend.

```json
{
  "items": [
    {"id": "P1", "label": "Cadrage et discovery", "group": "Phases", "start": "2026-10-19", "end": "2026-10-30"},
    {"id": "L1", "label": "Rédaction du dossier", "group": "Livrables", "start": "2026-11-23", "end": "2026-12-11", "owner": "Léo"}
  ],
  "milestones": [{"label": "Soutenance", "date": "2026-12-17"}],
  "ceremonies": [
    {"name": "Daily scrum", "kind": "daily", "when": "Chaque jour, 9 h 30", "duration": "15 min",
     "who": "Developers", "purpose": "Inspecter la progression vers l'objectif du sprint, planifier la journée"}
  ]
}
```

## Finish

```bash
python3 .claude/scrum-kit/render.py . --check
```

Fix every ERROR (dates above all). Note assumptions in `scrum/decisions.md`.
