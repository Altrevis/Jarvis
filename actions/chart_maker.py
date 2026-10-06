"""
generate_chart — draw a chart locally and show it where the HUD core sits.

Free and offline: matplotlib renders a PNG on this machine, nothing is uploaded.
Three ways in, because a voice request arrives in three shapes:

    data        "fais un graphique de mes notes : maths 14, physique 12 …"
                -> labels + series, straight from the conversation (or from a
                   web_search result the model fetched first for live figures)
    function    "trace la courbe de x² - 3x entre -5 et 5"
                -> expression + x range, evaluated with numpy through a
                   whitelist — no eval() of arbitrary text
    description "un camembert de la population par continent"
                -> request, turned into data by the Gemini ladder

The image lands in <Pictures>/JARVIS/charts so it can be reused in a document.
"""
from __future__ import annotations

import ast
import math
import re
import sys
import time
from pathlib import Path

from core.user_dirs import jarvis_output_dir

_TYPES = ("bar", "barh", "line", "area", "pie", "doughnut", "scatter",
          "histogram", "function")


# ── Colours ──────────────────────────────────────────────────────────────────

def _palette(theme: str) -> dict:
    """The HUD's live colours (they follow the accent picker), or a plain light
    theme for charts meant to go into a document."""
    ui = sys.modules.get("ui")
    C = getattr(ui, "C", None)
    get = (lambda k, d: getattr(C, k, d)) if C else (lambda k, d: d)
    pri, acc, acc2 = get("PRI", "#00d4ff"), get("ACC", "#ff6b00"), get("ACC2", "#ffcc00")
    green, red, med = get("GREEN", "#00ff88"), get("RED", "#ff3355"), get("TEXT_MED", "#5ab8cc")
    series = [pri, acc, green, acc2, red, "#b388ff", med, "#ff8ad8"]
    if theme == "light":
        return {"bg": "#ffffff", "panel": "#ffffff", "grid": "#d9dee3",
                "text": "#1d2b36", "dim": "#5b6b78",
                "series": ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728",
                           "#9467bd", "#8c564b", "#e377c2", "#17becf"]}
    return {"bg": get("BG", "#00060a"), "panel": get("PANEL", "#010d14"),
            "grid": get("BORDER", "#0d3347"), "text": get("WHITE", "#d8f8ff"),
            "dim": get("TEXT_DIM", "#3a8a9a"), "series": series}


# ── Input cleaning ───────────────────────────────────────────────────────────

def _num(v) -> float:
    """'1 234,5', '12%', '€3.50' and 7 all become floats; anything else NaN."""
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v or "").strip().replace(" ", "").replace(" ", "")
    s = re.sub(r"[^\d,.\-eE+]", "", s)
    if "," in s and "." not in s:
        s = s.replace(",", ".")
    else:
        s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return float("nan")


def _series(raw) -> list[tuple[str, list[float]]]:
    out = []
    if isinstance(raw, dict):
        raw = [{"name": k, "values": v} for k, v in raw.items()]
    for i, s in enumerate(raw or []):
        if isinstance(s, dict):
            name = str(s.get("name") or s.get("label") or f"Série {i + 1}")
            vals = s.get("values") or s.get("data") or []
        else:
            name, vals = f"Série {i + 1}", s
        if not isinstance(vals, (list, tuple)):
            vals = [vals]
        out.append((name, [_num(v) for v in vals]))
    return [s for s in out if s[1]]


# ── Safe function evaluation ─────────────────────────────────────────────────

_FUNCS = {"sin", "cos", "tan", "arcsin", "arccos", "arctan", "sinh", "cosh",
          "tanh", "exp", "log", "log10", "log2", "sqrt", "abs", "floor", "ceil",
          "round", "sign"}
_ALIASES = {"ln": "log", "asin": "arcsin", "acos": "arccos", "atan": "arctan",
            "racine": "sqrt", "rac": "sqrt"}
_CONSTS = {"pi": math.pi, "e": math.e}
_OK_NODES = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Call, ast.Name,
             ast.Constant, ast.Load, ast.Add, ast.Sub, ast.Mult, ast.Div,
             ast.Pow, ast.Mod, ast.FloorDiv, ast.USub, ast.UAdd)


