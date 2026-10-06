"""
create_motion_video — motion design, written by Claude, rendered here to MP4.

Claude is a motion designer who writes code, so the animation is written as one
HTML page — CSS animations, SVG, canvas, GSAP — and rendered on this machine:

    1. Claude writes the page for an exact frame size and duration.
    2. Chromium (already here for browser_control) loads it with every clock the
       page can read — requestAnimationFrame, performance.now, Date, timers,
       CSS and Web Animations — replaced by a virtual one. Each frame is taken
       at exactly i / fps seconds, however long it took to draw, so the video is
       smooth on any machine and identical every time.
    3. ffmpeg (imageio-ffmpeg) encodes the frames to H.264.
    4. Claude looks at four of the frames and fixes what it sees — text cut off
       by the edge, overlaps, an empty frame — then it is rendered again.

The MP4 plays on the HUD when it is done and is saved in <Videos>/JARVIS/motion
with the HTML beside it, so an animation can be tweaked and re-rendered.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from core import gemini, jobs
from core.user_dirs import jarvis_videos_dir

_WRITER = "gemini-3.5-flash"        # REST if Gemini ever has to step in; see create_document
_WRITE_TIMEOUT_MS = 300_000
_FORMATS = {"landscape": (1920, 1080), "portrait": (1080, 1920), "square": (1080, 1080)}
_GSAP = "https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.5/gsap.min.js"

# Every clock a page can read, replaced by one the renderer moves. Installed
# before any of the page's own scripts run.
_VIRTUAL_TIME = r"""
(() => {
  let now = 0;
  const RealDate = Date, start = RealDate.now();
  let raf = new Map(), rafId = 0;
  const timers = new Map(); let timerId = 0;
  Object.defineProperty(performance, 'now', {value: () => now, configurable: true});
  window.Date = class extends RealDate {
    constructor(...a) { if (a.length) super(...a); else super(start + now); }
    static now() { return start + now; }
  };
  window.requestAnimationFrame = cb => { raf.set(++rafId, cb); return rafId; };
  window.cancelAnimationFrame = id => { raf.delete(id); };
  window.setTimeout = (fn, ms, ...args) => {
    timers.set(++timerId, {at: now + Math.max(0, +ms || 0), fn, args, every: 0});
    return timerId;
  };
  window.setInterval = (fn, ms, ...args) => {
    const every = Math.max(1, +ms || 1);
    timers.set(++timerId, {at: now + every, fn, args, every});
    return timerId;
  };
  window.clearTimeout = window.clearInterval = id => { timers.delete(id); };
  const born = new WeakMap();
  window.__motionAdvance = t => {
    for (let guard = 0; guard < 10000; guard++) {
      let next = null;
      for (const [id, tm] of timers)
        if (tm.at <= t && (!next || tm.at < next[1].at)) next = [id, tm];
      if (!next) break;
      const [id, tm] = next;
      now = tm.at;
      if (tm.every) tm.at += tm.every; else timers.delete(id);
      try { typeof tm.fn === 'function' ? tm.fn(...tm.args) : (0, eval)(tm.fn); }
      catch (e) { console.error(e && e.message || String(e)); }
    }
    now = t;
    const cbs = raf; raf = new Map();
    for (const cb of cbs.values()) {
      try { cb(now); } catch (e) { console.error(e && e.message || String(e)); }
    }
    for (const a of document.getAnimations()) {
      if (!born.has(a)) born.set(a, now);
      a.pause();
      a.currentTime = Math.max(0, t - born.get(a));
    }
  };
})();
"""


def _ffmpeg() -> str | None:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return shutil.which("ffmpeg")


def _slug(text: str) -> str:
    try:
        from core.fuzzy_find import normalize
        text = normalize(text)
    except Exception:
        pass
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:48] or "motion"


def _extract_html(text: str) -> str | None:
    m = re.search(r"<!DOCTYPE html.*</html>", text or "", re.S | re.I)
    return m.group(0) if m else None


# ── Writing ──────────────────────────────────────────────────────────────────

def _brief(request, style, language, duration, w, h, fps) -> str:
    safe = round(min(w, h) * 0.06)
    return f"""You are a senior motion designer. Create a {duration:g}-second motion
design animation as ONE self-contained HTML file. A headless browser renders it
frame by frame into a {w}x{h} MP4 at {fps} fps.

THE BRIEF
{request}
Style: {style or "your call — pick what serves the brief"}.
Language of any on-screen text: {language or "the language of the brief"}.

HARD TECHNICAL RULES — the renderer depends on them
- The page is exactly {w}x{h} px: html, body {{ margin: 0; width: {w}px;
  height: {h}px; overflow: hidden; }} with a full-bleed background. Design for
  that exact size; no responsive layout, no scrollbars.
- It starts by itself when the page loads and lasts exactly {duration:g} s. The
  last ~0.8 s holds the final composition (or the loop closes seamlessly).
  Nothing waits for clicks, hover, scroll or audio.
