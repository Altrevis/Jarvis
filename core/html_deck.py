"""
html_deck — a slide deck written as a web page, turned into PowerPoint.

Claude designs far better in HTML and CSS than through python-pptx: grids,
gradients, masks, blend modes, SVG, real typography. So a deck is authored as
one page of <section class="slide"> elements, 1920 x 1080 CSS px each, and this
module is everything around that page:

    shoot()       each slide as a PNG, plus a lint of what a designer would
                  catch (clipped or tiny text, overlaps, broken images, fonts)
    to_pptx()     the PowerPoint version, built in two layers per slide:
                    - the design: Chromium's own rendering of the slide with
                      its text made invisible, as the slide background, so
                      every gradient, shadow and SVG survives pixel for pixel;
                    - the words: one native text box per text block, at the
                      exact place, font, size, colour and line breaks Chromium
                      used, so the text stays editable in PowerPoint.
                  Text a text box cannot reproduce — rotated, gradient-filled,
                  blurred, outlined, blended — stays in the picture instead.
    export_web()  the same page as a self-contained web presentation (arrow
                  keys, fullscreen), images inlined, fonts linked from Google
    motion_frames() preview frames of a motion-design page under virtual time

HOW THE TEXT IS HIDDEN WITHOUT MOVING ANYTHING
    Wrapping text in elements to recolour it can change which CSS selectors
    match (:first-child, a > span) and with them the layout. The CSS Custom
    Highlight API recolours ranges instead, with no DOM change at all, and it
    leaves list markers and ::before / ::after content — decoration — in place.

UNITS
    1920 CSS px is 13.333 in, so 1 px = 6350 EMU = 0.5 pt.
"""
from __future__ import annotations

import base64
import json
import mimetypes
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

SW, SH = 1920, 1080
EMU_PX = 6350
PT_PX = 0.5
_BG_SCALE = 1.5          # background pictures at 2880 x 1620

_BASE_CSS = """
html, body { margin: 0 !important; padding: 0 !important; }
body { display: block !important; }
section.slide { position: relative !important; width: 1920px !important;
  height: 1080px !important; overflow: hidden !important; margin: 0 !important;
  flex: none !important; box-sizing: border-box; }
aside.notes { display: none !important; }
::highlight(jx-hide) { color: transparent; -webkit-text-fill-color: transparent;
  text-shadow: none; text-decoration-color: transparent; }
"""

# ── The page side ────────────────────────────────────────────────────────────

_COMMON_JS = r"""
const ICON_FONT = /icon|symbol|awesome|phosphor|glyph|emoji/i;
const cv = document.createElement('canvas'); cv.width = cv.height = 1;
const cx = cv.getContext('2d', {willReadFrequently: true});
const colorCache = new Map(), metricCache = new Map();
function rgba(c) {
  if (colorCache.has(c)) return colorCache.get(c);
  cx.clearRect(0, 0, 1, 1); cx.fillStyle = '#000'; cx.fillStyle = c; cx.fillRect(0, 0, 1, 1);
  const d = cx.getImageData(0, 0, 1, 1).data;
  const v = [d[0], d[1], d[2], d[3] / 255];
  colorCache.set(c, v); return v;
}
function metrics(cs) {
  const font = `${cs.fontStyle} ${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
  if (!metricCache.has(font)) {
    cx.font = font;
    const m = cx.measureText('Hg'), s = cx.measureText(' ');
    metricCache.set(font, [m.fontBoundingBoxAscent, m.fontBoundingBoxDescent, s.width]);
  }
  return metricCache.get(font);
}
function firstFamily(ff) { return ff.split(',')[0].trim().replace(/^["']|["']$/g, ''); }
function blockOf(el, slide) {
  let b = el;
  while (b !== slide) {
    const d = getComputedStyle(b).display;
    if (d !== 'inline' && d !== 'contents') break;
    b = b.parentElement;
  }
  return b;
}
function rasterReason(el, slide) {
  for (let e = el; e; e = e.parentElement) {
    if (e.hasAttribute('data-raster')) return 'data-raster';
    const cs = getComputedStyle(e);
    if (cs.transform !== 'none') {
      const m = new DOMMatrixReadOnly(cs.transform);
      if (Math.abs(m.a - 1) > 1e-3 || Math.abs(m.b) > 1e-3 || Math.abs(m.c) > 1e-3 ||
          Math.abs(m.d - 1) > 1e-3) return 'transform';
    }
    if (cs.rotate && cs.rotate !== 'none') return 'rotate';
    if (cs.scale && cs.scale !== 'none') return 'scale';
    if (cs.filter !== 'none') return 'filter';
    if (cs.mixBlendMode !== 'normal') return 'blend';
    if (cs.clipPath !== 'none') return 'clip-path';
    if ((cs.maskImage && cs.maskImage !== 'none') ||
        (cs.webkitMaskImage && cs.webkitMaskImage !== 'none')) return 'mask';
    if (cs.webkitBackgroundClip === 'text' || cs.backgroundClip === 'text') return 'gradient text';
    if (e === slide) break;
  }
  const cs = getComputedStyle(el);
  if (cs.textShadow !== 'none') return 'text-shadow';
  if (parseFloat(cs.webkitTextStrokeWidth) > 0) return 'text-stroke';
  if (rgba(cs.webkitTextFillColor)[3] === 0 && rgba(cs.color)[3] > 0) return 'text-fill';
  if (!cs.writingMode.startsWith('horizontal')) return 'vertical text';
  if (ICON_FONT.test(cs.fontFamily)) return 'icon font';
  if (el.closest('svg')) return 'svg text';
  if (cs.hyphens === 'auto') return 'hyphenation';
  return '';
}
function opacityOf(el, slide) {
  let o = 1;
  for (let e = el; e; e = e.parentElement) { o *= parseFloat(getComputedStyle(e).opacity); if (e === slide) break; }
  return o;
}
function textNodes(slide) {
  const out = [], w = document.createTreeWalker(slide, NodeFilter.SHOW_TEXT);
  let n;
  while ((n = w.nextNode())) {
    if (!n.nodeValue.trim()) continue;
    const el = n.parentElement;
    if (!el || el.closest('aside.notes, script, style, noscript, template, textarea, select')) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility !== 'visible') continue;
    if (!n.parentElement.getClientRects().length) continue;
    out.push(n);
  }
  return out;
}
"""

