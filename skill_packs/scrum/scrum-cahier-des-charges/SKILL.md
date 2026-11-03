---
name: scrum-cahier-des-charges
description: >-
  Writes the cahier des charges (functional specification) of an IT project,
  following NF EN 16271 (which replaced NF X50-151): context, measurable
  objectives, scope and exclusions, users, life-cycle situations, functional
  requirements linked to the service functions of the pieuvre, non-functional
  requirements with criterion / level / flexibility, technical environment,
  interfaces, data, organisation, budget, deliverables, acceptance, support
  and reversibility, glossary. Use when the user says "cahier des charges",
  "CDC", "cahier des charges fonctionnel", "CdCF", "spécifications",
  "exigences", "specification", "requirements document".
---

# scrum-cahier-des-charges

One file: `scrum/cahier-des-charges.json`. The assistant assembles it with the
other deliverables into one numbered document (HTML, PDF, Word): the need
statement comes from `bete-a-cornes.json`, the interaction diagram and the
service functions from `pieuvre.json`, the stakeholders from
`parties-prenantes.json`, the RACI from `raci.json`, the personas from
`discovery.json`, the risks from `risques.json`, the Gantt and ceremonies
from `planning.json`. **Never copy their content here**: write only what no
other file says. Never write HTML or Word.

## Read first

