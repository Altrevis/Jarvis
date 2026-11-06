---
name: chiffrage-budget
description: >-
  Turns the estimate into an exhaustive build budget: team profiles and their
  daily rates (TJM) or loaded salaries, who does which work package, the
  costs outside the team (licences, environments, tools, legal, security),
  a contingency computed from the estimate's P80 or from the risks, a
  management reserve, the margin, VAT and the payment schedule — at a fixed
  price, time and materials, or for an internal project. Use when the user
  says "budget", "chiffrage", "devis", "prix", "coût du projet", "TJM",
  "taux journalier", "jours-homme en euros", "forfait", "régie", "provision
  pour risques", "contingence", "réserve", "marge", "échéancier",
  "combien ça coûte".
---

# chiffrage-budget

One deliverable: `chiffrage/budget.json`, built on `chiffrage/estimation.json`
(run `chiffrage-estimation` first). Write the rates, the allocation and the
costs with their sources; `chiffrage.py` multiplies and adds.

Read `CLAUDE.md`, `chiffrage/wbs.json` (assumptions, exclusions),
`chiffrage/estimation.json`, `scrum/risques.json` and
`scrum/parties-prenantes.json` (who is in the team). Update the file if it
exists.

## The pricing model

`pricing`:

- `forfait` (fixed price): the supplier commits to a scope, a price and a
  date — **the risk is the supplier's**, so a contingency is mandatory and
  the payment is split by milestones.
- `regie` (time and materials): the client pays the days worked; the risk is
  the client's. The budget is a forecast, the P80 figure a ceiling to agree.
- `interne`: an internal project — at cost, no margin, no VAT.

## Team: profiles and rates

One `profiles` entry per role (developer, lead dev, UX/UI designer,
project manager / Scrum Master, DevOps, QA…), with **either**:

- `tjm`: the market daily rate excluding VAT. Orders of magnitude in France,
  2026, for a freelance full stack developer: about 450 € (0–3 years),
  515 € (3–5), 580 € (5–8), 650 € (8+) (Hays); Île-de-France 15–30 % above
  the regions. An agency or ESN sells higher than a freelance.
- or `salary`: gross yearly salary for an employee; the calculator loads it
  with `charges` (employer contributions, 0.45 by default) over `days`
  worked a year (218 by default, the legal ceiling of a forfait-jours).

Do not mix the two: selling rates already include a margin, salaries do not.
Every profile has a `basis` (barometer, job offer, collective agreement).

`allocation` says who does what: `"default"` for most work, then a WBS id
(a lot applies to every package under it) or an overhead label, mapped to a
profile or to shares adding up to 1 (`{"dev": 0.7, "ux": 0.3}`).

## Costs outside the team

`costs`, one-off build costs with a `category`: `licences` (design tools,
IDE, paid libraries), `infra` (recette and pre-production environments
during the build), `outils` (CI minutes, monitoring, project tools),
`sous-traitance` (illustrations, copywriting, translations), `materiel`
(test devices), `formation`, `juridique` (CGU, privacy policy, GDPR
register, trademark), `securite` (penetration test before go-live), `autre`.
Each with a `basis`. Running costs after delivery go in the TCO, not here.

## Contingency, reserve, margin — visible, never hidden

Do not pad the estimates one by one: a padded estimate cannot be defended
and the padding disappears in negotiation. Put the money for uncertainty in
plain sight:

- `contingency` — for the **known** risks, managed by the project manager
  (PMI's contingency reserve). `{"method": "percentile"}` (default): the
  days between P50 and the committed percentile, at the average rate — the
  price of committing at P80. Or `{"method": "risks", "risks": [{"id",
  "label", "probability": 0.3, "cost": 6000}]}`: Σ probability × cost of the
  identified risks (link to `scrum/risques.json`). Or `{"method": "rate",
  "rate": 0.15}`.
- `management_reserve` — for the **unknown** unknowns, held by the sponsor,
  not in the team's baseline: 0 to 10 % (0.05 = 5 %).
- `margin` — only when rates are costs (salaries) and you sell: 10–20 % on
  cost. Zero when the TJM are already selling rates, zero internally.
- `vat`: 0.2 by default (0 for `interne`).

## Payment schedule

At a fixed price, `schedule` splits the price by milestone, shares adding
up to 1: e.g. order 30 %, end of build / recette 40 %, VSR (vérification de
service régulier) 30 %. Cash arrives late; a schedule that pays nothing
before the end is a cash-flow risk for the supplier.

```json
{
  "pricing": "forfait",
  "currency": "EUR",
  "profiles": [
    {"id": "dev", "title": "Développeur full stack confirmé", "tjm": 515, "basis": "Hays 2026, 3–5 ans"},
    {"id": "cp", "title": "Chef de projet / Scrum Master", "tjm": 600, "basis": "..."},
    {"id": "ux", "title": "UX/UI designer", "tjm": 480, "basis": "..."}
  ],
  "allocation": {"default": "dev", "1": "cp", "Gestion de projet": "cp", "2.1": {"dev": 0.7, "ux": 0.3}},
  "costs": [
    {"label": "Environnement de recette", "category": "infra", "amount": 360, "basis": "30 €/mois × 12"},
    {"label": "Test d'intrusion avant MEP", "category": "securite", "amount": 3500, "basis": "devis"}
  ],
  "contingency": {"method": "percentile"},
  "management_reserve": 0.05,
  "margin": 0,
  "schedule": [{"label": "Commande", "share": 0.3}, {"label": "Recette", "share": 0.4},
               {"label": "VSR", "share": 0.3}]
}
```

## Finish

```bash
python3 .claude/chiffrage-kit/chiffrage.py .
```

Fix every ERROR. Read the budget table in `livrables/chiffrage.md`: the
price without contingency (P50) and with it (P80) are the two ends of the
range you will present. Note in `chiffrage/decisions.md` where each rate
comes from.
