#!/usr/bin/env python3
"""WCAG 2.x contrast checker for colour pairs. Standard library only.

Computes the contrast ratio of a foreground and a background colour from their
relative luminance: each sRGB channel is linearised (c / 12.92 when
c <= 0.04045, else ((c + 0.055) / 1.055) ** 2.4), L = 0.2126 R + 0.7152 G +
0.0722 B, and ratio = (L1 + 0.05) / (L2 + 0.05) with L1 the lighter colour.
Each pair is reported pass/fail against:

    AA normal text   4.5:1      AAA normal text  7.0:1
    AA large text    3.0:1      AAA large text   4.5:1
    UI components    3.0:1      (non-text contrast: input borders, icons,
                                 focus indicators, chart marks)

Ratios are displayed rounded to 2 decimals but compared unrounded, so 4.497
fails 4.5. When rounding would hide a failure the text output shows 4 decimals.

Usage:
    python3 contrast.py "#1a1a1a" "#ffffff"
    python3 contrast.py "rgb(26, 26, 26)" white --json
    python3 contrast.py --palette tokens.json
    python3 contrast.py --palette tokens.json --json

Quote every colour on the command line: an unquoted # starts a shell comment.

Palette file (UTF-8 JSON object; other top-level keys are ignored, so a full
token file can carry its own "colors" and "pairs"):
    {"colors": {"text": "#1a1a1a", "surface": "#ffffff"},
     "pairs": [["text", "surface"]]}
Each pair is [foreground name, background name] and both names must be keys of
"colors". Colours that no pair uses are not parsed (a translucent scrim token
may sit in the file).

Colour formats: #rgb, #rrggbb, #rrggbbaa (alpha must be ff), rgb(r, g, b) with
integers 0-255, and the 16 basic CSS named colours.

Exit codes: 0 = every checked pair reaches AA normal text (4.5:1); 1 = at least
one pair is below 4.5:1 (also when that pair only needs 3:1, such as large text
or a UI component: read its own column); 2 = usage or input error, reported on
one line on stderr.

Limitations: opaque colours only (contrast with transparency depends on what is
behind it: flatten the colour onto its background first); no rgba(), hsl(),
oklch() or extended named colours; WCAG 2.x formula only (not APCA); it checks
numbers, not font size or weight, so deciding whether text is "large" (at least
24 CSS px, or 18.66 CSS px bold) is up to you; no colour-blindness simulation.
"""

import argparse
import json
import math
import re
import sys
from pathlib import Path

PROG = "contrast.py"

# (json key, label, minimum ratio)
LEVELS = (
    ("aa_normal", "AA normal text", 4.5),
    ("aa_large", "AA large text", 3.0),
    ("aaa_normal", "AAA normal text", 7.0),
    ("aaa_large", "AAA large text", 4.5),
    ("ui_component", "UI components", 3.0),
)
SHORT = {"aa_normal": "AA", "aa_large": "AA-lg", "aaa_normal": "AAA",
         "aaa_large": "AAA-lg", "ui_component": "UI"}
GATE = "aa_normal"

# The 16 basic colour keywords of CSS (HTML 4 / CSS 2.1).
NAMED = {
    "black": "#000000", "silver": "#c0c0c0", "gray": "#808080",
    "white": "#ffffff", "maroon": "#800000", "red": "#ff0000",
    "purple": "#800080", "fuchsia": "#ff00ff", "green": "#008000",
    "lime": "#00ff00", "olive": "#808000", "yellow": "#ffff00",
    "navy": "#000080", "blue": "#0000ff", "teal": "#008080",
    "aqua": "#00ffff",
}
FORMATS = "#rgb, #rrggbb, #rrggbbaa, rgb(r, g, b) or one of the 16 basic CSS names"
RGB_RE = re.compile(r"rgb\(\s*([^,()]*?)\s*,\s*([^,()]*?)\s*,\s*([^,()]*?)\s*\)",
                    re.IGNORECASE)
HEX_DIGITS = re.compile(r"[0-9a-fA-F]+")


class InputError(Exception):
    """Bad colour, file or palette: one line on stderr, exit 2."""


class Parser(argparse.ArgumentParser):
    """argparse with one-line errors and exit code 2."""

    def error(self, message):
        sys.stderr.write("%s: error: %s (see --help)\n" % (PROG, message))
        sys.exit(2)


