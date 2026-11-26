"""
lecture — « Écoute le cours »: a lecture listened to in the background,
transcribed by Gemini as it goes, and a PDF synthesis when it ends.

WHY
    The user follows many lectures, cannot type everything on the computer,
    and some of what is said matters a great deal to them. One button in the
    window (right column) starts listening; the same button stops it, and the
    synthesis is made.

HOW
    - A microphone stream of its own, on the microphone picked in ⚙ AUDIO,
      beside the Live one: the recording carries on through a reconnect or a
      /compact of the conversation. The window mutes Jarvis's microphone while
      it runs, or the Live model would hear — and bill — the whole lecture.
    - The audio is cut into segments of SEGMENT_SECONDS. Each finished
      segment is encoded to MP3 (with the ffmpeg imageio-ffmpeg ships) and
      transcribed by Gemini on a worker of its own, each segment on its own
      and at temperature 0 (see the note above _transcript_prompt): the
      transcription is done while the lecture goes on, and stopping only
      waits for the last segment.
    - Then one more call reads the whole transcription, writes the synthesis
      — what the teacher stressed, the instructions and dates included — and
      the PDF (Chromium, as create_document renders it) opens: the synthesis
      first, the timestamped transcription after it.
    - Gemini only (core.gemini.direct): Claude takes no audio, and the user
      asked for this one to stay on Gemini.

WHAT IS KEPT ON DISK, AND WHY
    Everything finish() needs is in the folder — the audio, segments.json (when
    each segment starts) and the transcription — so a segment Gemini could not
    transcribe during the lecture (no network, quota) is done at the end, and a
    lecture cut short by Jarvis closing can still be finished later:
        python -m actions.lecture "<the lecture's folder>"

COST
    Gemini counts audio at 32 tokens a second: about 19 000 tokens per ten
    minutes, 175 000 for an hour and a half, plus the text it writes. A
    segment with nothing audible (a break, a dead microphone) is not sent.

FILES — <Documents>/JARVIS/cours/<date heure>/
    audio/segment-01.mp3 …           the lecture, to listen to again
    transcription/segment-01.md …    what was said, segment by segment
    segments.json                    when each segment starts, how long, how loud
    synthese.md                      synthesis + transcription, plain editable text
    <titre>.html, <titre>.pdf
"""
from __future__ import annotations

import html
import json
import queue
import re
import subprocess
import sys
import threading
import time
import wave
from datetime import datetime
from pathlib import Path

from core import gemini
from core.user_dirs import jarvis_documents_dir

SEGMENT_SECONDS = 10 * 60
RATE = 16_000
_BLOCK = 1024
# A segment whose loudest sample stays under this holds nothing to note (a
# muted or dead microphone reads 0 to a few dozen). Kept low on purpose: a
# distant voice must never be taken for silence and skipped.
SILENT_PEAK = 150
_TIMEOUT_MS = 150_000      # per model tried: a stalled one gives way to the next
_MP3_BITRATE = "32k"        # speech, mono: ~2.4 MB per ten minutes
_NOTHING = "(silence)"
_FOLDER_FORMAT = "%Y-%m-%d %Hh%M"      # the lecture's folder: when it started
# Temperature 0 to transcribe: the same audio gives the same words, and the
# model does not improvise. The synthesis is writing, a little more freedom.
_TRANSCRIBE_TEMPERATURE = 0.0
_SYNTHESIS_TEMPERATURE = 0.3
_RETRY_AFTER = 15           # seconds before a segment no model took is tried again

_active: "Lecture | None" = None    # one lecture at a time


