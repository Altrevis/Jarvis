---
name: chiffrage-estimation
description: >-
  Estimates every work package of the WBS in three points (optimistic, most
  likely, pessimistic) the PERT way, adds the proportional overheads, and
  cross-checks the total with a second method — function points (IFPUG),
  COCOMO 81 / II, story points and velocity, analogy or expert judgement.
  The calculator turns it into a probability (P50, P80, P90, Monte Carlo),
  the critical path and the delay, and places it on the cone of
  uncertainty. Use when the user says "estimation", "estimer", "chiffrer la
  charge", "jours-homme", "PERT", "trois points", "estimation 3 points",
  "Planning Poker", "story points", "vélocité", "points de fonction",
  "COCOMO", "paramétrique", "cône d'incertitude", "Monte Carlo", "P80",
  "chemin critique", "délai", "combien de temps".
---

# chiffrage-estimation

One deliverable: `chiffrage/estimation.json`, built on `chiffrage/wbs.json`
(run `chiffrage-wbs` first). **Write the inputs and the reasons; never
compute the totals** — `chiffrage.py` does every sum, root and percentile.

Read `CLAUDE.md`, `chiffrage/wbs.json`, `scrum/product-backlog.json` (story
points, refined stories), `scrum/sprints.json` (a measured velocity beats any
guess) and `scrum/risques.json`. If the file exists, update it.

## Why it is hard

At the concept stage an estimate is worth ×0.25 to ×4 (Boehm, McConnell);
the range narrows only as decisions are made. The biases are known:
**optimism** (we picture the happy path), **anchoring** on a first figure,
the **client's pressure**. The answers: decompose (the WBS), estimate in
three points, give a range, cross two methods. And: **estimating is not
committing** — an estimate is a forecast, a commitment is a decision taken
on it. Never shrink an estimate to fit a budget: cut the scope instead.

## Three points per work package (PERT)

For every leaf of the WBS, in jours-homme (person-days):

- `o`, optimistic: everything goes right — about 1 chance in 20 of doing
  better. Not "if nothing at all happens".
- `m`, most likely: the value you would see most often — not the average.
- `p`, pessimistic: what goes wrong usually does (third-party API late, a
  rule misunderstood, one rework round) — about 1 chance in 20 of doing
  worse. Not the asteroid: catastrophes are risks, not estimates.
- `people`: people on that package at the same time (1 by default); the
  delay of the package is its effort divided by it.
- `basis`: why this figure, in one line ("CRUD + rôles, déjà fait sur le
  projet X", "API Stripe jamais utilisée par l'équipe").

Rules: 0 ≤ o ≤ m ≤ p. `p` well above `m` is normal (work overruns more than
it underruns). `p` above 3 × `m` means you do not know: plan a spike first.
`m` above 10 days: go back to the WBS and split. If the people who will do
the work are known, the estimate is theirs (Planning Poker: estimate in
secret, reveal together, the lowest and the highest explain, estimate again;
the debate brings out the misunderstandings before coding).

The calculator gives per package Dp = (O + 4M + P) / 6 and σ = (P − O) / 6,
for the project ΣDp and σ = √Σσ², then P50, P80 = P50 + 0.84 σ, P90, and a
Monte Carlo of 10 000 runs on PERT-Beta laws that also gives the delay along
the critical path. **One commits at P80 and aims at P50** — announce 32 j,
not 30. The packages are assumed independent; in reality their errors go the
same way, so the true spread is wider: that is what the cone reminds.

## Overheads (proportional work)

`overheads`: activities with no deliverable of their own, as a rate of the
work packages' effort. Usual values: project management 10–15 %, Scrum
ceremonies (dailies, planning, review, retro, refinement) about 10 %, code
reviews 5 %. Tests written with the code are in each package; recette,
CI/CD and mise en production are WBS packages, not overheads. The checker
warns when pure development is above 70 % of the total: something indirect
was forgotten.

## Cross-check with a second method

At least one `cross_checks` entry — « jamais une seule méthode à
l'aveugle ». The checker warns when a method lands outside ×0.67–×1.5 of the
PERT total: then find why (scope missing from the WBS? optimism? the
productivity used?) and write it in `chiffrage/decisions.md`. Choose:

- **Velocity** (`velocite`), the agile one, for delivery: backlog points ÷
  velocity range = number of sprints × sprint days × team. Points are taken
  from the backlog if you give none. Velocity is a **range** (Cohn): measured
  over the last sprints when there are some, otherwise forecast from the
  team's capacity and say so.
- **Function points** (`points-de-fonction`, IFPUG), for pre-sales or a
  macro estimate: count what the software *does*, whatever the techno. EI
  (external inputs: a form, an import), EO (outputs with computation: a
  report, an export, an invoice), EQ (queries: a search, a display), ILF
  (groups of data the app maintains: users, bookings), EIF (data maintained
  by another system and only read: the payment provider's transactions, an
  ERP catalogue). Give a count per type (average weight) or
  `{"low", "avg", "high"}`. Weights: EI 3/4/6, EO 4/5/7, EQ 3/4/6,
  ILF 7/10/15, EIF 5/7/10. Adjust with `vaf` (0.65–1.35) or the 14 `gsc`
  ratings (0–5). Productivity `hours_per_fp`: about 10 h/FP in the course —
  calibrate it on your own past projects, it varies by techno and team.
- **COCOMO** (`cocomo`, basic COCOMO 81): effort = a × KLOC^b
  person-months, duration = 2.5 × effort^d months, with organique 2.4 /
  1.05 / 0.38, semi-détaché 3.0 / 1.12 / 0.35, embarqué 3.6 / 1.20 / 0.32
  (Boehm 1981 — note that the duration exponent differs by mode).
  `cocomo2` uses COCOMO II (2.94 × KLOC^E, E = 0.91 + 0.01 ΣSF, nominal
  scale factors by default). The size in KLOC is itself an estimate — the
  weakest input: use it as an order of magnitude.
- **Analogy** (`analogie`): a finished project like this one, its actual
  effort and a `factor` for the differences.
- **Expert judgement** (`expert`): quick and subjective; name the expert.

## Shape

```json
{
  "confidence": 0.8,
  "team": 3,
  "estimates": [
    {"id": "1.1", "o": 2, "m": 3, "p": 5, "basis": "2 ateliers + rédaction"},
    {"id": "3.2", "o": 4, "m": 7, "p": 14, "people": 1,
     "basis": "Stripe jamais intégré par l'équipe : forte incertitude"}
  ],
  "overheads": [
    {"label": "Gestion de projet", "rate": 0.12},
    {"label": "Cérémonies Scrum", "rate": 0.10}
  ],
  "cross_checks": [
    {"method": "velocite", "velocity": [18, 24], "sprint_days": 10, "team": 3},
    {"method": "points-de-fonction", "counts": {"EI": 6, "EO": 4, "EQ": 5, "ILF": 3, "EIF": 1},
     "vaf": 1.05, "hours_per_fp": 10},
    {"method": "cocomo", "kloc": 12, "mode": "organique"}
  ]
}
```

`confidence` is the percentile you commit at (0.8 by default). `team` is the
number of people who share the packages: the delay is at least the effort
divided by the team, whatever the critical path says.

## Finish

```bash
python3 .claude/chiffrage-kit/chiffrage.py .
```

Fix every ERROR, act on the warnings, then read `livrables/chiffrage.md`:
the packages on the critical path, the biggest σ (the riskiest packages, to
clarify first), the gap between methods. Write in `chiffrage/decisions.md`
the figures you will defend and why.
