"""
create_document — a PDF report or a PowerPoint deck, written by Claude.

Claude writes the content; this file does the layout, locally, so the result
looks the same every time and nothing is uploaded:

    pdf    Claude writes one print-ready HTML page (CSS for A4, inline SVG for
           any diagram) and Chromium — already here for browser_control —
           prints it with page numbers.
    pptx   Claude (Opus, as an agent) designs the deck as a web page — one
           <section> per slide, HTML and CSS being where it designs best —
           in an art direction chosen for this subject and audience (never
           the look of the last few decks), checks it in Chromium and fixes
           it, then core/html_deck.py converts it: each slide's design as its
           background, its words as native, editable text boxes. The page
           also ships as a web presentation, and a second agent turns it into
           a motion-design MP4. When Claude cannot, the deck falls back to
           JSON drawn on one of the fixed themes below.

Both run in the background: a PDF takes 30 to 90 seconds, a designed deck
five to fifteen minutes, and its motion version follows in five to ten more.
The first page goes on the display when it is done, and the file opens.
Files land in <Documents>/JARVIS/documents.
"""
from __future__ import annotations

import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

from actions.chart_maker import _num
from core import gemini, jobs
from core.user_dirs import jarvis_documents_dir

# Long-form writing wants a REST model if Gemini ever has to step in: the Live
# rung returns its answer as a transcript of speech, which is the wrong way to
# carry ten thousand characters of HTML. Claude is asked first regardless.
_WRITER = "gemini-3.5-flash"
_WRITE_TIMEOUT_MS = 240_000

THEMES = {
    "dark":  {"bg": "0B1220", "surface": "131C2E", "text": "E8EEF7", "muted": "9AA8BD",
              "accent": "22D3EE", "accent2": "F59E0B"},
    "light": {"bg": "FFFFFF", "surface": "F1F5F9", "text": "1B2430", "muted": "5B6B7D",
              "accent": "2563EB", "accent2": "F97316"},
    "bold":  {"bg": "111111", "surface": "1D1D1D", "text": "FAFAFA", "muted": "A3A3A3",
              "accent": "FF4D2E", "accent2": "FFD400"},
}


# ── Inputs ───────────────────────────────────────────────────────────────────

def _read_source(path: str, limit: int = 40_000) -> str:
    p = Path(path).expanduser()
    ext = p.suffix.lower()
    try:
        if ext == ".pdf":
            import pdfplumber
            with pdfplumber.open(str(p)) as pdf:
                text = "\n".join((pg.extract_text() or "") for pg in pdf.pages[:60])
        elif ext == ".docx":
            import docx
            text = "\n".join(par.text for par in docx.Document(str(p)).paragraphs)
        elif ext == ".pptx":
            from pptx import Presentation
            text = "\n".join(sh.text_frame.text for sl in Presentation(str(p)).slides
                             for sh in sl.shapes if sh.has_text_frame)
        else:
            text = p.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"[could not read {p.name}: {e}]"
    return text[:limit]


def _slug(text: str) -> str:
    try:
        from core.fuzzy_find import normalize
        text = normalize(text)
    except Exception:
        pass
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:48] or "document"


def _open(path: Path) -> None:
    try:
        if sys.platform == "win32":
            os.startfile(str(path))                         # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
    except Exception as e:
        print(f"[Document] could not open {path}: {e}")


def _preview(pdf_path: Path) -> Path | None:
    """First page of a PDF as a PNG, for the display."""
    try:
        import pypdfium2 as pdfium
        doc = pdfium.PdfDocument(str(pdf_path))
        img = doc[0].render(scale=1.6).to_pil()
        out = Path(tempfile.gettempdir()) / f"jarvis-preview-{int(time.time() * 1000)}.png"
        img.save(out)
        return out
    except Exception as e:
        print(f"[Document] preview failed: {e}")
        return None


# ── PDF ──────────────────────────────────────────────────────────────────────

def _pdf_prompt(request: str, language: str, pages: int, theme: dict, sources: str) -> str:
    return f"""Write a document as ONE complete, self-contained HTML5 page that will be
printed to PDF on A4 paper by Chromium.

WHAT THE DOCUMENT IS
{request}

Language: {language or "the language of the request"}. Length: about {pages} A4 page(s).
Today's date: {date.today().isoformat()}.
{sources}
CONTENT
- Real, specific, accurate content. Concrete facts, figures and examples; no
  filler, no placeholder text, no "lorem ipsum", no instructions to the reader
  to fill something in.
- A title block at the top (title, one-line subtitle, date), then sections with
  clear headings. Use tables, numbered steps, callout boxes, and key-figure
  highlights where they genuinely help.
- When a diagram or chart would help, draw it as inline SVG (no external images).

DESIGN
- Palette: background #{theme['bg']}, panels #{theme['surface']}, text #{theme['text']},
  secondary text #{theme['muted']}, accent #{theme['accent']}, second accent #{theme['accent2']}.
  The page background must be the palette background, edge to edge.
- @page {{ size: A4; margin: 18mm 16mm 20mm 16mm; }} and set the background on
  html and body; use print-color-adjust: exact.
- One Google Font for headings and one for body text via <link> (e.g. Inter,
  Manrope, Source Serif 4), with system fallbacks.
- Readable body size (10.5-11.5pt), generous line height, clear hierarchy.
- Avoid breaking a table row, a callout or a figure across pages
  (break-inside: avoid). No fixed heights that could clip text.
- No JavaScript.

Output ONLY the HTML, starting with <!DOCTYPE html>."""


def _html_to_pdf(html: str, out: Path, theme: dict) -> None:
    from playwright.sync_api import sync_playwright

    footer = (f"<div style=\"width:100%;font-size:8px;color:#{theme['muted']};"
              f"padding:0 16mm;text-align:right;font-family:sans-serif\">"
              f"<span class=\"pageNumber\"></span> / <span class=\"totalPages\"></span></div>")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.set_content(html, wait_until="load", timeout=45_000)
            try:
                page.wait_for_load_state("networkidle", timeout=10_000)
                page.evaluate("document.fonts.ready")
            except Exception:
                pass                     # offline: the fallback fonts print fine
            page.pdf(path=str(out), format="A4", print_background=True,
                     prefer_css_page_size=True, display_header_footer=True,
                     header_template="<span></span>", footer_template=footer)
        finally:
            browser.close()


