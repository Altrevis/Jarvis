---
name: ui-design
description: >-
  Designs or reviews a user interface and delivers it as files: users and top
  tasks, user flows and screen inventory, ASCII wireframes or a static HTML
  prototype, spacing, type and colour tokens with light and dark themes,
  component specs with every state, WCAG 2.2 AA checks with a bundled contrast
  tool, UX copy and a Nielsen heuristic review. Use when asked to design,
  wireframe or critique a screen or an app, build a palette or a design system,
  or check accessibility. Se déclenche sur : maquette, wireframe, charte
  graphique, palette de couleurs, design system, accessibilité, contraste, revue
  UX, ergonomie.
---

# ui-design

Turns a brief or an existing interface into a design developers can build
without guessing: flows, screen inventory, wireframes, design tokens (JSON and
CSS, light and dark), component specs with every state, UX copy and a measured
accessibility check. In review mode it produces a prioritised heuristic and
WCAG 2.2 evaluation. Every deliverable is a file in the shared work folder.

## Before you start
- From the task: product, audience, platforms (web, iOS, Android, desktop),
  screens or flows wanted, brand constraints (colours, fonts, tone), languages,
  fidelity (wireframes only, or a full visual system).
- From the handoffs: requirements, user stories, architecture (which screens
  exist), decisions already made.
- From the target folders (Glob, Grep): token files (`*tokens*.json`), CSS
  custom properties (`:root {`), `tailwind.config.*`, theme files (`theme.*`,
  `*.qss`), the component library in `package.json` (MUI, Chakra, shadcn/ui,
  Bootstrap, Vuetify...), Storybook stories, i18n files with the real copy.
  An existing system wins: extend it and keep its token names.
- When something is missing, assume and record it under Decisions: responsive
  web, mobile-first, light and dark themes, WCAG 2.2 AA, system font stack,
  16 px base, copy in the user's language.

## Method
1. **Users and tasks.** 1-3 user profiles as role + goal + context (device,
   environment, expertise, accessibility needs); no invented biographies. Rank
   the top 3-7 tasks by frequency x importance: the ranking sets navigation
   order and what each screen puts first.
2. **Flows.** Per top task: entry point, steps, decisions, success end state,
   and the error, empty and cancel paths, as numbered steps or a Mermaid
   `flowchart`.
3. **Information architecture.** Pick the navigation model (checklist), then
   write the screen inventory. One primary action per screen.
4. **Wireframes.** ASCII wireframes in fenced blocks for each key screen at the
   narrowest and widest layouts, real copy (never lorem ipsum), numbered
   annotations for behaviour. Squint test: the title and the primary action are
   the most prominent elements.
5. **Visual system.** Spacing, grid, breakpoints, type scale, colour roles,
   radius, elevation, motion. Write tokens.json, then tokens.css from it.
6. **Contrast.** Put every text/background combination of both themes in
   `pairs` and run `contrast.py --palette` on tokens.json (see Tool). Change the
   token, never drop the pair, until exit 0. Check each non-text pair (input
   border on surface, focus ring on background, icon on surface) with a
   single-pair run and read its "UI components" line.
7. **Components.** For each component the screens use: anatomy, variants,
   sizes, the state table, behaviour (keyboard, touch, responsive), role and
   accessible name, tokens used. Prefer native elements (`button`, `a`,
   `input`, `select`, `dialog`) to a scripted `div`.
8. **Copy.** Labels, buttons, helper text, errors, empty states, confirmations
   and success messages for every screen, in the user's language.
9. **Prototype (optional).** One self-contained prototype.html: semantic HTML,
   the tokens.css content in an inline `<style>`, no external fonts, scripts or
   images, a small inline script only for theme, menu or dialog toggles. You
   cannot render it: tell the user to open it.
10. **Review mode.** Walk each top task through the existing UI (code,
    screenshots or notes in the target folders) against the heuristics and the
    WCAG table. Log each problem once: location, heuristic or SC, severity 0-4,
    fix. Lead with the three most severe.
11. Write ui-spec.md. In the handoff's For the user, list what you could not
    check: open prototype.html at 320 px and 200 % zoom, a keyboard-only run, a
    screen reader pass, a five-user usability test.

## Checklists

**Layout and type**