_EXTRACT_JS = "() => {" + _COMMON_JS + r"""
const slides = [...document.querySelectorAll('section.slide')];
const hide = new Highlight();
const result = slides.map((slide) => {
  const sr = slide.getBoundingClientRect();
  const notesEl = slide.querySelector('aside.notes');
  const notes = notesEl ? notesEl.textContent.replace(/\s+/g, ' ').trim() : '';
  const byBlock = new Map(), rasterBlocks = new Set(), raster = [];
  for (const node of textNodes(slide)) {
    const el = node.parentElement, block = blockOf(el, slide);
    if (!byBlock.has(block)) byBlock.set(block, []);
    byBlock.get(block).push(node);
    const why = rasterReason(el, slide);
    if (why && !rasterBlocks.has(block)) {
      rasterBlocks.add(block);
      raster.push(`${why}: "${block.textContent.replace(/\s+/g, ' ').trim().slice(0, 40)}"`);
    }
  }
  const blocks = [];
  for (const [block, nodes] of byBlock) {
    if (rasterBlocks.has(block)) continue;
    const bcs = getComputedStyle(block);
    const tokens = [];
    let space = false;
    for (const node of nodes) {
      const el = node.parentElement, cs = getComputedStyle(el);
      const [asc, desc, spaceW] = metrics(cs);
      const col = rgba(cs.color), op = opacityOf(el, slide);
      let underline = false;
      for (let e = el; e && e !== block.parentElement; e = e.parentElement)
        if (getComputedStyle(e).textDecorationLine.includes('underline')) { underline = true; break; }
      const st = {family: firstFamily(cs.fontFamily), generic: cs.fontFamily,
                  size: parseFloat(cs.fontSize), weight: parseInt(cs.fontWeight, 10) || 400,
                  italic: cs.fontStyle !== 'normal',
                  color: [col[0], col[1], col[2], +(col[3] * op).toFixed(3)],
                  ls: cs.letterSpacing === 'normal' ? 0 : parseFloat(cs.letterSpacing) || 0,
                  underline, asc, desc, spaceW};
      if (st.color[3] < 0.02) continue;
      const tt = cs.textTransform, text = node.nodeValue, re = /\S+/g;
      let m, end = 0;
      while ((m = re.exec(text))) {
        if (m.index > end) space = true;
        end = m.index + m[0].length;
        let word = m[0];
        if (tt === 'uppercase') word = word.toUpperCase();
        else if (tt === 'lowercase') word = word.toLowerCase();
        else if (tt === 'capitalize' && space) word = word[0].toUpperCase() + word.slice(1);
        const r = document.createRange();
        r.setStart(node, m.index); r.setEnd(node, end);
        const rects = [...r.getClientRects()].filter(q => q.width > 0.1 && q.height > 0.1);
        if (!rects.length) continue;
        if (rects.length === 1) {
          tokens.push({text: word, space, st, r: rects[0]});
        } else {          // a word broken across lines: go letter by letter
          let first = true;
          for (let i = 0; i < m[0].length; i++) {
            const rc = document.createRange();
            rc.setStart(node, m.index + i); rc.setEnd(node, m.index + i + 1);
            const q = [...rc.getClientRects()].find(q => q.width > 0.1);
            if (!q) continue;
            tokens.push({text: word[i] || '', space: first ? space : false, st, r: q, glue: !first});
            first = false;
          }
        }
        space = false;
      }
      if (end < text.length) space = true;
      hideNode(node);
    }
    if (!tokens.length) continue;
    // lines: the next word starting left of where the last one ended is a wrap
    const lines = [];
    let cur = null, last = null;
    for (const t of tokens) {
      const r = t.r;
      const nl = last && ((r.left < last.right - 2 &&
                           r.top > last.top + 0.25 * Math.min(r.height, last.height)) ||
                          r.top >= last.bottom - 1);
      if (!cur || nl) { cur = []; lines.push(cur); t.space = false; }
      else if (t.glue && r.left < last.right + 1) t.space = false;
      cur.push(t); last = r;
    }
    const justify = bcs.textAlign === 'justify';
    const outLines = lines.map(line => {
      const segs = [];
      let seg = null, prev = null;
      for (const t of line) {
        const gap = prev ? t.r.left - prev.r.right : 0;
        const expected = t.space ? t.st.spaceW + t.st.ls : 0;
        if (!seg || (!justify && gap - expected > Math.max(0.5 * t.st.size, 8))) {
          seg = {x0: t.r.left - sr.left, runs: []}; segs.push(seg);
          if (prev) t.space = false;
        }
        seg.runs.push({text: t.text, space: t.space, st: t.st});
        seg.x1 = t.r.right - sr.left;
        prev = t;
      }
      let base = -1e9, top = 1e9, bottom = -1e9, big = 0;
      for (const t of line) {
        top = Math.min(top, t.r.top - sr.top); bottom = Math.max(bottom, t.r.bottom - sr.top);
        if (t.st.size >= big) { big = t.st.size; base = t.r.top - sr.top + t.st.asc; }
      }
      return {segs, baseline: base, top, bottom, size: big};
    });
    const lh = parseFloat(bcs.lineHeight);
    let align = bcs.textAlign;
    if (align === 'start') align = bcs.direction === 'rtl' ? 'right' : 'left';
    if (align === 'end') align = bcs.direction === 'rtl' ? 'left' : 'right';
    blocks.push({align, lineHeight: isNaN(lh) ? null : lh, lines: outLines,
                 tag: block.tagName.toLowerCase()});
  }
  return {notes, blocks, raster};
});
function hideNode(node) { const r = new Range(); r.selectNodeContents(node); hide.add(r); }
window.__jxHide = hide;
return result;
}"""

