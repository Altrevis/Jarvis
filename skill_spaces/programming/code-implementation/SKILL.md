---
name: code-implementation
description: >-
  Implements, fixes or refactors code in an existing or new codebase: reads
  the project's conventions first, reproduces a bug with a failing test and
  fixes its root cause from evidence, makes the smallest correct change, runs
  the tests, self-reviews the diff and writes change-notes.md. Includes idioms
  for Python, JS/TS, Java, C#, Go, Rust and C/C++ and a measure-first method
  for performance. Use when asked to write, fix, debug, refactor, optimise or
  explain code. Se déclenche sur : "écris une fonction", "corrige ce bug",
  "pourquoi ça plante", "refactorise", "optimise ce code", "ajoute des tests".
---

# code-implementation
Turns a coding task into a small, tested, self-reviewed change plus
`change-notes.md`. Use it for features, bug fixes, refactors, performance work
and code explanations, in the user's code (a target folder) or in a new
project.

## Before you start
| Input | Where to find it | If missing |
|---|---|---|
| Goal and acceptance criteria | task message | derive testable criteria from the goal; list them under Decisions |
| Earlier decisions (API contracts, schemas, architecture) | handoff files named in the task | follow the task text; note the gap |
| The code | target folder | no target folder: create a project folder in the shared work folder |
| Language and version | `pyproject.toml`, `package.json` (`engines`), `go.mod`, `Cargo.toml`, `*.csproj`, `pom.xml` / `build.gradle`, `CMakeLists.txt` | new script: Python 3, standard library only |
| How tests run | `scripts` in `package.json`, `pytest.ini` or `[tool.pytest.ini_options]`, CI files, README | pytest for Python, `node --test` for JavaScript |

Never ask: make the reasonable assumption, record it under Decisions in the
handoff and in change-notes.md, and go on.

- You can run: `python3` (also `-m pytest`, `-m timeit`, `-m cProfile`),
  `pytest`, `ruff check`, `ruff format --check`, `mypy`, `node`, `npx`
  (`npx tsc --noEmit`, `npx eslint .`), `npm ci`, `npm i`, `npm test`,
  `npm run <script>`, `git init <folder>`, and git as
  `git -C "<target>" status|diff|log|show|branch|add|commit`. Run project
  commands from its folder: `cd "<target>" && python3 -m pytest -q` — except
  git: `cd ... && git` is refused, always use `git -C "<target>"`. Push, reset,
  checkout, clean, stash, `commit --amend` and `-c` options are refused.
- You cannot run: other ecosystems' compilers and build tools (`javac`, `mvn`,
  `gradle`, `dotnet`, `go`, `cargo`, `gcc`, `clang`, `make`, `cmake`),
  debuggers, GUIs. For those languages write the code and its tests, check
  them by careful reading, and give the user the command (`mvn test`,
  `./gradlew test`, `dotnet test`, `go test ./...`, `cargo test`, `ctest`).

## Method
1. **Survey, read only.** Glob the tree two levels deep. Read the README or
   CONTRIBUTING, the manifest, the lint and format config (`.editorconfig`,
   `ruff.toml` or `[tool.ruff]`, `eslint.config.*` or `.eslintrc*`,
   `.prettierrc*`, `rustfmt.toml`, `.clang-format`) and one existing test.
   Grep the symbol you will change and all its callers. Note the naming,
   error-handling, logging and test style, and the language of comments.
2. **Baseline.** In a git repository: `git -C "<target>" status --short`
   (the user's uncommitted work: keep it intact) and
   `git -C "<target>" log --oneline -n 15`. Run the
   test suite once and record what already fails, so you neither blame nor
   "fix" it by accident.
3. **Classify** the task and follow its track: bug → 4, feature → 5,
   refactor → 6, performance → 7. Explanation or review: read, then write the
   explanation or the findings in change-notes.md without changing code.
4. **Bug: evidence before edits.**
   - Reproduce: write the smallest failing test (or script) and watch it fail
     for the reported reason.
   - Read the stack trace bottom-up to the first frame in project code; read
     that code and the values reaching it.
   - List 2–3 hypotheses. For each, name the observation that would refute
     it: a logged value, an assert, a narrower test, `git -C "<target>" log -S "<text>"`
     or `git -C "<target>" log -L <start>,<end>:<file>` to see when the line changed. Run the
     cheapest observation first; drop refuted hypotheses.
   - Fix the cause, not the symptom: no blanket `try/except`, no
     `if x is None: return` that hides a broken invariant. Remove the
     temporary logging.
   - The failing test passes; run the whole suite.
5. **Feature: interface first.** Write the signature, inputs, outputs and
   error cases; write a test per acceptance criterion plus the edge cases
   below; implement until green; then tidy names and structure.
6. **Refactor: behaviour stays identical.** Tests must cover the code first;
   add characterisation tests if they don't. Move in small steps (rename,
   extract function, inline, move, replace a conditional with a lookup table)
   and run the tests after each. Never mix a behaviour change into a refactor.
