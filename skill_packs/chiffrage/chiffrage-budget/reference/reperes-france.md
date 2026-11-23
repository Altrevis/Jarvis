# Repères français — what French public IT projects really cost

Measured figures from French sources, to back a chiffrage in front of a
French jury or decision-maker. Read the section you need; quote the source
id and page with every figure (« selon la Cour des comptes, 2020, p. 143 »).

These are **large State programmes** (≥ 9 M€, 6 years on average). They
calibrate the order of magnitude of overruns and the cost structure; they
are not the contingency rate of a three-month full-stack project. The
contingency of a budget still comes from its own estimate (P50 → P80) or
its own risks, as `chiffrage-budget` says.

## Sources (checked 2026-11-23)

| Id | Document | Licence / reuse |
|---|---|---|
| P | DINUM, « Panorama des grands projets numériques de l'État », 22 editions, 18/11/2016 → 01/12/2025, one fiche per project — [data.gouv.fr](https://www.data.gouv.fr/fr/datasets/panorama-des-grands-projets-numeriques-de-letat/) | Licence Ouverte (Etalab): reuse freely, cite « DINUM, Panorama des grands projets numériques de l'État » |
| C | Cour des comptes, « La conduite des grands projets numériques de l'État », communication à la commission des finances du Sénat, juillet 2020, 206 p. — [PDF](https://www.vie-publique.fr/files/rapport/pdf/276699.pdf), [notice](https://www.vie-publique.fr/rapport/276699-la-conduite-des-grands-projets-numeriques-de-l-etat) | Public report: quote and cite |
| M | Fiche « Action n° 6-3 — Sécuriser la mise en œuvre des grands projets numériques de l'État », pilote DINUM, mise à jour janvier 2022, 2 p. — [PDF](https://www.modernisation.gouv.fr/files/fileadmin-legacy/Book/Fiche6_3.pdf) | Public document: quote and cite |
| U | Université Frères Mentouri Constantine 1 (ISTA), cours « Chiffrage d'un projet : évaluation des charges », L2 GIM, 4 p. — [PDF](https://fac.umc.edu.dz/ista/pdf/cours/L2-GIM_Chiffrage%20de%20projet.pdf) | No licence stated: reuse the layout, not the text |
| S | Smartsheet, « Modèle d'estimation de coûts de projet informatique » (FR), 8 p. — [PDF](https://fr.smartsheet.com/sites/default/files/2024-01/IC-IT-Project-Costing-11369_WORD_FR.pdf) | Proprietary template: reuse the outline, not the text |

## 1. Overruns measured on French State IT projects

### Across the 22 editions of the Panorama (P)

Each project's last published cost and duration divided by its first
published ones, the projects matched by name across editions (computed
2026-11-23 from the 22 files). 196 projects, 163 with a cost in at least two
editions.

| Ratio last / first | Median | P75 | P80 | P90 | Grew | > +15 % | > +50 % | Doubled | Fell |
|---|---|---|---|---|---|---|---|---|---|
| Cost | ×1.02 | ×1.25 | ×1.35 | ×1.68 | 58 % | 31 % | 13 % | 7 % | 17 % |
| Duration | ×1.06 | ×1.25 | ×1.33 | ×1.54 | 64 % | 38 % | 10 % | 5 % | 16 % |

All projects together: 6 804 → 9 610 M€ (×1.41). Latest edition
(01/12/2025): 59 projects, 4 530 M€, median cost 32.8 M€, mean planned
duration 6.5 years (median 6.3).

Limits: the first figure is the first one *published*, often after launch,
so the true drift from the very first estimate is larger; the ratios mix
estimation error and scope changes; a renamed project counts twice.

### From launch to 2019, in the State budget documents (C, p. 142–144)

Tableau n° 9 of the Cour: 49 projects of the PAP 2019 with their cost and
duration at launch and updated.

- All together: costs 1 624.3 → 2 440.0 M€ (**+50 %**), durations
  3 137 → 3 772 months (**+20 %**); without SIRHEN, abandoned, +26 % and
  +19 % (p. 142).
- 65 % of the projects cost more than at launch; 70 % last 5 years or
  more, six of them 10 years or more; mean updated duration 6 years
  4 months (p. 143).
- Per project (computed from the table): cost median ×1.09, **P80 ×1.63**,
  P90 ×2.40; 39 % above +25 %, 29 % above +50 %, 18 % doubled, 12 %
  cheaper. Duration median ×1.00, P80 ×1.40, P90 ×1.70.