_HIDE_JS = "() => { CSS.highlights.set('jx-hide', window.__jxHide); return window.__jxHide.size; }"

_LINT_JS = "() => {" + _COMMON_JS + r"""
const issues = [];
const slides = [...document.querySelectorAll('section.slide')];
if (!slides.length) return ['no <section class="slide"> found in the page'];
const fams = new Set();
slides.forEach((slide, i) => {
  const n = i + 1, sr = slide.getBoundingClientRect();
  if (Math.round(sr.width) !== 1920 || Math.round(sr.height) !== 1080)
    issues.push(`slide ${n}: is ${Math.round(sr.width)}x${Math.round(sr.height)}, must be 1920x1080`);
  if (!slide.querySelector('aside.notes')) issues.push(`slide ${n}: no <aside class="notes"> speaker notes`);
  const boxes = [];
  const seen = new Set();
  for (const node of textNodes(slide)) {
    const el = node.parentElement, cs = getComputedStyle(el);
    fams.add(firstFamily(cs.fontFamily) + '|' + cs.fontFamily);
    const block = blockOf(el, slide);
    const fs = parseFloat(cs.fontSize);
    const label = '"' + block.textContent.replace(/\s+/g, ' ').trim().slice(0, 40) + '"';
    if (fs < 24 && !seen.has('s' + label)) {
      seen.add('s' + label);
      issues.push(`slide ${n}: ${label} is ${fs}px (${fs / 2}pt) — under 24px is unreadable when projected`);
    }
    const r = document.createRange(); r.selectNodeContents(node);
    for (const raw of r.getClientRects()) {
      if (raw.width < 0.5) continue;
      const mid = raw.top + (raw.height - fs) / 2;
      const q = {left: raw.left, right: raw.right, top: mid, bottom: mid + fs};
      if (q.left < sr.left - 1 || q.right > sr.right + 1 || q.top < sr.top - 1 || q.bottom > sr.bottom + 1) {
        if (!seen.has('o' + label)) { seen.add('o' + label); issues.push(`slide ${n}: text ${label} runs off the slide`); }
      }
      // clipped by an ancestor that hides overflow
      for (let a = el.parentElement; a && a !== slide; a = a.parentElement) {
        const acs = getComputedStyle(a);
        if (acs.overflow === 'visible' && acs.overflowX === 'visible' && acs.overflowY === 'visible') continue;
        const ar = a.getBoundingClientRect();
        if (q.left < ar.left - 1 || q.right > ar.right + 1 || q.top < ar.top - 1 || q.bottom > ar.bottom + 1) {
          if (!seen.has('c' + label)) { seen.add('c' + label); issues.push(`slide ${n}: text ${label} is cut off by its container`); }
        }
        break;
      }
    }
    // the em box of each line fragment: line boxes and font content areas
    // overlap by design with tight leading, the letters themselves do not
    let bx = boxes.find(b => b.block === block);
    if (!bx) { bx = {block, label, q: null}; boxes.push(bx); }
    for (const q of r.getClientRects()) {
      if (q.width < 0.5) continue;
      const t = q.top + (q.height - fs) / 2, e = {left: q.left, right: q.right, top: t, bottom: t + fs};
      bx.q = bx.q ? {left: Math.min(bx.q.left, e.left), right: Math.max(bx.q.right, e.right),
                     top: Math.min(bx.q.top, e.top), bottom: Math.max(bx.q.bottom, e.bottom)} : e;
    }
  }
  for (let a = 0; a < boxes.length; a++) for (let b = a + 1; b < boxes.length; b++) {
    const A = boxes[a], B = boxes[b];
    if (!A.q || !B.q) continue;
    if (A.block.contains(B.block) || B.block.contains(A.block)) continue;
    const ix = Math.min(A.q.right, B.q.right) - Math.max(A.q.left, B.q.left);
    const iy = Math.min(A.q.bottom, B.q.bottom) - Math.max(A.q.top, B.q.top);
    if (ix > 6 && iy > 6) issues.push(`slide ${n}: text ${A.label} overlaps ${B.label}`);
  }
  for (const img of slide.querySelectorAll('img')) {
    if (!img.complete || !img.naturalWidth) issues.push(`slide ${n}: image ${img.getAttribute('src')} did not load`);
  }
});
return {issues, families: [...fams]};
}"""