def _make_pdf(request, language, pages, theme, sources, progress) -> Path:
    progress("Claude is writing the document")
    html = gemini.text(_pdf_prompt(request, language, pages, theme, sources),
                       tier=_WRITER, timeout_ms=_WRITE_TIMEOUT_MS)
    m = re.search(r"<!DOCTYPE html.*</html>", html or "", re.S | re.I)
    if not m:
        raise RuntimeError("the model did not return an HTML document")
    html = m.group(0)
    title = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
    name = _slug(title.group(1) if title else request[:40])
    out = jarvis_documents_dir("documents") / f"{time.strftime('%Y%m%d-%H%M%S')}-{name}.pdf"
    progress("printing the PDF")
    _html_to_pdf(html, out, theme)
    return out


# ── PPTX ─────────────────────────────────────────────────────────────────────

_DECK_SCHEMA = """{
  "title": "deck title",
  "slides": [
    {"layout": "title", "title": "...", "subtitle": "..."},
    {"layout": "section", "title": "...", "subtitle": "..."},
    {"layout": "bullets", "title": "...", "bullets": ["...", "..."]},
    {"layout": "two_columns", "title": "...", "left_title": "...", "left": ["..."],
     "right_title": "...", "right": ["..."]},
    {"layout": "stats", "title": "...", "stats": [{"value": "87%", "label": "..."}]},
    {"layout": "chart", "title": "...", "chart_type": "bar | line | pie",
     "categories": ["..."], "series": [{"name": "...", "values": [1, 2]}]},
    {"layout": "timeline", "title": "...", "steps": [{"label": "2019", "text": "..."}]},
    {"layout": "quote", "quote": "...", "author": "..."},
    {"layout": "closing", "title": "...", "subtitle": "..."}
  ]
}
Every slide may also carry "notes": the speaker notes, 2-4 sentences."""


def _pptx_prompt(request: str, language: str, slides: int, sources: str) -> str:
    return f"""Plan a presentation deck and return it as JSON.

WHAT THE DECK IS
{request}

Language: {language or "the language of the request"}. About {slides} slides.
Today's date: {date.today().isoformat()}.
{sources}
FORMAT — exactly this JSON shape; pick a layout per slide:
{_DECK_SCHEMA}

RULES
- First slide "title", last slide "closing". Vary the layouts: a deck of only
  bullet slides is a failure. Use "stats" for key numbers, "chart" only with
  real figures, "timeline" for sequences or history, "section" between parts
  of a long deck.
- Slide titles at most 60 characters. 3 to 5 bullets per slide, each at most
  110 characters, each a real statement — not a topic label.
- stats: 2 to 4 entries; timeline: 3 to 6 steps; chart: at most 8 categories
  and 3 series, numbers only.
- Real, specific, accurate content; no placeholders.

Output ONLY the JSON."""


def _rgb(hexstr: str):
    from pptx.dml.color import RGBColor
    return RGBColor.from_string(hexstr.lstrip("#").upper())


