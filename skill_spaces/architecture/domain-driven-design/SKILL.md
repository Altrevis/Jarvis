---
name: domain-driven-design
description: >-
  Applies Domain-Driven Design (Evans, 2003) to the folder you work in, new
  or existing code: the ubiquitous language, subdomains and the core
  domain, bounded contexts and the context map (customer-supplier,
  conformist, anticorruption layer, open host service, shared kernel,
  separate ways), the tactical model (aggregates and invariants, entities,
  value objects, services, repositories, factories, specifications, domain
  events), layered architecture, and for existing code a review that finds
  the anemic model, the implicit concepts, the leaking foreign models and
  the aggregate boundaries that do not hold, with a refactoring path. Writes
  domain-model.md. Se déclenche sur : DDD, conception pilotée par le
  domaine, langage omniprésent, contexte délimité, carte des contextes,
  agrégat, objet-valeur, couche anticorruption, modèle anémique, refonte
  du modèle métier.
---

# domain-driven-design
Produces `domain-model.md` in the folder you were given: the strategic
design (language, subdomains, contexts, map), the tactical model of the
parts that deserve one, and — on existing code — the findings and the
refactoring steps. For a greenfield project with a Scrum file, Jarvis has a
dedicated pipeline (the `ddd` pack, run by Direction Projet); this skill is
for any other codebase, Jarvis itself included.

## Before you start
| Input | Where | If missing |
|---|---|---|
| What the software is for | task, README, CLAUDE.md, specs, backlog | infer it from the code and the UI texts; record it |
| The business words | specs, UI labels, error messages, table names, tickets | list them from the code itself |
| Existing structure | folders, imports, schema, migrations, API routes | greenfield |
| Earlier decisions | `adr/`, `docs/`, `architecture.md` | none |

## Method
1. **Knowledge crunching**: collect the domain's nouns (candidate entities
   and value objects), verbs (operations), rules (invariants,
   specifications), states and events — from the documents first, the code
   second. What you cannot settle goes in *Questions for the domain experts*;
   never invent the answer.
2. **Ubiquitous language**: a table term · definition · name in the code ·
   words to avoid. One word per concept, the same in talk, code and tests.
   On existing code, list every place the code uses another word for the
   same concept (`Booking` here, `Reservation` there).
3. **Distillation**: split the domain into subdomains — **core** (why the
   software is worth building; small), **supporting**, **generic** (auth,
   payment, email: buy or open source). Write the domain vision statement
   (one paragraph). Decide the approach per subdomain honestly:
   model-driven only where rules are rich; Smart UI / transaction script is
   a valid choice for plain CRUD (Evans, ch. 4).
4. **Bounded contexts**: where one model and its language hold. Split on a
   word that means two things, a part that changes for other reasons or
   belongs to other people, a generic subdomain next to the core. Business
   boundaries, never technical layers. 1 to 5 for most projects.
5. **Context map**: every pair that talks, upstream → downstream, with its
   pattern (table below) and why. An external system talking to the core
   goes through an anticorruption layer unless its model is good enough to
   conform to.
6. **Tactical model** of each model-driven context (checklist below).
7. **Layers**: per context, `domain/` (model, repository interfaces) that
   depends on nothing, `application/` (one use case per command, one
   aggregate per transaction), `infrastructure/` (persistence, adapters,
   anticorruption layers), `interface/` (API, UI).
8. **Existing code only — review** (findings below), then a refactoring
   path in small safe steps: name things first, extract value objects,
   move rules into the model, draw the aggregate boundaries, put an
   anticorruption layer in front of the leaking system. Each step keeps the
   tests green.
9. **Write** `domain-model.md`.

## Context map patterns
| Pattern | When |
|---|---|
| Customer / supplier | two teams; the upstream plans for the downstream's needs |
| Conformist | the downstream takes the upstream model as it is; fine outside the core |
| Anticorruption layer | translate at the border so a foreign model does not leak in |
| Open host service + published language | the upstream offers one documented API / format for all consumers |
| Shared kernel | a tiny part of the model owned and changed together |
| Separate ways | no integration: duplicating is cheaper than connecting |

## Tactical checklist
- **Entity**: identity that lasts through change; say what the identity is.
- **Value object**: no identity, immutable, compared by value, holds its
  validation. Prefer them: most "small entities" are value objects.
- **Aggregate**: one root; the invariants it protects (no invariant, no
  aggregate); outside objects reference the root only, by identity; small;
  one transaction changes one aggregate, the others follow by a domain
  event.
- **Repository**: for aggregate roots only; interface in the domain,
  implementation in infrastructure.
- **Factory**: only when creation is complex or must check invariants.
- **Service**: a stateless operation that belongs to no entity, named in
  the language; domain, application or infrastructure.
- **Specification**: a named predicate for validation, selection or
  building to order.
- **Domain event** (Evans, DDD Reference 2015): something the business cares
  about that happened, named in the past.
- **Modules**: named in the language, by concept — never `entities/`,
  `services/`.
- **Supple design**: intention-revealing names (`annuler()`, not
  `setStatus(3)`), side-effect-free functions on value objects, assertions
  for invariants.

## Review findings (existing code)
| Smell | Sign in the code | Fix |
|---|---|---|
| Anemic model | entities with getters/setters only, rules in services or controllers | move each rule to the object whose data it reads |
| Smart UI where it hurts | business rules in handlers, views or SQL | extract a domain layer for that context only |
| Implicit concept | the same condition or calculation repeated; a boolean pair that is really a state | name it: value object, specification, state |
| Leaking foreign model | a provider's types (Stripe, an ERP) used across the code | anticorruption layer |
| Aggregate that does not hold | invariants checked in several places; deep object graphs saved together | redraw the boundary around the invariant |
| Language drift | two names for one concept, one name for two | glossary + rename |
| Big ball of mud | no boundaries, everything imports everything | map what exists first (as-is context map), then carve one context at a time |

## Output template
```markdown
# Domain model — <project>
## Vision statement
## Ubiquitous language
| Term | Definition | In the code | Avoid |
## Subdomains
| Subdomain | Core / supporting / generic | Approach | Why |
## Bounded contexts
| Context | Responsibility | Owns (features, data) | Code folder |
## Context map
<Mermaid flowchart, upstream → downstream, edge label = pattern>
| Upstream | Downstream | Pattern | Translation / shared | Why |
## Tactical model (per model-driven context)
### <Context>
- Aggregate <name> — root, entities, value objects, invariants, commands, references, events
- Services · specifications · domain events · modules
## Layers and folders
## Review findings (existing code)
| Smell | Where (file:line) | Impact | Fix |
## Refactoring path
## Questions for the domain experts
## Decisions
```

## Pitfalls
- Modelling every CRUD screen as aggregates: over-engineering is a cost.
- Contexts named after layers or technologies.
- One big aggregate behind a single root; repositories for inner entities.
- Domain code importing the web framework, the ORM or a provider SDK.
- A glossary written once and never used in the code.
- Inventing business rules instead of asking: an unanswered question is a
  finding, not a gap to fill.