_VIEWER = """
<style id="jx-viewer">
html.jx-view, html.jx-view body { margin: 0; width: 100%; height: 100%; overflow: hidden; background: #0b0b0b; }
html.jx-view section.slide { position: absolute !important; left: 50%; top: 50%; margin: 0 !important;
  width: 1920px; height: 1080px; transform: translate(-50%, -50%) scale(var(--jx-s, 1));
  visibility: hidden; }
html.jx-view section.slide.jx-on { visibility: visible; }
html.jx-view aside.notes { display: none !important; }
#jx-count { position: fixed; right: 14px; bottom: 10px; font: 12px/1 system-ui, sans-serif;
  color: rgba(255,255,255,.55); z-index: 99; user-select: none; }
@media print { html.jx-view section.slide { position: relative !important; left: 0; top: 0;
  transform: none; visibility: visible; page-break-after: always; } #jx-count { display: none; } }
</style>
<script id="jx-viewer-js">
(() => {
  const root = document.documentElement; root.classList.add('jx-view');
  const slides = [...document.querySelectorAll('section.slide')];
  const count = document.createElement('div'); count.id = 'jx-count'; document.body.appendChild(count);
  let i = Math.max(0, (parseInt(location.hash.slice(1), 10) || 1) - 1);
  const fit = () => root.style.setProperty('--jx-s', Math.min(innerWidth / 1920, innerHeight / 1080));
  const show = n => {
    i = Math.max(0, Math.min(slides.length - 1, n));
    slides.forEach((s, k) => s.classList.toggle('jx-on', k === i));
    count.textContent = (i + 1) + ' / ' + slides.length;
    history.replaceState(null, '', '#' + (i + 1));
  };
  addEventListener('resize', fit);
  addEventListener('keydown', e => {
    if (['ArrowRight', 'PageDown', ' ', 'Enter'].includes(e.key)) show(i + 1);
    else if (['ArrowLeft', 'PageUp', 'Backspace'].includes(e.key)) show(i - 1);
    else if (e.key === 'Home') show(0);
    else if (e.key === 'End') show(slides.length - 1);
    else if (e.key === 'f' || e.key === 'F') {
      document.fullscreenElement ? document.exitFullscreen() : root.requestFullscreen();
    } else return;
    e.preventDefault();
  });
  addEventListener('click', e => show(e.clientX < innerWidth / 3 ? i - 1 : i + 1));
  fit(); show(i);
})();
</script>
"""


# ── Browser ──────────────────────────────────────────────────────────────────

class _Page:
    """The deck loaded in headless Chromium, ready to measure or photograph."""

    def __init__(self, html_path: Path, scale: float = 1.0):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self.browser = self._pw.chromium.launch()
        self.errors: list[str] = []
        self.page = self.browser.new_page(viewport={"width": SW, "height": SH},
                                          device_scale_factor=scale)
        self.page.on("pageerror", lambda e: self.errors.append(str(e)[:200]))
        self.page.on("console", lambda m: self.errors.append(m.text[:200])
                     if m.type == "error" else None)
        self.page.goto(Path(html_path).resolve().as_uri(), wait_until="load", timeout=60_000)
        try:
            self.page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception:
            pass
        self.page.add_style_tag(content=_BASE_CSS)
        self.page.evaluate("document.fonts.ready.then(() => true)")
        self.page.wait_for_timeout(250)

    def slides(self):
        return self.page.query_selector_all("section.slide")

    def close(self):
        try:
            self.browser.close()
        finally:
            self._pw.stop()