def _clock(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


def _ffmpeg() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


# ── Prompts ──────────────────────────────────────────────────────────────────

# What was measured on 2026-11-26, and shaped this:
# - Asked for notes that also judged what mattered, the lite model wrote "no
#   content" for the very segment where the teacher said "c'est très
#   important, ce sera à l'examen". So: a plain transcription per segment —
#   what a model does reliably — and finding what was stressed is a text task
#   over the whole lecture, in the synthesis.
# - Given the end of the previous segment "for continuity", the model
#   continued the story instead of transcribing: one segment came back as an
#   invented dialogue (a hotel, a train) and the next one carried it on. Each
#   segment is now transcribed on its own; a word cut at a boundary costs far
#   less than a passage made up.

def _transcript_prompt(seg: dict) -> str:
    # The segment's place in the lecture is NOT given: told "from 0:20 to
    # 0:40", the model wrote lecture times, and they were offset a second time.
    prompt = (
        f"Transcris fidèlement, en français, l'audio joint : un extrait de "
        f"{max(1, round(seg['seconds'] / 60))} minute(s) d'un cours.\n"
        f"- Écris ce qui est dit, phrase par phrase, sans résumer et sans rien trier : retire "
        f"seulement les hésitations (euh, hum) et les répétitions involontaires.\n"
        f"- Va à la ligne à chaque changement d'idée, et commence chaque paragraphe par son "
        f"moment depuis le début de cet extrait, au format [MM:SS].\n"
        f"- Un passage incompréhensible s'écrit [inaudible] : ne devine pas un mot que tu "
        f"n'entends pas.\n"
        f"- Une intervention d'étudiant commence par « — Étudiant : ».\n"
        f"- N'écris que ce que tu entends dans cet audio : n'ajoute aucune phrase, ne complète "
        f"pas une idée coupée au début ou à la fin de l'extrait.\n"
        f"- Seulement s'il n'y a aucune parole dans tout l'extrait, écris : {_NOTHING}\n"
        f"Réponds uniquement avec la transcription.")
    return prompt


def _synthesis_prompt(transcript: str, seconds: float) -> str:
    sections = (
        ("L'essentiel", "5 à 8 phrases qui disent de quoi parle le cours et ce qu'il apprend."),
        ("Plan du cours", "les parties du cours, dans l'ordre, en liste."),
        ("À retenir absolument",
         "chaque passage où l'enseignant signale que c'est important — « c'est important », "
         "« retenez », « à savoir », « ce sera à l'examen », « je le répète », une formule ou "
         "une définition qu'il répète. Une puce par point, qui commence par « ⚠ », avec "
         "l'horodatage [H:MM:SS] du passage pris dans la transcription. N'en oublie aucun ; "
         "« Aucun point signalé. » s'il n'y en a pas."),
        ("Notions et définitions",
         "une puce par notion : « **terme** : définition », la définition telle que "
         "l'enseignant la donne ; pour une notion qu'il cite sans la définir, écris « (citée, "
         "non définie dans le cours) » plutôt qu'une définition de ton cru."),
        ("Exemples et méthodes", "les exemples, démonstrations et méthodes du cours."),
        ("Consignes et dates",
         "les devoirs, rendus, dates, examens et lectures demandés : une puce par consigne, qui "
         "commence par « 📌 », avec son horodatage ; « Aucune. » s'il n'y en a pas."),
        ("Questions pour réviser", "5 questions numérotées."),
    )
    return (
        f"Voici la transcription d'un cours de {max(1, round(seconds / 60))} minute(s), segment "
        f"par segment ; [H:MM:SS] donne le moment de chaque paragraphe dans le cours. Rédige la "
        f"synthèse du cours en français, en Markdown, pour un étudiant qui révise.\n"
        f"La transcription vient de la reconnaissance vocale : un mot qui ne fait pas sens dans "
        f"le contexte est une erreur d'écoute — corrige-le d'après le contexte, ou laisse-le de "
        f"côté, ne le recopie pas.\n"
        f"Commence par « # » suivi du titre du cours, déduit de son contenu. Puis ces sections, "
        f"avec ces titres exacts et rien d'autre sur la ligne du titre :\n"
        + "\n".join(f"## {title}\n   → {what}" for title, what in sections)
        + "\nN'ajoute rien qui ne soit pas dans la transcription. Réponds seulement avec le "
        f"Markdown.\n\nTRANSCRIPTION :\n{transcript}")


def _demote(md: str) -> str:
    """Notes under a segment heading: their own headings one level down."""
    return re.sub(r"^(#{1,5})(?=\s)", r"#\1", md, flags=re.M)


# ── Times ────────────────────────────────────────────────────────────────────

def _absolute_times(text: str, seg: dict) -> str:
    """A time in the segment — [MM:SS], or [HH:MM:SS] as some models write it —
    → [H:MM:SS] in the lecture, so a point can be found again in the audio.
    Applied once, to the model's raw text. A time past the segment's end is
    left as it is rather than turned into a wrong one."""
    def swap(m: re.Match) -> str:
        t = int(m.group(1) or 0) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
        if t > seg["seconds"] + 30:
            return m.group(0)
        return f"[{_clock(seg['start'] + t)}]"
    return re.sub(r"\[(?:(\d{1,2}):)?(\d{1,2}):([0-5]\d)\]", swap, text)


# ── Markdown → clean HTML (no dependency; the output is meant to be edited) ──

def _inline(text: str) -> str:
    out = html.escape(text, quote=False)
    out = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", out)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    out = re.sub(r"\[(\d+:\d{2}(?::\d{2})?)\]", r'<span class="time">[\1]</span>', out)
    return out


def _cls(text: str) -> str:
    if text.startswith("⚠"):
        return ' class="important"'
    if text.startswith("📌"):
        return ' class="consigne"'
    return ""


def md_to_html(md: str, indent: int = 2) -> str:
    """Headings, nested bullet and numbered lists, paragraphs, rules, bold,
    italic, code — what the notes and the synthesis use. One element per line,
    indented, so the file reads and edits by hand."""
    out: list[str] = []
    stack: list[tuple[str, int]] = []          # open lists: (tag, level)
    para: list[str] = []
    gap = False                                # a blank line since the last text

    def put(line: str) -> None:
        out.append("  " * (indent + 2 * len(stack)) + line)

    def flush() -> None:
        if para:
            text = " ".join(para)
            put(f"<p{_cls(text)}>{_inline(text)}</p>")
            para.clear()

    def close_to(level: int) -> None:
        while stack and stack[-1][1] > level:
            tag, _ = stack.pop()
            out.append("  " * (indent + 2 * len(stack) + 1) + "</li>")
            put(f"</{tag}>")

    for raw in md.splitlines():
        line = raw.rstrip()
        text = line.strip()
        if not text:
            flush()
            gap = True
            continue
        after_gap, gap = gap, False
        head = re.match(r"(#{1,4})\s+(.*)", text)
        if head and not line.startswith(" "):
            flush()
            close_to(-1)
            n = len(head.group(1))
            put(f"<h{n}>{_inline(head.group(2))}</h{n}>")
            continue
        if re.fullmatch(r"(-{3,}|\*{3,}|_{3,})", text):
            flush()
            close_to(-1)
            put("<hr>")
            continue
        item = re.match(r"(\s*)([-*+]|\d+[.)])\s+(.*)", line)
        if item:
            flush()
            level = len(item.group(1).expandtabs(4)) // 2
            tag = "ol" if item.group(2)[0].isdigit() else "ul"
            close_to(level)
            if stack and stack[-1][1] == level:
                if stack[-1][0] == tag:
                    out.append("  " * (indent + 2 * len(stack) - 1) + "</li>")
                else:
                    close_to(level - 1)
            if not stack or stack[-1][1] < level:
                put(f"<{tag}>")
                stack.append((tag, level))
            body = item.group(3)
            out.append("  " * (indent + 2 * len(stack) - 1) + f"<li{_cls(body)}>{_inline(body)}")
            continue
        if stack and not after_gap and line[:1].isspace():   # the item above, carried on
            out[-1] += " " + _inline(text)
            continue
        # Anything else ends the list: a « ⚠ IMPORTANT » line right under the
        # bullets is a block of its own, not the end of the last bullet.
        close_to(-1)
        if _cls(text):                  # each ⚠ / 📌 line stands alone
            flush()
            para.append(text)
            flush()
            continue
        para.append(text)
    flush()
    close_to(-1)
    return "\n".join(out)


_CSS = """
    @page { size: A4; margin: 18mm 16mm 20mm; }
    body { font-family: "Segoe UI", "Noto Sans", "DejaVu Sans", Arial, sans-serif;
           color: #1d2330; font-size: 10.5pt; line-height: 1.5; }
    header { border-bottom: 3px solid #4f46e5; margin-bottom: 18px; padding-bottom: 8px; }
    header .kicker { color: #4f46e5; font-weight: 700; letter-spacing: 2px; font-size: 8.5pt; }
    header .meta { color: #667085; font-size: 9pt; }
    h1 { font-size: 20pt; margin: 4px 0 2px; }
    h2 { font-size: 13.5pt; color: #312e81; margin: 20px 0 6px;
         border-bottom: 1px solid #e0e3ea; padding-bottom: 3px; }
    h3 { font-size: 11.5pt; margin: 14px 0 4px; }
    h2, h3 { break-after: avoid; }
    ul, ol { margin: 4px 0 8px; padding-left: 20px; }
    li { margin: 2px 0; }
    li, p { break-inside: avoid; }
    .important { background: #fff4e5; border-left: 3px solid #f59e0b; padding: 2px 6px;
                 list-style: none; margin-left: -14px; }
    .consigne { background: #eef2ff; border-left: 3px solid #4f46e5; padding: 2px 6px;
                list-style: none; margin-left: -14px; }
    .time { color: #667085; font-family: "DejaVu Sans Mono", monospace; font-size: 8.5pt; }
    code { background: #f2f4f7; padding: 0 3px; border-radius: 3px; }
    .transcript { break-before: page; }
    .transcript h2.segment { color: #667085; font-size: 10.5pt; letter-spacing: 1px; }
    .transcript p { margin: 0 0 6px; }
    .missing { color: #b42318; }
"""


def _page(title: str, meta: str, synthesis: str, transcript: list[tuple[str, str]]) -> str:
    parts = [
        "<!DOCTYPE html>",
        '<html lang="fr">',
        "<head>",
        '  <meta charset="utf-8">',
        f"  <title>{html.escape(title)}</title>",
        f"  <style>{_CSS}  </style>",
        "</head>",
        "<body>",
        "  <header>",
        '    <div class="kicker">SYNTHÈSE DE COURS</div>',
        f'    <div class="meta">{html.escape(meta)}</div>',
        "  </header>",
        "  <main>",
        md_to_html(synthesis, indent=2),
        "  </main>",
        '  <section class="transcript">',
        "    <h1>Transcription</h1>",
    ]
    for heading, body in transcript:
        parts.append(f'    <h2 class="segment">{html.escape(heading)}</h2>')
        parts.append(md_to_html(body, indent=2))
    parts += ["  </section>", "</body>", "</html>", ""]
    return "\n".join(parts)


# ── The lecture ──────────────────────────────────────────────────────────────

class Lecture:
    """One lecture: listen() records and transcribes as it goes, stop() ends
    the recording, finish() makes the synthesis. finish() also works on a
    folder left by a lecture that did not get that far (from_folder)."""

    def __init__(self, folder: Path | None = None):
        if folder is None:
            root = jarvis_documents_dir("cours")
            name = datetime.now().strftime(_FOLDER_FORMAT)
            folder, n = root / name, 2
            while folder.exists():                    # two lectures in the same minute
                folder, n = root / f"{name} ({n})", n + 1
        self.folder = Path(folder)
        self.index: list[dict] = []
        self.transcribed = 0                 # segments done (or found silent)
        self.failed = 0                      # segments Gemini could not do yet
        self._audio: queue.Queue = queue.Queue()
        self._segments: queue.Queue = queue.Queue()
        self._stream = None
        self._threads: list[threading.Thread] = []
        self._frames = 0
        self._last_loud = time.monotonic()
        self._lock = threading.Lock()

    # ── recording ──
    def listen(self) -> None:
        """Open the microphone and start. Raises with a reason in French."""
        global _active
        if _active is not None:
            raise RuntimeError("Une écoute de cours est déjà en cours.")
        if not gemini.api_key():
            raise RuntimeError("Aucune clé Gemini n'est configurée (⚙ SETUP).")
        try:
            _ffmpeg()
        except Exception:
            raise RuntimeError("ffmpeg manque : réinstalle les dépendances "
                               "(pip install imageio-ffmpeg).") from None
        (self.folder / "audio").mkdir(parents=True, exist_ok=True)
        (self.folder / "transcription").mkdir(exist_ok=True)
        self._stream = self._open_stream()
        self._threads = [threading.Thread(target=self._write, daemon=True, name="lecture-write"),
                         threading.Thread(target=self._transcribe_all, daemon=True,
                                          name="lecture-transcribe")]
        for t in self._threads:
            t.start()
        self._stream.start()
        _active = self
        print(f"[Lecture] listening — {self.folder}")

    def _open_stream(self):
        import sounddevice as sd
        from core import audio_devices
        from memory.config_manager import get_input_device
        wanted = audio_devices.resolve(get_input_device(), "input")
        for device in dict.fromkeys((wanted, None)):     # the chosen one, then the default
            try:
                return sd.InputStream(samplerate=RATE, channels=1, dtype="int16",
                                      blocksize=_BLOCK, device=device, callback=self._on_audio)
            except Exception as e:
                print(f"[Lecture] microphone {device!r} refused: {e}")
        raise RuntimeError("Impossible d'ouvrir le micro : vérifie ⚙ AUDIO.")

    def _on_audio(self, indata, frames, time_info, status) -> None:
        # The audio thread: copy and go, the writer does the rest.
        if int(indata.max()) > SILENT_PEAK or -int(indata.min()) > SILENT_PEAK:
            self._last_loud = time.monotonic()
        self._audio.put(indata.copy())

    def stop(self) -> None:
        """End the recording; the last segment goes to be noted."""
        global _active
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as e:
                print(f"[Lecture] closing the microphone: {e}")
            self._stream = None
            self._audio.put(None)
        if _active is self:
            _active = None

    def elapsed(self) -> float:
        return self._frames / RATE

    def quiet_for(self) -> float:
        """Seconds since the microphone last heard anything — the window warns
        when it is long: an hour of a dead microphone is an hour lost."""
        return time.monotonic() - self._last_loud

    def _write(self) -> None:
        wav, seg = None, None
        while True:
            block = self._audio.get()
            if block is None:
                break
            if wav is None:
                n = len(self.index) + 1
                path = self.folder / "audio" / f"segment-{n:02d}.wav"
                wav = wave.open(str(path), "wb")
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(RATE)
                seg = {"index": n, "file": path.name, "start": self._frames / RATE,
                       "seconds": 0.0, "peak": 0}
            wav.writeframes(block.tobytes())
            self._frames += len(block)
            seg["seconds"] += len(block) / RATE
            seg["peak"] = max(seg["peak"], int(block.max()), -int(block.min()))
            if seg["seconds"] >= SEGMENT_SECONDS:
                wav.close()
                self._close_segment(seg)
                wav, seg = None, None
        if wav is not None:
            wav.close()
            if seg["seconds"] >= 1:
                self._close_segment(seg)
        self._segments.put(None)

    def _close_segment(self, seg: dict) -> None:
        seg["seconds"] = round(seg["seconds"], 2)
        with self._lock:
            self.index.append(seg)
            self._save_index()
        self._segments.put(seg)

    def _save_index(self) -> None:
        (self.folder / "segments.json").write_text(
            json.dumps(self.index, indent=2, ensure_ascii=False), encoding="utf-8")

    # ── transcription ──
    def _transcribe_all(self) -> None:
        while True:
            seg = self._segments.get()
            if seg is None:
                break
            self._transcribe(seg)

    def _text_path(self, seg: dict) -> Path:
        return self.folder / "transcription" / f"segment-{seg['index']:02d}.md"

    def _to_mp3(self, seg: dict) -> Path:
        """The segment's audio as MP3 (the WAV goes once it is encoded)."""
        audio = self.folder / "audio" / seg["file"]
        if audio.suffix == ".mp3":
            return audio
        mp3 = audio.with_suffix(".mp3")
        done = subprocess.run([_ffmpeg(), "-y", "-loglevel", "error", "-i", str(audio),
                               "-ac", "1", "-ar", str(RATE), "-b:a", _MP3_BITRATE, str(mp3)],
                              capture_output=True, timeout=300)
        if done.returncode != 0 or not mp3.is_file():
            raise RuntimeError(f"ffmpeg: {done.stderr.decode(errors='replace')[-200:]}")
        audio.unlink(missing_ok=True)
        with self._lock:
            seg["file"] = mp3.name
            self._save_index()
        return mp3

    def _transcribe(self, seg: dict) -> bool:
        """One segment's transcription, written to transcription/. False when
        Gemini could not (finish() tries again). A segment the microphone
        heard nothing in is marked silent without being sent: that is
        measured, never left for the model to judge."""
        try:
            mp3 = self._to_mp3(seg)
        except Exception as e:
            print(f"[Lecture] segment {seg['index']}: {e}")
            self.failed += 1
            return False
        if seg["peak"] <= SILENT_PEAK:
            text = _NOTHING
        else:
            from google.genai import types as gtypes
            parts = [gtypes.Part.from_bytes(data=mp3.read_bytes(), mime_type="audio/mp3"),
                     _transcript_prompt(seg)]
            config = gtypes.GenerateContentConfig(temperature=_TRANSCRIBE_TEMPERATURE)
            text = gemini.direct(parts, gemini.AUDIO, timeout_ms=_TIMEOUT_MS, config=config)
            if not text:
                # "High demand" 503s come in spikes. Once every model has
                # failed they are all resting, and the ladder then tries
                # them all again: one more go, a little later.
                time.sleep(_RETRY_AFTER)
                text = gemini.direct(parts, gemini.AUDIO, timeout_ms=_TIMEOUT_MS,
                                     config=config)
            if not text:
                print(f"[Lecture] segment {seg['index']}: no Gemini model answered")
                self.failed += 1
                return False
            text = _absolute_times(text, seg)
        self._text_path(seg).write_text(text.strip() + "\n", encoding="utf-8")
        self.transcribed += 1
        return True

    # ── the synthesis ──
    @classmethod
    def from_folder(cls, folder: Path) -> "Lecture":
        """A lecture already on disk: segments.json, the audio, the transcription."""
        lec = cls(Path(folder))
        try:
            lec.index = json.loads((lec.folder / "segments.json").read_text(encoding="utf-8"))
        except Exception:
            raise RuntimeError(f"Pas de segments.json dans {lec.folder}") from None
        return lec

    def finish(self, progress=print) -> Path:
        """Wait for the transcription, do what is missing, write the synthesis
        and the PDF, open it. Returns the PDF."""
        if self._stream is not None:
            self.stop()
        for t in self._threads:
            t.join()
        if not self.index:
            raise RuntimeError("Rien n'a été enregistré.")
        for seg in self.index:                       # what failed during the lecture
            if not self._text_path(seg).is_file():
                progress(f"transcription du segment {seg['index']} …")
                self._transcribe(seg)

        texts, missing = [], []
        for seg in self.index:
            head = (f"Segment {seg['index']} — {_clock(seg['start'])} à "
                    f"{_clock(seg['start'] + seg['seconds'])}")
            path = self._text_path(seg)
            if not path.is_file():
                missing.append(seg)
                texts.append((head, "*Ces minutes n'ont pas pu être transcrites : Gemini n'a "
                                    f"pas répondu. L'audio est dans audio/{seg['file']}.*"))
                continue
            text = path.read_text(encoding="utf-8").strip()
            if text.startswith(_NOTHING):
                continue                              # a break: nothing to show
            texts.append((head, _demote(text)))
        total = sum(s["seconds"] for s in self.index)
        heard = [body for _, body in texts if not body.startswith("*Ces minutes")]
        if not heard:
            raise RuntimeError("Aucune parole n'a été entendue : vérifie le micro choisi "
                               f"dans ⚙ AUDIO. L'audio est gardé dans {self.folder}.")

        progress("synthèse du cours …")
        joined = "\n\n".join(f"### {h}\n\n{b}" for h, b in texts)
        from google.genai import types as gtypes
        synthesis = gemini.direct(
            _synthesis_prompt(joined, total), gemini.AUDIO, timeout_ms=_TIMEOUT_MS,
            config=gtypes.GenerateContentConfig(temperature=_SYNTHESIS_TEMPERATURE))
        synthesis = re.sub(r"^```(?:markdown|md)?\s*|\s*```$", "", synthesis or "").strip()
        try:
            started = datetime.strptime(self.folder.name[:16], _FOLDER_FORMAT)
        except ValueError:                            # a folder renamed by hand
            started = datetime.fromtimestamp((self.folder / "segments.json").stat().st_mtime
                                             - total)
        when = started.strftime("%d/%m/%Y à %Hh%M")
        if not synthesis:
            synthesis = (f"# Cours du {when}\n\nLa synthèse n'a pas pu être écrite : Gemini n'a "
                         f"pas répondu. La transcription est ci-dessous ; relance avec "
                         f"`python -m actions.lecture \"{self.folder}\"` pour la refaire.")
        found = re.search(r"^#\s+(.+)$", synthesis, re.M)
        title = (found.group(1).strip() if found else f"Cours du {when}")[:120]
        meta = (f"{when} · {_clock(total)} d'écoute · {len(self.index)} segment"
                f"{'s' if len(self.index) > 1 else ''}"
                + (f" · {len(missing)} non transcrit{'s' if len(missing) > 1 else ''}"
                   if missing else ""))

        (self.folder / "synthese.md").write_text(
            f"{synthesis}\n\n---\n\n# Transcription\n\n"
            + "\n\n".join(f"## {h}\n\n{b}" for h, b in texts) + "\n", encoding="utf-8")
        name = re.sub(r'[\\/:*?"<>|\n]+', " ", title).strip()[:80] or "synthese"
        page = self.folder / f"{name}.html"
        page.write_text(_page(title, meta, synthesis, texts), encoding="utf-8")
        progress("mise en page du PDF …")
        pdf = self.folder / f"{name}.pdf"
        from actions.create_document import _html_to_pdf, _open
        _html_to_pdf(page.read_text(encoding="utf-8"), pdf, {"muted": "98a2b3"})
        _open(pdf)
        print(f"[Lecture] synthesis: {pdf}")
        return pdf


def active() -> "Lecture | None":
    return _active


if __name__ == "__main__":          # finish a lecture already on disk
    if len(sys.argv) != 2:
        sys.exit('usage: python -m actions.lecture "<dossier du cours>"')
    print(Lecture.from_folder(Path(sys.argv[1])).finish())