def _prepare_expr(expr: str) -> str:
    e = expr.strip().lower()
    e = re.sub(r"^\s*(y|f\s*\(\s*x\s*\))\s*=", "", e)
    e = e.replace("^", "**").replace("²", "**2").replace("³", "**3").replace("×", "*")
    e = e.replace("−", "-").replace("÷", "/")
    for a, b in _ALIASES.items():
        e = re.sub(rf"\b{a}\b", b, e)
    # Implicit multiplication: 2x, 3(x+1), x(x-1), )( and 2pi — but only for
    # a number standing on its own, so log10(x) and 1e5 are left alone.
    e = re.sub(r"(?<![a-z_\d.])(\d+(?:\.\d+)?)\s*(?!e\d)([a-z(])", r"\1*\2", e)
    e = re.sub(r"\)\s*([a-z0-9(])", r")*\1", e)
    e = re.sub(r"\bx\s*\(", "x*(", e)
    return e


def _eval_expr(expr: str, x):
    import numpy as np
    tree = ast.parse(_prepare_expr(expr), mode="eval")
    for node in ast.walk(tree):
        if not isinstance(node, _OK_NODES):
            raise ValueError(f"not allowed in a formula: {type(node).__name__}")
        if isinstance(node, ast.Call):
            if not (isinstance(node.func, ast.Name) and node.func.id in _FUNCS):
                raise ValueError("unknown function in the formula")
        elif isinstance(node, ast.Name) and node.id not in _FUNCS \
                and node.id != "x" and node.id not in _CONSTS:
            raise ValueError(f"unknown name '{node.id}' in the formula")
    env = {f: getattr(np, f) for f in _FUNCS if f != "abs"}
    env.update(abs=np.abs, x=x, **_CONSTS)
    with np.errstate(all="ignore"):
        y = eval(compile(tree, "<formula>", "eval"), {"__builtins__": {}}, env)  # noqa: S307 — AST-whitelisted above
    y = np.asarray(y, dtype=float) * np.ones_like(x)
    # Asymptotes (tan, 1/x) would draw a vertical wall across the plot.
    y[~np.isfinite(y)] = np.nan
    if np.isfinite(y).any():
        lo, hi = np.nanpercentile(y, [1, 99])
        span = max(hi - lo, 1e-9)
        y[(y < lo - 3 * span) | (y > hi + 3 * span)] = np.nan
    return y


# ── Spec from a description ──────────────────────────────────────────────────

def _spec_from_request(request: str, chart_type: str) -> dict:
    from core import gemini
    prompt = (
        "Turn this chart request into data. Reply with JSON only, keys: "
        '"chart_type" (one of ' + ", ".join(_TYPES) + '), "title", "labels" '
        '(list of strings), "series" (list of {"name", "values": list of numbers '
        'aligned with labels}), "x_label", "y_label"; for a mathematical curve use '
        'chart_type "function" with "expression" (numpy-style, in x) and "x_min", '
        '"x_max" instead. Use accurate, real figures you are confident of. If the '
        'request needs live or private data you do not have, return '
        '{"error": "<what is missing>"}. Title and labels in the language of the '
        f"request.\nPreferred chart type: {chart_type or 'choose the clearest'}.\n"
        f"Request: {request}"
    )
    spec = gemini.as_json(prompt, tier=gemini.SMART, timeout_ms=30_000, default=None)
    return spec if isinstance(spec, dict) else {}


# ── Rendering ────────────────────────────────────────────────────────────────

def _slug(text: str) -> str:
    from core.fuzzy_find import normalize
    s = normalize(text).replace(" ", "-")[:48].strip("-")
    return s or "chart"


