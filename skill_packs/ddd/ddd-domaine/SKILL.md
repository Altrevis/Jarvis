---
name: ddd-domaine
description: >-
  First step of Domain-Driven Design on a project that has its Scrum file:
  crunches the cahier des charges and the backlog into the ubiquitous
  language (one word per concept, with its name in the code and the words to
  avoid), splits the domain into subdomains — the core that makes the
  product worth building, the supporting ones, the generic ones to buy or
  take open source — says honestly how each is built (model-driven only
  where it pays, Smart UI for plain CRUD), and writes the domain vision
  statement. Use when the user says "DDD", "domain-driven design",
  "conception pilotée par le domaine", "langage omniprésent", "langage
  ubiquitaire", "ubiquitous language", "glossaire métier", "vocabulaire
  métier", "sous-domaines", "core domain", "domaine cœur", "cœur de
  métier", "vision du domaine", "knowledge crunching".
---

# ddd-domaine

One deliverable: `ddd/domaine.json`. The first of three steps (then
`ddd-contextes`, `ddd-modele`); it is the bridge between the project file
and the code: everything the developers name comes from here. Write the
data only; `ddd.py` checks it and writes `livrables/ddd.md`.

Read `CLAUDE.md` and, when they exist, `scrum/cahier-des-charges.json`
(glossary, requirements and their RG rules, users, `technical.data`,
out of scope), `scrum/product-backlog.json` (epics, stories, acceptance
criteria) and `scrum/discovery.json` (personas). If `ddd/domaine.json`
exists, **update it**: keep the ids and the terms already chosen.

## Knowledge crunching

Evans: the model is distilled from what the domain experts say, not from
the database. Go through the requirements, rules and stories and sort
their words:

- **nouns** that the business tracks over time → candidate entities
  (Réservation, Client); nouns that only describe → value objects
  (Montant, Créneau horaire, Adresse);
- **verbs** → the operations (réserver, annuler, rembourser);
- **rules** (RG-xx, "ne peut pas", "au plus", "seulement si") → the
  invariants and specifications of `ddd-modele`;
- **states** (en attente, confirmée, annulée) and **events** ("quand le
  paiement est reçu") → lifecycles and domain events.

What the sources leave open goes into `questions`: the questions you would
ask a domain expert ("Une réservation annulée libère-t-elle le créneau
tout de suite ?"). Never invent the answer: make a reasonable choice, note
it in `ddd/decisions.md`, and keep the question.

## The ubiquitous language

One word per concept, the same in the stories, the meetings, the code and
the tests — "a change in the language is a change in the model".

- `term`: the word the business uses, in the project's language
  (« Réservation », not « Booking » nor « Order »).
- `definition`: in domain terms, one or two sentences — what it *is* and
  the rule that makes it what it is, never "a table that…".
- `code`: the identifier it gets in the code (`Reservation`,
  `CreneauHoraire`): PascalCase, no accents, the same everywhere.
- `avoid`: the synonyms people will be tempted to use, so nobody does
  (`["booking", "commande"]`). A word is either a term or avoided, never
  both.

10 to 30 terms for a student project. Take every term of the cahier des
charges glossary, or list it in an `avoid` when the team chose another
word. Technical words (API, base de données) are not domain terms.

## Subdomains and distillation

- **core**: the part that makes the product worth building rather than
  buying — usually one, at most two. It gets the best people and the
  model-driven design.
- **supporting**: specific to this business but not what it wins on
  (back-office, reporting).
- **generic**: every product needs it, nobody wins with it —
  authentication, payment, email, notifications, invoicing, search.

`approach` for each, honestly — over-engineering is a real cost:

| approach | when |
|---|---|
| `model-driven` | rich rules that change: the core, a complex supporting part |
| `transaction-script` | a few procedures over the data, little logic |
| `smart-ui` | plain CRUD: forms on tables. Evans (ch. 4) calls it a valid choice for simple work — just not for the core |
| `buy` | a SaaS or a paid component (Stripe, Auth0, Brevo) |
| `open-source` | a maintained library or product (Keycloak, Meilisearch) |

Then `vision` (the **domain vision statement**: one paragraph on what the
core is and why it is worth it, not how it works) and `highlighted_core`
(3 to 7 lines naming the core elements everyone on the team must know).

```json
{
  "project": "App de réservation",
  "vision": "Les clubs perdent 20 % de leurs créneaux en annulations tardives. Le cœur du produit est la gestion des créneaux et des réservations, avec une liste d'attente qui réattribue un créneau libéré en quelques minutes ; c'est ce qu'aucun outil générique ne fait.",
  "highlighted_core": ["Une Réservation tient un Créneau pour un Membre", "Annuler libère le Créneau au premier de la Liste d'attente"],
  "subdomains": [
    {"id": "SD1", "name": "Réservation de créneaux", "type": "core", "approach": "model-driven",
     "why": "Règles d'annulation et de liste d'attente : là où le produit se distingue"},
    {"id": "SD2", "name": "Paiement", "type": "generic", "approach": "buy",
     "why": "Stripe Checkout : rien à gagner à le refaire"},
    {"id": "SD3", "name": "Back-office du club", "type": "supporting", "approach": "smart-ui",
     "why": "Formulaires sur les terrains et les horaires, pas de règle"}
  ],
  "glossary": [
    {"term": "Réservation", "definition": "L'engagement d'un Membre sur un Créneau, confirmée une fois payée.",
     "code": "Reservation", "avoid": ["booking", "commande"]},
    {"term": "Créneau", "definition": "Un terrain sur une plage horaire ; au plus une Réservation confirmée.",
     "code": "Creneau", "avoid": ["slot"]}
  ],
  "questions": ["Une annulation à moins de 24 h est-elle remboursée ?"]
}
```

Ids: `SD1`, `SD2`… Everything you write for the user is in the project's
language.

## Finish

```bash
python3 .claude/ddd-kit/ddd.py . --check
```

Fix every ERROR; act on the warnings about the core and the missing
terms. Note your choices in `ddd/decisions.md`.
