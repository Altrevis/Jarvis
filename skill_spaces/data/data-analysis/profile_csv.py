#!/usr/bin/env python3
"""Profile a CSV file before cleaning or analysing it.

Standard library only, read-only, no network, deterministic. Bundled with the
data-analysis skill of the Jarvis "data" space.

Usage
  python3 profile_csv.py data.csv
  python3 profile_csv.py data.csv --json
  python3 profile_csv.py export.csv --delimiter ";" --encoding cp1252
  python3 profile_csv.py big.csv --max-rows 200000 --json

Detection
  encoding   utf-8 (reported as utf-8-sig when the file starts with a BOM),
             then cp1252, then latin-1; a UTF-16 BOM is honoured.
             --encoding forces one.
  delimiter  csv.Sniffer on the first 64 KiB, limited to , ; tab |; if it
             cannot decide, the candidate that splits the header into the most
             fields. --delimiter forces one ("tab" or "\\t" for a tab).

Per column
  type       integer, decimal, boolean, date, text, or empty (no values).
             decimal accepts a comma separator (3,14) when the delimiter is
             not a comma. boolean = true/false/yes/no/oui/non/0/1 (any case),
             only when the column is not numeric: a 0/1 column is integer.
             date = yyyy-mm-dd, dd/mm/yyyy, yyyy-mm-dd hh:mm:ss (a T separator,
             no seconds, fractional seconds and a Z or +hh:mm offset are also
             accepted). A column gets a type only when every non-empty value
             matches it; otherwise it is text, with a "mostly <type>" note.
  counts     non-empty, empty and empty % (empty = "", NA, N/A, null, None,
             NaN, -; any case, surrounding spaces ignored), distinct values,
             3 example values.
  stats      numbers: min, max, mean, median, sample standard deviation;
             dates: min, max; text and booleans: top 5 values with counts,
             min and max length.
  notes      hints for the cleaning log: surrounding spaces, case or accent
             variants, values that block a type, leading zeros, long
             identifiers, digit-group separators, units and currency symbols,
             mixed date formats, ambiguous day/month, US dates, time zones.
Dataset
  rows, columns, duplicate rows, entirely empty rows and columns, ragged rows
  (field count differs from the header, with line numbers), blank lines
  skipped, header problems, likely mojibake (text decoded with the wrong
  encoding upstream, e.g. "CafÃ©").

Exit codes
  0  profile printed (also for a header-only file: 0 rows)
  2  usage or input error: path missing or not a file, empty file, binary or
     XLSX file, undecodable with --encoding, malformed CSV, bad option value

Limitations
  Keeps a counter of distinct values per column in memory: use --max-rows on
  very large files (the profile then covers the first N data rows only).
  "NA" counts as empty although it is also Namibia's country code. Other date
  formats (dd-mm-yyyy, mm/dd/yyyy, 2-digit years) are typed as text. Line
  numbers are those where a record ends (quoted fields may span lines).
"""

import argparse
import codecs
import csv
import hashlib
import json
import math
import re
import sys
import unicodedata
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

SAMPLE_BYTES = 64 * 1024
CANDIDATE_DELIMITERS = [",", ";", "\t", "|"]
EMPTY_MARKERS = {"", "na", "n/a", "null", "none", "nan", "-"}
BOOL_TOKENS = {"true", "false", "yes", "no", "oui", "non", "0", "1"}
MOSTLY = 0.8          # share of non-empty rows that makes a "mostly <type>" note
TOP_N = 5
EXAMPLES = 3

INT_RE = re.compile(r"[+-]?\d+\Z")
DEC_DOT_RE = re.compile(r"[+-]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?\Z")
DEC_COMMA_RE = re.compile(r"[+-]?\d*,\d+\Z")
GROUPED_RE = re.compile(
    r"[+-]?(?:\d{1,3}(?:[ \u00a0\u202f]\d{3})+(?:[.,]\d+)?"   # 1 234,56
    r"|\d{1,3}(?:,\d{3})+(?:\.\d+)?"                          # 1,234.56
    r"|\d{1,3}(?:\.\d{3})+(?:,\d+)?)\Z")                      # 1.234,56
LEADING_ZERO_RE = re.compile(r"[+-]?0\d")
ISO_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})\Z")
DMY_RE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})\Z")
ISO_DT_RE = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2})(?:[.,](\d{1,9}))?)?"
    r"(Z|[+-]\d{2}:?\d{2})?\Z")
