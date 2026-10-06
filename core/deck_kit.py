"""
deck_kit — the bench a Claude agent designs a PowerPoint deck on.

create_document hands slide decks to a Claude agent that designs them as a web
page (one <section> per slide), so every deck gets a layout and a look made for
its subject instead of the same nine templates. What the agent cannot do from
inside its sandbox is see the result, measure text, fetch a font or convert the
page. This file does those things, and the agent runs it through its job
folder's kit.py shim:

    python3 kit.py html deck.html        the web deck: every slide as a PNG,
                                         contact sheets, a lint (clipped, tiny
                                         or overlapping text, broken images);
                                         installs the Google Fonts it names
    python3 kit.py pptx deck.html d.pptx the PowerPoint (core/html_deck.py),
                                         rendered back through LibreOffice and
                                         compared with the HTML side by side
    python3 kit.py motion motion.html    frames of a motion-design page under
                                         the MP4 renderer's virtual clock
    python3 kit.py render deck.pptx      a .pptx as PNGs, contact sheets and a
                                         lint: text that does not fit its box,
                                         shapes off the slide, type under 12 pt
    python3 kit.py fonts                 font families installed here
    python3 kit.py font "Family Name"    installs a Google Font for this user
    python3 kit.py image "prompt" out --aspect landscape
                                         one generated picture (see
                                         actions/image_generator.py)

WHY THE LINT MEASURES TEXT ITSELF
    python-pptx gives a text box a size and no idea of what fits in it. Worse,
    LibreOffice grows a box to fit its text on load and PowerPoint does not, so
    a deck that looks right in the preview overflows on the projector. The
    report measures each paragraph with the real font file (fc-match) and says
    which box is short, and by how much.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_EMU_PER_PT = 12700
_SHEET_COLS, _SHEET_ROWS = 3, 3
_THUMB_W = 600


# ── Fonts ────────────────────────────────────────────────────────────────────

def _fc(*args: str) -> str:
    exe = shutil.which(args[0])
    if not exe:
        return ""
    try:
        return subprocess.run([exe, *args[1:]], capture_output=True, text=True,
                              timeout=20).stdout
    except Exception:
        return ""


def installed_families() -> list[str]:
    out = _fc("fc-list", ":", "family")
    fams = {line.split(",")[0].strip() for line in out.splitlines() if line.strip()}
    skip = re.compile(r"^noto|mathjax|droid|lohit|kacst|"
                      r"tlwg|samyak|sarai|smc|padauk|khmer|tibet|opensymbol|symbol|"
                      r"keyboard|initials|emoji|d050000l|z003", re.I)
    return sorted(f for f in fams if f and not skip.search(f))


def _font_file(family: str, bold: bool = False, italic: bool = False) -> tuple[str, bool]:
    """(path of the file that would render this family, whether it is the family
    asked for or a substitute)."""
    pattern = family + (":bold" if bold else "") + (":italic" if italic else "")
    out = _fc("fc-match", "-f", "%{family}\t%{file}", pattern)
    if "\t" not in out:
        return "", False
    got, path = out.split("\t", 1)
    exact = family.lower() in [g.strip().lower() for g in got.split(",")]
    return path.strip(), exact


def _user_font_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Fonts"
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Microsoft" / "Windows" / "Fonts"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "fonts" / "jarvis-google"


def _register_windows_font(path: Path, name: str) -> None:
    import winreg                                               # noqa: PLC0415
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                         r"Software\Microsoft\Windows NT\CurrentVersion\Fonts",
                         0, winreg.KEY_SET_VALUE)
    with key:
        winreg.SetValueEx(key, f"{name} (TrueType)", 0, winreg.REG_SZ, str(path))


_GF_META_URL = "https://fonts.google.com/metadata/fonts"
_gf_cache: dict | None = None


def _gf_meta() -> dict:
    """Google Fonts' catalogue, family (lower case) -> its entry, which lists
    the exact weights and italics each family has. Cached for two weeks."""
    global _gf_cache
    if _gf_cache is not None:
        return _gf_cache
    cache = Path.home() / ".cache" / "jarvis" / "gf_meta.json"
    data = None
    try:
        if cache.exists() and time.time() - cache.stat().st_mtime < 14 * 86400:
            data = json.loads(cache.read_text(encoding="utf-8"))
    except Exception:
        data = None
    if data is None:
        try:
            import requests
            r = requests.get(_GF_META_URL, timeout=30)
            text = r.text[r.text.find("{"):]
            data = json.loads(text)
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(data), encoding="utf-8")
        except Exception:
            data = {}
    _gf_cache = {f["family"].lower(): f for f in data.get("familyMetadataList", [])}
    return _gf_cache


def _gf_family(name: str) -> dict | None:
    return _gf_meta().get(" ".join(name.split()).lower())


def install_font(family: str) -> str:
    """Fetch a Google Font's static TTFs (regular, bold, italics and the weights
    between) into the user's font folder. Returns a line for the agent."""
    import requests

    family = " ".join(family.split())
    if not family:
        return "ERROR: no family name given"
    _, exact = _font_file(family)
    if exact:
        return f"OK: '{family}' is already installed — use font name '{family}'"
    meta = _gf_family(family)
    if meta:
        # Exactly the styles the family has: asking for one it lacks makes
        # Google refuse the whole request.
        family = meta["family"]
        keys = sorted(meta.get("fonts", {}).keys(),
                      key=lambda k: (k.endswith("i"), int(k.rstrip("i") or 400)))
        tries = ["ital,wght@" + ";".join(f"{1 if k.endswith('i') else 0},{k.rstrip('i')}"
                                         for k in keys)] if keys else [""]
    else:
        tries = ["wght@400;700", ""]
    url = "https://fonts.googleapis.com/css2"
    # An old user agent makes Google answer with plain TrueType URLs, which is
    # what PowerPoint and LibreOffice read; a modern one gets woff2.
    headers = {"User-Agent": "Mozilla/4.0"}
    css = ""
    for axes in tries:
        q = family + (f":{axes}" if axes else "")
        try:
            r = requests.get(url, params={"family": q}, headers=headers, timeout=20)
        except Exception as e:
            return f"ERROR: Google Fonts unreachable ({type(e).__name__}) — use an installed font"
        if r.status_code == 200 and "src:" in r.text:
            css = r.text
            break
    if not css:
        return f"ERROR: Google Fonts has no family named '{family}' — check the exact name"

    dest = _user_font_dir()
    if sys.platform not in ("darwin", "win32"):
        dest = dest / re.sub(r"[^A-Za-z0-9]+", "", family)
    dest.mkdir(parents=True, exist_ok=True)
    saved = 0
    for block in re.findall(r"@font-face\s*{(.*?)}", css, re.S):
        src = re.search(r"url\((https://[^)]+\.ttf)\)", block)
        if not src:
            continue
        style = re.search(r"font-style:\s*(\w+)", block)
        weight = re.search(r"font-weight:\s*(\d+)", block)
        name = (f"{family.replace(' ', '')}-{weight.group(1) if weight else '400'}"
                f"{'Italic' if style and style.group(1) == 'italic' else ''}.ttf")
        target = dest / name
        if not target.exists():
            try:
                data = requests.get(src.group(1), timeout=30).content
            except Exception:
                continue
            if data[:4] not in (b"\x00\x01\x00\x00", b"true", b"OTTO"):
                continue
            target.write_bytes(data)
            if sys.platform == "win32":
                try:
                    _register_windows_font(target, f"{family} {name}")
                except Exception:
                    pass
        saved += 1
    if not saved:
        return f"ERROR: could not download '{family}' — use an installed font"
    if sys.platform not in ("darwin", "win32"):
        _fc("fc-cache", "-f", str(dest))
    _, exact = _font_file(family)
    if not exact and sys.platform not in ("darwin", "win32"):
        return f"ERROR: '{family}' was downloaded but is not visible to fontconfig"
    return (f"OK: installed '{family}' ({saved} styles) — use font name '{family}'. "
            f"It is installed on this computer only: a different computer shows "
            f"the deck in a substitute font.")