class _Deck:
    """Draws the JSON deck onto blank 16:9 slides with the chosen theme."""

    W, H = 13.333, 7.5
    FONT = "Calibri"

    def __init__(self, theme: dict):
        from pptx import Presentation
        from pptx.util import Inches
        self.t = theme
        self.prs = Presentation()
        self.prs.slide_width = Inches(self.W)
        self.prs.slide_height = Inches(self.H)
        self.n = 0
        self.sections = 0

    # primitives
    def _slide(self, bg: str | None = None):
        s = self.prs.slides.add_slide(self.prs.slide_layouts[6])
        fill = s.background.fill
        fill.solid()
        fill.fore_color.rgb = _rgb(bg or self.t["bg"])
        self.n += 1
        return s

    def _rect(self, s, x, y, w, h, color, shape=None):
        from pptx.enum.shapes import MSO_SHAPE
        from pptx.util import Inches
        r = s.shapes.add_shape(shape or MSO_SHAPE.RECTANGLE,
                               Inches(x), Inches(y), Inches(w), Inches(h))
        r.fill.solid()
        r.fill.fore_color.rgb = _rgb(color)
        r.line.fill.background()
        r.shadow.inherit = False
        return r

    def _text(self, s, x, y, w, h, text, size, color, bold=False, italic=False,
              align="left", anchor="top"):
        from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
        from pptx.util import Inches, Pt
        tb = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        tf = tb.text_frame
        tf.word_wrap = True
        tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
        tf.vertical_anchor = {"top": MSO_ANCHOR.TOP, "middle": MSO_ANCHOR.MIDDLE,
                              "bottom": MSO_ANCHOR.BOTTOM}[anchor]
        for i, line in enumerate(str(text).split("\n")):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.alignment = {"left": PP_ALIGN.LEFT, "center": PP_ALIGN.CENTER,
                           "right": PP_ALIGN.RIGHT}[align]
            r = p.add_run()
            r.text = line
            f = r.font
            f.size, f.bold, f.italic, f.name = Pt(size), bold, italic, self.FONT
            f.color.rgb = _rgb(color)
        return tb

    def _bullets(self, s, x, y, w, h, items, size):
        from pptx.oxml.ns import qn
        from pptx.util import Inches, Pt
        tb = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        tf = tb.text_frame
        tf.word_wrap = True
        tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
        for i, item in enumerate(items):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.space_after = Pt(size * 0.7)
            p.line_spacing = 1.08
            # A real bullet with a hanging indent, so a wrapped line lines up
            # with the text above it instead of running under the marker.
            # Appended after the spacing elements python-pptx just wrote, which
            # is the order the schema requires.
            pPr = p._p.get_or_add_pPr()
            pPr.set("marL", str(int(Pt(size * 1.25))))
            pPr.set("indent", str(-int(Pt(size * 1.25))))
            clr = pPr.makeelement(qn("a:buClr"), {})
            clr.append(clr.makeelement(qn("a:srgbClr"), {"val": self.t["accent"]}))
            pPr.append(clr)
            pPr.append(pPr.makeelement(qn("a:buSzPct"), {"val": "60000"}))
            pPr.append(pPr.makeelement(qn("a:buFont"), {"typeface": "Arial"}))
            pPr.append(pPr.makeelement(qn("a:buChar"), {"char": "■"}))
            r = p.add_run()
            r.text = str(item)
            r.font.size, r.font.name = Pt(size), self.FONT
            r.font.color.rgb = _rgb(self.t["text"])

    def _title(self, s, title):
        size = 34 if len(title) <= 40 else 28
        self._text(s, 0.8, 0.55, self.W - 1.6, 0.9, title, size, self.t["text"], bold=True,
                   anchor="bottom")
        self._rect(s, 0.8, 1.55, 1.1, 0.07, self.t["accent"])

    def _footer(self, s):
        self._text(s, self.W - 1.6, self.H - 0.55, 0.9, 0.3, str(self.n), 11,
                   self.t["muted"], align="right")

    @staticmethod
    def _notes(s, notes):
        if notes:
            s.notes_slide.notes_text_frame.text = str(notes)

    # layouts
    def title(self, d, closing=False):
        s = self._slide()
        self._rect(s, 0, 0, 0.28, self.H, self.t["accent"])
        t = d.get("title", "")
        self._text(s, 1.1, 2.0 if not closing else 2.6, self.W - 2.2, 2.0, t,
                   54 if len(t) <= 34 else 42, self.t["text"], bold=True, anchor="bottom")
        if d.get("subtitle"):
            self._text(s, 1.1, 4.25 if not closing else 4.85, self.W - 2.6, 1.2,
                       d["subtitle"], 22, self.t["muted"])
        if not closing:
            self._text(s, 1.1, self.H - 1.0, 4, 0.4, date.today().strftime("%d/%m/%Y"),
                       13, self.t["accent"])
        return s

    def section(self, d):
        s = self._slide(self.t["surface"])
        self.sections += 1
        self._text(s, 0.8, 1.6, 3.5, 2.2, f"{self.sections:02d}", 110, self.t["accent"],
                   bold=True)
        self._text(s, 0.8, 3.9, self.W - 1.6, 1.2, d.get("title", ""), 44,
                   self.t["text"], bold=True)
        if d.get("subtitle"):
            self._text(s, 0.8, 5.05, self.W - 1.6, 1.0, d["subtitle"], 20, self.t["muted"])
        return s

    def bullets(self, d):
        s = self._slide()
        self._title(s, d.get("title", ""))
        items = [str(b) for b in (d.get("bullets") or [])][:7]
        longest = max((len(b) for b in items), default=0)
        size = 30 if len(items) <= 3 else 26 if len(items) <= 5 else 22
        if longest > 90:
            size -= 2
        self._bullets(s, 0.8, 2.15, self.W - 1.6, self.H - 2.9, items, size)
        self._footer(s)
        return s

    def two_columns(self, d):
        s = self._slide()
        self._title(s, d.get("title", ""))
        cw = (self.W - 1.6 - 0.4) / 2
        for i, side in enumerate(("left", "right")):
            x = 0.8 + i * (cw + 0.4)
            self._rect(s, x, 2.0, cw, self.H - 2.8, self.t["surface"])
            self._rect(s, x, 2.0, cw, 0.07, self.t["accent"] if i == 0 else self.t["accent2"])
            self._text(s, x + 0.35, 2.3, cw - 0.7, 0.6, d.get(f"{side}_title", ""), 22,
                       self.t["accent"] if i == 0 else self.t["accent2"], bold=True)
            items = [str(b) for b in (d.get(side) or [])][:6]
            self._bullets(s, x + 0.35, 3.05, cw - 0.7, self.H - 4.1, items,
                          20 if len(items) <= 3 else 18 if len(items) <= 4 else 16)
        self._footer(s)
        return s

    def stats(self, d):
        s = self._slide()
        self._title(s, d.get("title", ""))
        items = list(d.get("stats") or [])[:4] or [{"value": "—", "label": ""}]
        gap = 0.35
        cw = (self.W - 1.6 - gap * (len(items) - 1)) / len(items)
        for i, st in enumerate(items):
            x = 0.8 + i * (cw + gap)
            self._rect(s, x, 2.3, cw, 3.6, self.t["surface"])
            val = str(st.get("value", ""))
            self._text(s, x + 0.3, 2.7, cw - 0.6, 1.5, val,
                       60 if len(val) <= 5 else 44, self.t["accent"], bold=True, anchor="middle")
            self._text(s, x + 0.3, 4.35, cw - 0.6, 1.4, str(st.get("label", "")), 17,
                       self.t["text"])
        self._footer(s)
        return s

    def chart(self, d):
        from pptx.chart.data import CategoryChartData
        from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
        from pptx.util import Inches, Pt

        s = self._slide()
        self._title(s, d.get("title", ""))
        cats = [str(c) for c in (d.get("categories") or [])][:8]
        series = list(d.get("series") or [])[:3]
        kind = str(d.get("chart_type") or "bar").lower()
        if not cats or not series:
            return self.bullets({"title": d.get("title", ""), "bullets": d.get("bullets") or []})
        data = CategoryChartData()
        data.categories = cats
        for se in series:
            # chart_maker's parser: "0,21", "1 234,5" and "12 %" are all
            # figures a French request will produce.
            vals = [v if v == v else 0.0            # NaN -> 0
                    for v in (_num(x) for x in list(se.get("values") or [])[:len(cats)])]
            vals += [0.0] * (len(cats) - len(vals))
            data.add_series(str(se.get("name") or ""), vals)
        ctype = {"line": XL_CHART_TYPE.LINE_MARKERS, "pie": XL_CHART_TYPE.DOUGHNUT}.get(
            kind, XL_CHART_TYPE.COLUMN_CLUSTERED)
        gf = s.shapes.add_chart(ctype, Inches(0.8), Inches(1.95), Inches(self.W - 1.6),
                                Inches(self.H - 2.7), data)
        ch = gf.chart
        ch.has_title = False                 # the slide title already says it
        ch.font.size, ch.font.name = Pt(14), self.FONT
        ch.font.color.rgb = _rgb(self.t["text"])
        palette = [self.t["accent"], self.t["accent2"], self.t["muted"], "8B5CF6",
                   "10B981", "EC4899", "64748B", "EAB308"]
        plot = ch.plots[0]
        if kind == "pie":
            ch.has_legend = True
            ch.legend.position = XL_LEGEND_POSITION.RIGHT
            ch.legend.include_in_layout = False
            plot.has_data_labels = True
            plot.data_labels.show_percentage = True
            plot.data_labels.show_value = False
            plot.data_labels.number_format = "0%"
            plot.data_labels.number_format_is_linked = False
            for i, pt in enumerate(plot.series[0].points):
                pt.format.fill.solid()
                pt.format.fill.fore_color.rgb = _rgb(palette[i % len(palette)])
        else:
            ch.has_legend = len(series) > 1
            if ch.has_legend:
                ch.legend.position = XL_LEGEND_POSITION.TOP
                ch.legend.include_in_layout = False
            for i, se in enumerate(plot.series):
                col = _rgb(palette[i % len(palette)])
                if kind == "line":
                    se.format.line.color.rgb = col
                    se.format.line.width = Pt(3)
                    se.smooth = False
                else:
                    se.format.fill.solid()
                    se.format.fill.fore_color.rgb = col
            if kind != "line":
                plot.gap_width = 80
            va = ch.value_axis
            va.major_gridlines.format.line.color.rgb = _rgb(self.t["surface"])
            va.format.line.fill.background()
            ch.category_axis.format.line.color.rgb = _rgb(self.t["muted"])
        self._footer(s)
        return s

    def timeline(self, d):
        from pptx.enum.shapes import MSO_SHAPE
        s = self._slide()
        self._title(s, d.get("title", ""))
        steps = list(d.get("steps") or [])[:6]
        if not steps:
            return s
        y = 3.4
        self._rect(s, 0.8, y + 0.17, self.W - 1.6, 0.06, self.t["muted"])
        cw = (self.W - 1.6) / len(steps)
        for i, st in enumerate(steps):
            cx = 0.8 + cw * i + cw / 2
            self._rect(s, cx - 0.2, y, 0.4, 0.4,
                       self.t["accent"] if i % 2 == 0 else self.t["accent2"], MSO_SHAPE.OVAL)
            self._text(s, cx - cw / 2 + 0.1, y - 1.0, cw - 0.2, 0.8, str(st.get("label", "")),
                       22, self.t["accent"], bold=True, align="center", anchor="bottom")
            self._text(s, cx - cw / 2 + 0.15, y + 0.75, cw - 0.3, 2.6, str(st.get("text", "")),
                       15 if len(steps) > 4 else 17, self.t["text"], align="center")
        self._footer(s)
        return s

    def quote(self, d):
        s = self._slide(self.t["surface"])
        self._text(s, 0.9, 0.6, 2, 2, "“", 160, self.t["accent"], bold=True)
        q = str(d.get("quote", ""))
        self._text(s, 1.6, 2.2, self.W - 3.2, 3.0, q, 34 if len(q) <= 120 else 26,
                   self.t["text"], italic=True, anchor="middle")
        if d.get("author"):
            self._text(s, 1.6, 5.5, self.W - 3.2, 0.6, f"— {d['author']}", 20,
                       self.t["muted"])
        return s

    def build(self, spec: dict, out: Path) -> int:
        slides = [sl for sl in (spec.get("slides") or []) if isinstance(sl, dict)]
        if not slides:
            raise RuntimeError("the deck has no slides")
        for sl in slides:
            layout = str(sl.get("layout") or "bullets").lower()
            draw = {"title": self.title, "section": self.section,
                    "bullets": self.bullets, "two_columns": self.two_columns,
                    "stats": self.stats, "chart": self.chart,
                    "timeline": self.timeline, "quote": self.quote,
                    "closing": lambda d: self.title(d, closing=True)}.get(layout, self.bullets)
            try:
                s = draw(sl)
            except Exception as e:                      # one odd slide, not the deck
                print(f"[Document] slide '{layout}' failed ({e}) — drawn as bullets")
                s = self.bullets({"title": sl.get("title", ""),
                                  "bullets": sl.get("bullets") or []})
            self._notes(s, sl.get("notes"))
        self.prs.save(str(out))
        return len(slides)