| Item | Default | Check |
|---|---|---|
| Spacing | 4-point scale: 4, 8, 12, 16, 24, 32, 48, 64 px | Every margin, padding and gap is a token |
| Grid | 4 columns on phones, 8-12 above; 16-24 px gutters; side margins >= 16 px | Max content width set (about 1200-1280 px) |
| Breakpoints | Where the content breaks, or the framework's (Tailwind: 640, 768, 1024, 1280, 1536) | Each screen specified at each breakpoint |
| Type scale | 16 px (1rem) base, ratio 1.2-1.25, rounded: 12, 14, 16, 20, 24, 30, 36 | At most 6 sizes, 2 families, 3 weights |
| Line height | Body 1.5, headings 1.1-1.3 | Body lines 45-75 characters (`max-width` in `ch`) |
| Units | `rem` for type and spacing | Text resizes to 200 % without loss |
| Form fields | Input text >= 16 px on mobile | iOS Safari zooms into smaller inputs |

**Colour roles** (one token per role and theme; components use roles only)

| Role | Used for | Must reach |
|---|---|---|
| background, surface | Page; cards, sheets, menus | Carry text at 4.5:1 |
| text, text-muted | Body; secondary text | 4.5:1 on background and surface |
| border, border-input | Dividers (decorative); control outlines | border-input 3:1 |
| primary / on-primary, secondary / on-secondary | Main and secondary actions; text on those fills | on-* 4.5:1 on its fill |
| success, warning, error, info (+ on-*) | Status text, icons, fills | Text 4.5:1, icon or fill 3:1, never colour alone |
| focus | Focus ring | 3:1 against adjacent colours |