def _render(spec: dict, theme: str) -> tuple[Path, str]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    pal = _palette(theme)
    ctype = str(spec.get("chart_type") or "bar").lower().strip()
    ctype = {"camembert": "pie", "donut": "doughnut", "courbe": "line",
             "histogramme": "histogram", "column": "bar", "colonnes": "bar",
             "nuage": "scatter", "barres": "bar", "hbar": "barh",
             "curve": "function", "fonction": "function"}.get(ctype, ctype)
    if ctype not in _TYPES:
        ctype = "bar"
    title = str(spec.get("title") or "").strip()
    labels = [str(l) for l in (spec.get("labels") or [])]
    series = _series(spec.get("series"))
    expr = str(spec.get("expression") or "").strip()
    if expr and not series:
        ctype = "function"

    fig, ax = plt.subplots(figsize=(10, 6.25), dpi=160)
    fig.patch.set_facecolor(pal["bg"])
    ax.set_facecolor(pal["panel"])
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(pal["grid"])
    ax.tick_params(colors=pal["dim"], labelsize=9)
    ax.grid(True, color=pal["grid"], linewidth=0.6, alpha=0.8)
    ax.set_axisbelow(True)
    cols = pal["series"]

    if ctype == "function":
        x0, x1 = _num(spec.get("x_min", -10)), _num(spec.get("x_max", 10))
        if not (math.isfinite(x0) and math.isfinite(x1)) or x0 == x1:
            x0, x1 = -10.0, 10.0
        x0, x1 = min(x0, x1), max(x0, x1)
        x = np.linspace(x0, x1, 1200)
        exprs = [e for e in re.split(r"[;\n]", expr) if e.strip()]
        if not exprs:
            raise ValueError("no formula to plot")
        for i, e in enumerate(exprs):
            ax.plot(x, _eval_expr(e, x), color=cols[i % len(cols)], linewidth=2.2,
                    label=f"y = {e.strip()}")
        ax.axhline(0, color=pal["dim"], linewidth=0.9)
        ax.axvline(0, color=pal["dim"], linewidth=0.9) if x0 < 0 < x1 else None
        ax.legend(facecolor=pal["panel"], edgecolor=pal["grid"], labelcolor=pal["text"])
        if not title:
            title = "Courbe de " + " ; ".join(f"y = {e.strip()}" for e in exprs)

    elif not series:
        raise ValueError("no data to draw — give labels and series values")

    elif ctype in ("pie", "doughnut"):
        name, vals = series[0]
        pairs = [(l, v) for l, v in zip(labels or [f"#{i+1}" for i in range(len(vals))], vals)
                 if math.isfinite(v) and v > 0]
        if not pairs:
            raise ValueError("a pie chart needs positive values")
        ax.grid(False)
        wedges, texts, autotexts = ax.pie(
            [v for _l, v in pairs], labels=[l for l, _v in pairs],
            colors=[cols[i % len(cols)] for i in range(len(pairs))],
            autopct="%1.1f%%", startangle=90, pctdistance=0.78 if ctype == "doughnut" else 0.6,
            wedgeprops={"width": 0.42 if ctype == "doughnut" else 1.0,
                        "edgecolor": pal["bg"], "linewidth": 2},
            textprops={"color": pal["text"], "fontsize": 10})
        for t in autotexts:
            t.set_color(pal["bg"] if theme != "light" else "#ffffff")
            t.set_fontweight("bold")

    elif ctype == "histogram":
        vals = [v for _n, vs in series for v in vs if math.isfinite(v)]
        ax.hist(vals, bins="auto", color=cols[0], edgecolor=pal["bg"], alpha=0.9)

    else:
        n = max(len(v) for _n, v in series)
        xl = labels[:n] + [str(i + 1) for i in range(len(labels), n)]
        idx = np.arange(n)
        if ctype in ("bar", "barh"):
            k = len(series)
            w = 0.8 / k
            for i, (name, vals) in enumerate(series):
                vals = vals + [float("nan")] * (n - len(vals))
                pos = idx - 0.4 + w * (i + 0.5)
                bars = (ax.barh if ctype == "barh" else ax.bar)(
                    pos, vals, w * 0.92, label=name, color=cols[i % len(cols)])
                if n * k <= 16:
                    ax.bar_label(bars, fmt="%g", color=pal["text"], fontsize=8, padding=2)
            if ctype == "barh":
                ax.set_yticks(idx, xl)
                ax.invert_yaxis()
            else:
                ax.set_xticks(idx, xl, rotation=30 if max(map(len, xl), default=0) > 8 else 0,
                              ha="right" if max(map(len, xl), default=0) > 8 else "center")
        else:
            numeric_x = all(math.isfinite(_num(l)) for l in xl) and bool(labels)
            xs = [_num(l) for l in xl] if numeric_x else idx
            for i, (name, vals) in enumerate(series):
                vals = vals + [float("nan")] * (n - len(vals))
                c = cols[i % len(cols)]
                if ctype == "scatter":
                    ax.scatter(xs, vals, color=c, s=46, label=name, edgecolors=pal["bg"])
                else:
                    ax.plot(xs, vals, color=c, linewidth=2.2, label=name,
                            marker="o" if n <= 30 else None, markersize=4)
                    if ctype == "area":
                        ax.fill_between(xs, vals, color=c, alpha=0.18)
            if not numeric_x:
                step = max(1, n // 14)
                ax.set_xticks(idx[::step], xl[::step],
                              rotation=30 if n > 8 else 0, ha="right" if n > 8 else "center")
        if len(series) > 1:
            ax.legend(facecolor=pal["panel"], edgecolor=pal["grid"], labelcolor=pal["text"])

    if spec.get("x_label") and ctype not in ("pie", "doughnut"):
        ax.set_xlabel(str(spec["x_label"]), color=pal["dim"])
    if spec.get("y_label") and ctype not in ("pie", "doughnut"):
        ax.set_ylabel(str(spec["y_label"]), color=pal["dim"])
    if title:
        ax.set_title(title, color=pal["text"], fontsize=14, fontweight="bold", pad=14)

    fig.tight_layout()
    out = jarvis_output_dir("charts") / f"{time.strftime('%Y%m%d-%H%M%S')}-{_slug(title)}.png"
    fig.savefig(out, facecolor=fig.get_facecolor())
    plt.close(fig)
    return out, title or "Chart"


# ── Tool ─────────────────────────────────────────────────────────────────────

def generate_chart(parameters: dict, player=None) -> str:
    p = dict(parameters or {})
    theme = "light" if str(p.get("theme", "")).lower().startswith(("light", "clair")) else "dark"
    has_data = bool(p.get("series")) or bool(str(p.get("expression") or "").strip())
    request = str(p.get("request") or "").strip()

    if not has_data:
        if not request:
            return ("No data given. Pass labels + series, an expression for a "
                    "curve, or a 'request' describing the chart.")
        spec = _spec_from_request(request, str(p.get("chart_type") or ""))
        if not spec:
            return "Could not work out data for that chart right now."
        if spec.get("error"):
            return (f"Missing data for this chart: {spec['error']}. Search for it "
                    f"with web_search, then call generate_chart with the figures.")
        for k in ("title", "x_label", "y_label"):
            if p.get(k):
                spec[k] = p[k]
        if p.get("chart_type") and spec.get("chart_type") != "function":
            spec["chart_type"] = p["chart_type"]
        p = spec

    try:
        path, title = _render(p, theme)
    except Exception as e:
        return f"Chart failed: {e}"

    if player is not None and hasattr(player, "show_image"):
        player.show_image(str(path), f"CHART — {title}")
    return (f"Chart '{title}' is now on the display and saved to {path}. Tell the "
            f"user in one short sentence that it is on screen; do not read the "
            f"figures back unless they ask.")


TOOL = {
    "name": "generate_chart",
    "description": (
        "Draws a chart and shows it on the assistant's display: bar, horizontal "
        "bar, line, area, pie, doughnut, scatter, histogram, or the curve of a "
        "mathematical function. Use it whenever the user asks for a graph, chart, "
        "plot, curve, diagram or visual comparison of numbers. Pass the figures in "
        "'labels' and 'series' when you have them — from the conversation, or "
        "call web_search FIRST for live or recent figures (prices, scores, "
        "statistics) and then pass what it returned. For a mathematical curve "
        "pass 'expression' with x_min and x_max. Only when you have no figures at "
        "all, describe the chart in 'request'. Free and local; the PNG is saved "
        "in the user's Pictures/JARVIS/charts folder."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "chart_type": {"type": "STRING",
                           "description": "bar | barh | line | area | pie | doughnut | scatter | histogram | function"},
            "title": {"type": "STRING", "description": "Chart title, in the user's language"},
            "labels": {"type": "ARRAY", "items": {"type": "STRING"},
                       "description": "Category or x-axis labels, in order"},
            "series": {
                "type": "ARRAY",
                "description": "One or more data series; each 'values' list lines up with 'labels'",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "name": {"type": "STRING", "description": "Series name (legend)"},
                        "values": {"type": "ARRAY", "items": {"type": "NUMBER"}},
                    },
                },
            },
            "x_label": {"type": "STRING", "description": "X axis title"},
            "y_label": {"type": "STRING", "description": "Y axis title (with unit)"},
            "expression": {"type": "STRING",
                           "description": "For a function curve: formula in x, e.g. 'x**2 - 3*x' or 'sin(x)'; several separated by ';'"},
            "x_min": {"type": "NUMBER", "description": "Start of the x range for a function"},
            "x_max": {"type": "NUMBER", "description": "End of the x range for a function"},
            "request": {"type": "STRING",
                        "description": "Only when no figures are given: what the chart should show, in the user's words"},
            "theme": {"type": "STRING",
                      "description": "dark (default, matches the display) | light (for documents and printing)"},
        },
    },
    "handler": generate_chart,
}