- Examples (cost M€, duration months, launch → updated): SIRHEN 80.1 →
  496.4, 84 → 144; CPF 9.0 → 77.7, 36 → 60; CYCLADES 12.5 → 51.8, 84 → 153;
  CASSIOPÉE V2 4.4 → 20.6, 26 → 84; ANTARES 118.6 → 169.3, 120 → 204. On
  target: DSN 21.5 → 21.5, 70 → 70; FRANCECONNECT phase II 7.9 → 7.9,
  36 → 36.

### The official indicator (C, M)

- The drifts « ont plus que doublé » since 2015 and « dépassent
  sensiblement le seuil de 30 % » (C, p. 8). Target of the TECH.GOUV plan
  (2019): under 20 % by 2022 (C, p. 8 and 41).
- December 2021 (14th edition, 50 projects, 2.62 Md€): mean budget drift
  13.5 % and schedule drift 15.4 %, down 23.1 and 10.2 points from June
  2020 (M) — so about 36.6 % and 25.6 % in June 2020. Target: 15 % at the
  end of 2022 (M). Part of the fall is mechanical: old projects (Sirhen,
  Source solde, prélèvement à la source, Cyclades) leave the panorama
  (C, p. 41).

### Three failures to cite (C, p. 18–21)

- **Louvois** (military pay, 2001): deployed ten years later; its eventual
  abandonment was announced at the end of 2013. Initial development about 80 M€, then 156.4 M€ of extra costs since
  2013; pay errors of 465 M€ in 2012 alone.
- **ONP** (pay of 2.7 million civil servants, 2007, 3 800 posts of
  productivity promised): about 346 M€ spent in 6 years by end 2013, then
  422 M€ + about 290 M€ still needed when it was stopped; 140 M€ written
  off. The architecture was never audited by independent experts; the
  State pays on about 1 500 pay elements where a large company has about a
  hundred (p. 20).
- **Cassiopée** (criminal justice chain, 2001): cost and duration about
  double at deployment in 2013, without meeting the users' needs; seven
  project directors in 2001–2014; full cost about 108 M€ over nearly twelve
  years (65.8 external, 36.5 internal, about 6 for data migration).
- The counter-example: **prélèvement à la source**, 212 M€ over 56 months,
  delivered without systemic failure (M).

## 2. Cost structure ratios (C, annexe 8, p. 153–154)

| Ratio | Value |
|---|---|
| Costs outside development (hardware, network, licences, training…) | about **15 %** of the total budget |
| Business side (MOA) to build side (MOE) | about 30 MOA resources per 100 MOE |
| Floors set by the DINUM | 1 internal per 1 external in MOA, 1 internal per 3 external in MOE |
| Minimum the Cour derives from these metrics | at least **37 %** internal in the budget for human resources (internal + external) |
| Measured | 25 % internal on the Panorama projects, 32 % on projects > 5 M€ (economy and finance ministries 49 %, culture 15 %, justice 9 %); worldwide average 65 % (Gartner, cited by the Cour) |
| Full yearly cost of a category A civil servant (MAREVA 2 standard costs, DGFiP) | **75 000 €** — salary, allowances, pensions, employer charges and workstation; about 344 € a day over 218 days (derived) |

What it means for a budget:

- Count the internal labour. Ministries « avaient et ont toujours trop
  souvent tendance à présenter leurs seuls coûts budgétaires d'achat de
  prestations externes » (C, p. 44): AMOA, AMOE, licences, training,
  hardware. MAREVA requires the internal cost too. For an `interne` budget,
  every person of the client who specifies, tests and decides is a line.
- Check `costs` against the 15 %: environments, licences, devices and
  training far below that share usually mean a forgotten line.
- The 30 MOA / 100 MOE ratio covers the whole business side (product owner,
  AMOA, functional acceptance), not only the project manager's 10–15 %
  overhead of `chiffrage-estimation`: on a client project, ask who on the
  client's side pays for that time.

## 3. Budget conventions of the State (C, p. 142)

- The budget of an IT project in the PAP = initial costs, internal staff
  included (titre 2), **plus two years of maintenance** (arrêté du 14
  novembre 2014, art. 2, for décret n° 2014-879).
- Initial duration and budget: from the notification of the MOE contract.
  Updated ones: estimated at the date of the budget document, to the end of
  the project. The expected gains must be valued.
- A drift is explained by its cause: regulatory change, price index, or
  execution hazards.

## 4. Value and return (C, p. 44–45)