def _pptx_preview(pptx: Path) -> Path | None:
    """Slide 1 as a PNG through LibreOffice, when it is installed."""
    exe = shutil.which("soffice") or shutil.which("libreoffice")
    if not exe:
        return None
    tmp = Path(tempfile.mkdtemp(prefix="jarvis-pptx-"))
    # Its own profile, or a LibreOffice window the user has open makes the
    # conversion fail silently.
    profile = (tmp / "profile").as_uri()
    try:
        subprocess.run([exe, f"-env:UserInstallation={profile}", "--headless",
                        "--convert-to", "pdf", "--outdir", str(tmp), str(pptx)],
                       capture_output=True, timeout=90)
        pdf = tmp / (pptx.stem + ".pdf")
        return _preview(pdf) if pdf.exists() else None
    except Exception as e:
        print(f"[Document] pptx preview failed: {e}")
        return None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)    # the profile alone is megabytes


# ── PPTX, designed by a Claude agent ─────────────────────────────────────────
# The JSON deck above always comes out as the same nine templates on one of
# three palettes. Here Claude (Opus, as an agent) is the designer, and it
# designs where it is strongest: a web page. It picks an art direction for this
# subject and audience, writes the slides as HTML and CSS, looks at them in a
# real browser and fixes what it sees, then core/html_deck.py turns the page
# into PowerPoint — the design as each slide's background, the words as native
# text boxes. The same page ships as a web presentation, and a second agent
# turns it into a motion-design video. The JSON deck stays as the fallback
# when Claude cannot do it.

_DESIGN_TIMEOUT = 1500.0
_MOTION_TIMEOUT = 1200.0
_STYLE_HISTORY = 12

