# Skill packs

Claude skills that ship with the app but are **not** installed in
`workspace/.claude/skills/`. A pack is a method for **another project** — a
product, a project file, an estimate — never for changing Jarvis itself
(that is a mission targeting this repository; see `skill_spaces/README.md`,
"Two purposes"). A pack can still be pointed at Jarvis as its subject: the
Scrum file or the chiffrage of the Jarvis project are documents about it, not
changes to its code. Every `ask_claude` task lists every skill it can
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

Ours. Eight skills, one per step of a Scrum project file, each writing JSON in
the workspace's `scrum/` and reading what the previous ones wrote:

| Skill | Writes |
|---|---|
| `scrum-cadrage` | `bete-a-cornes.json`, `pieuvre.json`, `swot.json`, the vision in `meta.json` |
| `scrum-parties-prenantes` | `parties-prenantes.json` (power/interest), `raci.json` |
| `scrum-discovery` | `discovery.json` (personas, hypotheses, experiments) |
| `scrum-cahier-des-charges` | `cahier-des-charges.json` (the specification, NF EN 16271; assembled with the files above into one document, PDF and Word) |
| `scrum-backlog` | `product-backlog.json` (product goal, epics, stories, bugs, technical items, spikes, DoR, DoD; also drawn as the value / effort matrix and the Scrum framework page) |
| `scrum-sprint` | `sprints.json` (goals, tasks, burndown, review, retrospective; velocity and burn-up are computed) |
| `scrum-risques` | `risques.json` (drawn three ways: register, risk matrix before / after treatment, heat map) |
| `scrum-planning` | `planning.json` (Gantt, milestones, ceremonies) |

`render.py` draws all of it — standard library only, no network — into
self-contained HTML with inline SVG, and `--check` validates the data (one A
per RACI row, an FP links two elements, story points on the Fibonacci scale,
dates…). Each shape is documented in the SKILL.md that writes it.

Used by `actions/scrum.py`: each workspace gets the skills in
`<workspace>/.claude/skills/` and a copy of the renderer in
`.claude/scrum-kit/` for the agents' own checks, both refreshed from here
before every run so older workspaces follow changes. The assistant always
draws with the copy here, which no agent can edit.

## chiffrage/

Ours. Five skills for estimating and pricing a software project, following
the Ynov M1 module « Estimation & Chiffrage de projets complexes »
(WBS → estimation → budget → TCO → pitch). Each writes in the workspace's
`chiffrage/` and reads what the previous ones wrote; the first one also
reads the Scrum pack's `scrum/product-backlog.json`, so a chiffrage builds
on a backlog when there is one.

| Skill | Writes |
|---|---|
| `chiffrage-wbs` | `wbs.json` (work packages of 1–10 days with deliverables, indirect work, dependencies, phase on the cone of uncertainty, assumptions, exclusions; every backlog story in one package) |
| `chiffrage-estimation` | `estimation.json` (three points per package, overheads, cross-checks: velocity, function points, COCOMO 81 / II, analogy, expert; engagement percentile) |
| `chiffrage-budget` | `budget.json` (profiles and TJM or loaded salaries, allocation, costs outside the team, contingency, reserve, margin, VAT, payment schedule) |
| `chiffrage-tco` | `tco.json` (run over 3–5 years, end of life, alternatives, gains) |
| `chiffrage-pitch` | `pitch.md` (the defence in front of a decision-maker, with the objections) |

`chiffrage.py` does every calculation — standard library only, no network:
PERT per package and for the project (√Σσ²), P50 / P80 / P90, a seeded
Monte Carlo of 10 000 runs on PERT-Beta laws with the critical path of each
run, the delay and the delivery date, the cone of uncertainty, the
cross-check methods, the budget and the year-by-year TCO with ROI and
payback. It writes `chiffrage/synthese.json` and `livrables/chiffrage.md`;
`--check` validates only (100 % rule against the backlog, o ≤ m ≤ p,
packages above 10 days, dependency cycles, allocation shares, schedule
adding up to 100 %, a pitch section missing…), `--json` prints the summary.
The agents must never do the arithmetic themselves.

The skills call it as `.claude/chiffrage-kit/chiffrage.py`, like the Scrum
pack's renderer: whatever installs the pack copies the skills to
`<workspace>/.claude/skills/` and `chiffrage.py` to
`<workspace>/.claude/chiffrage-kit/`. No action installs it yet.