# UTF-8 bytes shown through cp1252/latin-1: "Ã©" for "é", "â€™" for "'", "Â°" for "°"
MOJIBAKE_RE = re.compile(
    "\u00c3[\u0080-\u00bf\u0152\u0153\u0160\u0161\u0178\u017d\u017e\u0192\u02c6"
    "\u02dc\u2013\u2014\u2018-\u201e\u2020-\u2022\u2026\u2030\u2039\u203a\u20ac\u2122]"
    "|\u00e2\u20ac|\u00c2[\u00a0-\u00bf]")
SYMBOL_CHARS = "%\u20ac$\u00a3 \u00a0\u202f"   # % € $ £ and spaces


class InputError(Exception):
    """Bad input: reported as one line on stderr, exit 2."""


class DecodeFailure(Exception):
    def __init__(self, encoding, line):
        Exception.__init__(self, encoding)
        self.encoding = encoding
        self.line = line


class Parser(argparse.ArgumentParser):
    def error(self, message):
        sys.stderr.write("%s: error: %s (see --help)\n" % (self.prog, message))
        sys.exit(2)


# ---------------------------------------------------------------- parsing values

def parse_number(s, comma_decimal):
    """Return (kind, value, decimal_separator) or None."""
    if INT_RE.match(s):
        if len(s) > 300:
            return None
        return ("int", int(s), None)
    if DEC_DOT_RE.match(s):
        v = float(s)
        return ("dec", v, "." if "." in s else None) if math.isfinite(v) else None
    if comma_decimal and DEC_COMMA_RE.match(s):
        v = float(s.replace(",", "."))
        return ("dec", v, ",") if math.isfinite(v) else None
    return None


def numberish(s):
    """True for numbers that only fail because of separators (1 234,56 / 3,14)."""
    return bool(GROUPED_RE.match(s) or DEC_COMMA_RE.match(s))


def parse_date(s):
    """Return (format, sort_key, utc_offset_or_None) or None."""
    try:
        m = ISO_DATE_RE.match(s)
        if m:
            y, mo, d = (int(x) for x in m.groups())
            return ("yyyy-mm-dd", datetime(y, mo, d), None)
        m = DMY_RE.match(s)
        if m:
            d, mo, y = (int(x) for x in m.groups())
            return ("dd/mm/yyyy", datetime(y, mo, d), None)
        m = ISO_DT_RE.match(s)
        if m:
            y, mo, d, hh, mi = (int(m.group(i)) for i in range(1, 6))
            ss = int(m.group(6) or 0)
            frac = m.group(7) or ""
            micro = int((frac + "000000")[:6]) if frac else 0
            dt = datetime(y, mo, d, hh, mi, ss, micro)
            tz = m.group(8)
            if tz:
                if tz == "Z":
                    minutes = 0
                else:
                    digits = tz[1:].replace(":", "")
                    oh, om = int(digits[:2]), int(digits[2:])
                    if oh > 23 or om > 59:
                        return None
                    minutes = (oh * 60 + om) * (1 if tz[0] == "+" else -1)
                dt = dt - timedelta(minutes=minutes)   # sort key in UTC
            return ("yyyy-mm-dd hh:mm:ss", dt, tz)
    except (ValueError, OverflowError):
        return None
    return None


def is_us_date(s):
    """dd/mm/yyyy fails but mm/dd/yyyy works (e.g. 03/15/2024)."""
    m = DMY_RE.match(s)
    if not m:
        return False
    a, b, y = (int(x) for x in m.groups())
    try:
        datetime(y, b, a)
        return False
    except ValueError:
        pass
    try:
        datetime(y, a, b)
        return True
    except ValueError:
        return False