# Thrown into the brief at random, three at a time. Left alone a model drifts
# back to its favourite look — navy, one cyan accent, a thin rule under the
# title — so a deck about Roman history and a startup pitch end up twins. These
# break the habit; the subject still decides.
_DIRECTIONS = (
    "Swiss typographic: strict grid, oversized grotesk headings, one strong colour on white",
    "editorial magazine: serif display type, pull quotes, asymmetric columns, warm paper tone",
    "keynote dark: near-black stage, one vivid accent, huge numbers, very little text",
    "Bauhaus geometry: primary colours, circles and bars as structure, bold blocks",
    "soft and friendly: pastel palette, rounded shapes, generous friendly sans",
    "brutalist: raw black and white, giant type, hard borders, one shock colour",
    "premium corporate: deep ink blue and ivory, restrained gold, serif + sans pairing",
    "organic nature: earthy greens and sand, blob shapes, humanist sans",
    "70s retro: warm orange, brown and cream, heavy rounded display type, stripes",
    "80s synthwave: neon pink and cyan on deep purple, grid horizon, chrome titles",
    "academic poster: clean white, figure-first, numbered sections, serif body text",
    "blueprint: engineering blue, white line work, monospace annotations, grid paper",
    "broadsheet newspaper: columns, hairline rules, condensed headline serif, newsprint",
    "luxury minimal: black and ivory, thin high-contrast serif, vast margins",
    "startup pitch: bold colour blocks, product-like cards, punchy one-line claims",
    "Japanese minimal: off-white, one red accent, vertical rhythm, lots of air",
    "data journalism: charts lead, annotated figures, greys plus one highlight colour",
    "sketchbook: kraft-paper tone, marker-like accents, casual hand-feel type",
    "art deco: black and gold, geometric ornament, tall condensed display type",
    "Memphis 90s: confetti shapes, bright clashing colours, playful layouts",
    "material cards: light grey canvas, white cards, colourful category chips",
    "monochrome: every shade of a single hue, depth from tints only",
    "glass and gradients: soft multi-colour gradients, translucent cards, airy sans",
    "museum label: gallery white, small precise captions, one artwork-like visual per slide",
)


def _history_file() -> Path:
    from core import claude
    return claude.workspace() / ".deck_styles.json"


def _style_history() -> list[dict]:
    try:
        data = json.loads(_history_file().read_text(encoding="utf-8"))
        return [d for d in data if isinstance(d, dict)] if isinstance(data, list) else []
    except Exception:
        return []


def _remember_style(style: dict, request: str) -> None:
    entry = {"date": date.today().isoformat(), "request": " ".join(request.split())[:80],
             "name": str(style.get("name") or "")[:80],
             "summary": str(style.get("summary") or "")[:240],
             "palette": [str(c) for c in (style.get("palette") or [])][:8],
             "fonts": [str(f) for f in (style.get("fonts") or [])][:4]}
    hist = (_style_history() + [entry])[-_STYLE_HISTORY:]
    try:
        _history_file().write_text(json.dumps(hist, ensure_ascii=False, indent=1),
                                   encoding="utf-8")
    except Exception as e:
        print(f"[Document] could not save the style history: {e}")


