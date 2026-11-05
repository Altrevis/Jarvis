#!/usr/bin/env python3
"""scan_secrets.py — find likely secrets in files, without ever printing one.

Walks a file or a folder and reports lines that look like credentials:
private keys, cloud and SaaS API keys, tokens, passwords embedded in URLs,
literal passwords in code, values in .env files. Each match is shown masked
(its first 4 characters and its length), never in full.

Usage:
    python3 scan_secrets.py ./my-app
    python3 scan_secrets.py ./my-app --json
    python3 scan_secrets.py config/settings.py --include-tests --max-files 20000

Exit codes: 0 nothing found, 1 findings, 2 usage or input error.

Limits: regular expressions miss custom secret formats and flag look-alikes
(example keys in documentation, test fixtures). Every finding is a lead to
confirm by reading the file. Standard library only; no network; writes
nothing.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SKIP_DIRS = {".git", ".hg", ".svn", "node_modules", ".venv", "venv", "env", "__pycache__",
             "dist", "build", ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".next",
             ".nuxt", "target", ".gradle", ".idea", ".vscode", "coverage", ".terraform"}
TEST_DIRS = {"test", "tests", "__tests__", "spec", "specs", "fixtures", "testdata", "__mocks__"}
TEST_FILE = re.compile(r"(^test_.*|.*_test\.\w+|.*\.(test|spec)\.\w+|^conftest\.py)$", re.I)
ENV_TEMPLATE = re.compile(r"\.(example|sample|template|dist|tpl)$", re.I)
MAX_BYTES = 1_000_000
MAX_LINE = 20_000

# (rule id, severity, description, pattern, group holding the secret: 0 = whole match)
RULES = [
    ("private-key", "high", "private key block",
     re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----"), 0),
    ("aws-access-key-id", "high", "AWS access key id",
     re.compile(r"(?<![A-Z0-9])(?:AKIA|ASIA)[0-9A-Z]{16}(?![A-Z0-9])"), 0),
    ("github-token", "high", "GitHub token",
     re.compile(r"(?<![A-Za-z0-9_])(?:gh[pousr]_[A-Za-z0-9]{36,255}|github_pat_[A-Za-z0-9_]{22,255})"), 0),
    ("slack-token", "high", "Slack token",
     re.compile(r"(?<![A-Za-z0-9])xox[baprs]-[A-Za-z0-9-]{10,}"), 0),
    ("google-api-key", "high", "Google API key",
     re.compile(r"(?<![A-Za-z0-9_-])AIza[0-9A-Za-z_\-]{35}(?![0-9A-Za-z_\-])"), 0),
    ("stripe-live-key", "high", "Stripe live secret or restricted key",
     re.compile(r"(?<![A-Za-z0-9])[sr]k_live_[0-9A-Za-z]{16,}"), 0),
    ("anthropic-key", "high", "Anthropic API key",
     re.compile(r"(?<![A-Za-z0-9])sk-ant-[A-Za-z0-9_\-]{20,}"), 0),
    ("openai-key", "medium", "OpenAI-style secret key",
     re.compile(r"(?<![A-Za-z0-9])sk-(?!ant-)(?:proj-|svcacct-|admin-)?[A-Za-z0-9_\-]{20,}"), 0),
    ("jwt", "medium", "JSON Web Token",
     re.compile(r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"), 0),
    ("url-credentials", "high", "password embedded in a URL",
     re.compile(r"(?<![A-Za-z0-9+.\-])[A-Za-z][A-Za-z0-9+.\-]{1,20}://[^\s/:@'\"<>]{1,64}:([^\s/@'\"<>]{3,128})@[A-Za-z0-9.\-\[\]]+"), 1),
    ("generic-assignment", "low", "password, secret, token or key assigned a literal",
     re.compile(r"(?i)(?:password|passwd|pwd|secret|token|api[_-]?key|apikey|access[_-]?key|private[_-]?key)"
                r"[\w.\-]{0,30}[\"']?\s*(?::|=|=>|:=)\s*[\"']([^\"'\s]{8,})[\"']"), 1),
]
ENV_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_.]*)\s*=\s*(.*?)\s*$")
PLACEHOLDER = re.compile(r"(changeme|change_me|example|placeholder|dummy|redacted|your[_\-]?|xxxx|\*\*\*\*|"
                         r"<[^>]*>|\$\{[^}]*\}|\{\{[^}]*\}\}|^%\(|^\$[A-Z_]+$|^(password|secret|token|test|"
                         r"none|null|true|false)$)", re.I)


def mask(value: str) -> str:
    return f"{value[:4]}…({len(value)} chars)"


def placeholder(value: str) -> bool:
    v = value.strip().strip("\"'")
    return not v or len(set(v)) <= 2 or PLACEHOLDER.search(v) is not None


def is_env_file(path: Path) -> bool:
    name = path.name.lower()
    if ENV_TEMPLATE.search(name):
        return False
    return name == ".env" or name.startswith(".env.") or name.endswith(".env")


def is_test(path: Path, root: Path) -> bool:
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        parts = path.parts
    return any(p.lower() in TEST_DIRS for p in parts[:-1]) or TEST_FILE.match(path.name) is not None


def files_of(root: Path, include_tests: bool, max_files: int):
    """(files to scan, number skipped, truncated?)"""
    out: list[Path] = []
    skipped = 0
    if root.is_file():
        return [root], 0, False
    stack = [root]
    while stack:
        d = stack.pop()
        try:
            entries = sorted(d.iterdir(), key=lambda p: p.name)
        except OSError:
            skipped += 1
            continue
        for p in entries:
            if p.is_symlink():
                skipped += 1
                continue
            if p.is_dir():
                if p.name in SKIP_DIRS:
                    skipped += 1
                else:
                    stack.append(p)
                continue
            if not include_tests and is_test(p, root):
                skipped += 1
                continue
            if len(out) >= max_files:
                return out, skipped, True
            out.append(p)
    return out, skipped, False


def read_text(path: Path) -> str | None:
    try:
        if path.stat().st_size > MAX_BYTES:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if b"\0" in data[:8192]:
        return None
    return data.decode("utf-8", errors="replace")


def scan_file(path: Path, shown: str) -> list[dict]:
    text = read_text(path)
    if text is None:
        return []
    found, seen = [], set()
    env = is_env_file(path)
    for no, line in enumerate(text.splitlines(), 1):
        line = line[:MAX_LINE]
        spans: list[tuple[int, int]] = []      # what a specific rule already reported
        for rule, sev, desc, rx, grp in RULES:
            for m in rx.finditer(line):
                secret = m.group(grp) if grp else m.group(0)
                if grp and placeholder(secret):
                    continue
                start, end = m.span(grp)
                if rule == "generic-assignment" and any(s < end and start < e for s, e in spans):
                    continue                    # the same value, already named precisely
                spans.append((start, end))
                key = (no, rule)
                if key in seen:
                    continue
                seen.add(key)
                found.append({"path": shown, "line": no, "rule": rule, "severity": sev,
                              "masked": mask(secret), "description": desc})
        if env and not line.lstrip().startswith("#"):
            m = ENV_LINE.match(line)
            if m:
                value = m.group(2)
                if value and value[0] not in "\"'":
                    value = value.split(" #", 1)[0].strip()
                value = value.strip("\"'")
                if value and not placeholder(value) and not any(f["line"] == no for f in found):
                    found.append({"path": shown, "line": no, "rule": "env-value", "severity": "medium",
                                  "masked": mask(value), "description": f"value of {m.group(1)} in a .env file"})
    return found


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="scan_secrets.py",
        description="Find likely secrets in a file or folder. Matches are always masked.",
        epilog="Exit codes: 0 nothing found, 1 findings, 2 usage or input error.")
    ap.add_argument("path", help="file or folder to scan")
    ap.add_argument("--json", action="store_true", help="print one JSON object")
    ap.add_argument("--max-files", type=int, default=5000, metavar="N",
                    help="stop after N files (default 5000)")
    ap.add_argument("--include-tests", action="store_true",
                    help="also scan test folders and test files (skipped by default)")
    a = ap.parse_args(argv)
    root = Path(a.path).expanduser()
    if not root.exists():
        print(f"scan_secrets.py: error: no such file or folder: {root}", file=sys.stderr)
        return 2
    if a.max_files < 1:
        print("scan_secrets.py: error: --max-files must be at least 1", file=sys.stderr)
        return 2
    files, skipped, truncated = files_of(root, a.include_tests, a.max_files)
    findings: list[dict] = []
    scanned = 0
    for f in files:
        shown = f.name if root.is_file() else f.relative_to(root).as_posix()
        if read_text(f) is None:
            skipped += 1
            continue
        scanned += 1
        findings += scan_file(f, shown)
    order = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda x: (order[x["severity"]], x["path"], x["line"]))
    counts = {s: sum(1 for x in findings if x["severity"] == s) for s in ("high", "medium", "low")}
    if a.json:
        print(json.dumps({"scanned_files": scanned, "skipped": skipped, "truncated": truncated,
                          "findings": findings, "counts": counts}, ensure_ascii=False, indent=1))
    else:
        for x in findings:
            print(f"{x['path']}:{x['line']}  [{x['severity']}] {x['rule']}  {x['masked']}  — {x['description']}")
        note = f" (stopped at --max-files {a.max_files})" if truncated else ""
        print(f"Scanned {scanned} files, skipped {skipped}{note}. Findings: high {counts['high']}, "
              f"medium {counts['medium']}, low {counts['low']}.")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