# ── Rendering ────────────────────────────────────────────────────────────────

def _soffice() -> str | None:
    for name in ("soffice", "libreoffice"):
        exe = shutil.which(name)
        if exe:
            return exe
    if sys.platform == "win32":
        for base in (os.environ.get("PROGRAMFILES", ""), os.environ.get("PROGRAMFILES(X86)", "")):
            p = Path(base) / "LibreOffice" / "program" / "soffice.exe"
            if base and p.exists():
                return str(p)
    if sys.platform == "darwin":
        p = Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")
        if p.exists():
            return str(p)
    return None


def _to_pdf(pptx: Path, work: Path) -> Path:
    exe = _soffice()
    if not exe:
        raise RuntimeError("LibreOffice is not installed, so slides cannot be previewed")
    # Its own profile: with the user's LibreOffice open, a shared profile makes
    # the conversion fail without a word. Kept per job, so the second render of
    # an iteration does not pay for building a profile again.
    profile = (pptx.parent / ".lo-profile").resolve().as_uri()
    subprocess.run([exe, f"-env:UserInstallation={profile}", "--headless",
                    "--convert-to", "pdf", "--outdir", str(work), str(pptx)],
                   capture_output=True, timeout=180)
    pdf = work / (pptx.stem + ".pdf")
    if not pdf.exists():
        raise RuntimeError("LibreOffice could not convert the deck — is the .pptx valid?")
    return pdf


