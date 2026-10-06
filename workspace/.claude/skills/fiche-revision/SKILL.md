---
name: fiche-revision
description: Turn a course (pasted text or a file) into a one-page Markdown revision sheet with key definitions, formulas, and 5 self-test questions with answers. Use when the user asks for a "fiche de révision", "fiche de cours", "résumé de cours", "révisions", "fiche synthèse", "revision sheet", "study sheet" or "cheat sheet" from course material.
---

# Fiche de révision

Convert course material into a single-page Markdown revision sheet.

## Steps

1. **Get the source.** If the user pasted text, use it. If they gave a file path, read it (for PDFs, use the `pdf` skill if available; for .docx/.pptx/.md/.txt read or extract the text). If neither text nor file is provided, ask for it.
2. **Pick the language.** Write the sheet in the language of the course (default: French if the user writes in French). Keep technical terms as in the course.
3. **Select, don't summarize everything.** One page means about 350–500 words. Keep only what is likely to be tested: core definitions, formulas/theorems/rules, key distinctions, common pitfalls. Drop anecdotes, history, and examples unless one is essential to understand a concept.
4. **Stay faithful.** Use only what the course says. Never invent definitions or formulas. If the source is ambiguous, incomplete, or seems wrong, say so in a short note at the end instead of silently fixing it. If no formulas exist in the course, omit the Formules section (don't fabricate any).
5. **Write the questions.** Exactly 5 self-assessment questions, mixing recall ("Qu'est-ce que…"), understanding ("Pourquoi…", "Quelle différence entre…"), and application (a small calculation or case) when the content allows. Each has a short answer (1–2 sentences).
6. **Output** the sheet in the format below. Offer to save it as a `.md` file if the user didn't specify; if they asked for a file, write it (name: `fiche-<sujet>.md`).

## Format

```markdown
# Fiche de révision : <Titre du cours / chapitre>

## Définitions clés
- **Terme** : définition courte et précise.
- ...

## Formules / règles à retenir
- Nom : `formule` (signification des symboles, conditions d'usage)
- ...

## À ne pas confondre / pièges
- ... (optional, 2–3 lines max)

## Auto-évaluation
1. Question ?
2. ...
(5 total)

### Réponses
1. Réponse.
2. ...
```

## Conventions

- Definitions: 5–10 entries, each one line.
- Formulas: use inline code or LaTeX (`$...$`) only if the user's context renders it; default to plain inline code. Always explain the symbols.
- Put answers in a separate "Réponses" section after the questions so the user can test themselves.
- Bullets and short phrases, no long paragraphs.
- If the course is very long (many chapters), ask whether to produce one sheet per chapter instead of cramming it into one page.

## Example (excerpt)

Source: "La complexité d'un tri par comparaison est au minimum O(n log n)…"

```markdown
## Définitions clés
- **Complexité temporelle** : nombre d'opérations en fonction de la taille n de l'entrée.

## Formules / règles à retenir
- Borne inférieure des tris par comparaison : `Ω(n log n)`

## Auto-évaluation
1. Pourquoi un tri par comparaison ne peut-il pas faire mieux que O(n log n) ?
```
