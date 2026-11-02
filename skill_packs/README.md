# Skill packs

Claude skills that ship with the app but are **not** installed in
`workspace/.claude/skills/`. Every `ask_claude` task lists every skill it can
see there, so a pack only one feature uses would be paid for, in tokens, on
every task that never touches it. A pack here is copied into the folder of the
thing that needs it instead.

## replica/

The Replica pack by Jake Schincariol — eleven skills that take an app from
recon to launch, each reading what the previous one wrote in `replica/`.

- Source: https://github.com/Jakeschincariol/replica-skill
- Commit: `77c9436fb3d18c3d58169efb8caf4fe906b0dc51` (2026-10-03)
- Licence: MIT, see `replica/LICENSE`
- Left out: the repository's `tests/` and `.claude-plugin/` manifest

Used by `actions/project.py`: each project gets its own copy in
`<project>/.claude/skills/`. The bundled Python tools are standard-library only
and make no network calls. To update, copy the `replica-*` folders from a newer
commit over these and change the commit above.

## scrum/

Ours. Seven skills, one per step of a Scrum project file, each writing JSON in
the workspace's `scrum/` and reading what the previous ones wrote:

| Skill | Writes |
|---|---|
| `scrum-cadrage` | `bete-a-cornes.json`, `pieuvre.json`, `swot.json`, the vision in `meta.json` |
| `scrum-parties-prenantes` | `parties-prenantes.json` (power/interest), `raci.json` |
| `scrum-discovery` | `discovery.json` (personas, hypotheses, experiments) |
| `scrum-backlog` | `product-backlog.json` (epics, stories, DoR, DoD) |
| `scrum-sprint` | `sprints.json` (goals, tasks, burndown) |
| `scrum-risques` | `risques.json` |
| `scrum-planning` | `planning.json` (Gantt, milestones, ceremonies) |

`render.py` draws all of it — standard library only, no network — into
self-contained HTML with inline SVG, and `--check` validates the data (one A
per RACI row, an FP links two elements, story points on the Fibonacci scale,
dates…). Each shape is documented in the SKILL.md that writes it.

Used by `actions/scrum.py`: each workspace gets the skills in
`<workspace>/.claude/skills/` and a copy of the renderer in
`.claude/scrum-kit/` for the agents' own checks. The assistant always draws
with the copy here, which no agent can edit.
