---
name: test-strategy
description: >-
  Plans, writes and runs tests: a risk-based strategy, the test pyramid, a
  test plan with entry and exit criteria, case design by equivalence
  partitions, boundary values, decision tables, state transitions and
  pairwise, deterministic unit tests (AAA, fakes), integration and contract
  tests, Playwright end-to-end tests with role locators and no sleeps, flaky
  test hygiene, coverage as a signal, load test basics with SLOs, and bug
  reports. Use to test an app or write a test plan. Se déclenche sur : tests
  unitaires, plan de test, recette, tests end-to-end, Playwright, pytest,
  couverture de code, rapport de bug, non-régression.
---

# test-strategy
Produces tests in the target folder and `test-report.md` (scope, cases,
results as run, coverage, bugs, risks left); or `test-plan.md` when the task
is planning only.

## Before you start
| Input | Where | If missing |
|---|---|---|
| Requirements, acceptance criteria | task, handoffs, `features.csv`, user stories | derive criteria from the feature; record them |
| Code under test | target folders | plan only: `test-plan.md` |
| Test framework and command | `package.json` scripts, `pytest.ini`/`pyproject.toml`, existing tests | pytest for Python, Vitest or Jest for JS/TS, Playwright for end-to-end |
| Environments | README, compose files | local only; anything else goes to For the user |
| Known bugs, flaky tests | issues, CI logs in the target | none known |

## Method
1. **Risks**: list features × what can go wrong; rate impact and likelihood
   (1–3 each); test the highest products first and say what is not tested.
2. **Levels** (pyramid): business rules and edge cases → unit tests; module
   boundaries, database, external APIs → integration and contract tests; the
   3–5 journeys that make money or lose data → end-to-end.
3. **Design cases** with the techniques below; write them as a table before
   coding (input, expected result, technique).
4. **Baseline**: run the existing suite once and record its state
   (`cd "<target>" && python3 -m pytest -q`, `npm test`).
5. **Write tests** in the project's style: Arrange-Act-Assert, one behaviour
   each, fakes over deep mocks, fixtures for setup, parametrised cases for
   tables.
6. **Run**, read every failure: product bug (report it), test bug (fix the
   test), environment (note it).
7. **Coverage** when the tool is there (`python3 -m pytest --cov` with
   pytest-cov, `npx vitest run --coverage`, `npx jest --coverage`): read
   uncovered branches in critical code, not the global percentage.
8. **End-to-end** with Playwright when installed (`npx playwright test`);
   browsers may be missing: then write the tests and list
   `npx playwright install` For the user.
9. **Write `test-report.md`** (and bug reports).

## Checklists

### Case design techniques
| Technique | Use when | Example |
|---|---|---|
| Equivalence partitioning | ranges and categories | age: <0 invalid, 0–17 minor, 18+ adult — one case per class |
| Boundary values | limits | 17, 18, 19; max length 255 and 256 |
| Decision table | combined conditions | member × coupon × total > 50 → discount |
| State transitions | workflows | order: created → paid → shipped; forbidden: shipped → paid |
| Pairwise | many parameters | browser × OS × locale: cover every pair, not every combination |
| Error guessing | known weak spots | empty input, unicode, duplicate submit, timeout, retry |

### Unit tests
- Deterministic: inject the clock and randomness; no network; temp dirs for
  files.
- Fast: milliseconds each; the suite runs on every change.
- Assert behaviour and outputs, not private implementation details.
- Mocks only at boundaries you own; prefer fakes (in-memory repository).
- Each bug fixed gets a regression test that failed before the fix.

### Integration and contract
- Real database engine in a container (user command) or SQLite when the SQL
  is portable; transactions rolled back between tests.
- External HTTP APIs: a local fake server or recorded responses; contract
  tests on the request/response shape both sides agree on.

### End-to-end (Playwright)
- Locators: `getByRole`, `getByLabel`, `getByTestId`; no XPath or deep CSS.
- Web-first assertions (`await expect(locator).toBeVisible()`), never
  `waitForTimeout`.
- Each test creates its own data and cleans up; tests run in any order.
- Traces and screenshots on failure; retries only to diagnose, never to hide
  flakiness.

### Flaky tests
Causes: timing and fixed sleeps, shared state or order dependence, real time
and time zones, network, randomness, resource leaks. Quarantine with a
ticket; fix the cause; never just add retries.

### Performance and load (plan)
Define SLOs first (e.g. p95 latency < 300 ms at 50 requests/s, error rate
< 1 %); scenarios: ramp-up, steady state, spike, soak; tools: k6 or Locust;
report p50/p95/p99, throughput, errors, saturation. Run by the user against
an environment they own.

### Code review for testability
Pure functions for logic; dependencies injected; side effects at the edges;
clear error types; no hidden global state.

## Deliverable
Tests in the target folder. In the shared work folder, `test-report.md`
(translate the headings into the user's language):

```markdown
# Test report — <system / feature>
## Summary
<what was tested, pass/fail counts, the most serious bug, main untested risk>
## Scope and risks
| Feature | Risk | Impact | Likelihood | Tested at level |
## Traceability
| Acceptance criterion | Tests |
## Results (as run)
| Suite | Command | Passed | Failed | Skipped | Duration |
## Coverage
## Bugs found
### BUG-01 — <title>
Severity: … · Priority: … · Environment: …
Steps to reproduce: 1. … 2. …
Expected: … · Actual: … · Evidence: <test name, output>
## Not tested and why
## Decisions
## Next steps
```

## Pitfalls
- Reporting tests as passing when they were not run (no browser, refused
  command): write "not run" with the command.
- Testing implementation details so every refactor breaks the suite.
- Fixed sleeps and order-dependent tests.
- 100 % line coverage as a goal while critical branches stay untested.
- End-to-end tests for every edge case: slow, flaky, and they still miss logic
  bugs that unit tests catch.
- "Fixing" a failing test by changing its expectation without checking the
  product is right.
- Severity (impact) confused with priority (order of fixing).