7. **Performance: measure, then change.** Profile on a realistic input size
   (commands below), find the hot path, work out its big-O, fix the
   algorithm or data structure before micro-tuning, re-measure on the same
   input, and keep the change only if the gain is clear and tests still pass.
8. **Verify.** Run the tests, then the linters and type checkers the project
   already configures (`ruff check .`, `ruff format --check .`, `mypy <pkg>`,
   `npm run lint`, `npx tsc --noEmit`). Do not introduce a tool the project
   does not use. Record each command and its result.
9. **Self-review the diff** (`git -C "<target>" diff`, or re-read every changed file) with
   the checklist below; fix what it finds; run the tests again.
10. **Commit** only when the task asks for it or the repository is one you
    created: `git -C "<target>" add <file> ...` by name, one logical change per commit,
    message in the imperative ("Fix rounding of invoice totals").
11. **Write `change-notes.md`** in the shared work folder.

## Checklists

### Diff self-review
| Area | Check |
|---|---|
| Correctness | Every acceptance criterion has a test; boundaries and off-by-one cases handled |
| Naming | Names say what, not how (`retry_count`, not `n2`); the codebase's term for each concept |
| Functions | One job each; about 40 lines at most; ≤ 4 parameters or an options object |
| Error handling | Raised at the right level with context; no empty catch; resources released on every path; meaningful exit codes |
| Input validation | At every boundary (CLI args, files, network, user input): type, range, length, encoding |
| Complexity | No accidental O(n²) on data that grows; no repeated work inside loops |
| Duplication | Same logic in 3+ places: extract it; two look-alikes are not yet a pattern |
| Dead code | No commented-out code, unused imports or parameters, debug prints, ownerless TODOs |
| Security basics | Parameterised SQL; no `eval`/`exec` or `shell=True` on input; paths resolved and kept under a base folder; no `pickle` or `yaml.load` on untrusted data (`yaml.safe_load`); secrets from env; no secrets or personal data in logs |
| Comments | Explain why (constraint, trade-off, bug link), not what the code says; docstrings on public functions |
| Compatibility | Public signatures, CLI flags, file formats and config keys unchanged, or the migration is noted |
| Tests | Deterministic (no real clock, network or unseeded randomness); one behaviour each; fast |

### Edge cases to test
- Collections: empty, one item, many, duplicates, already sorted, very large.
- Numbers: 0, negative, type limits and overflow (Java, C#, Go wrap; signed
  overflow is undefined in C/C++), NaN, float rounding: money in integer
  cents or `Decimal`.
- Absent values: `None`/`null`/`undefined`, missing key, empty string.
- Text: accents and emoji (characters, not bytes), surrounding whitespace,
  case, very long lines, `\r\n` line endings.
- Time: time zones and DST changes, 29 February, end of month; UTC inside.
- Files and paths: missing, unreadable, empty, spaces or non-ASCII in names.
- Concurrency and I/O: two calls at once, timeouts, partial failure, a retry
  of an operation that already succeeded (idempotency).

### Idioms (stable across versions)
| Language | Do | Avoid |
|---|---|---|
| Python | `with` for files and locks; `pathlib`; f-strings; `enumerate`/`zip`; comprehensions for pure transforms; `dataclasses`; type hints on public functions; specific exception classes; `logging` in libraries | mutable default arguments (`def f(x=[])`); bare `except:`; `== None`; paths or SQL built by string concatenation |
| JavaScript / TypeScript | `const`, else `let`; `===`; `async`/`await` with errors handled; `?.` and `??`; TS `strict`, `unknown` plus narrowing, discriminated unions | `var`; floating promises (neither awaited nor caught); `\|\|` for defaults when `0` or `""` are valid; `any`; mutating arguments |
| Java | try-with-resources; immutable value classes or records; `Optional` as a return type only; interface types in signatures; `equals` with `hashCode`; empty collections, not `null` | catching `Exception` or `Throwable` broadly; `Optional` fields or parameters; `+=` on strings in loops (`StringBuilder`) |
| C# | `using` declarations; async all the way with a `CancellationToken`; nullable reference types enabled; records for data | `.Result` or `.Wait()` on tasks (deadlocks); `async void` outside event handlers; enumerating one LINQ query several times |
| Go | check every `err`; wrap with `fmt.Errorf("...: %w", err)` and test with `errors.Is`/`errors.As`; `defer` the close right after a successful open; `context.Context` first parameter; small consumer-side interfaces; table-driven tests; `gofmt` | discarding errors with `_`; goroutines nothing can stop; `panic` for expected errors |
| Rust | `Result` plus `?`; `&str` and `&[T]` parameters; iterators over index loops; exhaustive `match`; `clippy` clean | `unwrap()`/`expect()` on recoverable errors; `.clone()` to silence the borrow checker; `unsafe` without a `// SAFETY:` comment |
| C++ | RAII; `std::unique_ptr` via `std::make_unique`; `std::vector`, `std::string`; `const` and `const&` parameters; rule of zero | owning raw pointers with `new`/`delete`; C arrays and C-style casts; undefined behaviour (out of bounds, use after free) |
| C | check every return value (`malloc`, `fopen`, `read`); `snprintf`; `sizeof *p`; one owner frees each allocation; warnings and sanitizers on (`-Wall -Wextra -fsanitize=address,undefined`, user command) | `gets`, `strcpy`, `sprintf`; unchecked lengths; double `free` |