`CLAUDE.md`, everything in `sources/` (a brief, a call for tenders, notes:
that is the client's voice — reuse its facts, figures and words), then the
`scrum/` files that exist. `pieuvre.json` matters most: its function ids
(FP1, FC2…) are what your requirements point to. If the file already exists,
update it: keep every id, bump `document.version` and add a line to
`document.history`.

## What a cahier des charges is

A contract-grade statement of **the need, not the solution** (NF EN 16271,
expression fonctionnelle du besoin). The client says what the product must do,
for whom, how well, under which constraints, and how it will be accepted; the
supplier chooses how. A reader who was not in the room must be able to build
the product and to check it was built right. So:

- **One requirement, one verifiable thing.** "Le système permet à
  l'enseignant d'exporter les notes d'une classe au format CSV." — not "gestion
  des notes".
- **Active voice, a precise verb, an actor, an object**: "Le système permet à
  <acteur> de <verbe à l'infinitif> <objet> [<condition>]". Avoid vague verbs
  (gérer, traiter, faire) when a precise one exists (créer, modifier,
  supprimer, consulter, exporter, notifier, valider).
- **No vague adjectives** — rapide, simple, intuitif, convivial, performant,
  moderne, robuste, "etc." — the checker flags them. Replace each with a
  number and a unit in a non-functional requirement: "≤ 2 s pour 95 % des
  requêtes", "≤ 3 clics depuis l'accueil", "99,5 % par mois".
- **No solution unless it is imposed.** "Stocker les fichiers sur AWS S3" is
  a solution; "Conserver les fichiers 5 ans dans l'Union européenne" is a
  need. A technology the client really imposes goes in
  `technical.imposed`, with the reason.
- **Write the exclusions.** What is not written out of scope may later be
  claimed as included.
- **Do not invent facts.** A budget, a date or a volume you do not know is an
  assumption: put your estimate, say "à confirmer" in the note, and record it
  in `scrum/decisions.md`; questions only the client can answer go in
  `open_questions`.

## Sections and how to fill them

**document** — `title` (default "Cahier des charges fonctionnel"),
`version` ("1.0"), `status` (`brouillon`, `en revue`, `validé`), `date`,
`client` (maître d'ouvrage: who expresses the need and pays), `provider`
(maître d'œuvre: who builds — the team or "à désigner"), `authors`,
`confidentiality`, `history` [{version, date, author, changes}], `approvals`
[{name, role, date, decision}] — leave `date` and `decision` empty: the client
signs.

**context** — `organisation` (who the client is, in 2-3 sentences),
`background` (why this project, why now), `current` (how it is done today:
tools, process, volumes), `problems` (what goes wrong today, measured when the
sources say so), `stakes` (what is at stake: money, time, image, law).

**objectives** — 2 to 5, SMART: `id` OBJ1…, `text`, `indicator` (what is
measured), `target` (the value), `deadline`. An objective is a result
("Réduire de 50 % le temps de saisie"), not a feature ("Avoir une appli").

**scope** — `in`, `out` (always some), `assumptions`, `dependencies`
(what the project relies on but does not control).

**users** — every kind of user: `role`, `description`, `count`
("≈ 300"), `frequency` ("quotidienne"), `skills` ("non technique"). The
`actor` of every requirement must be one of these roles, a persona or a
stakeholder.

**life_cycle** — the situations of life studied (NF EN 16271: the need is
expressed for every phase, not only normal use). For software, usually:
installation / déploiement, utilisation normale, mode dégradé (réseau coupé,
service tiers indisponible), administration, maintenance / mise à jour, fin
de vie / réversibilité. `phase`, `description` — what the product meets in
that phase.

**extra_criteria** — the pieuvre gives each function one criterion; add the
others here so every service function is fully characterised:
`function` (FP1…), `criteria`, `level`, `flexibility`.

Flexibility, for every level: **F0** impératif (flexibilité nulle) · **F1**
peu négociable · **F2** négociable · **F3** très négociable. Legal and safety
constraints are F0.

**modules** — 3 to 8 functional areas (`id` M1…, `name`, `description`),
following the user's world: "Inscription", "Gestion des cours",
"Administration" — not technical layers.

**requirements** — the functional requirements, 15 to 40 depending on size:

- `id` EF-01…, `module`, `title` (short, a verb), `description` (the
  sentence above).
- `actor`, `priority`: `must` (without it the product is useless — keep it
  around 60 % of the effort), `should`, `could`, `wont` (agreed out of this
  version: keep them, they prevent arguments later).
- `functions`: the ids of the pieuvre functions it serves. **Every FP and FC
  must be served by at least one requirement** (functional or not) — the
  checker lists the orphans.
- `rules`: business rules ("RG : un étudiant ne peut s'inscrire qu'à 3 options").
- `acceptance`: how it will be accepted, required for every `must` —
  "Étant donné …, quand …, alors …", with numbers. Cover the error case too.

**journeys** — 2 to 4 key user journeys: `name`, `actor`, `steps` (one
action per step, in order). They show the requirements work together.

**non_functional** — 8 to 15, each `id` ENF-01…, `category`, `title`,
`description`, `criteria` (what is measured), `level` (the threshold, with a
unit), `flexibility`, `verification` (`test`, `inspection`, `analysis`,
`demonstration`), and `functions` when it characterises an FC. Categories
(ISO/IEC 25010): `performance`, `security`, `availability`, `usability`
(include accessibility: RGAA 4.1 / WCAG 2.1 AA for anything web or public),
`compatibility` (browsers, OS, devices), `maintainability`, `portability`
(including reversibility: getting the data back, in an open format, at the
end of the contract), `compliance` (RGPD as soon as personal data is
processed: legal basis, retention, rights of access and erasure), `operability`
(logs, monitoring, backups), `other`.

**technical** — `environment` (what exists and must be supported),
`imposed` (choices the client imposes, each with its reason), `hosting`,
`interfaces` [{system, direction (`entrant`, `sortant`, `bidirectionnel`),
data, protocol, frequency}], `data` [{entity, description, volume,
sensitivity (publique, interne, personnelle, sensible), retention}],
`migration` (data to take over from the current tools).

**constraints** — [{type, text}]: `réglementaire`, `budgétaire`,
`calendaire`, `technique`, `organisationnelle`.

**organisation** — `method` (Scrum: sprint length, who is Product Owner,
how the client takes part), `roles` [{role, name, responsibilities}],
`committees` [{name, frequency, participants, purpose}] (comité de pilotage,
sprint review with the client…). The RACI and the ceremonies come from their
own files.

**milestones** — [{label, date YYYY-MM-DD}]: the commitments (kick-off,
validation of the CdC, MVP, recette, mise en production). If
`planning.json` exists, use the same dates.

**budget** — `currency` ("EUR"), `envelope`, `items` [{label, amount
(a number), note}] — development, licences, hosting per year, maintenance —
and `notes`. Unknown: estimate, say so in the note.

**deliverables** — [{name, description, format, due}]: the software, the
source code and its repository, the technical documentation, the user guide,
the test report, the training…

**acceptance** — `process` (in order: recette par sprint, VABF — vérification
d'aptitude au bon fonctionnement, VSR — vérification de service régulier),
`criteria` ("100 % des exigences must vérifiées", "aucune anomalie bloquante
ou majeure ouverte"), `severity` [{level, definition, threshold}]
(bloquante, majeure, mineure), `warranty` (duration and what it covers).

**support** — `maintenance` (corrective, évolutive, who and how long),
`sla` [{level, response, resolution}], `training`, `documentation` (list),
`reversibility`.

**response** — only when suppliers will answer (the brief mentions an appel
d'offres, a prestataire, an agence): `variants` (allowed or not, on which
points), `expected` (contents of the offer: compréhension du besoin, réponse
exigence par exigence — conforme / partiel / non conforme —, planning,
équipe, prix détaillé), `criteria` [{criterion, weight}] adding up to 100,
`calendar` [{label, date}], `contact`. Leave it out for an internal or school
project.

**glossary** — every acronym and business term the document uses (MOA, MOE,
RGPD, VABF, the client's own words). **references** — the documents used:
`sources/` files, standards (NF EN 16271, RGAA 4.1…). **open_questions** —
what only the client can answer.

## Shape

```json
{
  "document": {"version": "1.0", "status": "brouillon", "date": "2026-11-03",
    "client": "Ynov Campus — direction pédagogique", "provider": "Équipe projet Ydays",
    "authors": ["Léo"], "confidentiality": "Interne",
    "history": [{"version": "1.0", "date": "2026-11-03", "author": "Léo", "changes": "Création"}],
    "approvals": [{"name": "Mme Martin", "role": "Responsable pédagogique", "date": "", "decision": ""}]},
  "context": {"organisation": "…", "background": "…", "current": "…",
    "problems": ["Les plannings sont envoyés par mail en PDF : 4 versions par semaine"],
    "stakes": ["…"]},
  "objectives": [{"id": "OBJ1", "text": "Réduire le temps de construction d'un planning",
    "indicator": "Temps moyen par planning hebdomadaire", "target": "≤ 30 min (contre 3 h)", "deadline": "2027-02-01"}],
  "scope": {"in": ["…"], "out": ["La paie des intervenants"], "assumptions": ["…"], "dependencies": ["…"]},
  "users": [{"role": "Responsable pédagogique", "description": "…", "count": "12", "frequency": "quotidienne", "skills": "Bureautique"}],
  "life_cycle": [{"phase": "Utilisation normale", "description": "…"},
    {"phase": "Mode dégradé", "description": "Connexion perdue pendant une saisie"}],
  "extra_criteria": [{"function": "FP1", "criteria": "Conflits de salle détectés", "level": "100 %", "flexibility": "F0"}],
  "modules": [{"id": "M1", "name": "Construction du planning", "description": "…"}],
  "requirements": [
    {"id": "EF-01", "module": "M1", "title": "Placer un cours", "actor": "Responsable pédagogique",
     "description": "Le système permet au responsable pédagogique de placer un cours sur un créneau, une salle et un intervenant.",
     "priority": "must", "functions": ["FP1"],
     "rules": ["RG-01 : une salle n'accueille qu'un cours par créneau"],
     "acceptance": ["Étant donné une salle libre, quand je place un cours, alors il apparaît dans le planning de la classe et de l'intervenant",
                    "Étant donné une salle occupée, quand je place un cours, alors le conflit est signalé et le cours n'est pas enregistré"]}
  ],
  "journeys": [{"name": "Publier le planning de la semaine", "actor": "Responsable pédagogique", "steps": ["…", "…"]}],
  "non_functional": [
    {"id": "ENF-01", "category": "performance", "title": "Affichage d'un planning",
     "description": "Temps entre la demande et l'affichage complet", "criteria": "Temps de réponse",
     "level": "≤ 2 s pour 95 % des requêtes, 200 utilisateurs simultanés", "flexibility": "F1",
     "verification": "test", "functions": ["FC2"]}
  ],
  "technical": {"environment": ["Navigateurs : Chrome, Firefox, Edge, Safari (2 dernières versions)"],
    "imposed": ["Authentification par le SSO de l'école (CAS) — tous les comptes y sont déjà"],
    "hosting": "…", "interfaces": [{"system": "SSO de l'école", "direction": "entrant", "data": "Identité, rôle", "protocol": "CAS 3.0", "frequency": "À chaque connexion"}],
    "data": [{"entity": "Intervenant", "description": "…", "volume": "≈ 250", "sensitivity": "personnelle", "retention": "Durée du contrat + 3 ans"}],
    "migration": "…"},
  "constraints": [{"type": "réglementaire", "text": "RGPD : données des intervenants hébergées dans l'UE"}],
  "organisation": {"method": "Scrum, sprints de 2 semaines…", "roles": [{"role": "Product Owner", "name": "…", "responsibilities": "…"}],
    "committees": [{"name": "Comité de pilotage", "frequency": "Mensuel", "participants": "…", "purpose": "…"}]},
  "milestones": [{"label": "Validation du cahier des charges", "date": "2026-11-20"}],
  "budget": {"currency": "EUR", "envelope": 30000,
    "items": [{"label": "Développement", "amount": 24000, "note": "40 jours × 600 €, à confirmer"}], "notes": "…"},
  "deliverables": [{"name": "Code source", "description": "…", "format": "Dépôt Git", "due": "2027-01-15"}],
  "acceptance": {"process": ["…"], "criteria": ["…"],
    "severity": [{"level": "Bloquante", "definition": "Empêche un parcours must", "threshold": "0"}], "warranty": "…"},
  "support": {"maintenance": "…", "sla": [{"level": "Bloquante", "response": "4 h ouvrées", "resolution": "2 jours ouvrés"}],
    "training": "…", "documentation": ["…"], "reversibility": "…"},
  "glossary": [{"term": "VABF", "definition": "Vérification d'aptitude au bon fonctionnement : …"}],
  "references": ["sources/brief.pdf", "NF EN 16271 (2013), expression fonctionnelle du besoin et cahier des charges fonctionnel"],
  "open_questions": ["…"]
}
```

Ids are stable across runs (EF-07 stays EF-07; a dropped requirement becomes
`wont`, it is not renumbered): the product backlog and the traceability
matrix point to them.

## Finish

```bash
python3 .claude/scrum-kit/render.py . --check
```

Fix every ERROR. Treat the warnings as a reviewer's remarks: fix vague words,
orphan functions and missing exclusions unless you have a reason, and write
that reason in `scrum/decisions.md`.
