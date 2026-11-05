---
name: web-app
description: >-
  Builds or reviews a website or web app: stack choice (static, SPA, SSR or
  hybrid; back-end framework), project structure, REST API design with status
  codes, pagination and RFC 9457 problem details, GraphQL when it fits,
  sessions vs tokens, Argon2id/bcrypt, OAuth/OIDC, server-side authorisation,
  security headers and CORS, input validation, Core Web Vitals, accessibility
  and SEO basics, env config and a README. Use for a site, web app, API or
  front-end. Se déclenche sur : site web, application web, front-end,
  back-end, API REST, React, Django, authentification, performance web, SEO.
---

# web-app
Produces the code (in the target folder, or a new project in the shared work
folder) and `web-notes.md`: architecture, routes and API table, how to run,
checks done, open issues.

## Before you start
| Input | Where | If missing |
|---|---|---|
| Pages, features, users | task, handoffs (spec, design, architecture) | the smallest useful set of pages; record it |
| Design | design handoff (`ui-spec.md`, `tokens.json`) | semantic HTML with a clean, accessible default style |
| Data and API contracts | database or architecture handoffs | design the API here and note it for the database specialist |
| Existing stack | `package.json`, `requirements.txt`, `pyproject.toml`, `composer.json` | choose with the table below |
| Hosting | task, cloud or devops handoffs | runnable locally; deployment For the user |

## Method
1. **Stack** (table below); stay with the project's framework when there is
   one.
2. **Structure**: routes or pages, components, API layer, data access,
   configuration; one folder per feature beats one folder per file type for
   larger apps.
3. **Thin slice**: one page that calls one API route that reads and writes one
   record, running locally.
4. **API**: resources and methods per the rules below; write the API table
   first; validate every input with a schema (Zod, Pydantic, Django forms or
   serializers, Joi...).
5. **Authentication and authorisation** per the checklist; authorisation
   enforced in the back-end on every request, never only by hiding UI.
6. **Front-end**: semantic HTML, forms with labels and server-side errors
   shown next to fields, loading, empty and error states.
7. **Security headers, CORS, cookies** set in one place (middleware).
8. **Performance**: image sizes and formats, lazy loading below the fold,
   code splitting, caching headers for static assets.
9. **Run** from the project folder: `npm ci` then `npm run build`, `npm test`,
   `npm run lint` (or `python3 -m pytest`, `ruff check .`); fix what fails.
10. **README** with requirements, `.env.example`, install, run, test.
11. **Write** `web-notes.md`.

## Checklists

### Stack choice
| Need | Fits |
|---|---|
| Content site, docs, landing page | static site (plain HTML/CSS or a static generator); CDN hosting |
| App behind a login, rich interactions | SPA (React, Vue, Svelte) + API |
| SEO plus interactivity, mixed content | server-rendered or hybrid (Next.js, Nuxt, SvelteKit) |
| Forms and CRUD with an admin | server-rendered framework (Django, Laravel, Rails-like) |
| API only | FastAPI, Express, Django REST framework, Laravel |

### REST API
| Rule | Detail |
|---|---|
| Resources | plural nouns: `GET /orders`, `GET /orders/{id}`, `POST /orders`, `PATCH /orders/{id}`, `DELETE /orders/{id}` |
| Status codes | 200 OK, 201 Created (+ `Location`), 204 No Content, 400 invalid input, 401 not authenticated, 403 not allowed, 404 not found, 409 conflict, 422 validation (if the framework uses it), 429 rate limited, 500 server error |
| Errors | one shape everywhere, e.g. RFC 9457 problem details (`type`, `title`, `status`, `detail`, `instance`) plus field errors |
| Pagination | `limit` + cursor for large or changing lists; `page`/`offset` for small ones; maximum page size |
| Filtering, sorting | query parameters with an allowlist of fields |
| Versioning | `/v1/` prefix or a header; additive changes stay compatible |
| Idempotency | `PUT`/`DELETE` idempotent; idempotency keys for retried `POST` (payments) |
| Documentation | OpenAPI generated or written next to the code |

GraphQL: when clients need flexible, nested reads across many types; add
depth and complexity limits and per-field authorisation.

### Authentication and sessions
- Server sessions with a cookie (`HttpOnly`, `Secure`, `SameSite=Lax` or
  `Strict`) for first-party web apps; tokens (short-lived access token +
  refresh) for third-party or mobile clients.
- Passwords: Argon2id (or bcrypt) via a maintained library; never a plain
  fast hash; rate limiting on login and reset.
- OAuth 2.0 / OpenID Connect through a provider library (authorisation code
  flow with PKCE); never implement the protocol by hand.
- CSRF protection for cookie-authenticated state changes; rotate the session
  at login.

### Security headers and input
`Content-Security-Policy` (no `unsafe-inline` scripts where avoidable),
`Strict-Transport-Security` on HTTPS, `X-Content-Type-Options: nosniff`,
`frame-ancestors 'none'` (or `X-Frame-Options: DENY`), `Referrer-Policy:
strict-origin-when-cross-origin`. CORS: explicit origins; never `*` with
credentials. Output encoding by the template engine; no `innerHTML` with user
data. Uploads: size and type limits, random names, stored outside the web root.

### Performance (Core Web Vitals "good")
| Metric | Target | Usual fixes |
|---|---|---|
| LCP | ≤ 2.5 s | compress and size the hero image, preload it, server response fast, no render-blocking CSS/JS |
| INP | ≤ 200 ms | less JavaScript on interaction, break long tasks, avoid heavy re-renders |
| CLS | ≤ 0.1 | width/height on images and embeds, reserved space for ads and banners, `font-display` |

### Accessibility and SEO basics
Labels for every input; alt text for meaningful images; headings in order;
keyboard reachable with visible focus; colour contrast per the design tokens.
SEO: unique `<title>` and meta description per page, `lang` on `<html>`,
canonical URLs, `sitemap.xml`, `robots.txt`, readable URLs.

## Deliverable
Code in the target folder or `web/` in the shared work folder, a README and
`.env.example`, and `web-notes.md` (translate the headings into the user's
language):

```markdown
# Web notes — <app>
## Summary
## Architecture
<stack, structure, data flow; Mermaid diagram if useful>
## Pages and routes
| Route | Page / purpose | Auth |
## API
| Method | Path | Body / query | Responses | Auth |
## How to run
<commands from the README>
## Checks done
| Check | Command | Result |
## Open issues
## Decisions
## Next steps
```

## Pitfalls
- Authorisation checked only in the front-end.
- Tokens in `localStorage` for a first-party app (any XSS steals them).
- Different error shapes per endpoint; 200 with `{"error": ...}`.
- `Access-Control-Allow-Origin: *` with cookies.
- A framework chosen for fashion when a static site would do.
- Unsized images causing layout shift; a megabyte of JavaScript for a form.
- Secrets in front-end bundles (anything shipped to the browser is public).
- README commands that were never run.
