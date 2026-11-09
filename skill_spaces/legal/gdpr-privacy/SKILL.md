---
name: gdpr-privacy
description: >-
  GDPR and privacy by design for a software project: the data map and the
  record of processing (art. 30), legal bases, minimisation, retention,
  data-subject rights built into the app, processors and transfers outside
  the EU, cookies and trackers with prior consent (CNIL rules), third-party
  services that leak visitors' data (Google Fonts, Analytics, YouTube, Maps,
  reCAPTCHA, CDNs), the DPIA screening, and the drafts of the privacy policy,
  the legal notice and the cookie banner. Use for a GDPR audit, before
  launching a site or an app that handles personal data, or to write the
  legal pages. Se déclenche sur : RGPD, données personnelles, CNIL, cookies,
  consentement, politique de confidentialité, mentions légales, registre.
---

# gdpr-privacy

Deliverables, in the project: `rgpd/registre.md` (the record of processing),
the legal pages in the app's own format (privacy policy, legal notice,
cookie policy when there are trackers), and the GDPR part of
`conformite.md`. Run `licensing-copyright/legal_scan.py` first: it already
finds trackers, Google Fonts, embeds, CDNs, real personal data and missing
legal pages.

Not legal advice: a lawyer or the user's DPO validates before a commercial
launch. Write what you are sure of; the rest goes to For the user as a
question.

## Does it apply?

Personal data is anything about an identified or identifiable person: name,
e-mail, phone, address, IP address, cookie or device id, location, photo,
voice, an account id. Any app with accounts, a contact form, analytics or
logs processes some. Sensitive data (health, religion, opinions, sexual
life, biometrics, criminal records — art. 9, 10) is forbidden unless an
exception applies: flag it for the user.

## 1. Map the data

Read the models, the forms, the API and the third-party calls. For every
processing (account management, orders, newsletter, support, audience
measurement, logs…) write in `rgpd/registre.md` (art. 30):

| Field | Content |
|---|---|
| Purpose | why — one purpose per processing |
| Legal basis (art. 6) | contract, consent, legal obligation, legitimate interest (with the balance written down)… |
| Data | each field, flagged when optional |
| People | customers, prospects, employees, visitors |
| Recipients | internal teams; processors (host, e-mail, payment, analytics) with their country |
| Transfers outside the EU | the country and the safeguard: adequacy decision (EU-US Data Privacy Framework for certified companies), standard contractual clauses |
| Retention | a duration and what triggers deletion (e.g. prospects: 3 years after the last contact, CNIL guidance) |
| Security | measures — handed to the cyber specialist |

## 2. Privacy by design in the code (art. 25)

Check, and fix or hand over:

- **Minimisation**: forms ask only what the purpose needs; optional fields
  say so. No date of birth "just in case".
- **Retention**: a scheduled job deletes or anonymises what has passed its
  duration (inactive accounts, old logs, abandoned carts).
- **Rights** (art. 15–21): the user can see and export their data (15, 20),
  correct it (16), delete their account (17), object to marketing (21) —
  in the app, or a documented e-mail procedure answered within one month.
- **Consent**, when it is the basis: a separate unticked box per purpose,
  recorded (who, when, which text version), withdrawable as easily as given.
  Every marketing e-mail has an unsubscribe link. In France, a child under 15
  needs a parent's consent too for an online service based on consent.
- **Logs and analytics** without names, e-mails or full IPs when they are not
  needed; short retention.
- **Test data and seeds** are fake (Faker); never a real customer export.
- **Security** (art. 32) — passwords hashed (Argon2id, bcrypt), TLS,
  access control, encryption of sensitive fields: the cyber specialist's.

## 3. Cookies and trackers

French rules (art. 82 of the loi Informatique et Libertés, CNIL guidelines
and recommendation of 2020):

- **Prior consent** for every tracker that is not strictly necessary:
  analytics, advertising, social pixels, A/B testing, embedded players.
  Nothing of it loads before the visitor accepts.
- Exempt: session, authentication, cart, load balancing, the consent cookie
  itself, security, and audience measurement configured as the CNIL exempts
  it (e.g. Matomo set up per CNIL's guide).
- The banner: "Tout accepter" and "Tout refuser" at the same level, as easy
  as each other; no pre-ticked box; details per purpose; the choice kept
  about 6 months; a link in the footer to change it at any time.
- Use an open-source consent manager (tarteaucitron.js, Klaro, Orejime,
  vanilla-cookieconsent) and load trackers through it.

Third-party services that send visitors' data before any consent:

| Service | Fix |
|---|---|
| Google Fonts from fonts.googleapis.com | self-host the font files (a German court fined it, LG München, 20 Jan 2022) |
| Google Analytics, Meta pixel, Hotjar… | behind consent, or a CNIL-exempt tool (Matomo configured) |
| YouTube, Vimeo, Google Maps, social embeds | click to load; youtube-nocookie.com; OpenStreetMap for maps |
| reCAPTCHA | disclose it in the policy, or a privacy-friendly alternative |
| Public CDNs (jsDelivr, unpkg, cdnjs) | install the package and bundle it |

## 4. Processors and DPIA

- Every processor (host, e-mail sender, payment, analytics, support tool)
  needs a data processing agreement (art. 28): list them, their country and
  where their DPA is. Prefer EU hosting regions.
- **DPIA screening** (art. 35): large-scale sensitive data, systematic
  monitoring, profiling with effects on people, new technologies on
  vulnerable people… If two criteria of the CNIL list are met, a DPIA is
  likely required: flag it for the user, do not write it alone.
- A data breach must be notified to the CNIL within 72 hours (art. 33):
  note who would do it in `conformite.md`.

## 5. The legal pages

Draft them from the record, in the app's format and language, never a
generic template:

- **Privacy policy** (art. 13–14): the controller and its contact, the DPO
  if any, each purpose with its basis and retention, the recipients and
  processors, the transfers and their safeguard, the rights and how to use
  them, the right to complain to the CNIL, whether giving the data is
  required and what happens if not. Linked from every form and the footer.
- **Legal notice** (mentions légales, LCEN art. 6): the publisher (name or
  company, address, contact, company registration and capital for a
  company), the publication director, the host (name, address, phone).
  Unknown values stay as visible `[À compléter]` markers and go to For the
  user.
- **Cookie policy** and the banner, when there are trackers.
- Terms of use or sale (CGU / CGV): a draft at most, marked for a lawyer's
  review.

## Finish

Run the scanner again: no `tracker`, `google-fonts`, `private-link` or
`personal-data` left unexplained, the legal pages found. In `conformite.md`,
list what was checked, fixed, and what the user must do (the DPAs to sign,
the `[À compléter]` values, a lawyer's review).
