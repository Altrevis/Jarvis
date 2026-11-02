"""
Rebuilds the presentation from the two sources in this folder, with Jarvis's
own renderers (core/html_deck.py and actions/create_motion_video.py):

    slides.html  ->  ../Jarvis-slides.pptx   PowerPoint, text kept editable
                     ../Jarvis-slides.pdf    one page per slide
                     ../Jarvis-slides.html   self-contained web version
    motion.html  ->  ../Jarvis-motion.mp4    1920x1080, 30 fps, H.264, with a
                     voice-over (narration.json, Gemini TTS) and music (audio.py)

Run from the project root:   .venv/bin/python présentation/source/build.py
Only one part:               ... build.py slides  |  ... build.py motion
Sound only (keeps the cached silent render):        ... build.py son
"""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent
sys.path.insert(0, str(OUT.parent))

from core import html_deck                              # noqa: E402
from actions.create_motion_video import _render         # noqa: E402


def slides() -> None:
    src = HERE / "slides.html"
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        shots, issues, families = html_deck.shoot(src, tmp / "shots")
        for issue in issues:
            print(f"  ! {issue}")
        html_deck.export_web(src, OUT / "Jarvis-slides.html", families)
        print(f"web      {OUT / 'Jarvis-slides.html'}")
        report = html_deck.to_pptx(src, OUT / "Jarvis-slides.pptx", tmp / "convert")
        print(f"pptx     {OUT / 'Jarvis-slides.pptx'} — {report['slides']} slides, "
              f"{report['editable']} editable text boxes")
    _pdf(src, OUT / "Jarvis-slides.pdf")
    print(f"pdf      {OUT / 'Jarvis-slides.pdf'}")


def _pdf(src: Path, out: Path) -> None:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": html_deck.SW, "height": html_deck.SH})
            page.goto(src.resolve().as_uri(), wait_until="load")
            try:
                page.wait_for_load_state("networkidle", timeout=15_000)
            except Exception:
                pass
            page.add_style_tag(content=html_deck._BASE_CSS
                               + "section.slide { break-after: page; }")
            page.evaluate("document.fonts.ready.then(() => true)")
            page.pdf(path=str(out), width=f"{html_deck.SW}px", height=f"{html_deck.SH}px",
                     print_background=True, margin={"top": "0", "right": "0",
                                                    "bottom": "0", "left": "0"})
        finally:
            browser.close()


SILENT = HERE / "cache" / "motion-muet.mp4"


def motion() -> None:
    """The picture, without sound, into cache/ — then the soundtrack on top."""
    html = (HERE / "motion.html").read_text(encoding="utf-8")
    duration = html_deck.motion_duration(html, 49)
    SILENT.parent.mkdir(exist_ok=True)
    t0 = time.monotonic()
    errors, _ = _render(html, SILENT, 1920, 1080, 30, duration, [],
                        lambda msg: print(f"  {msg}", flush=True))
    for e in errors:
        print(f"  ! {e}")
    print(f"video    {SILENT} — {duration:g}s, rendered in {time.monotonic() - t0:.0f}s")
    sound()


def sound() -> None:
    """Voice-over (narration.json) and music, mixed onto the silent render."""
    import audio
    if not SILENT.exists():
        motion()
        return
    print("voice")
    voice = audio.voice(lambda msg: print(msg, flush=True))
    print("music")
    music = audio.music(lambda msg: print(msg, flush=True))
    audio.mix(SILENT, voice, music, OUT / "Jarvis-motion.mp4")
    print(f"mp4      {OUT / 'Jarvis-motion.mp4'} — with voice and music")


if __name__ == "__main__":
    sys.path.insert(0, str(HERE))
    what = set(sys.argv[1:]) or {"slides", "motion"}
    if "slides" in what:
        slides()
    if "motion" in what:
        motion()
    elif "son" in what:
        sound()
