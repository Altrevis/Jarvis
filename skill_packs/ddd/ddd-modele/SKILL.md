---
name: ddd-modele
description: >-
  Third step of Domain-Driven Design: the tactical model of each bounded
  context, the one the developers code — aggregates with their root, their
  entities and the invariants they protect (from the RG rules of the cahier
  des charges), value objects, domain services, repositories for roots
  only, factories, specifications (from the acceptance criteria) and domain
  events between contexts, grouped in modules named in the ubiquitous
  language. Use when the user says "agrégat", "aggregate", "racine
  d'agrégat", "entité", "objet-valeur", "value object", "repository",
  "dépôt", "factory", "fabrique", "service du domaine", "spécification",
  "domain events", "événements métier", "modèle du domaine", "modèle
  tactique", "diagramme de classes métier", "modèle métier".
---

# ddd-modele

One deliverable: `ddd/modele.json`. Last step, after `ddd-contextes`.
Write the data only; `ddd.py` checks it and writes `livrables/ddd.md`,
which the code is built from.

Read `CLAUDE.md`, `ddd/domaine.json`, `ddd/contextes.json`, and in
`scrum/cahier-des-charges.json` the requirements of each context with their
`rules` (RG-xx) and `technical.data`; in `scrum/product-backlog.json` the
acceptance criteria of each context's stories. If `ddd/modele.json`
exists, **update it**.

Model each internal context whose approach is `model-driven` in full. A
`smart-ui`, `transaction-script`, `buy` or `open-source` context gets one
`note` (what it stores, which screens) and no aggregate: modelling plain
CRUD is the over-engineering DDD warns against.

## The building blocks (Evans, ch. 5 and 6)

- **Entity**: has an identity that lasts through its changes (a Réservation
  stays the same one when its time changes). Say what the `identity` is.
- **Value object**: no identity, defined by its attributes, immutable,
  replaced as a whole (Montant, Créneau horaire, Adresse). **Prefer them**:
  most "small entities" are value objects. Put their validation `rules`
  in them.
- **Aggregate**: a cluster of entities and value objects that changes
  together, behind one **root** entity.
  - Its `invariants` are the rules that must hold at the end of every
    transaction — take them from the RG rules (`source`). No invariant,
    probably no aggregate.
  - Outside objects hold a reference to the **root only**, by identity
    (`references`: another aggregate of the context, or `BC2.Club` across
    a relation of the context map).
  - **Small aggregates**: one transaction changes one aggregate; the
    others follow by a domain event. A whole database behind one root is
    the classic mistake.
  - `commands`: its operations, named as the business says them
    (`annuler`, `confirmerPaiement`) — intention-revealing, not `setStatus`.
  - `repository` (true by default): **repositories are for aggregate roots
    only**, never for an inner entity or a value object.
  - `factory`: only when building it is complex or must check invariants
    (`"Reservation.depuisListeAttente(…)"`).
  - `stories`: the stories of this context it serves.
- **Service**: an operation that belongs to no entity, stateless, named in
  the language (`layer`: `domain` for business rules across aggregates,
  `application` for a use case that orchestrates, `infrastructure` for
  email, files, third parties).
- **Specification**: a business rule as a named predicate (Evans, ch. 9):
  `validation` (is this object valid?), `selection` (which ones match?),
  `building` (build what matches). Take them from the acceptance criteria
  and rules: `from` cites the story, requirement or rule.
- **Domain event** (DDD Reference, 2015): something that happened which
  the business cares about, named in the past (`ReservationAnnulee`):
  `raised_by` its aggregate, `consumed_by` the contexts that react (along a
  relation of the map), its `data`.
- **Module**: groups what belongs together, named in the language
  (`reservation.annulation`), never by pattern (`entities`, `services`).

**Every name is in the ubiquitous language.** Aggregates, entities and
value objects are glossary terms (or their `code`). When the model needs a
concept the glossary lacks, add it to `ddd/domaine.json` — the language
grows with the model — and never use a word of an `avoid` list.

```json
{
  "contexts": [
    {"context": "BC1",
     "value_objects": [
       {"name": "Créneau horaire", "attributes": ["début", "fin"], "rules": ["fin après début", "30 min minimum"]},
       {"name": "Montant", "attributes": ["valeur", "devise"], "rules": ["jamais négatif"]}
     ],
     "aggregates": [
       {"name": "Réservation", "root": "Réservation",
        "entities": [{"name": "Réservation", "identity": "numéro de réservation"}],
        "value_objects": ["Créneau horaire", "Montant"],
        "invariants": [{"rule": "Au plus une réservation confirmée par créneau", "source": "RG-01"},
                       {"rule": "Une réservation annulée ne se confirme plus", "source": "RG-04"}],
        "commands": ["confirmer", "annuler"], "references": ["Membre", "BC2.Terrain"],
        "stories": ["US-01", "US-02"]},
       {"name": "Membre", "root": "Membre",
        "entities": [{"name": "Membre", "identity": "e-mail vérifié"}],
        "invariants": [{"rule": "Au plus trois réservations à venir", "source": "RG-02"}]}
     ],
     "services": [{"name": "Réattribution", "layer": "domain",
                   "does": "Donne un créneau libéré au premier de la liste d'attente"}],
     "specifications": [{"name": "Annulable sans frais", "kind": "validation",
                         "rule": "Plus de 24 h avant le début du créneau", "from": ["US-04", "RG-05"]}],
     "events": [{"name": "Réservation annulée", "raised_by": "Réservation", "consumed_by": ["BC1"],
                 "data": ["réservation", "créneau"]}],
     "modules": [{"name": "reservation", "contains": ["Réservation", "Créneau horaire", "Montant"]},
                 {"name": "membres", "contains": ["Membre"]}]},
    {"context": "BC2", "note": "Smart UI : terrains, horaires et tarifs en CRUD dans le back-office."}
  ]
}
```

## Finish

```bash
python3 .claude/ddd-kit/ddd.py . --check
python3 .claude/ddd-kit/ddd.py .
```

Fix every ERROR — references to inner entities, repositories on non-roots
and words to avoid are errors. Act on the warnings about names missing
from the language. Read `livrables/ddd.md` once: the "Pour le code"
section is what the developers will follow. Note your choices in
`ddd/decisions.md`.
