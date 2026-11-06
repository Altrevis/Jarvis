---
name: chiffrage-pitch
description: >-
  Prepares the oral defence of a chiffrage in front of a decision-maker or a
  jury: the decision asked for in the first thirty seconds, the scope and
  the assumptions, the method, the figure as a range (P50 / P80), the
  budget, the 3-year TCO, the risks and their provision, the options when
  the answer is "too expensive", the next re-estimation points, the slide
  plan with the speaker's script and timing, and the answers to the
  objections a decision-maker will raise. Use when the user says "pitch",
  "soutenance", "oral", "présenter le chiffrage", "défendre le budget",
  "jury", "comité", "décideur", "convaincre", "objections", "questions du
  jury", "slides du chiffrage".
---

# chiffrage-pitch

One deliverable: `chiffrage/pitch.md`. Every figure in it comes from
`chiffrage/synthese.json` or `livrables/chiffrage.md` — run
`python3 .claude/chiffrage-kit/chiffrage.py .` first and **copy, never
recompute**. A figure the jury can trace back is a figure it believes.

Read `CLAUDE.md`, `livrables/chiffrage.md`, `chiffrage/synthese.json`,
`chiffrage/wbs.json` (assumptions, exclusions), `chiffrage/decisions.md` and
`scrum/risques.json`.

## Who listens, what they want

A decision-maker (sponsor, steering committee, client, jury) has one
question: **should I commit this money, and what am I committing to?** They
do not want the method in detail; they want to trust it. So: the answer
first (pyramid principle), then what supports it. Ten minutes and questions:
about 1 000–1 300 spoken words, 8 to 12 slides.

## The structure (one `##` heading each)

1. **La décision demandée** (30 s) — the amount, the delay, what it buys and
   the date of the decision. "Nous demandons 48 k€ HT et 14 semaines pour
   livrer la réservation en ligne, décision attendue le 1er décembre."
2. **Périmètre et hypothèses** (1 min) — what is in, what is out
   (exclusions), the 3–4 assumptions the price stands on. A changed
   assumption changes the price: say it now, not after.
3. **Méthode** (1 min) — N work packages, three points each, the
   overheads, a second method and its gap. One sentence on why the two
   methods agree, or why they differ and which one you trust.
4. **Le chiffre en fourchette** (1 min 30) — P50 and P80, the phase on the
   cone. "50 % de chances à 44 k€, 80 % à 48 k€ : nous nous engageons sur 48."
   Never a single figure.
5. **Budget** (1 min) — four masses: team, costs outside the team,
   provision, margin. Who is in the team, at what rate, from what source.
6. **TCO** (1 min 30) — build vs run over 3 years, the comparison with the
   alternative, the ROI or payback when there are gains. "Le build n'est que
   55 % du coût sur trois ans."
7. **Risques** (1 min) — the 3 biggest, what is done against them, how the
   provision covers them. The package with the largest σ is one of them.
8. **Options** (1 min) — when the answer is "too expensive": the triangle
   scope / delay / cost. Two or three costed scenarios — a reduced MVP (the
   must-haves), the target, a phased delivery — each with what it gives up.
   **Negotiate the scope, never the estimate.**
9. **Prochaines étapes** (30 s) — the decision, then the points where the
   estimate is redone (end of specs, after sprint 2 with a measured
   velocity): the cone narrows, the figure gets firmer.
10. **Questions préparées** — not presented: the objections and answers
    below, ready.

Under each heading: the slide (title as a message, ≤ 3 figures, one
visual — the cone, the P50/P80 curve, the TCO stack) and the script, with
its timing.

## Objections to prepare

Write 6 to 10, with a short answer and the figure that backs it:

- « C'est trop cher. » → the options of section 8; what each scenario drops.
- « Faites-le pour 30 % de moins. » → show where that figure falls on the
  probability curve (often near or below the P10: 9 chances in 10 of
  overrunning). At that price, which features do we remove?
- « Pourquoi pas le chiffre à 50 % ? » → one project in two would overrun;
  the provision is the price of the guarantee, it is visible, not hidden.
- « Et avec des juniors ? » → rate down, days up, risk up: show the total.
- « Un SaaS ne suffirait pas ? » → the TCO comparison and what the SaaS does
  not do.
- « Garantissez-vous la date ? » → estimating is not committing: 80 % at
  this date, and the milestones where we re-estimate.
- « D'où sortent vos TJM ? » → the sources of `budget.json`.
- « Et si l'hypothèse X tombe ? » → its impact, written in the assumptions.

## Style

Ranges, not points. Round figures (48 k€, not 47 862 €), the same rounding
everywhere. Everything the jury hears is in `livrables/chiffrage.md`. No
jargon without a sentence of explanation (P80, σ, TCO, VSR). Speak of the
client's money as if it were yours.

## Finish

```bash
python3 .claude/chiffrage-kit/chiffrage.py . --check
```

It warns about a missing section. Read the pitch once against the report:
every figure must match it.