def _design_brief(job: Path, request: str, language: str, slides: int, style: str,
                  has_sources: bool) -> str:
    recent = _style_history()[-6:]
    if recent:
        seen = "\n".join(f"- {h.get('name')}: {h.get('summary')} — palette "
                         f"{', '.join(h.get('palette') or [])}; fonts "
                         f"{', '.join(h.get('fonts') or [])}" for h in recent)
        recent_txt = ("RECENT DECKS — this user has already seen these looks. Yours must "
                      "be clearly different from every one of them (palette, type, "
                      "layout language), unless the user's own style request asks for "
                      f"one:\n{seen}\n")
    else:
        recent_txt = ""
    ideas = "\n".join(f"- {d}" for d in random.sample(_DIRECTIONS, 3))
    html, kit = job / "deck.html", job / "kit.py"
    try:
        from actions.image_generator import _pollinations_key
        keyed = bool(_pollinations_key())
    except Exception:
        keyed = False
    pictures = ("about 10 s each: use up to 6, wherever a picture beats shapes"
                if keyed else
                "up to a minute each: at most 3, only where a picture beats shapes")
    return f"""You are a world-class presentation designer and a sharp writer — the
level of the studios behind Apple keynotes, Pentagram brand decks and the best
editorial data stories. You work alone and unattended: nobody will answer a
question, so decide and deliver.

You build the deck as a WEB PAGE first — HTML and CSS, where you design best —
check it in a real browser, then convert it to PowerPoint with the bench.

WHERE THINGS ARE
- Job folder: {job}  (absolute paths everywhere; no `cd`, no `&&`)
- The deck: {html}   pictures: {job}/img/
- Bench: {kit}
    python3 {kit} font "Family Name"    install a Google Font (a few seconds)
    python3 {kit} fonts                 families already installed
    python3 {kit} image "prompt" {job}/img/name --aspect landscape|square|portrait|wide
        an AI-generated picture (English prompt: describe a photo or an
        illustration in the deck's art direction). One call at a time,
        {pictures}. If a call fails, do not call it again: design without
    python3 {kit} html {html}
        every slide as a 1920x1080 PNG, contact sheets, and a lint
    python3 {kit} pptx {html} {job}/deck.pptx
        the PowerPoint, plus comparison sheets (HTML left, PowerPoint right)
{f"- Source material: {job}/sources.txt — read it first; the deck is built from it and must not contradict it" if has_sources else ""}

THE DECK
- Request: in the user message.
- Language of every word on the slides and in the notes: {language or "the language of the request"}.
- About {slides} slides. Today's date: {date.today().isoformat()}.
- Style asked by the user: {style or "none — you choose, from the subject, audience and tone"}.

1. ART DIRECTION FIRST
Before any code, decide a direction that fits THIS subject, audience and tone —
a kids' science class, an investor pitch, a history lecture and a security
audit must not look alike. Fix it as a small design system:
- a concept in one line, and a visual motif you repeat across slides
- a palette of 3 to 6 hex colours with roles; text contrast at least 4.5:1
- a type pairing: at most two Google Fonts families (display + text) with real
  character, and a clear scale. Never the default look (Arial, Calibri,
  Liberation, DejaVu).
- a layout language: grid, margins, where titles sit, how images behave.
Ideas to break habit (random — use one only if it truly fits, or ignore them):
{ideas}
{recent_txt}
Save it to {job}/style.json as
{{"name": "...", "summary": "one sentence", "palette": ["#RRGGBB", ...], "fonts": ["...", "..."]}}

2. CONTENT
- One idea per slide. Titles state the takeaway ("Sales doubled after the
  redesign"), not the topic ("Sales").
- Real, specific, accurate content: facts, figures, examples. No placeholders.
  If unsure of a figure, round it and say "about", or leave it out.
- Little text on screen (usually under 35 words); the detail goes in the
  speaker notes, 2 to 4 sentences on every slide.
- A real cover first; the last slide closes (key message, next steps, thanks).

3. THE PAGE — technical contract
- One HTML file. Each slide is <section class="slide">, exactly 1920 x 1080 px,
  position: relative; overflow: hidden; slides follow each other in the page.
  Size everything in px — no vw/vh.
- Each slide holds its notes: <aside class="notes">...</aside>. <title> = deck title.
- Fonts: install them with the bench, then use them by family name in CSS. No
  @import and no <link> for fonts. Only the weights the family has.
- Images: relative img/... paths only, no remote images. Draw illustrations,
  icons, diagrams and charts as inline SVG — they are part of the design.
- Use the whole of CSS: grid, gradients (linear, radial, conic), clip-path,
  masks, mix-blend-mode, filters, shadows, pseudo-elements, object-fit crops,
  duotone images, SVG noise textures, oversized background type.
- Not allowed: animation or transitions (this is the still deck), scripts that
  change the layout after load, hyphens: auto, <canvas> text, iframes, video.
- Text sizes: nothing under 24 px; body 28-40 px; titles 56-110 px; display
  type as big as the design wants.

4. TEXT STAYS EDITABLE IN POWERPOINT
The converter keeps each slide's design pixel-perfect as its background and
rebuilds the words as real PowerPoint text boxes — same place, font, size,
colour, line breaks. Plain text (headings, paragraphs, list items, spans)
becomes editable. Text that is rotated or scaled, gradient-filled
(background-clip: text), outlined, shadowed, blurred, blended, inside SVG or
marked data-raster stays in the picture: identical look, not editable. Use
those effects for display type and decoration when they serve the design; keep
titles, body text, figures and labels plain so they can be edited.

5. MAKE IT STRIKING
- One focal point per slide, readable in two seconds. Hierarchy from scale
  contrast (a 220 px figure beside a 28 px label), weight and colour — not
  from boxes around everything.
- A 12-column grid, margins of at least 96 px, a steady vertical rhythm;
  titles in the same place except on slides that break the grid on purpose
  (cover, section breaks, statements).
- Vary the structures: statement, big figure, SVG chart with real data (one
  highlighted series, direct labels instead of a legend), comparison, process
  or timeline, image-led slide with a bold crop, quote, table, grid of items,
  section break. Never three slides in a row with the same structure.
- Typographic craft: tight tracking on big display type, 1.35-1.5 line height
  for body, 60-70 characters per line at most, tabular figures for numbers.
  In French: « guillemets », and &nbsp; before : ; ! ? and inside « ».
- Colour with intent: one dominant, one accent kept for emphasis.
- Details that read as designed, not generated: layering and overlap, bold
  image crops, hairlines, small captions and numbered labels, subtle texture.
- Avoid the generic AI-deck look: emoji as icons, the same three-card row on
  every slide, everything centred, gradient blobs for no reason,
  glassmorphism by default, neon unless asked, walls of bullets.

6. WORK LIKE A DESIGNER
a. Direction and style.json; install the fonts; make the pictures.
b. Write deck.html, then run the bench's html command and Read every contact
   sheet; open single slides that look doubtful. Fix every lint issue and
   everything you see — alignment, spacing, hierarchy, balance, contrast,
   crowding, repetition. Be your harshest critic: two to four rounds until it
   would win a design award.
c. Run the pptx command and Read the comparison sheets. Both sides must match;
   where a text block drifts, simplify its CSS or mark it data-raster.
d. {job}/deck.pptx must exist when you finish. Keep the job under about 15 minutes.

When done, reply with ONE short sentence (in the deck's language) naming the
style you chose and why it fits — the voice assistant reads it to the user."""


def _motion_brief(job: Path, n_slides: int, language: str) -> str:
    from actions.create_motion_video import _GSAP
    total = max(20, min(90, n_slides * 5))
    kit = job / "kit.py"
    return f"""You are a senior motion designer. The slide deck in {job}/deck.html
(read it, and {job}/style.json) becomes a motion-design video: same art
direction — palette, fonts, pictures in {job}/img/, motifs — made to move. You
work alone and unattended: decide and deliver.

Write {job}/motion.html: one page, rendered frame by frame into a 1920x1080
MP4 at 30 fps.

STORY
- One scene per slide (merge or drop weak ones), 4 to 7 s each, about {total} s
  in total and never more than 90. Open on the cover, close on an end card.
- Condense: each scene carries the slide's key message, figures and visuals,
  not its paragraphs. On-screen text: at least 40 px, on screen at least 0.3 s
  per word. Language: {language or "the deck's language"}.

MOTION
- Kinetic typography, staggered reveals, mask and clip-path wipes, counters
  for key figures, charts that draw themselves (SVG stroke-dashoffset),
  parallax on pictures, depth from scale, opacity and blur.
- Purposeful easing (power3 / expo out; linear only for constant drifts).
- Transitions in the deck's own language (wipes, pushes, match cuts on the
  motif). Each scene holds its final composition for about 0.8 s.

HARD TECHNICAL RULES — the renderer depends on them
- html, body {{ margin: 0; width: 1920px; height: 1080px; overflow: hidden; }}
  with a full-bleed background.
- <meta name="duration" content="SECONDS"> in <head>: the exact total length.
- It starts by itself on load; nothing waits for clicks, scroll or audio.
- Time comes ONLY from CSS animations/transitions, element.animate(), GSAP
  (<script src="{_GSAP}"></script>; plugins from the same cdnjs folder),
  requestAnimationFrame's timestamp, performance.now() or setTimeout /
  setInterval. Build the GSAP timeline at load. No <video>, <audio>, GIF,
  Lottie or WebGL.
- Fonts: the deck's installed families, by name. Pictures: img/... paths.
- No console errors.

WORK
- Write motion.html, then: python3 {kit} motion {job}/motion.html
  (frames spread over the video; add --at 1.5,7.2 for precise moments). Read
  the frame sheets and fix text off-frame or cut, overlaps, empty or
  unbalanced frames, unreadable moments, an unfinished ending. Two or three
  rounds; keep the job under about 10 minutes. Absolute paths; no cd, no &&.

When done, reply with ONE short sentence (in the video's language) describing it."""