- MAREVA 2 (« Méthode d'Analyse et de REmontée de la VAleur »), the
  interministerial method: yearly financial trajectory, then VAN (net
  present value), TRI (internal rate of return) and délai de retour
  (payback). Used by 98 % of the Panorama projects in September 2019, 84 %
  in November 2016.
- Discount rate: **2 % or 4 %**, set by the Direction du budget.
- Of 37 projects whose MAREVA study the Cour received, 63 % show a positive
  return; mean payback **5.7 years**, few under 4.
- Example of a measured gain: online income-tax returns saved 64 FTE per
  million new online filers.
- Replacing an old system that is cheap to maintain can lower the return.

## 5. Size, lots and success (C)

- « Au vu de la corrélation entre la dimension des projets et leur
  probabilité d'échec », limit the size and split into lots delivered in
  short milestones; one accountable project director; users involved at
  every stage (p. 7). Doctrine: « Pensons grand et avançons petit » (p. 8,
  24).
- Recommendation: a few medium projects of **5 to 20 M€** full cost,
  delivered in **18 months to 3 years** at most (p. 9).
- Any State project above 9 M€ needs the DINUM's conforming opinion (p. 8);
  the Cour asks for mandatory DINUM support above 50 M€ (p. 10).
- Standish Group CHAOS 2018 data, as quoted by the Cour (p. 30–31): about
  25 000 projects of 2013–2017; very large projects fail in 43 % of cases
  and succeed in 4 %, very small ones fail in 8 % and succeed in 57 %;
  agile projects succeed in 48 % of cases against 26 %; fast decisions 58 %
  against 18 %. The Standish figures are disputed (definitions, sample):
  always cite them as « selon le Standish Group, cité par la Cour des
  comptes ».

## 6. French fiche formats

### The State's project fiche (P)

One line per project, the fields a French reader expects on a fiche:
ministère porteur · nom du projet · description et objectifs · projet
interministériel · début · durée prévisionnelle en années · phase en cours
(Cadrage, Conception / Réalisation, Expérimentation, Déploiement,
Déploiement / Bilan intermédiaire, Terminé) · coût estimé (M€) · tranche
(< 5 M€, entre 5 et 9, entre 9 et 20, entre 20 et 100, plus de 100 M€) ·
zone fonctionnelle · financement (programmes budgétaires) · date de
publication. The editions from June 2025 keep only ministry, name,
description, start, duration, cost, tranche, funding and date (zone
fonctionnelle went after June 2024, phase and projet interministériel after
December 2024). Figures under tender or under review are not published.

### The workload and cost sheet (U)

Header: projet, chef de projet, date. Lines grouped by phase (design,
fonctionnel, développement…), each phase with a subtotal, then the project
total. Columns: tâche · intervenant · charge (j/h) · coût journalier (TJM
of a contractor or internal daily cost) · total. Variant « tableau
croisé »: one pair of columns (j/h, coût) per person, under their rate, to
see each person's load and shorten the project by rebalancing it. Its
method: decompose to elementary tasks with a single profile each; estimate
from end-of-project reviews, experienced colleagues, a domain expert,
abaques (standard costs) and team estimation; three-point PERT
(a + 4m + p) / 6. `chiffrage-wbs`, `chiffrage-estimation` and
`chiffrage-budget` produce this sheet; lay it out this way when a jury
expects a « fiche d'estimation des charges ».

### The cost management plan (S)

Outline of a cost management plan, to borrow when a jury asks how the
budget is controlled after it is approved: purpose and communication ·
allowed variance per stage · spending authorisation levels (limit, who) ·
variance action plan (% of variance → action → owner) · estimation process
(thresholds, confidence) · cost baseline (WBS, estimation method, funding,
contingency and reserve) · control metrics · reporting · change control ·
final budget (contingency, fixed costs, materials, subcontracting, total).

## 7. Sources checked and set aside (2026-11-23)

- HAL halshs-00199166: S. Chatelain-Ponroy, « Du budget administratif au
  budget outil de gestion. Le cas des musées français », Finance Contrôle
  Stratégie, 1998, p. 5–33 — museum management control, not IT; full text
  behind HAL's anti-bot page.
- academia.edu « R22_Diallo_Thuillier »: refused (403). One of Diallo &
  Thuillier, International Journal of Project Management 22(1):19–31, 2004,
  or 23(3):237–252, 2005 — success of development projects in Africa,
  paywalled.
- UMMTO ummto/13093: W. Azzouz, Z. Taieb, master's thesis, 2020 — a MERN
  Gantt planning app for construction; no estimation method, a bibliography
  of web pages.
- Google Scholar « budget projet full stack »: anti-bot redirect; the query
  itself only finds off-topic works.
- Dead in November 2026: manager-go.com « estimation-des-charges.pdf »
  (404), CY Cergy gpi-3 / gpi-3a (404), IUT Caen « estimation des charges »
  (403), IUT Belfort-Montbéliard « business plan projet informatique »
  (domain gone).
