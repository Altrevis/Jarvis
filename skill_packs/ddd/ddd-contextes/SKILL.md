---
name: ddd-contextes
description: >-
  Second step of Domain-Driven Design: draws the bounded contexts of the
  project — where each model and its language hold — gives every backlog
  story and every requirement of the cahier des charges to the context that
  owns it, puts the external systems on the map, and writes the context map
  with the relationship of every pair (customer-supplier, conformist,
  anticorruption layer, open host service, published language, shared
  kernel, separate ways). The contexts become the modules or services of the
  code. Use when the user says "bounded context", "contexte délimité",
  "contextes bornés", "context map", "carte des contextes", "anticorruption
  layer", "couche anticorruption", "shared kernel", "noyau partagé", "open
  host service", "conformiste", "découpage en services", "frontières des
  microservices", "modules du code".
---

# ddd-contextes

One deliverable: `ddd/contextes.json`. Second step, after `ddd-domaine`
(read `ddd/domaine.json` first). Write the data only; `ddd.py` checks it.

Read `CLAUDE.md`, `ddd/domaine.json`, and when they exist
`scrum/cahier-des-charges.json` (modules, requirements,
`technical.interfaces`, `technical.imposed`) and
`scrum/product-backlog.json`. If `ddd/contextes.json` exists, **update
it**: keep the ids.

## Finding the contexts

A bounded context is the boundary inside which one model and its language
are consistent (Evans, ch. 14). Signs that a boundary is needed:

- the **same word means two things** — "Client" is a payer for the
  billing and a player for the booking: two contexts, and the word goes in
  `homonyms` with its meaning in each;
- a part of the domain changes for other reasons, at another pace, or is
  owned by other people;
- a subdomain of another type: keep generic subdomains out of the core's
  context (Segregated Core).

Do not split for the sake of it: every boundary costs a translation. **2 to
5 internal contexts** for a student project; a single context is honest
for a small app. Contexts follow the business, never the technical layers
("Front", "API" and "Base de données" are not contexts).

Give each internal context `subdomains` (from domaine.json),
`responsibility` (what it decides, what it leaves to others), `terms` (the
glossary terms it speaks), `code` (the folder or package name:
`reservation`) and what it **owns**:

- `stories`: every backlog item that is not `wont` goes to **exactly one**
  context — the one whose language it speaks. A story that really needs two
  is two stories: say so in `ddd/decisions.md`.
- `requirements` (EF-xx) and `modules` (M1…) of the cahier des charges.

Every system of `technical.interfaces` (payment provider, ERP, identity
provider, public API) is an **external** context: `"kind": "external"`,
its `system` name, what it gives (`responsibility`), and the generic
subdomain it carries when it is the one bought (`"subdomains": ["SD2"]`).
It owns no story.

## The context map

One relation per pair that talks, `upstream` (whose model the other
depends on) → `downstream`, with its `patterns` and `why`:

| pattern | when |
|---|---|
| `customer-supplier` | two teams; the downstream's needs are planned by the upstream |
| `conformist` | the downstream takes the upstream model as it is — fine when it is good enough and the downstream is not the core |
| `anticorruption-layer` | the downstream translates at the border so a foreign model does not leak into its own: **the default for an external system talking to the core**. Write `translation` (their concept → ours) |
| `open-host-service` | the upstream offers one documented API for all its consumers |
| `published-language` | the exchange format is shared and documented (JSON schema, iCal, standard) |
| `shared-kernel` | a small part of the model both own and change together; list it in `shared`, keep it tiny |
| `separate-ways` | no integration: cheaper to duplicate than to connect. Alone |
| `partnership` | two contexts that succeed or fail together (DDD Reference, 2015) |

Upstream-side patterns (`open-host-service`, `published-language`) combine
with downstream-side ones (`conformist` or `anticorruption-layer`, not
both).

```json
{
  "contexts": [
    {"id": "BC1", "name": "Réservation", "code": "reservation", "subdomains": ["SD1"],
     "responsibility": "Décide qui tient quel créneau ; gère annulations et liste d'attente.",
     "terms": ["Réservation", "Créneau", "Liste d'attente"],
     "stories": ["US-01", "US-02", "US-04"], "requirements": ["EF-01", "EF-02"], "modules": ["M1"]},
    {"id": "BC2", "name": "Club", "code": "club", "subdomains": ["SD3"],
     "responsibility": "Terrains, horaires d'ouverture et tarifs, saisis par le club.",
     "stories": ["US-07"], "requirements": ["EF-05"]},
    {"id": "BC3", "name": "Stripe", "kind": "external", "system": "Stripe", "subdomains": ["SD2"],
     "responsibility": "Encaisse et rembourse."}
  ],
  "relations": [
    {"upstream": "BC2", "downstream": "BC1", "patterns": ["customer-supplier"],
     "why": "Les créneaux naissent des horaires du club"},
    {"upstream": "BC3", "downstream": "BC1", "patterns": ["open-host-service", "anticorruption-layer"],
     "translation": "Checkout Session → Paiement ; charge.refunded → Remboursement",
     "why": "Le modèle de Stripe ne doit pas entrer dans le cœur"}
  ],
  "homonyms": [
    {"term": "Client", "meanings": {"BC1": "le membre qui réserve", "BC3": "le payeur Stripe (customer)"}}
  ]
}
```

Ids: `BC1`, `BC2`…; external systems are contexts too.

## Finish

```bash
python3 .claude/ddd-kit/ddd.py . --check
```

Fix every ERROR; act on the warnings about stories in no context and
external systems without a relation. Note your choices in
`ddd/decisions.md`.