def _kit_shim(job: Path) -> None:
    repo = Path(__file__).resolve().parent.parent
    (job / "kit.py").write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(repo)!r})\n"
        "from core.deck_kit import main\n"
        "sys.exit(main())\n", encoding="utf-8")


def _design_pptx(request, language, slides, style, sources, progress,
                 keep_job: bool = False) -> dict:
    """The agent route: the deck as a web page, then PowerPoint. Returns
    {pptx, web, slides, said, preview, title, job}. `job` is the working folder,
    kept for the motion version when keep_job is set (its caller removes it);
    otherwise it is gone. Raises when the agent did not deliver."""
    from core import claude, html_deck
    from pptx import Presentation

    job = Path(tempfile.mkdtemp(prefix="jarvis-deck-"))
    keep = False
    try:
        _kit_shim(job)
        (job / "img").mkdir()
        if sources:
            (job / "sources.txt").write_text(sources, encoding="utf-8")

        def on_event(ev):
            act = claude.tool_activity(ev)
            if act:
                progress(act.replace(str(job) + "/", ""))

        progress(f"Claude ({claude.model_for(claude.AGENT)}) is designing the deck")
        res = claude.agent(request, append_system=_design_brief(
                               job, request, language, slides, style, bool(sources)),
                           add_dirs=[str(job)], timeout=_DESIGN_TIMEOUT, on_event=on_event)
        html = job / "deck.html"
        if not html.exists():
            raise RuntimeError(f"the designer finished without a deck: {res.text[:200]}")
        deck = job / "deck.pptx"
        if not deck.exists() or deck.stat().st_mtime < html.stat().st_mtime:
            progress("converting the page to PowerPoint")       # the agent skipped it
            html_deck.to_pptx(html, deck, job / "convert")
        prs = Presentation(str(deck))                 # also proves the file is valid
        count = len(prs.slides)
        if not count:
            raise RuntimeError("the designer's deck has no slides")

        try:
            style_info = json.loads((job / "style.json").read_text(encoding="utf-8"))
            if isinstance(style_info, dict):
                _remember_style(style_info, request)
        except Exception:
            pass

        title = prs.core_properties.title or request[:40]
        stem = f"{time.strftime('%Y%m%d-%H%M%S')}-{_slug(title)}"
        out_dir = jarvis_documents_dir("documents")
        out = out_dir / f"{stem}.pptx"
        shutil.copy2(deck, out)
        web = None
        try:
            _, _, fams = html_deck.shoot(html, job / "final")
            web = html_deck.export_web(html, out_dir / f"{stem}.html", fams)
        except Exception as e:
            print(f"[Document] web version failed: {e}")
        preview = None
        first = job / "final" / "slide-01.png"
        if first.exists():
            preview = Path(tempfile.gettempdir()) / f"jarvis-preview-{int(time.time() * 1000)}.png"
            shutil.copy2(first, preview)
        keep = keep_job
        return {"pptx": out, "web": web, "slides": count, "said": res.text.strip()[:300],
                "preview": preview, "title": title, "job": job if keep else None}
    finally:
        if not keep:
            shutil.rmtree(job, ignore_errors=True)


def _start_motion(player, job: Path, request: str, title: str, slides: int,
                  language: str) -> None:
    """The motion-design version of a finished deck, as its own background job."""
    from actions import create_motion_video as cmv
    from core import claude, html_deck
    from core.user_dirs import jarvis_videos_dir

    def work(progress) -> str:
        t0 = time.monotonic()
        try:
            if not cmv._ffmpeg():
                raise RuntimeError("video encoding is not available (pip install imageio-ffmpeg)")

            def on_event(ev):
                act = claude.tool_activity(ev)
                if act:
                    progress(act.replace(str(job) + "/", ""))

            progress(f"Claude ({claude.model_for(claude.AGENT)}) is animating the deck")
            res = claude.agent(f"Make the motion-design version of this deck. The original "
                               f"request was: {request}",
                               append_system=_motion_brief(job, slides, language),
                               add_dirs=[str(job)], timeout=_MOTION_TIMEOUT,
                               on_event=on_event)
            page = job / "motion.html"
            if not page.exists():
                raise RuntimeError(f"the motion designer finished without a page: {res.text[:160]}")
            html = page.read_text(encoding="utf-8", errors="replace")
            dur = max(5.0, min(html_deck.motion_duration(html, 30.0), 120.0))
            html = html_deck.inline_assets(html, job)
            out_dir = jarvis_videos_dir("motion")
            stem = f"{time.strftime('%Y%m%d-%H%M%S')}-{_slug(title)}"
            out = out_dir / f"{stem}.mp4"
            progress(f"rendering {round(dur * 30)} frames")
            errors, _ = cmv._render(html, out, 1920, 1080, 30, dur, [dur / 2], progress)
            (out_dir / f"{stem}.html").write_text(html, encoding="utf-8")
            if player is not None and hasattr(player, "show_video"):
                player.show_video(str(out), f"MOTION — {out.name}", muted=True)
            warn = f" The page reported: {errors[0]}." if errors else ""
            return (f"The motion-design version of the deck is ready after "
                    f"{time.monotonic() - t0:.0f}s ({dur:g} s video, playing on the "
                    f"display): {out}. Claude's note: {res.text.strip()[:240]}.{warn} "
                    f"Tell the user in one sentence and name the folder.")
        finally:
            shutil.rmtree(job, ignore_errors=True)

    jobs.start(player, f"MOTION — {' '.join(title.split())[:46]}", work)


