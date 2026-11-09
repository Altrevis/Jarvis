---
name: licensing-copyright
description: >-
  Makes sure every asset, text, piece of code and dependency of a project may
  legally be used: where to find images, icons, illustrations, fonts, sounds
  and videos under a licence that allows commercial use, what is forbidden,
  the credits.json register with source, author, licence and credit, the
  open-source licence policy for dependencies and copied code, trademarks and
  logos, the project's own licence, and a scanner that finds unregistered
  assets, hotlinks, private links, Google Fonts, trackers and risky licences.
  Use for a licence audit, before publishing a project, or when adding
  assets. Se déclenche sur : droit d'auteur, licence, libre de droits,
  crédits, images, polices, open source, contrefaçon, marque, logo.
---

# licensing-copyright

Two deliverables: `credits.json` at the project root, always current, and
the licence part of `conformite.md`. The scanner checks both.

## The rule behind everything

In France, a work is protected from the moment it is created, with no
registration and no © needed (Code de la propriété intellectuelle,
L.111-1). Reproducing it without permission is infringement (contrefaçon,
L.335-2 and L.335-3: up to 3 years in prison and €300,000). There is no
"fair use". The author's moral right — to be credited — cannot be signed
away (L.121-1). A photo of an identifiable person also needs that person's
consent (droit à l'image, Code civil art. 9). So: **found online does not
mean free**. Every asset needs a known source and a licence that allows the
use, and the proof goes in `credits.json`.

## Where assets come from, in this order

1. **Make it.** An SVG drawn by hand, CSS shapes and gradients, a chart
   generated from data, an icon from a set below. A neutral placeholder
   (a grey block with its alt text) is better than a doubtful image.
2. **An approved source**, under its licence:

| Kind | Source | Licence | Obligations |
|---|---|---|---|
| Photos, videos | Unsplash, Pexels, Pixabay | their own licences | Commercial use allowed, no credit required. Not for resale as is, nor to build a competing image service. Check people (consent) and brands visible in the picture |
| Photos, media | Openverse, Wikimedia Commons, Flickr | per file | Read each file's licence: CC0 or CC BY / CC BY-SA only, credit as the licence says. Never NC, never ND if you crop or edit |
| Icons | Lucide (ISC), Heroicons (MIT), Tabler (MIT), Phosphor (MIT), Bootstrap Icons (MIT), Material Symbols (Apache-2.0), Font Awesome Free (icons CC BY 4.0) | permissive | Keep the notice; Font Awesome Free icons need a credit |
| Illustrations | unDraw | unDraw licence | Free, no credit; not to build a competing service |
| Fonts | Google Fonts catalogue, Fontsource (`@fontsource/*`) | mostly OFL-1.1 or Apache-2.0 | **Download and self-host**, never load from fonts.googleapis.com |
| Sounds | Freesound, Pixabay | per file | CC0 or CC BY only |
| Brand badges | "Sign in with Google", store badges, payment logos | the brand's guidelines | Only as the guidelines allow; licence `brand-guidelines`, source = the guidelines' URL |

3. **A paid licence** (Adobe Stock, Shutterstock…): only one the user has
   bought. Licence `commercial` with its `proof` (order or licence number).
   Read its limits (templates for resale, print runs, sensitive uses).

## Forbidden

- Images from Google Images, Pinterest, Dribbble, Behance, social networks,
  news sites, another company's site or app — even "just for the mock-up".
- Screenshots of other products in the shipped app (a clone's reference
  captures stay in `replica/screens/`, which is never shipped).
- Another company's logo, name, mascot or a product's distinctive look used
  as the user's own (trademark law), and look-alike names.
- Watermarked images; "free for personal use" fonts; CC BY-NC; CC BY-ND once
  modified; "editorial use only" stock.
- Hotlinking: loading an image, font or video from someone else's server.
- AI-generated images in the style of a living artist, or showing a brand, a
  character or a real person. Generated assets are allowed otherwise: source
  `generated`, the tool in `notes`. Their own copyright protection is
  uncertain: tell the user they may not get exclusive rights on them.
- Texts copied from elsewhere (competitors' descriptions, articles, reviews):
  write original ones. A short quotation names its source.

## credits.json

```json
{
  "assets": [
    {"path": "public/img/hero.webp", "source": "https://unsplash.com/photos/abc123",
     "author": "Jane Doe", "licence": "Unsplash"},
    {"path": "public/img/map.png", "source": "https://commons.wikimedia.org/wiki/File:X.png",
     "author": "John Roe", "licence": "CC-BY-4.0", "modified": true,
     "attribution": "« X » par John Roe, CC BY 4.0, modifié"},
    {"path": "public/icons/*.svg", "source": "https://lucide.dev", "author": "Lucide Contributors",
     "licence": "ISC"},
    {"path": "public/fonts/inter-*.woff2", "source": "https://fontsource.org/fonts/inter",
     "author": "Rasmus Andersson", "licence": "OFL-1.1"},
    {"path": "src/assets/logo.svg", "source": "original", "licence": "original"},
    {"path": "public/img/badge-google.svg", "source": "https://developers.google.com/identity/branding-guidelines",
     "author": "Google", "licence": "brand-guidelines"}
  ],
  "dependencies": {"some-gpl-cli": "build tool only, never distributed with the app"}
}
```

`path` is a file, a glob or, for an asset loaded from a CDN on purpose, its
URL. `licence`: an SPDX id (CC0-1.0, CC-BY-4.0, CC-BY-SA-4.0, MIT, ISC,
Apache-2.0, OFL-1.1…), `Unsplash`, `Pexels`, `Pixabay`, `original`,
`generated`, `brand-guidelines` or `commercial` (+ `proof`). Screenshots the
team takes of its own work are `original`. When a licence asks for a credit,
the app shows it: a "Crédits" page or the footer lists every `attribution`.

## Code and dependencies

Copied code keeps its licence:

- Stack Overflow answers are CC BY-SA 4.0: keep the link as the credit; the
  snippet stays under share-alike.
- A GitHub repository with no LICENSE is "all rights reserved": do not copy.
- GPL code makes the whole program GPL once distributed; AGPL also when the
  program is used over a network (SaaS).

Dependency licences, checked by the scanner from `node_modules` and the
project's virtual environment:

| Licence | Policy |
|---|---|
| MIT, BSD, ISC, Apache-2.0, 0BSD, Unlicense, CC0, Zlib, Python, MPL-2.0 | OK — keep the notices (Apache: the NOTICE file) |
| LGPL | OK as a separate library the user could replace; say so |
| GPL, EUPL | Only if the project itself is GPL-compatible and published as such; otherwise replace |
| AGPL, SSPL, BUSL, Elastic, Commons Clause, non-commercial, UNLICENSED, unknown | Replace, or justify in `credits.json` "dependencies" (e.g. a build-time tool never shipped) and tell the user |

The project's own licence: a private product keeps "all rights reserved" (no
open-source licence, a short notice); an open-source one picks MIT
(simplest), Apache-2.0 (patent grant) or GPL/AGPL (copyleft), compatible with
its dependencies. Ask in For the user when it is not obvious.

## Scan and fix

```bash
python3 .claude/skills/licensing-copyright/legal_scan.py "<project folder>"
python3 .claude/skills/licensing-copyright/legal_scan.py "<project folder>" --skip replica/screens
```

Errors to fix before anything is delivered: `asset-unregistered`,
`asset-licence`, `remote-media`, `private-link`, `google-fonts`, `tracker`
(without consent), `dependency-licence` (forbidden). Warnings to confirm one
by one and note in `conformite.md`. Run it again until it reports no error.
