---
name: data-analysis
description: >-
  Analyses a dataset end to end: frames the question, profiles the data with
  a bundled CSV profiler, cleans it in a script with a logged rule per change,
  computes descriptive statistics, group-bys, trends and distributions with
  sample sizes, chooses charts by question, designs idempotent ETL/ELT loads
  with data-quality checks, and writes a reproducible analysis.py and
  data-report.md. Use for CSV or Excel analysis, cleaning, KPIs, dashboards or
  a data pipeline. Se déclenche sur : analyse de données, nettoyage de
  données, fichier CSV, statistiques, tableau de bord, graphique, KPI,
  pipeline de données, ETL.
---

# data-analysis
Produces `analysis.py` (reproduces every number from the raw files) and
`data-report.md` (question, data, cleaning log, findings, charts or tables,
limitations). For a pipeline task, the load script and its quality checks.

## Before you start
| Input | Where | If missing |
|---|---|---|
| The question and the decision | task, handoffs | write the question you answer; record it |
| Data files | target folders, task paths | stop at the plan: list the data needed under For the user |
| Meaning of columns, units | data dictionary, README, column names | infer and mark as assumption |
| Period, population, filters | task | the whole file; say so |
| Tools available | `python3 -c "import pandas, matplotlib"` | standard library (`csv`, `statistics`) and Markdown tables |

Excel files: the agent cannot read `.xlsx` with the standard library; convert
with `soffice --headless --convert-to csv <file> --outdir <work folder>` when
LibreOffice is installed, or use pandas with openpyxl if they import.

## Method
1. **Frame**: the question, the metric that answers it (definition, unit,
   numerator and denominator), the comparison (over time, between groups,
   against a target).
2. **Profile** each input:
   `python3 .claude/skills/data-analysis/profile_csv.py "<file>" --json`.
   Read types, empty %, distinct counts, notes (mixed date formats, decimal
   commas, leading zeros, mojibake, duplicates, ragged rows).
3. **Plan the cleaning** from the profile; one rule per problem (checklist).
4. **Write `analysis.py`** in the shared work folder: read the raw files,
   apply the rules in order, print each rule's row counts, compute every
   figure, write tables (CSV) and charts (PNG) next to the report. Fixed
   random seeds if anything is sampled.
5. **Run it**: `cd "<work folder>" && python3 analysis.py`. Fix until it runs
   clean; copy the printed numbers into the report — never retype them.
6. **Analyse**: distributions first (median and quartiles for skewed data),
   then group comparisons with counts, then trends (same period lengths,
   seasonality noted). A difference between groups smaller than the noise is
   reported as "no clear difference", with the group sizes.
7. **Charts** by question (table below); when matplotlib is missing, Markdown
   tables instead.
8. **Write `data-report.md`**.
9. **Pipeline tasks**: design extract → validate → transform → load with the
   engineering checklist, write the script and a test run on a sample.

## Checklists

### Cleaning log — one row per rule
| Problem (from the profile) | Typical rule |
|---|---|
| Types: numbers as text, decimal commas, thousands separators, currency symbols | parse to numbers; keep the unit in the column name |
| Missing values (`""`, NA, N/A, null, -) | leave missing, impute (say how) or drop rows — decide per column and count |
| Duplicates | define the key; drop exact duplicates; investigate near-duplicates |
| Dates: mixed formats, dd/mm vs mm/dd, time zones | one format (ISO 8601), one zone (UTC or the business's), ambiguous values flagged |
| Categories: spelling, case, accents, spaces | trim, normalise case, map variants to one label |
| Outliers | check against reality (a 300-year-old customer is an error; a large order may be real); never drop without a rule |
| Identifiers with leading zeros (postcodes, SIRET) | keep as text |
| Encoding problems (`CafÃ©`) | re-read with the right encoding |

### Analysis
- Report n next to every percentage and mean.
- Mean and standard deviation for symmetric data; median and IQR otherwise.
- Compare like with like: same period length, same population definition.
- Correlation is not causation; name plausible confounders.
- Rates over counts when group sizes differ.
- Small groups (n < 30) flagged as fragile.

### Charts
| Question | Chart | Rules |
|---|---|---|
| Compare categories | bar (horizontal when labels are long) | zero baseline, sorted by value |
| Trend over time | line | regular time axis, one line per series, ≤ 5 series |
| Distribution | histogram or box plot | state the bin width |
| Relationship | scatter | both units on axes; trend line only if meaningful |
| Part of a whole | stacked bar; pie only for ≤ 5 slices | percentages sum to 100 |
Title says the finding ("Sales rose 12 % in Q3"), not the variable.

### Pipeline engineering
| Item | Rule |
|---|---|
| ETL vs ELT | transform before loading (ETL) for small, controlled targets; load raw then transform in the warehouse (ELT) for analytics |
| Idempotency | a run for the same period replaces, not appends (upsert on a key, or delete-then-insert per partition) |
| Incremental loads | watermark column (updated_at) or change data capture; full reload as a fallback |
| Validation before load | schema (columns, types), row count within expected range, nulls in required columns, unique keys, referential integrity |
| Observability | log rows read, rejected, loaded; rejected rows kept in a quarantine file |

## Deliverable
In the shared work folder: `analysis.py`, `data-report.md`, and the charts
(`fig-01-<topic>.png`) or tables it writes. Translate the headings into the
user's language:

```markdown
# Data report — <question>
## Summary
<3 findings with their numbers and n>
## Question and metric
## Data
| File | Rows | Columns | Period | Source |
## Cleaning log
| # | Rule | Why | Rows affected |
## Findings
### 1. <finding as a sentence>
<number, n, chart or table>
## Limitations
## Decisions
## Next steps
<how to rerun: `python3 analysis.py`; data the user should add>
```

## Pitfalls
- Cleaning by hand in the file: nobody can reproduce or audit it.
- Percentages without their base; averages of averages over unequal groups.
- Reading dd/mm/yyyy as mm/dd/yyyy (the profiler flags ambiguous columns).
- Dropping rows with missing values without counting them.
- Truncated bar axes that exaggerate differences.
- Treating postcodes or IDs as numbers and losing leading zeros.
- A pipeline that appends on every rerun and doubles the data.
- Reporting numbers typed from memory instead of the script's output.

## Tool
`profile_csv.py` — standard library only, read-only, deterministic.

```
python3 .claude/skills/data-analysis/profile_csv.py <file.csv> [--delimiter X] [--encoding E] [--max-rows N] [--json]
```
- Detects the encoding (UTF-8 with or without BOM, then cp1252, then latin-1)
  and the delimiter (`,` `;` tab `|`); both can be forced.
- Per column: type (integer, decimal — decimal comma accepted when the
  delimiter is not a comma —, boolean, date, text, empty), non-empty and empty
  counts and %, distinct values, examples; min, max, mean, median and sample
  standard deviation for numbers; min and max for dates; top 5 values and
  lengths for text; notes for the cleaning log.
- Dataset: rows, columns, duplicate rows, empty rows and columns, ragged rows
  with line numbers, header problems, likely mojibake.
- `--json` prints one object (per-column details under `column_profiles`).
- Exit 0 profile printed (also for a header-only file), 2 usage or input
  error (missing, empty, binary or XLSX file, undecodable, malformed CSV).
- Limits: keeps distinct values in memory — use `--max-rows` on very large
  files; formats such as dd-mm-yyyy or two-digit years are typed as text.
