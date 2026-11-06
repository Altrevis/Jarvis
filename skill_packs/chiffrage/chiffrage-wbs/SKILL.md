---
name: chiffrage-wbs
description: >-
  Breaks a software project down into estimable work packages before anyone
  estimates: a deliverable-oriented WBS that follows the 100 % rule, work
  packages of 1 to 10 days with a checkable deliverable, the indirect work
  (recette, CI/CD, mise en production, documentation), the real dependencies
  for the critical path, the phase on the cone of uncertainty, and the
  assumptions and exclusions the price rests on. Maps every backlog story to
  one work package. Use when the user says "WBS", "work breakdown structure",
  "découpage", "décomposer le projet", "lots de travaux", "organigramme des
  tâches", "OTP", "SDP", "structure de découpage", "périmètre à chiffrer",
  "hypothèses de chiffrage", "fil rouge".
---

# chiffrage-wbs

One deliverable: `chiffrage/wbs.json`. The first step of a chiffrage —
« on ne peut estimer que ce qui est découpé en unités assez petites et
claires ». Write the data only; `chiffrage.py` computes and draws.

Read `CLAUDE.md` and, when they exist, the project sheet (fiche projet) and
`scrum/cahier-des-charges.json` (scope, out of scope, constraints),
`scrum/product-backlog.json` (epics and stories), `scrum/risques.json`.
If `chiffrage/wbs.json` exists, **update it**: keep the ids, never renumber.

## What a WBS is

A tree of **what will be delivered**, not a to-do list and not a schedule
(PMBOK). Three rules:

- **100 % rule**: the children of a node add up to all of it, nothing more.
  The whole scope is in the tree; what is not in it is in `exclusions`.
- **Mutually exclusive**: one piece of work lives in one package only —
  otherwise it is counted twice.
- **Deliverable-oriented**: name packages by their result ("Paiement Stripe
  en recette"), not by an activity ("Coder"), and never by a technical layer
  at level 1 ("Backend", "Base de données"): a layer cannot be accepted by a
  client.

Levels:

- **Level 1**: the epics of the backlog (or the big functions of the
  specification) plus the transverse lots every project has:
  *Pilotage & cadrage*, *Qualité & recette*, *Industrialisation* (CI/CD,
  environments), *Mise en production & transfert* (MEP, documentation,
  training). Five to nine lots.
- **Level 2** (sometimes 3): the **work packages** — the leaves, the only
  nodes that get estimated. Three levels at most.

**Size of a work package: 1 to 10 days** (the 8/80-hour rule). Above
10 days it is still an epic: split it by workflow step, business rule, data
variation or happy path vs edge cases. Below half a day it is a task:
merge it. 12 to 40 packages for a student project.

## Direct and indirect work

`kind` is `dev` (default) for packages that build a function, `indirect`
for packages with their own deliverable that are not function building:
cadrage & specs, maquettes, CI/CD set-up, recette (PV de recette), mise en
production, documentation, training, data migration. **The pure dev is only
50–60 % of a project** — forgetting the indirect work is underestimating by
half.

Do **not** put proportional activities here (project management,
ceremonies, code reviews): they have no deliverable of their own and are
added as rates in `chiffrage-estimation`.

## Backlog link

When `scrum/product-backlog.json` exists, every item that is not `wont`
goes into **exactly one** work package (`stories`). A package may hold
several stories (the payment and the refund stories in "Paiement"); a story
too big for one package is split in the backlog first. `wont` items belong
in `exclusions`. The checker lists stories in no package.

## Dependencies

`depends_on` (finish-to-start) feeds the critical path. Only **real**
dependencies — the API before the screen that calls it, the specs before the
build, everything before the recette. A node's dependency applies to every
package under it (`"depends_on": ["3"]` = after all of lot 3). Do not chain
everything in a line: it serialises the plan and lengthens the delay for no
reason.

## Phase, assumptions, exclusions

- `phase`: where the project is on the cone of uncertainty — `concept`
  (an idea; ×0.25 to ×4), `besoins` (needs defined and validated; ×0.5 to
  ×2), `specs` (specification complete; ×0.67 to ×1.5), `conception`
  (design done; ×0.8 to ×1.25), `code`. Be honest: a student project with a
  backlog but no validated specification is at `besoins`.
- `assumptions`: 5 to 12 statements the estimate is true under, each
  checkable and with its impact if false ("Paiement par Stripe Checkout, sans
  marketplace — un paiement fractionné ajouterait ~5 jh"). Team, techno,
  third-party APIs, data volumes, who provides contents and mock-ups, how
  many review rounds, the browsers / devices supported.
- `exclusions`: what the price does not include (hosting after delivery,
  app store fees, content writing, translations, a native mobile app…).

« Une estimation sans fourchette ni hypothèses est une promesse déguisée. »

```json
{
  "project": "App de réservation",
  "phase": "besoins",
  "start": "2026-11-23",
  "hours_per_day": 7,
  "nodes": [
    {"id": "1", "title": "Pilotage & cadrage"},
    {"id": "1.1", "title": "Spécifications", "kind": "indirect",
     "deliverable": "Spécifications fonctionnelles validées par le client"},
    {"id": "3", "title": "Réservation", "depends_on": ["1"]},
    {"id": "3.1", "title": "Recherche de créneaux", "deliverable": "Recherche filtrée et paginée en recette",
     "stories": ["US-03", "US-04"]},
    {"id": "3.2", "title": "Paiement", "deliverable": "Paiement Stripe et remboursement en recette",
     "stories": ["US-05", "US-08"], "depends_on": ["3.1"]},
    {"id": "6", "title": "Qualité & recette", "depends_on": ["3"]},
    {"id": "6.1", "title": "Recette", "kind": "indirect", "deliverable": "PV de recette signé"}
  ],
  "assumptions": ["Paiement par Stripe Checkout, sans marketplace", "..."],
  "exclusions": ["Hébergement après la VSR", "..."]
}
```

Ids: `1`, `1.1`, `1.1.1`; a parent must exist for each child.
`hours_per_day` (7 by default) converts hours into days for the
parametric methods; `start` (optional) dates the delivery.

## Finish

```bash
python3 .claude/chiffrage-kit/chiffrage.py . --check
```

Fix every ERROR; act on the warnings about the 100 % rule and missing
deliverables. Note your choices in `chiffrage/decisions.md`.