- Time comes ONLY from CSS animations/transitions, element.animate(), GSAP
  (<script src="{_GSAP}"></script>; plugins from the same cdnjs folder),
  requestAnimationFrame's timestamp, performance.now() or setTimeout /
  setInterval. The renderer drives all of these. No <video>, <audio>, GIF,
  Lottie, WebGL / three.js, or scroll-driven animation.
- Build any GSAP timeline at load. No infinite repeat unless the loop is seamless.
- At most two Google Fonts via <link>. No images from the network: draw with
  HTML, CSS, SVG or canvas.
- No console errors.

DESIGN
- Real motion design: one clear concept, deliberate easing (linear only for
  constant drifts), staggered reveals, depth through scale, opacity and blur,
  strong typographic hierarchy, a palette of 2-4 colours, generous space, and an
  intro, development and outro.
- On-screen text stays long enough to read (at least 0.3 s per word) and never
  touches the frame edge: keep a {safe}px safe margin.
- Keep it renderable: no animated full-screen blur filters, no thousands of DOM
  nodes; canvas particles are fine up to ~1500.

Output ONLY the HTML document, starting with <!DOCTYPE html>."""


def _write(prompt: str, images=None) -> str | None:
    contents = list(images or []) + [prompt]
    return gemini.text(contents if images else prompt, tier=_WRITER,
                       timeout_ms=_WRITE_TIMEOUT_MS)


# ── Rendering ────────────────────────────────────────────────────────────────

def _render(html: str, out: Path, w: int, h: int, fps: int, duration: float,
            keep_at: list[float], progress) -> tuple[list[str], dict[float, bytes]]:
    """Render the page to `out`. Returns (page errors, {second: jpeg} for the
    requested review times)."""
    from playwright.sync_api import sync_playwright

    ff = _ffmpeg()
    if not ff:
        raise RuntimeError("ffmpeg is missing — pip install imageio-ffmpeg")
    frames = max(1, round(duration * fps))
    want = {min(frames - 1, round(t * fps)): t for t in keep_at}
    kept: dict[float, bytes] = {}
    errors: list[str] = []

    tmp = Path(tempfile.mkdtemp(prefix="jarvis-motion-"))
    page_file = tmp / "index.html"
    page_file.write_text(html, encoding="utf-8")
    enc = subprocess.Popen(
        [ff, "-y", "-loglevel", "error", "-f", "image2pipe", "-vcodec", "mjpeg",
         "-framerate", str(fps), "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-preset", "medium", "-crf", "18", "-movflags", "+faststart", str(out)],
        stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page(viewport={"width": w, "height": h},
                                        device_scale_factor=1)
                page.on("pageerror", lambda e: errors.append(str(e)[:300]))
                page.on("console", lambda m: errors.append(m.text[:300])
                        if m.type == "error" else None)
                page.add_init_script(_VIRTUAL_TIME)
                page.goto(page_file.as_uri(), wait_until="load", timeout=60_000)
                try:
                    page.wait_for_load_state("networkidle", timeout=15_000)
                    page.evaluate("document.fonts.ready.then(() => true)")
                except Exception:
                    pass
                t0 = time.monotonic()
                for i in range(frames):
                    page.evaluate("t => window.__motionAdvance(t)", i * 1000.0 / fps)
                    jpg = page.screenshot(type="jpeg", quality=92)
                    enc.stdin.write(jpg)
                    if i in want:
                        kept[want[i]] = jpg
                    if i and i % (fps * 2) == 0:
                        progress(f"frame {i}/{frames} ({time.monotonic() - t0:.0f}s)")
            finally:
                browser.close()
    finally:
        try:
            enc.stdin.close()
        except Exception:
            pass
        enc.wait(timeout=300)
        shutil.rmtree(tmp, ignore_errors=True)
    if enc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {enc.stderr.read().decode(errors='replace')[-300:]}")
    return list(dict.fromkeys(errors))[:12], kept


def _blank(jpgs: list[bytes]) -> bool:
    """True when every sampled frame is one flat colour — a page that never drew."""
    try:
        import io
        from PIL import Image, ImageStat
        return all(sum(ImageStat.Stat(Image.open(io.BytesIO(j)).convert("L")).stddev) < 2.0
                   for j in jpgs)
    except Exception:
        return False


def _review_parts(kept: dict[float, bytes]) -> list:
    """The sampled frames as image parts, shrunk: a review does not need 1080p."""
    import io
    from google.genai import types
    from PIL import Image
    parts = []
    for t in sorted(kept):
        im = Image.open(io.BytesIO(kept[t])).convert("RGB")
        im.thumbnail((960, 960))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=85)
        parts.append(types.Part.from_bytes(data=buf.getvalue(), mime_type="image/jpeg"))
    return parts


# ── Tool ─────────────────────────────────────────────────────────────────────

def create_motion_video(parameters: dict, player=None) -> str:
    p = parameters or {}
    request = str(p.get("request") or "").strip()
    if not request:
        return ("Describe the animation in 'request': message, on-screen text, mood, "
                "colours, where it will be used.")
    if not _ffmpeg():
        return "Video encoding is not available: pip install imageio-ffmpeg"
    fmt = str(p.get("format") or "landscape").lower()
    w, h = _FORMATS.get(fmt, _FORMATS["landscape"])
    duration = max(3.0, min(float(p.get("duration") or 8), 60.0))
    fps = int(p.get("fps") or 30)
    fps = fps if fps in (24, 25, 30, 60) else 30
    style = str(p.get("style") or "").strip()
    language = str(p.get("language") or "").strip()
    polish = p.get("polish", True) is not False

    label = f"MOTION — {' '.join(request.split())[:46]}"

    def work(progress) -> str:
        t_start = time.monotonic()
        progress("Claude is designing the animation")
        html = _extract_html(_write(_brief(request, style, language, duration, w, h, fps)))
        if not html:
            raise RuntimeError("the model did not return an HTML animation")

        out_dir = jarvis_videos_dir("motion")
        title = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
        stem = f"{time.strftime('%Y%m%d-%H%M%S')}-{_slug(title.group(1) if title else request[:40])}"
        out = out_dir / f"{stem}.mp4"
        review_at = [round(duration * f, 2) for f in (0.15, 0.4, 0.7, 0.97)]

        errors, kept = [], {}
        for attempt in range(3):
            progress(f"rendering {round(duration * fps)} frames at {w}x{h}"
                     + (f" (pass {attempt + 1})" if attempt else ""))
            errors, kept = _render(html, out, w, h, fps, duration, review_at, progress)
            problems = list(errors)
            if _blank(list(kept.values())):
                problems.append("every sampled frame is a single flat colour — nothing is drawn")
            if attempt == 2:
                break
            if problems:
                progress(f"fixing: {problems[0][:80]}")
                fixed = _extract_html(_write(
                    f"This HTML animation for a {w}x{h}, {duration:g}-second video has "
                    f"problems when rendered:\n- " + "\n- ".join(problems) +
                    "\n\nFix them, keep the design, follow the same rules as before "
                    "(virtual-time friendly, exact size, no network images). Return "
                    "the complete corrected HTML only.\n\n" + html))
                if fixed:
                    html = fixed
                    continue
                break
            if not polish:
                break
            progress("Claude is reviewing the frames")
            times = ", ".join(f"{t:g}s" for t in sorted(kept))
            verdict = _write(
                f"These are frames at {times} of the motion design video rendered from "
                f"the HTML below ({w}x{h}, {duration:g}s). The brief was: {request}\n\n"
                f"Check them like a senior motion designer: text cut off or touching "
                f"the edge, overlapping elements, unreadable contrast, empty or "
                f"unbalanced frames, an unfinished final frame, anything that misses "
                f"the brief. If it is good, reply with exactly OK. Otherwise return "
                f"the complete corrected HTML only.\n\n{html}",
                images=_review_parts(kept))
            fixed = _extract_html(verdict or "")
            if not fixed:
                break
            progress("applying the review")
            html = fixed

        (out_dir / f"{stem}.html").write_text(html, encoding="utf-8")
        if player is not None and hasattr(player, "show_video"):
            player.show_video(str(out), f"MOTION — {out.name}", muted=True)
        warn = f" The page still reported: {errors[0]}." if errors else ""
        return (f"The {duration:g}-second motion design video is ready after "
                f"{time.monotonic() - t_start:.0f}s and is playing on the display: "
                f"{out} (its HTML source is next to it).{warn} Tell the user in one "
                f"sentence and name the folder.")

    jobs.start(player, label, work)
    return ("status=started_in_background. Claude designs it, then it is rendered "
            "frame by frame — usually two to five minutes; you will be told when it "
            "plays. Say one short sentence.")


TOOL = {
    "name": "create_motion_video",
    "description": (
        "Creates a motion design video (MP4): animated titles, kinetic typography, "
        "logo reveals, animated infographics and key figures, intros, social media "
        "clips, explainer sequences. Claude designs it and it is rendered on this "
        "computer frame by frame, then plays on the display. Silent video. Runs in "
        "the background (2-5 minutes). Put the full brief in 'request': message, "
        "exact on-screen text, mood, colours, brand, purpose. Saved in the user's "
        "Videos/JARVIS/motion folder."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "request": {"type": "STRING",
                        "description": "The full creative brief, including any exact on-screen text"},
            "duration": {"type": "NUMBER", "description": "Seconds, 3 to 60 (default 8)"},
            "format": {"type": "STRING",
                       "description": "landscape 1920x1080 (default) | portrait 1080x1920 | square 1080x1080"},
            "style": {"type": "STRING",
                      "description": "Optional look: minimal, neon, corporate, playful, cinematic, retro…"},
            "language": {"type": "STRING", "description": "Language of on-screen text, e.g. 'French'"},
            "fps": {"type": "INTEGER", "description": "24, 25, 30 (default) or 60"},
            "polish": {"type": "BOOLEAN",
                       "description": "Let Claude review rendered frames and fix issues (default true; false is faster)"},
        },
        "required": ["request"],
    },
    "handler": create_motion_video,
}