def parse_colour(value):
    """Return (r, g, b) integers 0-255 for a supported colour string."""
    if not isinstance(value, str):
        raise InputError("colour must be a string, got %s" % json.dumps(value)[:40])
    text = value.strip()
    if not text:
        raise InputError("empty colour")
    low = text.lower()
    if low in NAMED:
        text = NAMED[low]
    if text.startswith("#"):
        digits = text[1:]
        if not HEX_DIGITS.fullmatch(digits) or len(digits) not in (3, 6, 8):
            raise InputError("%r is not a valid hex colour (use #rgb, #rrggbb or "
                             "#rrggbbaa)" % value)
        if len(digits) == 3:
            digits = "".join(c * 2 for c in digits)
        if len(digits) == 8:
            alpha = digits[6:].lower()
            if alpha != "ff":
                raise InputError("%r has alpha %s: contrast with transparency depends "
                                 "on what is behind it; flatten it onto its "
                                 "background and pass the opaque result" % (value, alpha))
            digits = digits[:6]
        return tuple(int(digits[i:i + 2], 16) for i in (0, 2, 4))
    match = RGB_RE.fullmatch(text)
    if match:
        channels = []
        for part in match.groups():
            if not re.fullmatch(r"\d{1,3}", part) or int(part) > 255:
                raise InputError("%r: rgb() takes three integers from 0 to 255" % value)
            channels.append(int(part))
        return tuple(channels)
    if low in ("grey", "darkgrey", "lightgrey"):
        raise InputError("%r is not one of the 16 basic CSS names (gray is); "
                         "use a hex value" % value)
    if HEX_DIGITS.fullmatch(text) and len(text) in (3, 6, 8):
        raise InputError("%r: a hex colour needs a leading # (and quotes on the "
                         "command line)" % value)
    raise InputError("%r is not a supported colour: use %s" % (value, FORMATS))


