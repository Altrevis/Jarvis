---
name: chiffrage-tco
description: >-
  Computes the total cost of ownership of the software over 3 to 5 years:
  the build from the budget, then every year of run — hosting, maintenance
  (corrective, adaptive, evolutive), licences and third-party services,
  support, operations, security, compliance, training — with growth and
  indexation, the end of life, a comparison with the alternatives (buy a
  SaaS, keep the existing) and, when gains are known, the ROI and the
  payback year. Use when the user says "TCO", "coût total de possession",
  "coût complet", "coût sur 3 ans", "coût sur 5 ans", "run", "build vs run",
  "maintenance", "TMA", "coûts récurrents", "make or buy", "ROI", "retour
  sur investissement", "rentabilité".
---

# chiffrage-tco

One deliverable: `chiffrage/tco.json`. The build comes from
`chiffrage/budget.json` (run `chiffrage-budget` first) unless you give an
amount. Write the recurring costs with their sources; `chiffrage.py` builds
the year-by-year table.

Read `CLAUDE.md`, `chiffrage/wbs.json` (techno, assumptions),
`chiffrage/budget.json`, `scrum/cahier-des-charges.json` (users, volumes,
availability and security requirements). Update the file if it exists.

## Why the TCO

The price of the build is the visible part. Over the life of a software the
run usually costs as much as the build or more: one study of 158 systems
found a development / five-year maintenance ratio around 1, about 20 % of
the build a year. A decision-maker compares options on their full cost over
the same horizon, not on their purchase price. Horizon: `years`, 3 by
default (the course), 5 for a structuring system.

## What the run holds

One `run` item per cost, each with a `category` and a `basis`:

- `hebergement`: production, pre-production, backups, CDN, domain names,
  certificates. Grows with the users (`growth`).
- `maintenance`: corrective (bugs) and adaptive (framework, runtime and
  dependency upgrades, security patches, browser and OS changes, API
  deprecations). Rule of thumb: **15–20 % of the build a year**
  (`rate_of_build`), an order of magnitude to replace with a TMA quote when
  there is one.
- `evolutions`: new features after go-live — a budget the client decides,
  keep it separate from maintenance.
- `licences`: per-seat SaaS, paid libraries — multiply by the number of
  users and their growth.
- `services`: third-party APIs billed per use — SMS, e-mail, maps, AI
  tokens, **payment fees** (a percentage of the transactions, often the
  biggest line of a marketplace).
- `support`: user support N1/N2, `exploitation`: monitoring, on-call,
  incident handling.
- `securite`: yearly penetration test, bug bounty, `conformite`: GDPR
  (register, DPO time, data requests), accessibility audit.
- `formation`: new users and turnover.

Each item gives **exactly one** of `monthly`, `yearly`, `rate_of_build`
(share of the build a year) or `amount` with its `year` (a one-off). Costs
grow with `growth` per year when given, otherwise with `indexation` (salary
and Syntec index, about 2–4 % a year). `from_year` delays a recurring item.

`end_of_life`: reversibility — data export and migration, decommissioning —
counted in the last year.

## Compare and justify

- `alternatives`: the other ways to meet the need over the same horizon —
  an off-the-shelf SaaS (`setup` + `monthly` per seat), keeping the current
  tool, a no-code solution. A build that costs more than a SaaS over three
  years needs a reason (differentiation, data ownership, specific rules).
- `gains` (optional): what the project saves or earns a year (time saved ×
  loaded cost, revenue, avoided licences), with a `basis`. The calculator
  gives the ROI and the payback year. Be conservative: gains are estimates
  too.

```json
{
  "years": 3,
  "indexation": 0.03,
  "build": "budget",
  "run": [
    {"label": "Hébergement (prod + préprod + sauvegardes)", "category": "hebergement",
     "monthly": 120, "growth": 0.2, "basis": "Scaleway, 2 instances + base managée"},
    {"label": "Maintenance corrective et adaptative", "category": "maintenance",
     "rate_of_build": 0.18, "basis": "15–20 % du build par an"},
    {"label": "Frais Stripe", "category": "services", "yearly": 1900,
     "basis": "1,5 % + 0,25 € × 6 000 réservations à 20 €"},
    {"label": "Test d'intrusion annuel", "category": "securite", "yearly": 3000, "from_year": 2,
     "basis": "devis"}
  ],
  "end_of_life": {"amount": 2000},
  "alternatives": [
    {"label": "SaaS de réservation du marché", "setup": 1000, "monthly": 450, "growth": 0.05,
     "basis": "tarif public, 10 praticiens"}
  ],
  "gains": [{"label": "Temps de secrétariat économisé", "yearly": 14000, "basis": "0,4 ETP"}]
}
```

## Finish

```bash
python3 .claude/chiffrage-kit/chiffrage.py .
```

Fix every ERROR. In `livrables/chiffrage.md`, read the share of the run in
the TCO and the gap with each alternative: these are the arguments of the
pitch. Note the sources in `chiffrage/decisions.md`.