### Performance: measure first
| Need | Command |
|---|---|
| Time a snippet | `python3 -m timeit -s "from mod import f, sample; d = sample()" "f(d)"` (prints the best of 5 repeats) |
| Profile a script | `python3 -m cProfile -s cumtime script.py <args>` (top rows are the hot path) |
| Keep and filter a profile | `python3 -m cProfile -o prof.out script.py`, then `python3 -c "import pstats; pstats.Stats('prof.out').sort_stats('cumtime').print_stats(15)"` |
| Node.js | `node --cpu-prof script.js` writes a `.cpuprofile` (the user opens it in Chrome DevTools); `performance.now()` around the suspect code |
| Other languages | user command: JMH (Java), BenchmarkDotNet (C#), `go test -bench .`, `cargo bench` |

| Pattern in the hot path | Usual fix |
|---|---|
| `x in some_list` inside a loop: O(n·m) | build a `set` or `dict` once: O(1) average lookup |
| Nested loops joining two collections | index one side by key |
| Sorting repeatedly, or to take the top k | sort once; `heapq.nlargest(k, items)` |
| String grown with `+=` in a loop | collect parts, then `"".join(parts)` / `StringBuilder` |
| One query or HTTP call per item (N+1) | batch, join, or cache for the request |
| Same pure computation repeated | memoise with a bounded cache (`functools.lru_cache(maxsize=...)`) |
| Whole file read to process lines | stream it line by line |

Benchmark rules: realistic sizes (the user's, not 10 items); warm up JIT
runtimes (JS, Java, C#) before timing; same input and machine before and
after; prefer algorithmic gains over micro-tricks; keep readability unless the
gain is measured and needed.

## Deliverable
Code goes in the target folder when there is one; otherwise in a project
folder inside the shared work folder, with its tests and a short README. Then
write `change-notes.md` in the shared work folder. Translate the headings into
the user's language; keep code, commands and identifiers unchanged.

```markdown
# Change notes — <short title>

## Summary
<2–4 lines: what changed and why. For a bug: symptom, root cause, fix.>

## Files changed
| File | Change | Why |
|---|---|---|
| `src/invoice.py` | round each line, not the total | totals were off by one cent |

## How to run and test
From `<target folder>`:
| Check | Command | Result |
|---|---|---|
| Unit tests | `python3 -m pytest -q` | 48 passed, incl. 1 new regression test |
| Lint | `ruff check .` | clean |
| Not run (no toolchain here) | `go test ./...` | for the user |

## Decisions
| Decision | Alternatives considered | Reason |
|---|---|---|

## Risks
- <behaviour changes, compatibility, performance, data migration — or "none known">

## Next steps
- <follow-ups; work for other specialists by space id; commands for the user>
```

- Performance task: add `## Measurements` with
  `| Case | Input size | Before | After | Command |`.
- Explanation or review: replace Files changed with `## Findings`,
  `| Severity | File:line | Issue | Suggested fix |`, most severe first.

## Pitfalls
- Editing before reproducing: the "fix" matches your reading of the code, not
  the user's failing case.
- Weakening or deleting a test to turn the suite green.
- Hiding a bug: a broad catch, a default that masks `None`, a retry around a
  deterministic failure.
- Reformatting or renaming untouched code, which buries the real change in
  the diff.
- Writing "tests pass" when they were not run (no toolchain, refused
  command): write "not run" and the command.
- Adding a dependency for something the standard library does, or not
  pinning it the way the project pins the others.
- `git add -A` or `git add .` in the user's repository: it sweeps in their
  unrelated work and stray files such as `.env`.
- Optimising without a profile, or benchmarking a toy input.
- Leaving debug prints, commented-out code or temporary files behind.
- Changing a public signature or output format inside a "refactor".