def channel(c8):
    c = c8 / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminance(rgb):
    r, g, b = (channel(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a, b):
    la, lb = luminance(a), luminance(b)
    hi, lo = (la, lb) if la >= lb else (lb, la)
    return (hi + 0.05) / (lo + 0.05)


def to_hex(rgb):
    return "#%02x%02x%02x" % rgb


def check_pair(fg_label, fg_rgb, bg_label, bg_rgb):
    ratio = contrast_ratio(fg_rgb, bg_rgb)
    row = {
        "foreground": fg_label,
        "background": bg_label,
        "foreground_hex": to_hex(fg_rgb),
        "background_hex": to_hex(bg_rgb),
        "ratio": round(ratio, 2),
        "ratio_unrounded": ratio,
    }
    for key, _label, minimum in LEVELS:
        row[key] = ratio >= minimum
    return row


def shown_ratio(ratio):
    """2 decimals, or 4 (truncated) when rounding up would hide a failure."""
    rounded = float("%.2f" % ratio)
    if any(ratio < minimum <= rounded for _k, _l, minimum in LEVELS):
        return "%.4f" % (math.floor(ratio * 10000) / 10000)
    return "%.2f" % ratio


def load_palette(path_text):
    if not path_text.strip():
        raise InputError("--palette needs a file path")
    path = Path(path_text)
    if path.is_dir():
        raise InputError("%s is a directory, not a JSON file" % path_text)
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        raise InputError("palette file not found: %s" % path_text)
    except UnicodeDecodeError:
        raise InputError("%s is not UTF-8 text" % path_text)
    except OSError as exc:
        raise InputError("cannot read %s: %s" % (path_text, exc.strerror or exc))
    try:
        data = json.loads(raw)
    except (ValueError, RecursionError) as exc:
        raise InputError("%s is not valid JSON: %s" % (path_text, exc))
    if not isinstance(data, dict):
        raise InputError('palette must be a JSON object with "colors" and "pairs"')
    colors = data.get("colors")
    if not isinstance(colors, dict) or not colors:
        raise InputError('palette needs a non-empty "colors" object mapping names '
                         'to colours')
    pairs = data.get("pairs")
    if not isinstance(pairs, list) or not pairs:
        raise InputError('palette needs a non-empty "pairs" list of '
                         '[foreground, background] names')
    parsed, rows = {}, []
    for number, pair in enumerate(pairs, 1):
        if not (isinstance(pair, list) and len(pair) == 2
                and all(isinstance(name, str) for name in pair)):
            raise InputError("pair %d must be a list of two colour names, got %s"
                             % (number, json.dumps(pair)[:60]))
        for name in pair:
            if name not in colors:
                raise InputError('pair %d uses %r, which is not a key of "colors"'
                                 % (number, name))
            if name not in parsed:
                try:
                    parsed[name] = parse_colour(colors[name])
                except InputError as exc:
                    raise InputError('colors[%s]: %s' % (json.dumps(name), exc))
        rows.append(check_pair(pair[0], parsed[pair[0]], pair[1], parsed[pair[1]]))
    return rows


def describe(label, hex_value):
    return hex_value if label.strip().lower() == hex_value else "%s (%s)" % (label, hex_value)


def print_single(row):
    print("%s on %s" % (describe(row["foreground"], row["foreground_hex"]),
                        describe(row["background"], row["background_hex"])))
    print("Contrast ratio: %s:1" % shown_ratio(row["ratio_unrounded"]))
    for key, label, minimum in LEVELS:
        print("  %-16s (%.1f:1)  %s" % (label, minimum, "pass" if row[key] else "FAIL"))


def print_table(rows, source):
    names = ["%s on %s" % (r["foreground"], r["background"]) for r in rows]
    width = max([len("pair")] + [len(n) for n in names])
    print("Palette %s: %d pair%s" % (source, len(rows), "" if len(rows) == 1 else "s"))
    head = "%-*s  %7s" % (width, "pair", "ratio")
    for key, _label, _minimum in LEVELS:
        head += "  %-6s" % SHORT[key]
    print(head.rstrip())
    for name, row in zip(names, rows):
        line = "%-*s  %7s" % (width, name, shown_ratio(row["ratio_unrounded"]))
        for key, _label, _minimum in LEVELS:
            line += "  %-6s" % ("pass" if row[key] else "FAIL")
        print(line.rstrip())


def summary(rows):
    failing = ["%s on %s" % (r["foreground"], r["background"]) for r in rows if not r[GATE]]
    if not failing:
        return "All %d pair(s) reach AA normal text (4.5:1)." % len(rows)
    return "%d of %d pair(s) below AA normal text (4.5:1): %s" % (
        len(failing), len(rows), "; ".join(failing))


def build_parser():
    parser = Parser(
        prog=PROG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="WCAG 2.x contrast ratio of colour pairs, with pass/fail for AA\n"
                    "and AAA text and for non-text UI components (3:1).",
        epilog=(
            "colour formats: " + FORMATS + ";\n"
            "  #rrggbbaa only with alpha ff (transparency depends on the backdrop).\n"
            "  Quote colours: an unquoted # starts a shell comment.\n\n"
            "palette file: {\"colors\": {\"text\": \"#1a1a1a\", \"surface\": \"#ffffff\"},\n"
            "               \"pairs\": [[\"text\", \"surface\"]]}\n"
            "  other top-level keys and colours used by no pair are ignored.\n\n"
            "thresholds: AA normal 4.5, AA large 3.0, AAA normal 7.0, AAA large 4.5,\n"
            "  UI components 3.0; compared unrounded, displayed to 2 decimals.\n\n"
            "examples:\n"
            "  python3 contrast.py \"#1a1a1a\" \"#ffffff\"\n"
            "  python3 contrast.py \"rgb(26, 26, 26)\" white --json\n"
            "  python3 contrast.py --palette tokens.json\n\n"
            "exit codes: 0 every pair reaches 4.5:1 (AA normal text); 1 a pair is\n"
            "  below 4.5:1, even one that only needs 3:1 (read its column);\n"
            "  2 usage or input error."
        ),
    )
    parser.add_argument("foreground", nargs="?", help="text or icon colour, e.g. \"#1a1a1a\"")
    parser.add_argument("background", nargs="?", help="colour behind it, e.g. \"#ffffff\"")
    parser.add_argument("--palette", metavar="FILE",
                        help="JSON file with \"colors\" (name -> colour) and \"pairs\"")
    parser.add_argument("--json", action="store_true",
                        help="print one JSON object instead of text")
    return parser


def main(argv=None):
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    args = build_parser().parse_args(argv)
    try:
        if args.palette is not None:
            if args.foreground is not None:
                raise InputError("give two colours or --palette FILE, not both")
            rows = load_palette(args.palette)
            mode, source = "palette", args.palette
        else:
            if args.foreground is None or args.background is None:
                raise InputError("give a foreground and a background colour, or "
                                 "--palette FILE; quote hex colours, since an "
                                 "unquoted # starts a shell comment")
            fg = parse_colour(args.foreground)
            bg = parse_colour(args.background)
            rows = [check_pair(args.foreground.strip(), fg, args.background.strip(), bg)]
            mode, source = "pair", None
    except InputError as exc:
        sys.stderr.write("%s: error: %s\n" % (PROG, exc))
        return 2

    failing = sum(1 for row in rows if not row[GATE])
    if args.json:
        print(json.dumps({
            "mode": mode,
            "source": source,
            "thresholds": {key: minimum for key, _label, minimum in LEVELS},
            "pairs": rows,
            "checked": len(rows),
            "failing_aa_normal": failing,
            "passed": failing == 0,
        }, indent=2))
    else:
        if mode == "pair":
            print_single(rows[0])
        else:
            print_table(rows, source)
        print(summary(rows))
    return 1 if failing else 0


if __name__ == "__main__":
    sys.exit(main())