def fold(s):
    """Key that ignores case, accents and repeated spaces."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return " ".join(s.casefold().split())


def is_empty(value):
    return value.strip().lower() in EMPTY_MARKERS


# ---------------------------------------------------------------- reading the file

def parse_delimiter_option(value):
    aliases = {"tab": "\t", "\\t": "\t", "comma": ",", "semicolon": ";", "pipe": "|", "space": " "}
    v = aliases.get(value.lower(), value) if len(value) > 1 else value
    if len(v) != 1 or v in ('"', "\r", "\n"):
        raise InputError("--delimiter must be one character or 'tab', got %r" % value)
    return v


def sniff_delimiter(sample_text):
    lines = [ln for ln in sample_text.splitlines() if ln.strip()]
    if not lines:
        return ",", "default"
    try:
        found = csv.Sniffer().sniff("\n".join(lines[:200]), delimiters="".join(CANDIDATE_DELIMITERS))
        if found.delimiter in CANDIDATE_DELIMITERS:
            return found.delimiter, "sniffed"
    except csv.Error:
        pass
    best, best_n = ",", 1
    for cand in CANDIDATE_DELIMITERS:
        n = len(next(csv.reader([lines[0]], delimiter=cand)))
        if n > best_n:
            best, best_n = cand, n
    return best, "fallback"


def encoding_candidates(sample, forced):
    if forced:
        try:
            name = codecs.lookup(forced).name
        except LookupError:
            raise InputError("unknown encoding: %s" % forced)
        if name == "utf-8" and sample.startswith(codecs.BOM_UTF8):
            return [("utf-8-sig", "given")]
        return [(forced, "given")]
    if sample.startswith(codecs.BOM_UTF8):
        return [("utf-8-sig", "bom"), ("cp1252", "fallback"), ("latin-1", "fallback")]
    if sample.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return [("utf-16", "bom")]
    if sample.startswith(b"PK\x03\x04"):
        raise InputError("this is a ZIP container (an .xlsx/.ods file?), not a CSV: convert it to CSV first")
    if b"\x00" in sample:
        raise InputError("binary content (NUL bytes): not a CSV text file "
                         "(for UTF-16 without a BOM pass --encoding utf-16-le)")
    return [("utf-8", "detected"), ("cp1252", "fallback"), ("latin-1", "fallback")]


def read_table(path, sample, encoding, delimiter, max_rows):
    sample_text = sample.decode(encoding, errors="replace").lstrip("\ufeff")
    if len(sample) == SAMPLE_BYTES and "\n" in sample_text:
        sample_text = sample_text[:sample_text.rfind("\n")]
    if delimiter is None:
        delimiter, dsource = sniff_delimiter(sample_text)
    else:
        dsource = "given"

    t = {"delimiter": delimiter, "delimiter_source": dsource, "header": None, "rows": 0,
         "blank": 0, "empty_rows": 0, "ragged": 0, "ragged_examples": [], "duplicates": 0,
         "truncated": False, "counters": [], "empties": [], "markers": []}
    seen = set()
    reader = None
    try:
        with open(str(path), "r", encoding=encoding, errors="strict", newline="") as fh:
            reader = csv.reader(fh, delimiter=delimiter)
            for record in reader:
                if not record or (len(record) == 1 and not record[0].strip()):
                    t["blank"] += 1
                    continue
                if t["header"] is None:
                    t["header"] = record
                    n = len(record)
                    t["counters"] = [Counter() for _ in range(n)]
                    t["empties"] = [0] * n
                    t["markers"] = [Counter() for _ in range(n)]
                    continue
                if max_rows is not None and t["rows"] >= max_rows:
                    t["truncated"] = True
                    break
                t["rows"] += 1
                ncols = len(t["header"])
                if len(record) != ncols:
                    t["ragged"] += 1
                    if len(t["ragged_examples"]) < 5:
                        t["ragged_examples"].append({"line": reader.line_num, "fields": len(record)})
                digest = hashlib.blake2b(repr(record).encode("utf-8", "surrogatepass"), digest_size=8).digest()
                if digest in seen:
                    t["duplicates"] += 1
                else:
                    seen.add(digest)
                if all(is_empty(v) for v in record):
                    t["empty_rows"] += 1
                for i in range(ncols):
                    v = record[i] if i < len(record) else ""
                    if is_empty(v):
                        t["empties"][i] += 1
                        t["markers"][i][v.strip()] += 1
                    else:
                        t["counters"][i][v] += 1
    except UnicodeDecodeError:
        raise DecodeFailure(encoding, (reader.line_num + 1) if reader is not None else 1)
    except csv.Error as exc:
        line = reader.line_num if reader is not None else 0
        hint = " (an unclosed quote?)" if "field larger" in str(exc) else ""
        raise InputError("malformed CSV near line %d: %s%s" % (line, exc, hint))
    except OSError as exc:
        raise InputError("cannot read %s: %s" % (path, exc.strerror or exc))
    return t


# ---------------------------------------------------------------- statistics

def number_stats(values):
    """values: dict number -> count. Returns min, max, mean, median, stdev."""
    items = sorted(values.items())
    n = sum(c for _, c in items)

    def at(k):  # k-th value (0-based) in sorted order, counting repeats
        seen = 0
        for v, c in items:
            seen += c
            if k < seen:
                return v
        return items[-1][0]

    mean = median = stdev = None
    try:
        mean = math.fsum(float(v) * c for v, c in items) / n
        median = at(n // 2) if n % 2 else (at(n // 2 - 1) + at(n // 2)) / 2
        if n > 1:
            var = math.fsum(c * (float(v) - mean) ** 2 for v, c in items) / (n - 1)
            stdev = math.sqrt(var)
    except OverflowError:
        pass
    return items[0][0], items[-1][0], mean, median, stdev


def rounded(x):
    if isinstance(x, float):
        return round(x, 6)
    return x


def quote(v, width=24):
    s = str(v).replace("\r", "\\r").replace("\n", "\\n").replace("\t", "\\t")
    if len(s) > width:
        s = s[:width - 3] + "..."
    return "'%s'" % s


def profile_column(index, name, counter, empty, markers, rows, comma_decimal):
    nonempty = sum(counter.values())
    col = {"index": index, "name": name, "type": "empty", "non_empty": nonempty, "empty": empty,
           "empty_pct": round(100.0 * empty / rows, 1) if rows else None,
           "distinct": len(counter), "examples": list(counter)[:EXAMPLES],
           "empty_markers": dict(sorted(markers.items(), key=lambda kv: (-kv[1], kv[0]))),
           "min": None, "max": None, "mean": None, "median": None, "stdev": None,
           "top": None, "min_length": None, "max_length": None, "notes": []}
    notes = col["notes"]
    if [k for k in markers if k]:
        notes.append("empty values written as " + ", ".join(
            "%s (%d)" % (quote(k), c) for k, c in sorted(markers.items(), key=lambda kv: (-kv[1], kv[0]))))
    if nonempty == 0:
        return col

    all_num = all_int = all_bool = all_date = True
    num_rows = bool_rows = date_rows = 0
    numbers, dec_sep = {}, Counter()
    dates, date_formats, offsets = [], Counter(), Counter()
    naive_dt = dmy_rows = dmy_day_gt12 = us_rows = 0
    spaces = lead0 = long_ids = sep_rows = sym_rows = 0
    parsed = []   # (raw, count, is_number, is_date, is_boolean)
    for raw, c in counter.items():
        s = raw.strip()
        if s != raw:
            spaces += c
        num = parse_number(s, comma_decimal)
        if num is None:
            all_num = all_int = False
            core = s.strip(SYMBOL_CHARS)
            if core != s and core and (parse_number(core, comma_decimal) or numberish(core)):
                sym_rows += c
            elif numberish(s):
                sep_rows += c
        else:
            num_rows += c
            kind, value, sep = num
            if kind != "int":
                all_int = False
            if sep:
                dec_sep[sep] += c
            numbers[value] = numbers.get(value, 0) + c
            if kind == "int" and LEADING_ZERO_RE.match(s):
                lead0 += c
            if kind == "int" and len(s.lstrip("+-")) > 15:
                long_ids += c
        if s.lower() in BOOL_TOKENS:
            bool_rows += c
        else:
            all_bool = False
        d = parse_date(s)
        if d is None:
            all_date = False
            if is_us_date(s):
                us_rows += c
        else:
            fmt, key, tz = d
            date_rows += c
            date_formats[fmt] += c
            dates.append((key, raw))
            if fmt == "dd/mm/yyyy":
                dmy_rows += c
                if int(DMY_RE.match(s).group(1)) > 12:
                    dmy_day_gt12 += c
            if fmt.endswith("ss"):
                if tz:
                    offsets["+00:00" if tz == "Z" else tz] += c
                else:
                    naive_dt += c
        parsed.append((raw, c, num is not None, d is not None, s.lower() in BOOL_TOKENS))

    if all_num:
        col["type"] = "integer" if all_int else "decimal"
    elif all_bool:
        col["type"] = "boolean"
    elif all_date:
        col["type"] = "date"
    else:
        col["type"] = "text"
    typ = col["type"]

    if typ in ("integer", "decimal"):
        lo, hi, mean, median, stdev = number_stats(numbers)
        col.update({"min": lo, "max": hi, "mean": rounded(mean), "median": rounded(median),
                    "stdev": rounded(stdev)})
    elif typ == "date":
        dates.sort()
        col["min"], col["max"] = dates[0][1], dates[-1][1]
    if typ in ("text", "boolean"):
        ranked = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
        col["top"] = [[v, c] for v, c in ranked[:TOP_N]]
        lengths = [len(v) for v in counter]
        col["min_length"], col["max_length"] = min(lengths), max(lengths)

    # ---- notes for the cleaning log
    if spaces:
        notes.append("%d values have leading/trailing spaces" % spaces)
    if typ in ("text", "boolean"):
        groups = {}
        for raw, c in counter.items():
            groups.setdefault(fold(raw), []).append((raw, c))
        multi = [g for g in groups.values() if len(g) > 1]
        if multi:
            multi.sort(key=lambda g: (-sum(c for _, c in g), fold(g[0][0])))
            shown = ["/".join(quote(v, 18) for v, _ in sorted(g, key=lambda vc: (-vc[1], vc[0]))[:3])
                     for g in multi[:3]]
            notes.append("%d groups of values differ only by case, accents or spaces: %s"
                         % (len(multi), "; ".join(shown)))
    if typ == "text":
        kinds = [("numeric", num_rows, 2), ("date", date_rows, 3), ("boolean", bool_rows, 4)]
        label, best_rows, flag = max(kinds, key=lambda k: k[1])
        share = best_rows / float(nonempty)
        if best_rows and share >= MOSTLY:
            bad = sorted([(p[0], p[1]) for p in parsed if not p[flag]], key=lambda vc: (-vc[1], vc[0]))
            notes.append("mostly %s (%.0f%% of values): %d values do not parse, e.g. %s"
                         % (label, 100 * share, nonempty - best_rows,
                            ", ".join(quote(v, 18) for v, _ in bad[:3])))
        if sep_rows:
            notes.append("%d values are numbers written with digit-group or comma separators "
                         "(e.g. '1 234,56', '3,14'): normalise before converting" % sep_rows)
        if sym_rows:
            notes.append("%d values carry a unit or currency symbol (%% € $ £): "
                         "move it to the column name or a unit column" % sym_rows)
    if typ == "integer" and lead0:
        notes.append("%d values have leading zeros: probably a code (postcode, id), keep as text" % lead0)
    if typ == "integer" and long_ids:
        notes.append("%d values have more than 15 digits: identifiers, not quantities "
                     "(Excel keeps 15 significant digits)" % long_ids)
    if typ in ("integer", "decimal") and len(dec_sep) > 1:
        notes.append("mixed decimal separators: %d with ',' and %d with '.'" % (dec_sep[","], dec_sep["."]))
    if date_rows and date_rows >= 0.5 * nonempty:
        if len(date_formats) > 1:
            notes.append("mixed date formats: " + ", ".join(
                "%s (%d)" % (f, c) for f, c in sorted(date_formats.items(), key=lambda kv: (-kv[1], kv[0]))))
        if dmy_rows and not dmy_day_gt12:
            notes.append("dd/mm/yyyy cannot be confirmed: no day above 12, the source may be mm/dd/yyyy")
        if offsets and naive_dt:
            notes.append("time zones mixed: %d datetimes with a UTC offset, %d without"
                         % (sum(offsets.values()), naive_dt))
        if len(offsets) > 1:
            notes.append("several UTC offsets (%s): convert to UTC before comparing"
                         % ", ".join(sorted(offsets)[:4]))
    if us_rows:
        notes.append("%d values only parse as mm/dd/yyyy (US order), not dd/mm/yyyy" % us_rows)
    return col


# ---------------------------------------------------------------- report

def build_report(path, args):
    if not path.exists():
        raise InputError("no such file: %s" % path)
    if not path.is_file():
        raise InputError("not a file: %s" % path)
    if args.max_rows is not None and args.max_rows < 1:
        raise InputError("--max-rows must be 1 or more")
    delimiter = parse_delimiter_option(args.delimiter) if args.delimiter is not None else None
    try:
        with open(str(path), "rb") as fh:
            sample = fh.read(SAMPLE_BYTES)
    except OSError as exc:
        raise InputError("cannot read %s: %s" % (path, exc.strerror or exc))
    if not sample:
        raise InputError("%s is empty (0 bytes)" % path)

    candidates = encoding_candidates(sample, args.encoding)
    failures, table, used = [], None, None
    for enc, source in candidates:
        try:
            table = read_table(path, sample, enc, delimiter, args.max_rows)
            used = (enc, source)
            break
        except DecodeFailure as fail:
            failures.append("not valid %s near line %d" % (fail.encoding, fail.line))
    if table is None:
        raise InputError("cannot decode %s: %s; try another --encoding" % (path, "; ".join(failures)))
    if table["header"] is None:
        raise InputError("%s has no header row (only blank lines)" % path)

    header = list(table["header"])
    notes = []
    for prefix in ("\ufeff", "\u00ef\u00bb\u00bf"):
        if header[0].startswith(prefix):
            header[0] = header[0][len(prefix):]
            if prefix != "\ufeff":
                notes.append("a UTF-8 BOM was read as text: the file is probably UTF-8 with a few invalid bytes")
    rows = table["rows"]
    comma_decimal = table["delimiter"] != ","
    columns = [profile_column(i + 1, header[i], table["counters"][i], table["empties"][i],
                              table["markers"][i], rows, comma_decimal) for i in range(len(header))]

    issues = []
    names = Counter(h.strip() for h in header)
    for h, c in sorted(names.items()):
        if h and c > 1:
            issues.append("duplicate column name %s (%d times)" % (quote(h), c))
    for i, h in enumerate(header, 1):
        if not h.strip():
            issues.append("column %d has no name" % i)
        elif h != h.strip():
            issues.append("column %d name %s has surrounding spaces" % (i, quote(h)))
    named = [h.strip() for h in header if h.strip()]
    if named and all(parse_number(h, comma_decimal) or parse_date(h) for h in named):
        issues.append("the header looks like data: the file may have no header row")

    moji = sum(c for counter in table["counters"] for raw, c in counter.items() if MOJIBAKE_RE.search(raw))
    moji += sum(1 for h in header if MOJIBAKE_RE.search(h))
    if moji:
        example = next((raw for counter in table["counters"] for raw in counter if MOJIBAKE_RE.search(raw)),
                       next((h for h in header if MOJIBAKE_RE.search(h)), ""))
        notes.append("%d cells look like mojibake (e.g. %s): text was decoded with the wrong encoding upstream"
                     % (moji, quote(example)))
    if rows == 0:
        notes.append("header only: no data rows")

    return {
        "file": str(path),
        "encoding": used[0],
        "encoding_source": used[1],
        "encoding_note": "; ".join(failures) or None,
        "delimiter": table["delimiter"],
        "delimiter_source": table["delimiter_source"],
        "rows": rows,
        "columns": len(header),
        "truncated": table["truncated"],
        "max_rows": args.max_rows,
        "duplicate_rows": table["duplicates"],
        "empty_rows": table["empty_rows"],
        "blank_lines_skipped": table["blank"],
        "ragged_rows": table["ragged"],
        "ragged_examples": table["ragged_examples"],
        "empty_columns": [c["name"] for c in columns if c["type"] == "empty"] if rows else [],
        "header_issues": issues,
        "notes": notes,
        "column_profiles": columns,
    }


def fmt_num(x):
    if x is None:
        return ""
    if isinstance(x, int):
        return str(x)
    if x != 0 and (abs(x) >= 1e12 or abs(x) < 1e-3):
        return "%.4g" % x
    s = ("%.4f" % x).rstrip("0").rstrip(".")
    return "0" if s in ("", "-0") else s


def table_lines(headers, rows, right=()):
    widths = [len(h) for h in headers]
    for r in rows:
        for i, cell in enumerate(r):
            widths[i] = max(widths[i], len(cell))
    out = []
    for cells in [headers] + rows:
        parts = [c.rjust(widths[i]) if i in right else c.ljust(widths[i]) for i, c in enumerate(cells)]
        out.append("  " + "  ".join(parts).rstrip())
    return out


def render_text(rep):
    delim = {"\t": "tab", " ": "space"}.get(rep["delimiter"], repr(rep["delimiter"]))
    lines = ["Profile of %s" % rep["file"],
             "  encoding: %s (%s)%s" % (rep["encoding"], rep["encoding_source"],
                                         "  [%s]" % rep["encoding_note"] if rep["encoding_note"] else ""),
             "  delimiter: %s (%s)" % (delim, rep["delimiter_source"]),
             "  rows: %d%s   columns: %d" % (rep["rows"], "  (stopped at --max-rows %d)" % rep["max_rows"]
                                             if rep["truncated"] else "", rep["columns"]),
             "  duplicate rows: %d   empty rows: %d   ragged rows: %d%s   blank lines skipped: %d" % (
                 rep["duplicate_rows"], rep["empty_rows"], rep["ragged_rows"],
                 " (lines %s)" % ", ".join("%d: %d fields" % (r["line"], r["fields"]) for r in rep["ragged_examples"])
                 if rep["ragged_examples"] else "", rep["blank_lines_skipped"]),
             "  entirely empty columns: %s" % (", ".join(quote(n) for n in rep["empty_columns"]) or "none"),
             ""]
    cols = rep["column_profiles"]
    rows = [[str(c["index"]), quote(c["name"], 22)[1:-1] or "(no name)", c["type"], str(c["non_empty"]),
             str(c["empty"]), "" if c["empty_pct"] is None else "%.1f%%" % c["empty_pct"], str(c["distinct"]),
             " | ".join(quote(v, 16)[1:-1] for v in c["examples"])] for c in cols]
    lines.append("Columns")
    lines += table_lines(["#", "column", "type", "non-empty", "empty", "empty%", "distinct", "examples"],
                         rows, right=(0, 3, 4, 5, 6))
    stats = [[quote(c["name"], 22)[1:-1], c["type"], fmt_num(c["min"]) if c["type"] != "date" else c["min"],
              fmt_num(c["max"]) if c["type"] != "date" else c["max"], fmt_num(c["mean"]),
              fmt_num(c["median"]), fmt_num(c["stdev"])]
             for c in cols if c["type"] in ("integer", "decimal", "date")]
    if stats:
        lines += ["", "Numbers and dates"]
        lines += table_lines(["column", "type", "min", "max", "mean", "median", "stdev"], stats,
                             right=(4, 5, 6))
    texts = [[quote(c["name"], 22)[1:-1], c["type"], str(c["min_length"]), str(c["max_length"]),
              ", ".join("%s (%d)" % (quote(v, 18), n) for v, n in c["top"])]
             for c in cols if c["top"]]
    if texts:
        lines += ["", "Text and booleans"]
        lines += table_lines(["column", "type", "min len", "max len", "top values"], texts, right=(2, 3))
    notes = ["  - file: %s" % n for n in rep["header_issues"] + rep["notes"]]
    if rep["duplicate_rows"]:
        notes.append("  - file: %d duplicate rows" % rep["duplicate_rows"])
    if rep["ragged_rows"]:
        notes.append("  - file: %d rows do not have %d fields" % (rep["ragged_rows"], rep["columns"]))
    for c in cols:
        notes += ["  - %s: %s" % (quote(c["name"], 22), n) for n in c["notes"]]
    lines += ["", "Notes for the cleaning log"] + (notes or ["  none"])
    return "\n".join(lines)


def main(argv=None):
    parser = Parser(prog="profile_csv.py", description=__doc__.split("\n\n")[0],
                    epilog=__doc__.split("\n\n", 1)[1], formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("file", help="CSV file to profile")
    parser.add_argument("--delimiter", metavar="X", help="force the delimiter: one character, or 'tab'")
    parser.add_argument("--encoding", metavar="E", help="force the encoding (e.g. utf-8, cp1252, latin-1)")
    parser.add_argument("--max-rows", metavar="N", type=int, help="profile only the first N data rows")
    parser.add_argument("--json", action="store_true", help="print one JSON object instead of tables")
    args = parser.parse_args(argv)
    try:
        report = build_report(Path(args.file), args)
    except InputError as exc:
        sys.stderr.write("profile_csv.py: error: %s\n" % exc)
        return 2
    except MemoryError:
        sys.stderr.write("profile_csv.py: error: out of memory, retry with --max-rows\n")
        return 2
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    if args.json:
        sys.stdout.write(json.dumps(report, ensure_ascii=False, indent=1) + "\n")
    else:
        sys.stdout.write(render_text(report) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