def render(pptx: Path, out: Path) -> list[Path]:
    """Each slide as out/slide-NN.png, plus out/sheet-N.png contact sheets."""
    import pypdfium2 as pdfium
    from PIL import Image, ImageDraw, ImageFont

    out.mkdir(parents=True, exist_ok=True)
    for old in list(out.glob("slide-*.png")) + list(out.glob("sheet-*.png")):
        old.unlink()
    with tempfile.TemporaryDirectory(prefix="deck-pdf-") as tmp:
        pdf = _to_pdf(pptx, Path(tmp))
        doc = pdfium.PdfDocument(str(pdf))
        slides = []
        for i in range(len(doc)):
            page = doc[i]
            scale = 1280 / page.get_width()
            img = page.render(scale=scale).to_pil().convert("RGB")
            p = out / f"slide-{i + 1:02d}.png"
            img.save(p)
            slides.append(p)
        doc.close()

    sheets = []
    per = _SHEET_COLS * _SHEET_ROWS
    try:
        label_font = ImageFont.truetype(_font_file("DejaVu Sans", bold=True)[0] or "DejaVuSans-Bold.ttf", 22)
    except Exception:
        label_font = ImageFont.load_default()
    for s in range(0, len(slides), per):
        chunk = slides[s:s + per]
        cols = min(_SHEET_COLS, len(chunk))
        rows = (len(chunk) + cols - 1) // cols
        th = round(_THUMB_W * 9 / 16)
        gap, pad = 14, 14
        sheet = Image.new("RGB", (pad * 2 + cols * _THUMB_W + (cols - 1) * gap,
                                  pad * 2 + rows * th + (rows - 1) * gap), (128, 128, 128))
        draw = ImageDraw.Draw(sheet)
        for k, path in enumerate(chunk):
            im = Image.open(path).resize((_THUMB_W, th), Image.LANCZOS)
            x = pad + (k % cols) * (_THUMB_W + gap)
            y = pad + (k // cols) * (th + gap)
            sheet.paste(im, (x, y))
            n = str(s + k + 1)
            draw.rectangle((x, y, x + 16 + 14 * len(n), y + 32), fill=(255, 0, 140))
            draw.text((x + 8, y + 3), n, fill=(255, 255, 255), font=label_font)
        p = out / f"sheet-{s // per + 1}.png"
        sheet.save(p)
        sheets.append(p)
    return sheets


# ── Lint ─────────────────────────────────────────────────────────────────────

_FONT_CACHE: dict = {}


def _measure_font(name: str, size_pt: float, bold: bool, italic: bool):
    from PIL import ImageFont
    key = (name, round(size_pt * 4), bold, italic)
    if key not in _FONT_CACHE:
        path, _ = _font_file(name, bold, italic)
        try:
            _FONT_CACHE[key] = ImageFont.truetype(path, max(1, round(size_pt * 4)))
        except Exception:
            _FONT_CACHE[key] = None
    return _FONT_CACHE[key]


def _text_width_pt(text: str, font, size_pt: float) -> float:
    if font is None:
        return len(text) * size_pt * 0.55
    return font.getlength(text) / 4


def _paragraph_height(p, width_pt: float, wrap: bool, default_size: float) -> tuple[float, float, list]:
    """(height in pt, widest line in pt, fonts used) for one paragraph."""
    runs = [r for r in p.runs if r.text]
    sizes, fonts_used = [], []
    words: list[tuple[str, object, float]] = []
    for r in runs:
        size = (r.font.size.pt if r.font.size else
                p.font.size.pt if p.font.size else default_size)
        name = r.font.name or p.font.name or "Calibri"
        bold = bool(r.font.bold if r.font.bold is not None else p.font.bold)
        italic = bool(r.font.italic if r.font.italic is not None else p.font.italic)
        font = _measure_font(name, size, bold, italic)
        fonts_used.append(name)
        sizes.append(size)
        for chunk in re.split(r"(\s+)", r.text):
            if chunk:
                words.append((chunk, font, size))
    size = max(sizes) if sizes else (p.font.size.pt if p.font.size else default_size)
    spacing = p.line_spacing if isinstance(p.line_spacing, float) else 1.0
    line_h = (p.line_spacing.pt if p.line_spacing is not None and not isinstance(p.line_spacing, float)
              else size * 1.2 * spacing)
    extra = ((p.space_before.pt if p.space_before is not None else 0)
             + (p.space_after.pt if p.space_after is not None else 0))
    indent = 0.0
    pPr = p._p.pPr
    if pPr is not None and pPr.get("marL"):
        indent = int(pPr.get("marL")) / _EMU_PER_PT
    avail = max(1.0, width_pt - indent)

    if not words:
        return line_h + extra, 0.0, fonts_used
    lines, cur, widest = 1, 0.0, 0.0
    for text, font, sz in words:
        w = _text_width_pt(text, font, sz)
        if wrap and cur + w > avail and text.strip() and cur > 0:
            widest = max(widest, cur)
            lines += 1
            cur = 0.0 if not text.strip() else w
            if lines > 200:
                break
        else:
            cur += w
    widest = max(widest, cur)
    return lines * line_h + extra, widest + indent, fonts_used


def _shapes(container):
    for sh in container.shapes:
        yield sh
        if sh.shape_type == 6:                                   # group
            yield from _shapes(sh)


def lint(pptx: Path) -> list[str]:
    from pptx import Presentation
    from pptx.util import Emu

    prs = Presentation(str(pptx))
    sw, sh_ = prs.slide_width, prs.slide_height
    issues: list[str] = []
    missing_fonts: dict[str, str] = {}
    for n, slide in enumerate(prs.slides, 1):
        if not slide.has_notes_slide or not slide.notes_slide.notes_text_frame.text.strip():
            issues.append(f"slide {n}: no speaker notes")
        for shape in _shapes(slide):
            name = f"'{shape.name}'"
            l, t, w, h = shape.left, shape.top, shape.width, shape.height
            if None in (l, t, w, h):
                continue
            tol = Emu(int(0.02 * 914400))
            in_group = getattr(shape, "_parent", None) is not None and \
                shape._parent.__class__.__name__ == "GroupShapes"
            if not in_group and (l < -tol or t < -tol or l + w > sw + tol or t + h > sh_ + tol):
                # Deliberate bleeds are common for decorative shapes; text is not.
                if shape.has_text_frame and shape.text_frame.text.strip():
                    issues.append(f"slide {n}: text shape {name} runs off the slide")
            if not shape.has_text_frame or not shape.text_frame.text.strip():
                continue
            tf = shape.text_frame
            body = tf._txBody.find("{http://schemas.openxmlformats.org/drawingml/2006/main}bodyPr")
            vert = body is not None and body.get("vert") not in (None, "horz")
            if vert or getattr(shape, "rotation", 0) not in (0, 0.0):
                continue

            def m(v, default_in):
                return (v if v is not None else Emu(int(default_in * 914400))) / _EMU_PER_PT
            width_pt = w / _EMU_PER_PT - m(tf.margin_left, 0.1) - m(tf.margin_right, 0.1)
            height_pt = h / _EMU_PER_PT - m(tf.margin_top, 0.05) - m(tf.margin_bottom, 0.05)
            wrap = tf.word_wrap is not False
            if body is not None and body.get("wrap") == "none":
                wrap = False
            total, widest = 0.0, 0.0
            for p in tf.paragraphs:
                ph, pw, used = _paragraph_height(p, width_pt, wrap, 18.0)
                total += ph
                widest = max(widest, pw)
                for r in p.runs:
                    sz = r.font.size.pt if r.font.size else None
                    if sz is not None and sz < 12 and r.text.strip():
                        issues.append(f"slide {n}: {name} has {sz:g} pt text — too small "
                                      f"to read when projected (12 pt minimum)")
                        break
                for fam in used:
                    if fam not in missing_fonts:
                        path, exact = _font_file(fam)
                        missing_fonts[fam] = "" if exact else (Path(path).stem if path else "?")
            if total > height_pt * 1.04 + 2:
                issues.append(
                    f"slide {n}: text in {name} needs ~{total / 72:.2f} in of height, the box "
                    f"has {max(height_pt, 0) / 72:.2f} in — PowerPoint will let it spill "
                    f"out. Enlarge the box, shorten the text or reduce the size")
            if not wrap and widest > width_pt * 1.04 + 2:
                issues.append(f"slide {n}: {name} is one unwrapped line ~{widest / 72:.2f} in "
                              f"wide in a {width_pt / 72:.2f} in box")
    for fam, sub in missing_fonts.items():
        if sub:
            issues.append(f"font '{fam}' is not installed here (renders as {sub}) — "
                          f"`python3 kit.py font \"{fam}\"` or pick an installed one")
    return issues


# ── Images ───────────────────────────────────────────────────────────────────

def image(prompt: str, out: Path, aspect: str) -> str:
    sys.path.insert(0, str(_REPO))
    try:
        from actions import image_generator as ig
    except Exception as e:
        return f"ERROR: image generator unavailable ({e}) — design without pictures"
    import random
    import time
    w, h = ig._SIZES.get(aspect, ig._SIZES["landscape"])
    seed = random.randint(1, 2_000_000_000)
    keyless = not ig._pollinations_key()
    errors = []
    # One picture at a time, machine-wide: an agent that fires two calls in
    # parallel would only have them race for the same keyless allowance.
    lock = None
    try:
        import fcntl
        lock = open(Path(tempfile.gettempdir()) / "jarvis-image.lock", "w")
        fcntl.flock(lock, fcntl.LOCK_EX)
    except Exception:
        pass
    for name, fn in (("Pollinations", lambda: ig._pollinations(prompt, w, h, seed)),
                     ("Hugging Face", lambda: ig._huggingface(prompt, w, h, seed))):
        # Without a key Pollinations hands out about one picture every 45-50 s
        # (measured Oct 2026) and answers 402 in between, so a refusal there
        # means "wait", not "no". So does its occasional 500.
        deadline = time.monotonic() + (75 if name == "Pollinations" and keyless else 0)
        while True:
            try:
                data = fn()
                break
            except Exception as e:
                err = str(e)
                if (("allowance" in err or "keyless HTTP 5" in err)
                        and time.monotonic() < deadline):
                    time.sleep(10)
                    continue
                errors.append(f"{name}: {err[:80]}")
                data = None
                break
        if data is None:
            continue
        ext = ig._ext_for(data) or ".png"
        path = out.with_suffix(ext)
        path.write_bytes(data)
        try:
            from PIL import Image
            with Image.open(path) as im:
                w, h = im.size
        except Exception:
            pass
        return f"OK: {path} ({w}x{h} px)"
    if lock is not None:
        lock.close()
    return ("ERROR: no image provider answered (" + "; ".join(errors)
            + "). Do not retry — design these slides without pictures.")


# ── CLI ──────────────────────────────────────────────────────────────────────

def _install_missing(families: list[str]) -> list[str]:
    """Install the Google Fonts the page names but this machine lacks.
    Returns what could not be installed."""
    from core import html_deck
    left = []
    for fam in html_deck.missing_families(families):
        msg = install_font(fam)
        print(f"font: {msg}")
        if not msg.startswith("OK"):
            left.append(fam)
    return left


def _print_issues(title: str, issues: list[str]) -> None:
    if issues:
        print(f"\n{title} — {len(issues)} issue(s) to fix:")
        for line in issues:
            print(f"  - {line}")
    else:
        print(f"\n{title} — no issues found. Still look at the images with a designer's eye.")


def _cmd_html(html: Path) -> int:
    from core import html_deck
    out = html.parent / "html"
    try:
        shots, issues, fams = html_deck.shoot(html, out)
        before = html_deck.missing_families(fams)
        if before and len(_install_missing(fams)) < len(before):
            shots, issues, fams = html_deck.shoot(html, out)      # with the new fonts
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")
        return 1
    if not shots:
        _print_issues("LINT", issues)
        return 1
    for fam in html_deck.missing_families(fams):
        issues.append(f"font '{fam}' is not installed and is not a Google Font — the "
                      f"browser shows a fallback; pick a Google Font")
    sh = html_deck.sheets(shots, out)
    print(f"Rendered {len(shots)} slides to {out}/slide-NN.png (1920x1080)")
    print("Contact sheets (look at these first): " + ", ".join(str(s) for s in sh))
    _print_issues("LINT", issues)
    return 0


def _cmd_pptx(html: Path, pptx: Path) -> int:
    from core import html_deck
    work = html.parent / "convert"
    shutil.rmtree(work, ignore_errors=True)
    try:
        _, _, fams = html_deck.shoot(html, work / "probe")
        _install_missing(fams)
        report = html_deck.to_pptx(html, pptx, work)
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"ERROR: conversion failed: {type(e).__name__}: {e}")
        return 1
    print(f"PowerPoint written: {pptx} — {report['slides']} slides, "
          f"{report['editable']} editable text boxes")
    if report["raster"]:
        print("Text kept as picture (looks identical, not editable in PowerPoint):")
        for r in report["raster"][:30]:
            print(f"  - {r}")
    issues = [f"page error: {e}" for e in report["errors"]]
    try:
        render(pptx, work / "pptx")
        pptx_shots = sorted((work / "pptx").glob("slide-*.png"))
        cmp_sheets, drift = html_deck.compare(report["html_shots"], pptx_shots, work)
        print("Comparison sheets, HTML left / PowerPoint right (look at them): "
              + ", ".join(str(s) for s in cmp_sheets))
        issues += drift
    except Exception as e:
        issues.append(f"could not render the PowerPoint for comparison: {e}")
    try:
        issues += [i for i in lint(pptx) if "no speaker notes" in i or "not installed" in i]
    except Exception:
        pass
    _print_issues("CONVERSION", issues)
    return 0