def _make_pptx(request, language, slides, theme, sources, progress) -> tuple[Path, int]:
    progress("Claude is planning the slides")
    spec = gemini.as_json(_pptx_prompt(request, language, slides, sources),
                          tier=_WRITER, timeout_ms=_WRITE_TIMEOUT_MS)
    if not isinstance(spec, dict) or not spec.get("slides"):
        raise RuntimeError("the model did not return a usable slide plan")
    name = _slug(str(spec.get("title") or request[:40]))
    out = jarvis_documents_dir("documents") / f"{time.strftime('%Y%m%d-%H%M%S')}-{name}.pptx"
    progress(f"drawing {len(spec['slides'])} slides")
    count = _Deck(theme).build(spec, out)
    return out, count


# ── Tool ─────────────────────────────────────────────────────────────────────

def create_document(parameters: dict, player=None) -> str:
    p = parameters or {}
    fmt = str(p.get("format") or "").lower().strip().lstrip(".")
    fmt = {"powerpoint": "pptx", "ppt": "pptx", "slides": "pptx", "presentation": "pptx",
           "deck": "pptx"}.get(fmt, fmt)
    if fmt not in ("pdf", "pptx"):
        return "Say which format: 'pdf' for a document, 'pptx' for a PowerPoint deck."
    request = str(p.get("request") or "").strip()
    if not request:
        return "Describe the document in 'request': subject, audience, what it must cover."
    language = str(p.get("language") or "").strip()
    style = str(p.get("style") or "").strip()
    theme = THEMES.get(str(p.get("theme") or "").lower(),
                       THEMES["light"] if fmt == "pdf" else random.choice(list(THEMES.values())))
    size = int(p.get("length") or (3 if fmt == "pdf" else 10))
    size = max(1, min(size, 20 if fmt == "pdf" else 30))
    open_after = p.get("open", True) is not False
    motion = fmt == "pptx" and p.get("motion", True) is not False

    sources = ""
    files = [str(f) for f in (p.get("source_files") or []) if str(f).strip()]
    if files:
        parts = [f"--- {Path(f).name} ---\n{_read_source(f)}" for f in files[:5]]
        sources = ("\nSOURCE MATERIAL — build the document from this; do not "
                   "contradict it:\n" + "\n\n".join(parts) + "\n")

    label = f"{'PDF' if fmt == 'pdf' else 'SLIDES'} — {' '.join(request.split())[:44]}"

    def work(progress) -> str:
        t0 = time.monotonic()
        extra = ""
        if fmt == "pdf":
            out = _make_pdf(request, language, size, theme, sources, progress)
            preview, what = _preview(out), "PDF"
        else:
            from core import claude
            out, said, deck = None, "", None
            if claude.enabled():
                try:
                    deck = _design_pptx(request, language, size, style, sources, progress,
                                        keep_job=motion)
                    out, n, said, preview = deck["pptx"], deck["slides"], deck["said"], deck["preview"]
                except Exception as e:                  # the JSON deck still delivers
                    print(f"[Document] the designer failed: {e}")
                    progress("the designer failed — using the standard layout")
            if out is None:
                out, n = _make_pptx(request, language, size, theme, sources, progress)
                preview = _pptx_preview(out)
            what = f"{n}-slide PowerPoint deck"
            if said:
                what += f" (designer's note: {said})"
            if deck and deck.get("web"):
                extra += (f" Its web version is next to it: {deck['web'].name} (opens in "
                          f"any browser, arrow keys to move, F for full screen).")
            if deck and deck.get("job"):
                _start_motion(player, deck["job"], request, deck["title"], n, language)
                extra += (" The motion-design video version is now being made in the "
                          "background (about five to ten minutes); say it is coming.")
        if preview and player is not None and hasattr(player, "show_image"):
            player.show_image(str(preview), f"{'PDF' if fmt == 'pdf' else 'PPTX'} — {out.name}")
        if open_after:
            _open(out)
        return (f"The {what} is ready after {time.monotonic() - t0:.0f}s: {out}"
                f"{' (opened, first page on the display)' if open_after else ''}.{extra} "
                f"Tell the user in one or two sentences and name the folder.")

    jobs.start(player, label, work)
    took = "30 to 90 seconds" if fmt == "pdf" else "five to fifteen minutes"
    return (f"status=started_in_background. Claude is making it ({took}); "
            "you will be told when it is ready. Say one short sentence.")


TOOL = {
    "name": "create_document",
    "description": (
        "Creates a finished document file: a PDF (report, course notes, cheat "
        "sheet, letter, guide…) or a slide deck. A deck comes as a PowerPoint "
        "(.pptx, editable text), a web version of it (.html) and, unless motion "
        "is false, a motion-design video version (.mp4) made right after. Claude "
        "writes the content from the request and optional source files and "
        "designs each deck with its own look; runs in the background and opens "
        "the file when done. Put "
        "EVERYTHING it needs in 'request': subject, audience, purpose, tone, "
        "sections or points to cover, figures from the conversation. Pass any "
        "visual wish of the user in 'style', in their words. Saved in the user's "
        "Documents/JARVIS/documents folder."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "format": {"type": "STRING", "description": "pdf | pptx"},
            "request": {"type": "STRING",
                        "description": "What the document must be and contain, with all context and figures"},
            "language": {"type": "STRING",
                         "description": "Language to write it in, e.g. 'French'"},
            "length": {"type": "INTEGER",
                       "description": "pdf: pages (default 3); pptx: slides (default 10)"},
            "style": {"type": "STRING",
                      "description": "Visual style the user asked for, in their words "
                                     "(e.g. 'minimaliste noir et blanc', 'rétro années 80', "
                                     "'sobre et corporate'). Leave empty when they did not "
                                     "say: Claude then picks a look that fits the subject"},
            "theme": {"type": "STRING",
                      "description": "pdf only: dark | light | bold (default light)"},
            "motion": {"type": "BOOLEAN",
                       "description": "pptx only: also make the motion-design video version "
                                      "(default true; false when the user does not want it)"},
            "source_files": {"type": "ARRAY", "items": {"type": "STRING"},
                             "description": "Full paths of files to build it from (pdf, docx, pptx, txt, md…)"},
            "open": {"type": "BOOLEAN", "description": "Open the file when done (default true)"},
        },
        "required": ["format", "request"],
    },
    "handler": create_document,
}