def _sheet(images: list[Path], out: Path, labels: list[str] | None = None,
           cols: int = 3, thumb_w: int = 600) -> Path:
    from PIL import Image, ImageDraw, ImageFont
    th = round(thumb_w * 9 / 16)
    rows = (len(images) + cols - 1) // cols
    cols = min(cols, len(images))
    gap, pad = 14, 14
    sheet = Image.new("RGB", (pad * 2 + cols * thumb_w + (cols - 1) * gap,
                              pad * 2 + rows * th + (rows - 1) * gap), (128, 128, 128))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 22)
    except Exception:
        font = ImageFont.load_default()
    for k, path in enumerate(images):
        im = Image.open(path).convert("RGB").resize((thumb_w, th), Image.LANCZOS)
        x = pad + (k % cols) * (thumb_w + gap)
        y = pad + (k // cols) * (th + gap)
        sheet.paste(im, (x, y))
        label = labels[k] if labels else str(k + 1)
        draw.rectangle((x, y, x + 16 + 13 * len(label), y + 32), fill=(255, 0, 140))
        draw.text((x + 8, y + 3), label, fill=(255, 255, 255), font=font)
    sheet.save(out)
    return out


# ── Shoot + lint ─────────────────────────────────────────────────────────────

def shoot(html_path: Path, out: Path, scale: float = 1.0) -> tuple[list[Path], list[str], list[str]]:
    """(slide PNGs, issues, font families used as 'first|full stack')."""
    out.mkdir(parents=True, exist_ok=True)
    for old in list(out.glob("slide-*.png")) + list(out.glob("sheet-*.png")):
        old.unlink()
    pg = _Page(html_path, scale)
    try:
        lint = pg.page.evaluate(_LINT_JS)
        if isinstance(lint, list):
            return [], lint, []
        shots = []
        for i, el in enumerate(pg.slides(), 1):
            p = out / f"slide-{i:02d}.png"
            el.screenshot(path=str(p))
            shots.append(p)
        issues = list(lint["issues"]) + [f"page error: {e}" for e in dict.fromkeys(pg.errors)][:5]
        return shots, issues, list(lint["families"])
    finally:
        pg.close()


def sheets(shots: list[Path], out: Path, prefix: str = "sheet") -> list[Path]:
    res = []
    for s in range(0, len(shots), 9):
        res.append(_sheet(shots[s:s + 9], out / f"{prefix}-{s // 9 + 1}.png",
                          [str(s + k + 1) for k in range(len(shots[s:s + 9]))]))
    return res


# ── Fonts ────────────────────────────────────────────────────────────────────

_GENERIC = {"serif", "sans-serif", "monospace", "cursive", "fantasy", "system-ui",
            "ui-sans-serif", "ui-serif", "ui-monospace", "ui-rounded", "-apple-system",
            "blinkmacsystemfont", "math", "emoji"}
_WEIGHT_NAMES = {100: "Thin", 200: "ExtraLight", 300: "Light", 500: "Medium",
                 600: "SemiBold", 800: "ExtraBold", 900: "Black"}


def _fc(*args: str) -> str:
    exe = shutil.which(args[0])
    if not exe:
        return ""
    try:
        return subprocess.run([exe, *args[1:]], capture_output=True, text=True,
                              timeout=20).stdout
    except Exception:
        return ""


def _installed_names() -> set[str]:
    names = set()
    for line in _fc("fc-list", ":", "family").splitlines():
        for n in line.split(","):
            if n.strip():
                names.add(n.strip().lower())
    return names


class _FontMap:
    """CSS (family, weight) -> the family name and bold flag PowerPoint needs.

    Google's static fonts carry a legacy family name per weight ("DM Sans
    Medium"), which is how PowerPoint and LibreOffice select a weight that is
    neither regular nor bold."""

    def __init__(self):
        self.names = _installed_names()
        self.generic: dict[str, str] = {}

    def resolve(self, family: str, weight: int, stack: str) -> tuple[str, bool]:
        fam = family
        if fam.lower() in _GENERIC or fam.lower() not in self.names:
            # what Chromium fell back to: the next installed family in the stack
            for f in [s.strip().strip("\"'") for s in stack.split(",")]:
                if f.lower() in self.names:
                    fam = f
                    break
                if f.lower() in _GENERIC:
                    if f not in self.generic:
                        got = _fc("fc-match", "-f", "%{family}", f).split(",")[0].strip()
                        self.generic[f] = got or "Liberation Sans"
                    fam = self.generic[f]
                    break
        w = min(900, max(100, int(round(weight / 100.0)) * 100))
        if w == 400:
            return fam, False
        if w == 700:
            return fam, True
        named = f"{fam} {_WEIGHT_NAMES[w]}"
        if named.lower() in self.names:
            return named, False
        return fam, w >= 600


def missing_families(families: list[str]) -> list[str]:
    """First families of the page's font stacks that are not installed here."""
    names = _installed_names()
    out = []
    for item in families:
        first = item.split("|", 1)[0].strip()
        if first and first.lower() not in _GENERIC and first.lower() not in names \
                and first not in out:
            out.append(first)
    return out


# ── PPTX ─────────────────────────────────────────────────────────────────────

def _hex(c) -> str:
    return "%02X%02X%02X" % tuple(int(round(v)) for v in c[:3])


def _set_background(slide, image: Path) -> None:
    """The picture as the slide's background fill, so it cannot be dragged
    around or selected by mistake while editing the text on top."""
    from lxml import etree
    from pptx.oxml.ns import qn
    pic = slide.shapes.add_picture(str(image), 0, 0, SW * EMU_PX, SH * EMU_PX)
    rid = pic._element.xpath(".//a:blip/@r:embed")[0]
    pic._element.getparent().remove(pic._element)
    cSld = slide._element.find(qn("p:cSld"))
    old = cSld.find(qn("p:bg"))
    if old is not None:
        cSld.remove(old)
    bg = cSld.makeelement(qn("p:bg"), {})
    cSld.insert(0, bg)
    bgPr = etree.SubElement(bg, qn("p:bgPr"))
    fill = etree.SubElement(bgPr, qn("a:blipFill"), {"dpi": "0", "rotWithShape": "1"})
    blip = etree.SubElement(fill, qn("a:blip"))
    blip.set(qn("r:embed"), rid)
    etree.SubElement(fill, qn("a:srcRect"))
    stretch = etree.SubElement(fill, qn("a:stretch"))
    etree.SubElement(stretch, qn("a:fillRect"))
    etree.SubElement(bgPr, qn("a:effectLst"))


# Where the first baseline lands in a text box with exact line spacing S and
# no inset. Impress lays pptx text out with font-independent metrics, so the
# line's descent is a fixed share of the font size whatever the typeface:
# measured at 0.18-0.22 em over DM Sans, Anton, Space Grotesk, Liberation
# Serif, DejaVu Sans and Ubuntu, sizes 30-190 px, line-heights 0.92-1.6.
_DESCENT_EM = 0.19


def _first_baseline(S: float, size: float) -> float:
    return S - _DESCENT_EM * size


def _add_text(slide, segs_lines: list, align: str, pitch: float, fonts: _FontMap,
              x0: float, x1: float, top_baseline: float, main: dict) -> None:
    from pptx.dml.color import RGBColor
    from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
    from pptx.oxml.ns import qn
    from pptx.util import Emu, Pt

    width = (x1 - x0)
    slack = width * 0.06 + main["size"] * 0.4
    if align == "center":
        left, w = x0 - slack / 2, width + slack
    elif align == "right":
        left, w = x0 - slack, width + slack
    else:
        left, w = x0, width + slack
    S = pitch
    top = top_baseline - _first_baseline(S, main["size"])
    h = S * len(segs_lines) + main["size"] * 0.3
    tb = slide.shapes.add_textbox(Emu(int(left * EMU_PX)), Emu(int(top * EMU_PX)),
                                  Emu(int(w * EMU_PX)), Emu(int(h * EMU_PX)))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.auto_size = MSO_AUTO_SIZE.NONE
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = MSO_ANCHOR.TOP
    p = tf.paragraphs[0]
    p.alignment = {"center": PP_ALIGN.CENTER, "right": PP_ALIGN.RIGHT}.get(align, PP_ALIGN.LEFT)
    p.line_spacing = Pt(S * PT_PX)
    p.space_before = p.space_after = Pt(0)
    for li, runs in enumerate(segs_lines):
        if li:
            p.add_line_break()
        merged: list[tuple[str, dict]] = []
        for i, r in enumerate(runs):
            text = (" " if r["space"] and i else "") + r["text"]
            if merged and merged[-1][1] == r["st"]:
                merged[-1] = (merged[-1][0] + text, merged[-1][1])
            else:
                merged.append((text, r["st"]))
        for text, st in merged:
            run = p.add_run()
            run.text = text
            f = run.font
            name, bold = fonts.resolve(st["family"], st["weight"], st["generic"])
            f.name = name
            f.size = Pt(round(st["size"] * PT_PX * 2) / 2)
            f.bold = bold
            f.italic = bool(st["italic"])
            if st.get("underline"):
                f.underline = True
            f.color.rgb = RGBColor.from_string(_hex(st["color"]))
            rPr = run._r.get_or_add_rPr()
            if st["color"][3] < 0.995:
                clr = rPr.find(qn("a:solidFill")).find(qn("a:srgbClr"))
                a = clr.makeelement(qn("a:alpha"), {"val": str(int(st["color"][3] * 100000))})
                clr.append(a)
            if abs(st["ls"]) > 0.01:
                rPr.set("spc", str(int(round(st["ls"] * PT_PX * 100))))
            rPr.set("kern", "0")
            for tag in ("a:ea", "a:cs"):
                if rPr.find(qn(tag)) is None:
                    rPr.append(rPr.makeelement(qn(tag), {"typeface": name}))


def to_pptx(html_path: Path, pptx_path: Path, work: Path) -> dict:
    """Build the PowerPoint version. Returns a report: slides, editable text
    blocks, text kept as picture (with why), page errors, and the paths of the
    with-text renders (for comparison)."""
    from pptx import Presentation
    from pptx.util import Emu

    work.mkdir(parents=True, exist_ok=True)
    pg = _Page(html_path, _BG_SCALE)
    report = {"slides": 0, "editable": 0, "raster": [], "errors": [], "html_shots": []}
    try:
        # renders with the text, for the comparison the agent looks at
        for i, el in enumerate(pg.slides(), 1):
            p = work / f"html-{i:02d}.png"
            el.screenshot(path=str(p), scale="css")
            report["html_shots"].append(str(p))
        data = pg.page.evaluate(_EXTRACT_JS)
        pg.page.evaluate(_HIDE_JS)
        pg.page.wait_for_timeout(100)
        bgs = []
        for i, el in enumerate(pg.slides(), 1):
            p = work / f"bg-{i:02d}.jpg"
            el.screenshot(path=str(p), type="jpeg", quality=90)
            bgs.append(p)
        report["errors"] = list(dict.fromkeys(pg.errors))[:5]
    finally:
        pg.close()

    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(SW * EMU_PX), Emu(SH * EMU_PX)
    fonts = _FontMap()
    title_text = ""
    for i, (sd, bg) in enumerate(zip(data, bgs), 1):
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        _set_background(slide, bg)
        for blk in sd["blocks"]:
            lines = blk["lines"]
            multi = any(len(l["segs"]) > 1 for l in lines)
            pitches = [b["baseline"] - a["baseline"] for a, b in zip(lines, lines[1:])]
            pitches = [p for p in pitches if p > 0]
            if pitches:
                pitch = sorted(pitches)[len(pitches) // 2]
            elif blk["lineHeight"]:
                pitch = blk["lineHeight"]
            else:
                pitch = lines[0]["bottom"] - lines[0]["top"]
            # the biggest run sets the metrics the first baseline is placed with
            main = max((r["st"] for l in lines for s in l["segs"] for r in s["runs"]),
                       key=lambda st: st["size"])
            if not multi:
                x0 = min(l["segs"][0]["x0"] for l in lines)
                x1 = max(l["segs"][0]["x1"] for l in lines)
                _add_text(slide, [l["segs"][0]["runs"] for l in lines], blk["align"], pitch,
                          fonts, x0, x1, lines[0]["baseline"], main)
                report["editable"] += 1
            else:
                for l in lines:
                    for s in l["segs"]:
                        _add_text(slide, [s["runs"]], "left", pitch, fonts, s["x0"], s["x1"],
                                  l["baseline"], main)
                        report["editable"] += 1
            if not title_text and blk["tag"] in ("h1", "h2"):
                title_text = " ".join(r["text"] for l in lines for s in l["segs"]
                                      for r in s["runs"])
        if sd["notes"]:
            slide.notes_slide.notes_text_frame.text = sd["notes"]
        report["raster"] += [f"slide {i}: {r}" for r in sd["raster"]]
    report["slides"] = len(data)
    title = re.search(r"<title>(.*?)</title>", Path(html_path).read_text(encoding="utf-8",
                                                                        errors="replace"), re.S | re.I)
    prs.core_properties.title = (title.group(1).strip() if title else title_text)[:200]
    prs.save(str(pptx_path))
    return report


def compare(html_shots: list[str], pptx_shots: list[Path], out: Path) -> tuple[list[Path], list[str]]:
    """Side-by-side sheets (HTML | PowerPoint) and the slides that drifted."""
    from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageStat
    pairs, drift = [], []
    for i, (h, p) in enumerate(zip(html_shots, pptx_shots), 1):
        a = Image.open(h).convert("RGB").resize((960, 540), Image.LANCZOS)
        b = Image.open(p).convert("RGB").resize((960, 540), Image.LANCZOS)
        d = ImageStat.Stat(ImageChops.difference(a, b).convert("L")).mean[0] / 255 * 100
        if d > 2.5:
            drift.append(f"slide {i}: the PowerPoint differs from the HTML by {d:.1f}% — compare them")
        pairs.append((i, a, b, d))
    sheets_out = []
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 20)
    except Exception:
        font = ImageFont.load_default()
    for s in range(0, len(pairs), 3):
        chunk = pairs[s:s + 3]
        sheet = Image.new("RGB", (960 * 2 + 42, len(chunk) * 554 + 14), (128, 128, 128))
        dr = ImageDraw.Draw(sheet)
        for k, (i, a, b, d) in enumerate(chunk):
            y = 14 + k * 554
            sheet.paste(a, (14, y))
            sheet.paste(b, (28 + 960, y))
            dr.rectangle((14, y, 14 + 190, y + 30), fill=(255, 0, 140))
            dr.text((20, y + 4), f"{i} HTML", fill="white", font=font)
            dr.rectangle((28 + 960, y, 28 + 960 + 260, y + 30), fill=(0, 120, 255))
            dr.text((34 + 960, y + 4), f"{i} PPTX  Δ{d:.1f}%", fill="white", font=font)
        p = out / f"compare-{s // 3 + 1}.png"
        sheet.save(p)
        sheets_out.append(p)
    return sheets_out, drift


# ── Web export ───────────────────────────────────────────────────────────────

def inline_assets(html: str, base: Path) -> str:
    """Relative image and media references -> data: URIs, so one file carries
    the whole deck."""
    def data_uri(ref: str) -> str | None:
        if re.match(r"^(data:|https?:|//|#)", ref):
            return None
        p = (base / ref.split("?")[0].split("#")[0]).resolve()
        if not p.is_file() or p.stat().st_size > 15_000_000:
            return None
        mime = mimetypes.guess_type(str(p))[0] or "application/octet-stream"
        return f"data:{mime};base64,{base64.b64encode(p.read_bytes()).decode('ascii')}"

    def attr(m):
        uri = data_uri(m.group(3))
        return f"{m.group(1)}={m.group(2)}{uri}{m.group(2)}" if uri else m.group(0)

    def url(m):
        uri = data_uri(m.group(2))
        return f"url({m.group(1)}{uri}{m.group(1)})" if uri else m.group(0)

    html = re.sub(r"""\b(src|href|xlink:href|poster)=(["'])([^"']+)\2""", attr, html)
    html = re.sub(r"""url\((["']?)([^)"']+)\1\)""", url, html)
    return html


def _google_link(families: list[str]) -> str:
    try:
        from core.deck_kit import _gf_family
    except Exception:
        return ""
    parts, seen = [], set()
    for fam in families:
        meta = _gf_family(fam)
        if not meta or meta["family"] in seen:
            continue
        seen.add(meta["family"])
        keys = sorted(meta["fonts"].keys(), key=lambda k: (k.endswith("i"), int(k.rstrip("i"))))
        axes = ";".join(f"{1 if k.endswith('i') else 0},{k.rstrip('i')}" for k in keys)
        parts.append("family=" + meta["family"].replace(" ", "+") + ":ital,wght@" + axes)
    if not parts:
        return ""
    return ('<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
            f'<link rel="stylesheet" href="https://fonts.googleapis.com/css2?{"&".join(parts)}&display=swap">\n')


def export_web(html_path: Path, out: Path, families: list[str]) -> Path:
    html = Path(html_path).read_text(encoding="utf-8", errors="replace")
    html = inline_assets(html, Path(html_path).parent)
    link = _google_link([f.split("|", 1)[0] for f in families])
    if link:
        html = re.sub(r"</head>", link + "</head>", html, count=1, flags=re.I) \
            if re.search(r"</head>", html, re.I) else link + html
    html = re.sub(r"</body>", _VIEWER + "</body>", html, count=1, flags=re.I) \
        if re.search(r"</body>", html, re.I) else html + _VIEWER
    out.write_text(html, encoding="utf-8")
    return out


# ── Motion preview ───────────────────────────────────────────────────────────

def motion_duration(html: str, default: float = 30.0) -> float:
    m = re.search(r"""<meta\s+name=["']duration["']\s+content=["']([\d.]+)""", html, re.I)
    try:
        return float(m.group(1)) if m else default
    except ValueError:
        return default


def motion_frames(html_path: Path, out: Path, times: list[float]) -> tuple[list[Path], list[str]]:
    """Frames of a motion page at the given seconds, under the same virtual
    clock the MP4 renderer uses."""
    from actions.create_motion_video import _VIRTUAL_TIME
    from playwright.sync_api import sync_playwright

    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("frame-*.png"):
        old.unlink()
    shots, errors = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": SW, "height": SH})
            page.on("pageerror", lambda e: errors.append(str(e)[:200]))
            page.on("console", lambda m: errors.append(m.text[:200]) if m.type == "error" else None)
            page.add_init_script(_VIRTUAL_TIME)
            page.goto(Path(html_path).resolve().as_uri(), wait_until="load", timeout=60_000)
            try:
                page.wait_for_load_state("networkidle", timeout=15_000)
                page.evaluate("document.fonts.ready.then(() => true)")
            except Exception:
                pass
            # Walk the clock frame by frame, as the MP4 renderer does: GSAP
            # treats a jump of more than half a second as lag and barely moves.
            now = 0.0
            for k, t in enumerate(sorted(times)):
                page.evaluate("""([from, to]) => {
                    for (let x = from; x < to; x += 1000 / 30) window.__motionAdvance(x);
                    window.__motionAdvance(to);
                }""", [now, t * 1000.0])
                now = t * 1000.0
                f = out / f"frame-{k + 1:02d}-{t:05.1f}s.png"
                page.screenshot(path=str(f))
                shots.append(f)
        finally:
            browser.close()
    return shots, list(dict.fromkeys(errors))[:8]