def _cmd_motion(html: Path, at: str) -> int:
    from core import html_deck
    text = html.read_text(encoding="utf-8", errors="replace")
    dur = html_deck.motion_duration(text, 0)
    if not dur:
        print('ERROR: add <meta name="duration" content="SECONDS"> to the page')
        return 1
    if at.strip():
        times = [float(t) for t in at.split(",") if t.strip()]
    else:
        n = 9 if dur <= 45 else 12
        times = [round(dur * (k + 0.5) / n, 2) for k in range(n)]
    times = [min(max(0.0, t), dur) for t in times]
    try:
        shots, errors = html_deck.motion_frames(html, html.parent / "motion", times)
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")
        return 1
    out = html.parent / "motion"
    sheet_paths = []
    for s in range(0, len(shots), 9):
        chunk = shots[s:s + 9]
        sheet_paths.append(html_deck._sheet(chunk, out / f"sheet-{s // 9 + 1}.png",
                                            [f"{t:g}s" for t in times[s:s + 9]]))
    print(f"Duration {dur:g}s. Frames at " + ", ".join(f"{t:g}s" for t in times))
    print("Frame sheets (look at them): " + ", ".join(str(p) for p in sheet_paths))
    _print_issues("MOTION", [f"page error: {e}" for e in errors])
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="kit.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("render")
    r.add_argument("pptx")
    r.add_argument("--out", default="")
    sub.add_parser("fonts")
    f = sub.add_parser("font")
    f.add_argument("family")
    i = sub.add_parser("image")
    i.add_argument("prompt")
    i.add_argument("out")
    i.add_argument("--aspect", default="landscape",
                   choices=["landscape", "square", "portrait", "wide"])
    h = sub.add_parser("html")
    h.add_argument("html")
    x = sub.add_parser("pptx")
    x.add_argument("html")
    x.add_argument("pptx")
    m = sub.add_parser("motion")
    m.add_argument("html")
    m.add_argument("--at", default="", help="comma-separated seconds")
    a = ap.parse_args(argv)
    sys.path.insert(0, str(_REPO))

    if a.cmd == "html":
        return _cmd_html(Path(a.html).resolve())
    if a.cmd == "pptx":
        return _cmd_pptx(Path(a.html).resolve(), Path(a.pptx).resolve())
    if a.cmd == "motion":
        return _cmd_motion(Path(a.html).resolve(), a.at)

    if a.cmd == "fonts":
        print(", ".join(installed_families()))
        print("\nAny Google Font can be added with: python3 kit.py font \"Family Name\"")
        return 0
    if a.cmd == "font":
        msg = install_font(a.family)
        print(msg)
        return 0 if msg.startswith("OK") else 1
    if a.cmd == "image":
        msg = image(a.prompt, Path(a.out), a.aspect)
        print(msg)
        return 0 if msg.startswith("OK") else 1

    pptx = Path(a.pptx).resolve()
    out = Path(a.out).resolve() if a.out else pptx.parent / "render"
    try:
        sheets = render(pptx, out)
    except Exception as e:
        print(f"ERROR: {e}")
        return 1
    print(f"Rendered {len(list(out.glob('slide-*.png')))} slides to {out}/slide-NN.png")
    print("Contact sheets (look at these first): " + ", ".join(str(s) for s in sheets))
    try:
        issues = lint(pptx)
    except Exception as e:
        issues = [f"(lint failed: {type(e).__name__}: {e})"]
    if issues:
        print(f"\nLINT — {len(issues)} issue(s) to fix:")
        for line in issues:
            print(f"  - {line}")
    else:
        print("\nLINT — no issues found. Still check the sheets with your own eyes.")
    print(json.dumps({"sheets": [str(s) for s in sheets], "issues": len(issues)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