Dark theme: its own values, not an inversion. Dark grey background (such as
#121212) rather than pure black, elevation by lighter surfaces, lighter and
less saturated accents, every pair re-checked.

**Component states**

| State | Visual | Behaviour and accessibility |
|---|---|---|
| default | Resting style from tokens | Role and accessible name defined |
| hover | Subtle tint | Never the only way to reveal something (no hover on touch) |
| focus-visible | 2 px outline, 2 px offset, focus token | `:focus-visible`; never `outline: none` without a replacement; not hidden under sticky bars |
| active / pressed | Darker tint | `aria-pressed` on toggle buttons |
| disabled | Lower emphasis (contrast-exempt) yet legible | Say why nearby; `aria-disabled` keeps it focusable if the reason must be found |
| loading | Spinner or skeleton, same size | `aria-busy`; block double submit; announce the result |
| error | Error token + icon + message under the field | `aria-invalid`, message tied by `aria-describedby`; focus the first error or a summary |
| empty | Explanation + the next action | Never a blank area |
| selected / current | Non-colour marker (check, weight, bar) | `aria-selected`, `aria-current` or `aria-checked` as fits |

Also design for: very long text, 0, 1 and 1,000 items, slow network, offline.

**WCAG 2.2 AA at design level**

| SC | Level | Check |
|---|---|---|
| 1.1.1 Non-text content | A | Alt text for meaningful images; decorative images marked |
| 1.3.1 Info and relationships | A | Headings in order, lists, table headers, labels tied to fields |
| 1.4.1 Use of color | A | Status, inline links, chart series and errors also use text, icon, pattern or underline |
| 1.4.3 Contrast (minimum) | AA | Text 4.5:1; large text (>= 24 px, or >= 18.66 px bold) 3:1 |
| 1.4.4 Resize text, 1.4.10 Reflow | AA | 200 % text size; 320 CSS px wide without horizontal scrolling |
| 1.4.11 Non-text contrast | AA | Control boundaries, icons, focus indicators, chart marks 3:1 |
| 1.4.12 Text spacing | AA | Survives line height 1.5, paragraph spacing 2x, letter 0.12x, word 0.16x font size |
| 1.4.13 Content on hover or focus | AA | Tooltips dismissible (Esc), hoverable, persistent |
| 2.1.1 Keyboard, 2.1.2 No keyboard trap | A | Every action by keyboard; dialogs keep focus inside and close with Esc |
| 2.4.3 Focus order, 2.4.7 Focus visible | A, AA | Order follows reading order; focus always visible |
| 2.4.11 Focus not obscured (minimum) | AA | Sticky headers, footers, banners never fully cover the focused element |
| 2.5.7 Dragging movements | AA | Every drag has a single-pointer alternative |
| 2.5.8 Target size (minimum) | AA | >= 24 x 24 CSS px, or spaced so 24 px circles do not overlap |
| 2.2.2 Pause, stop, hide; 2.3.1 Three flashes | A | Moving content over 5 s can be paused; no more than 3 flashes per second |
| 3.3.1, 3.3.2, 3.3.3 Errors, labels, suggestions | A, A, AA | Visible labels (not placeholders); errors name the field and the fix |
| 3.3.7 Redundant entry | A | Never ask twice for the same data in one process |
| 3.3.8 Accessible authentication (minimum) | AA | Paste and password managers allowed; no puzzle-only check |
| 3.2.6 Consistent help | A | Help and contact in the same place on every page |
| 2.5.3 Label in name, 4.1.2 Name, role, value | A | Icon-only buttons named; the name contains the visible label |

Beyond AA: honour `prefers-reduced-motion` (2.3.3 is AAA but cheap), keep
feedback transitions short (about 100-300 ms), support `forced-colors: active`.

**UX copy**
- Buttons: verb + object ("Save changes", "Delete project"), never a bare "OK",
  "Yes" or "Submit"; a confirm button repeats the action ("Delete 3 files").
- Errors: what happened and how to fix it, next to the field, no blame, no bare
  codes: "Enter the date as DD/MM/YYYY", not "Invalid input".
- Empty states: why it is empty and the next step ("No invoices yet. Create
  invoice").
- Destructive actions: name the object and the consequence ("This permanently
  deletes 12 photos").
- One term per concept across all screens (keep a glossary); sentence case;
  leave room for longer translations.

**Nielsen's 10 usability heuristics** (severity 0 not a problem, 1 cosmetic,
2 minor, 3 major, 4 catastrophe; weigh frequency, impact and persistence)

| # | Heuristic | Look for |
|---|---|---|
| 1 | Visibility of system status | Loading, progress, saved state, current location |
| 2 | Match between system and the real world | Users' words, not internal jargon; natural order |
| 3 | User control and freedom | Undo, cancel, back, a way out of every flow |
| 4 | Consistency and standards | Same thing looks and works the same; platform conventions |
| 5 | Error prevention | Constraints, good defaults, confirmation before destruction |
| 6 | Recognition rather than recall | Visible options, recent items, nothing to memorise |
| 7 | Flexibility and efficiency of use | Shortcuts, bulk actions, remembered choices |
| 8 | Aesthetic and minimalist design | One primary action, no competing noise |
| 9 | Help users recognize, diagnose, and recover from errors | Plain-language errors with a way out |
| 10 | Help and documentation | Contextual help where a task is complex |

**Navigation**: up to 5 top destinations on phones in a bottom tab bar, more in
a sidebar or a menu plus search; mark the current location (`aria-current`);
breadcrumbs for hierarchies deeper than two levels.

## Deliverable
Write in the shared work folder; translate the headings into the user's language.

`ui-spec.md` (default name):

````markdown
# UI specification — <product or feature>
## Summary
What is designed, for whom, the three key decisions, open risks.
## Users and top tasks
| # | Task | User | Frequency | Importance |
## Flows
### F1 <task>
1. <step> (error path: ..., empty path: ...)
## Information architecture
Navigation model and why.
| ID | Screen | Purpose | Entry points | Main components | States |
## Wireframes
### S01 <screen> — narrow (360 px)
```text
+----------------------------------+
| [=]  Invoices              [+ 1] |
| [ Search invoices...           ] |
| INV-042  Acme   1,200 EUR  Paid  |
+----------------------------------+
```
1. <annotation>
## Visual system
Spacing, grid and breakpoints, type, colour roles (light and dark), radius,
elevation, motion: token names and values.
## Components
### <Component>
Anatomy, variants, sizes, states table, behaviour, accessibility, tokens.
## Content and copy
| Key | Text | Notes |
## Accessibility
| Pair or check | Needed | Measured | Result |
What still needs testing with assistive technology.
## Review findings (review mode)
| # | Where | Problem | Heuristic or SC | Severity | Fix |
## Decisions
| Decision | Options considered | Why |
## Next steps
````

`tokens.json`: theme prefix, then the role; `pairs` makes the file its own
contrast check; other groups are free-form. Values below pass the tool.

```json
{
  "colors": {
    "light.background": "#ffffff", "light.surface": "#f6f7f9",
    "light.text": "#1a1d23", "light.text-muted": "#545a66",
    "light.border-input": "#7d8390", "light.primary": "#1f5fd1",
    "light.on-primary": "#ffffff", "light.error": "#b42318",
    "dark.background": "#121212", "dark.surface": "#1e1f22",
    "dark.text": "#e8eaed", "dark.text-muted": "#a8adb7",
    "dark.border-input": "#7b8190", "dark.primary": "#8ab4ff",
    "dark.on-primary": "#0b1b3a", "dark.error": "#ff8a80"
  },
  "pairs": [["light.text", "light.background"], ["light.text-muted", "light.surface"],
            ["light.on-primary", "light.primary"], ["light.error", "light.surface"],
            ["dark.text", "dark.background"], ["dark.text-muted", "dark.surface"],
            ["dark.on-primary", "dark.primary"], ["dark.error", "dark.surface"]],
  "space": {"1": "4px", "2": "8px", "3": "12px", "4": "16px", "5": "24px", "6": "32px"},
  "font": {"family": "system-ui, sans-serif", "size-base": "1rem", "line-body": "1.5"},
  "radius": {"sm": "4px", "md": "8px"},
  "motion": {"fast": "120ms", "base": "200ms"}
}
```

`tokens.css`: role `light.text` becomes `--color-text`; light is the default.

```css
:root { color-scheme: light; --color-text: #1a1d23; /* every light.* role */
        --space-1: 4px; --font-size-base: 1rem; --motion-base: 200ms; }
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) { color-scheme: dark; --color-text: #e8eaed; /* every dark.* role */ }
}
:root[data-theme="dark"] { color-scheme: dark; --color-text: #e8eaed; /* same dark values */ }
@media (prefers-reduced-motion: reduce) { :root { --motion-fast: 0ms; --motion-base: 0ms; } }
```

Native targets: map the same token names to the platform theme (Qt style sheet
or palette, SwiftUI asset colours, Compose theme, XAML resources), or note it
for the desktop or mobile specialist.

## Pitfalls
- Drawing screens before tasks and flows: polished screens, broken journeys.
- A placeholder as the only label: it vanishes on input and is often low contrast.
- Eyeballing greys: #999999 on white is 2.85:1; #8a909c on #f6f7f9 is 2.99:1, just
  under the 3:1 an input border needs. Measure every pair.
- A dark theme made by inverting colours or reusing light accents; re-run all pairs.
- `outline: none` with no replacement, or information shown on hover only.
- Status by colour alone: a red border without text, a green dot without a label.
- Disabled buttons with no reason; prefer an enabled button plus a clear message.
- Ideal data only: test long names, long translations, 0, 1 and 1,000 items, errors.
- Icon-only buttons without an accessible name, or smaller than 24 x 24 px.
- Unquoted hex colours on the command line: `#` starts a shell comment.

## Tool
`contrast.py` (standard library only) computes the WCAG 2.x contrast ratio. Use
`python` instead of `python3` on Windows; quote every colour.

```bash
python3 .claude/skills/ui-design/contrast.py "<foreground>" "<background>" [--json]
python3 .claude/skills/ui-design/contrast.py --palette <file.json> [--json]
```

- Colours: `#rgb`, `#rrggbb`, `#rrggbbaa` (alpha must be `ff`), `rgb(r, g, b)`
  with integers 0-255, and the 16 basic CSS names (`gray`, not `grey`).
- Palette: `{"colors": {name: colour}, "pairs": [[fg, bg], ...]}`; names must be
  keys of `colors`. Unused colours and other keys are ignored, so tokens.json
  is its own palette and a translucent scrim token may stay in it.
- Text output: the ratio rounded to 2 decimals (4 when rounding would hide a
  failure) and pass or FAIL for AA normal 4.5, AA large 3.0, AAA normal 7.0,
  AAA large 4.5 and UI components 3.0, then a summary line. Comparisons use the
  unrounded ratio.
- `--json`: one object: `mode`, `source`, `thresholds`, `pairs` (each with
  `foreground`, `background`, `foreground_hex`, `background_hex`, `ratio`,
  `ratio_unrounded`, `aa_normal`, `aa_large`, `aaa_normal`, `aaa_large`,
  `ui_component`), `checked`, `failing_aa_normal`, `passed`.
- Exit codes: 0 every pair reaches 4.5:1; 1 a pair is below 4.5:1, including a
  border or large-text pair that only needs 3:1 (read its column); 2 bad input
  or usage, one line on stderr.
- Limits: opaque colours only (flatten a translucent colour onto its backdrop
  first); no `rgba()`, `hsl()`, `oklch()` or extended names; WCAG 2.x formula,
  not APCA; it does not know font size or weight, and does not simulate colour
  blindness.
