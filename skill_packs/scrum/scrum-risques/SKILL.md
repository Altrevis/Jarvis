---
name: scrum-risques
description: >-
  Builds the risk register: each risk with its cause and consequence,
  probability and impact on a 1–5 scale, the resulting criticality, an owner,
  a prevention action and a contingency plan, drawn as a 5×5 heat map. Use
  when the user says "risques", "gestion des risques", "registre des
  risques", "matrice des risques", "plan de mitigation", "criticité", "que
  peut-il mal se passer".
---

# scrum-risques

One deliverable: `scrum/risques.json`.

Read `CLAUDE.md` and what exists in `scrum/`: SWOT weaknesses and threats,
resistant stakeholders with high power, the discovery hypotheses still in
`todo`, stories with big estimates, a sprint committed at full capacity — each
is a risk source. If the file exists, update it: keep ids, change statuses and
scores as things evolve.

## What a risk is

An **uncertain** event that would affect the project's goal. A certainty is
an issue, not a risk ("le budget est de 0 €" is a constraint). Write each one
as *cause → event → consequence*:

- `title`: the event, short ("Quota Claude atteint pendant la démo").
- `cause`: why it could happen.
- `consequence`: what it would do to the project — time, cost, quality,
  scope, grade.

Cover several categories: technical, human (availability, skills, conflict),
organisational, planning, external (suppliers, law, platform), quality,
security. 8 to 15 risks.

## Scoring

- `probability` 1–5: 1 très rare · 2 rare · 3 possible · 4 probable ·
  5 quasi certain.
- `impact` 1–5: 1 négligeable · 2 mineur · 3 modéré · 4 majeur · 5 critique.
- Criticality = probability × impact, computed by the renderer:
  1–4 faible, 5–9 moyen, 10–14 élevé, 15–25 critique.

Be honest: a register where everything is 2×2 is useless, and one where
everything is red is too.

## Responses

- `owner`: one person (from the RACI or stakeholders when they exist).
- `prevention`: what is done **now** to lower probability or impact —
  required from criticality 10 up.
- `contingency`: what is done **if it happens** (plan B).
- `status`: `ouvert`, `surveillé`, `maîtrisé`, `survenu`, `clos` (or the
  English equivalents if the project is in English).

```json
{
  "risks": [
    {"id": "R1", "title": "Quota Claude atteint pendant la démo", "category": "Technique",
     "cause": "Abonnement partagé par l'équipe", "consequence": "Livrable non généré devant le jury",
     "probability": 3, "impact": 5, "owner": "Léo",
     "prevention": "Générer les livrables la veille",
     "contingency": "Montrer le dossier PDF déjà exporté", "status": "ouvert"}
  ]
}
```

Ids R1, R2…, stable across runs.

## Finish

```bash
python3 .claude/scrum-kit/render.py . --check
```

Fix every ERROR. Note assumptions in `scrum/decisions.md`.
