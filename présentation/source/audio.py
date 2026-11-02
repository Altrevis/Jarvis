"""
The soundtrack of Jarvis-motion.mp4: a voice-over and a quiet music bed.

    voice()  each line of narration.json, spoken by Gemini TTS in Jarvis's own
             voice (Charon by default), trimmed and placed at its second. A
             line longer than its slot is sped up a little (at most x1.15);
             anything still too long is reported. Clips are cached in cache/,
             keyed by text, voice and model, so a rebuild costs no API call
             unless a line changed.
    music()  synthesised here with numpy — no sample, no licence: a pad whose
             chords change with the scenes, a sub bass, a soft arpeggio, a
             pulse in the middle part, whooshes into each cut and two low hits
             on the "JARVIS" reveals.
    mix()    music ducked under the voice (sidechain), both normalised, muxed
             onto the silent render with the video stream copied as is.
"""
from __future__ import annotations

import hashlib
import io
import json
import subprocess
import tempfile
import time
import wave
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
CACHE = HERE / "cache"
SR = 48_000
DURATION = 49.0

# Scene cuts in motion.html — the music changes chord on them.
CUTS = [5.0, 9.5, 15.6, 23.6, 28.8, 35.0, 43.2]

_TTS_MODELS = ("gemini-3.8-flash-tts", "gemini-3.1-flash-tts-preview",
               "gemini-2.5-flash-preview-tts")
# No style direction: the TTS models read a direction aloud with short lines,
# in French and in English alike. Charon's plain delivery is already calm.
_DIRECTION = ""
_MAX_SPEEDUP = 1.15


def _ffmpeg() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def _read_wav(data: bytes) -> tuple[np.ndarray, int]:
    with wave.open(io.BytesIO(data)) as w:
        sr, n, ch = w.getframerate(), w.getnframes(), w.getnchannels()
        a = np.frombuffer(w.readframes(n), np.int16).astype(np.float32) / 32768
    return (a.reshape(-1, ch).mean(axis=1) if ch > 1 else a), sr


def _write_wav(path: Path, a: np.ndarray, sr: int) -> None:
    a = np.clip(a, -1, 1)
    ch = 1 if a.ndim == 1 else a.shape[1]
    with wave.open(str(path), "wb") as w:
        w.setnchannels(ch)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((a * 32767).astype("<i2").tobytes())


# ── Voice ────────────────────────────────────────────────────────────────────

def _synth(text: str, voice: str) -> bytes:
    import sys
    sys.path.insert(0, str(HERE.parent.parent))
    from google import genai
    from google.genai import types
    from memory import config_manager

    client = genai.Client(api_key=config_manager.get_gemini_key())
    cfg = types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice))))
    last = None
    for model in _TTS_MODELS:
        for attempt in range(3):
            try:
                r = client.models.generate_content(model=model, contents=f"{_DIRECTION} {text}".strip(),
                                                   config=cfg)
                blob = r.candidates[0].content.parts[0].inline_data
                data = blob.data
                if not data.startswith(b"RIFF"):          # raw 16-bit PCM, 24 kHz
                    buf = io.BytesIO()
                    with wave.open(buf, "wb") as w:
                        w.setnchannels(1); w.setsampwidth(2); w.setframerate(24_000)
                        w.writeframes(data)
                    data = buf.getvalue()
                return data
            except Exception as e:                       # 503 / 429: wait, then next model
                last = e
                if "404" in str(e) or "400" in str(e):
                    break
                time.sleep(4 * (attempt + 1))
    raise RuntimeError(f"text-to-speech failed: {last}")


def _trim(a: np.ndarray, sr: int, pad: float = 0.06) -> np.ndarray:
    win = max(1, sr // 100)
    rms = np.sqrt(np.convolve(a * a, np.ones(win) / win, mode="same"))
    on = np.nonzero(rms > max(rms.max() * 0.03, 1e-4))[0]
    if not len(on):
        return a
    lo, hi = max(0, on[0] - int(pad * sr)), min(len(a), on[-1] + int(pad * sr))
    return a[lo:hi]


def _tempo(a: np.ndarray, sr: int, factor: float) -> np.ndarray:
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = Path(tmp) / "in.wav", Path(tmp) / "out.wav"
        _write_wav(src, a, sr)
        subprocess.run([_ffmpeg(), "-y", "-loglevel", "error", "-i", str(src),
                        "-filter:a", f"atempo={factor:.4f}", str(dst)], check=True)
        return _read_wav(dst.read_bytes())[0]


def voice(log=print) -> Path:
    spec = json.loads((HERE / "narration.json").read_text(encoding="utf-8"))
    voice_name = spec.get("voice") or "Charon"
    CACHE.mkdir(exist_ok=True)
    track = np.zeros(int(DURATION * SR), np.float32)
    for i, line in enumerate(spec["lines"], 1):
        text, at, until = line["text"], float(line["at"]), float(line["until"])
        key = hashlib.sha1(f"{_TTS_MODELS[0]}|{voice_name}|{_DIRECTION}|{text}".encode()).hexdigest()[:10]
        clip = CACHE / f"voix-{i:02d}-{key}.wav"
        if not clip.exists():
            for old in CACHE.glob(f"voix-{i:02d}-*.wav"):
                old.unlink()
            # a clip far longer than the text is the model reading something
            # else too (or rambling): try again before accepting it
            expected = len(text) / 12.0 + 0.6
            for attempt in range(3):
                data = _synth(text, voice_name)
                if len(_trim(*_read_wav(data))) / 24_000 <= 1.6 * expected:
                    break
                log(f"  line {i}: {len(_trim(*_read_wav(data))) / 24_000:.1f}s for "
                    f"{len(text)} characters, synthesising again")
            clip.write_bytes(data)
        a, sr = _read_wav(clip.read_bytes())
        a = _trim(a, sr)
        slot, length = until - at, len(a) / sr
        note = ""
        if length > slot:
            factor = min(length / slot, _MAX_SPEEDUP)
            a = _tempo(a, sr, factor)
            note = f"  sped up x{factor:.2f}"
            if len(a) / sr > slot + 0.05:
                note += f"  ! still {len(a) / sr - slot:.2f}s over — shorten the line"
        # to 48 kHz by linear interpolation: speech has nothing above 12 kHz
        x = np.interp(np.arange(int(len(a) * SR / sr)) * sr / SR, np.arange(len(a)), a)
        start = int(at * SR)
        end = min(len(track), start + len(x))
        track[start:end] += x[:end - start].astype(np.float32)
        log(f"  {at:5.1f}s  {length:4.2f}s / {slot:4.2f}s  {text}{note}")
    out = CACHE / "voix.wav"
    _write_wav(out, track, SR)
    return out


# ── Music ────────────────────────────────────────────────────────────────────

def _hz(midi: float) -> float:
    return 440.0 * 2 ** ((midi - 69) / 12)


# (start, end, bass, pad notes) — A minor / C major, one chord per scene or half scene
_CHORDS = [
    (0.0, 5.0, 45, (57, 60, 64, 71)),        # Am add9   boot
    (5.0, 9.5, 41, (53, 57, 60, 64)),        # Fmaj7     the name
    (9.5, 15.6, 36, (60, 64, 67, 74)),       # C add9    the four verbs
    (15.6, 19.6, 43, (55, 59, 62, 64)),      # G6        architecture
    (19.6, 23.6, 45, (57, 60, 64, 67)),      # Am7
    (23.6, 28.8, 41, (53, 57, 60, 64, 67)),  # Fmaj9     capabilities
    (28.8, 31.9, 36, (60, 64, 67, 74)),      # C add9    numbers
    (31.9, 35.0, 43, (55, 60, 62, 67)),      # Gsus4
    (35.0, 39.1, 45, (57, 60, 64, 71)),      # Am add9   Ydays
    (39.1, 43.2, 41, (53, 57, 60, 64)),      # Fmaj7
    (43.2, 49.0, 36, (48, 60, 64, 67, 74)),  # C add9    outro
]


def _chord_at(t: float):
    for c in _CHORDS:
        if c[0] <= t < c[1]:
            return c
    return _CHORDS[-1]


def _env(n: int, sr: int, attack: float, release: float) -> np.ndarray:
    e = np.ones(n, np.float32)
    a, r = min(n, int(attack * sr)), min(n, int(release * sr))
    e[:a] = np.linspace(0, 1, a) ** 2
    if r:
        e[-r:] *= np.linspace(1, 0, r) ** 1.5
    return e


def _pad(n: int, rng) -> np.ndarray:
    out = np.zeros((n, 2), np.float32)
    for start, end, _, notes in _CHORDS:
        tail = 1.8
        s, e = int(start * SR), min(n, int((end + tail) * SR))
        t = np.arange(e - s) / SR
        env = _env(e - s, SR, 1.4 if start else 2.5, tail + 0.4)
        for note in notes:
            for cents, pan in ((-8, 0.15), (0, 0.5), (8, 0.85)):
                f = _hz(note + cents / 100)
                ph = rng.uniform(0, 2 * np.pi)
                wave_ = sum(np.sin(2 * np.pi * f * k * t + ph * k) / k * np.exp(-k / 2.4)
                            for k in range(1, 7))
                trem = 1 + 0.06 * np.sin(2 * np.pi * 0.17 * t + ph)
                sig = (wave_ * env * trem).astype(np.float32) * 0.05
                out[s:e, 0] += sig * np.sqrt(1 - pan)
                out[s:e, 1] += sig * np.sqrt(pan)
    return out


def _bass(n: int) -> np.ndarray:
    out = np.zeros(n, np.float32)
    for start, end, root, _ in _CHORDS:
        if start < 5.0:
            continue
        s, e = int(start * SR), min(n, int((end + 0.3) * SR))
        t = np.arange(e - s) / SR
        f = _hz(root)
        sig = np.sin(2 * np.pi * f * t) + 0.35 * np.sin(4 * np.pi * f * t) + 0.12 * np.sin(6 * np.pi * f * t)
        out[s:e] += (sig * _env(e - s, SR, 0.25, 0.35)).astype(np.float32) * 0.10
    return out


def _arp(n: int) -> np.ndarray:
    out = np.zeros((n, 2), np.float32)
    step, pattern = 0.3, (0, 2, 1, 3, 2, 1, 3, 2)
    t, k = 9.5, 0
    note_len = int(0.7 * SR)
    tt = np.arange(note_len) / SR
    while t < 43.2:
        notes = sorted(_chord_at(t + 1e-3)[3])
        midi = notes[pattern[k % len(pattern)] % len(notes)] + 12
        f = _hz(midi)
        level = 0.05 if t < 15.6 else (0.075 if t < 35.0 else 0.075 + 0.04 * (t - 35.0) / 8.2)
        sig = (np.sin(2 * np.pi * f * tt) + 0.25 * np.sin(4 * np.pi * f * tt)) \
            * np.exp(-tt / 0.16) * np.minimum(1, tt / 0.004) * level
        s = int(t * SR)
        e = min(n, s + note_len)
        pan = 0.32 if k % 2 else 0.68
        out[s:e, 0] += sig[:e - s] * np.sqrt(1 - pan)
        out[s:e, 1] += sig[:e - s] * np.sqrt(pan)
        t += step
        k += 1
    # ping-pong echo, a dotted eighth
    d = int(0.45 * SR)
    echo = np.zeros_like(out)
    src = out.copy()
    for rep in range(1, 5):
        g = 0.38 ** rep
        side = rep % 2
        echo[d * rep:, side] += src[:-d * rep, 1 - side] * g
    return out + echo


def _pulse(n: int) -> np.ndarray:
    out = np.zeros(n, np.float32)
    ln = int(0.5 * SR)
    tt = np.arange(ln) / SR
    freq = 48 + 70 * np.exp(-tt / 0.03)
    kick = np.sin(2 * np.pi * np.cumsum(freq) / SR) * np.exp(-tt / 0.13) * 0.2
    t = 15.6
    while t < 43.2:
        s = int(t * SR)
        out[s:s + ln] += kick[:len(out[s:s + ln])]
        t += 1.2
    return out


def _lowpass_sweep(x: np.ndarray, f0: float, f1: float) -> np.ndarray:
    y = np.zeros_like(x)
    acc = 0.0
    cut = np.geomspace(f0, f1, len(x))
    alpha = 1 - np.exp(-2 * np.pi * cut / SR)
    for i in range(len(x)):
        acc += alpha[i] * (x[i] - acc)
        y[i] = acc
    return y


def _fx(n: int, rng) -> np.ndarray:
    out = np.zeros((n, 2), np.float32)
    # whoosh into every cut
    ln = int(0.9 * SR)
    for cut in CUTS:
        noise = rng.standard_normal((ln, 2)).astype(np.float32)
        shape = np.linspace(0, 1, ln) ** 3
        w = np.stack([_lowpass_sweep(noise[:, c], 300, 6000) for c in range(2)], axis=1)
        w = w * shape[:, None] * 0.09
        s = int(cut * SR) - ln
        out[s:s + ln] += w
    # low hits on the two "JARVIS" reveals
    for at in (5.3, 45.05):
        ln2 = int(2.2 * SR)
        tt = np.arange(ln2) / SR
        freq = 38 + 50 * np.exp(-tt / 0.08)
        boom = np.sin(2 * np.pi * np.cumsum(freq) / SR) * np.exp(-tt / 0.55) * 0.3
        s = int(at * SR)
        out[s:s + ln2] += boom[:, None]
    # the core lighting up, and the "OK"
    for at, notes, dec, lvl in ((2.0, (76, 83, 88), 1.6, 0.06), (2.7, (93,), 0.08, 0.03)):
        ln3 = int((dec * 3) * SR)
        tt = np.arange(ln3) / SR
        bell = sum(np.sin(2 * np.pi * _hz(m) * tt) for m in notes) * np.exp(-tt / dec) * lvl
        s = int(at * SR)
        out[s:s + ln3] += bell[:, None]
    # boot riser, under the rings drawing
    ln4 = int(2.2 * SR)
    tt = np.arange(ln4) / SR
    glide = np.sin(2 * np.pi * np.cumsum(np.geomspace(110, 220, ln4)) / SR)
    out[int(0.2 * SR):int(0.2 * SR) + ln4] += (glide * (tt / tt[-1]) ** 2 * 0.07)[:, None]
    return out


def _reverb(x: np.ndarray, rng, rt60: float = 2.6, mix: float = 0.32) -> np.ndarray:
    ln = int(rt60 * SR)
    tt = np.arange(ln) / SR
    ir = rng.standard_normal((ln, 2)) * np.exp(-6.9 * tt / rt60)[:, None]
    ir[:, 0] = _lowpass_sweep(ir[:, 0].astype(np.float32), 7000, 2500)
    ir[:, 1] = _lowpass_sweep(ir[:, 1].astype(np.float32), 7000, 2500)
    ir /= np.sqrt((ir ** 2).sum(axis=0))
    size = 1 << int(np.ceil(np.log2(len(x) + ln)))
    wet = np.stack([np.fft.irfft(np.fft.rfft(x[:, c], size) * np.fft.rfft(ir[:, c], size), size)[:len(x)]
                    for c in range(2)], axis=1)
    return x + wet.astype(np.float32) * mix


def _highpass(x: np.ndarray, corner: float = 45.0) -> np.ndarray:
    """Gentle high-pass in the frequency domain: nothing under ~30 Hz, where a
    laptop or a projector speaker only turns energy into mud."""
    freqs = np.fft.rfftfreq(len(x), 1 / SR)
    gain = 1 / np.sqrt(1 + (corner / np.maximum(freqs, 1e-3)) ** 4)
    return np.stack([np.fft.irfft(np.fft.rfft(x[:, c]) * gain, len(x)) for c in range(2)],
                    axis=1).astype(np.float32)


def music(log=print) -> Path:
    rng = np.random.default_rng(7)
    n = int(DURATION * SR)
    t0 = time.monotonic()
    pad, arp = _pad(n, rng), _arp(n)
    bed = _reverb(pad + arp, rng)
    mix = bed + _bass(n)[:, None] + _pulse(n)[:, None] + _reverb(_fx(n, rng), rng, 1.8, 0.25)
    fade_in = np.minimum(1, np.arange(n) / (0.05 * SR))
    fade_out = np.clip((DURATION - np.arange(n) / SR) / 2.5, 0, 1) ** 1.5
    mix = _highpass(mix) * (fade_in * fade_out)[:, None]
    mix /= np.abs(mix).max() / 0.89
    CACHE.mkdir(exist_ok=True)
    out = CACHE / "musique.wav"
    _write_wav(out, mix, SR)
    log(f"  music synthesised in {time.monotonic() - t0:.0f}s")
    return out


# ── Mix ──────────────────────────────────────────────────────────────────────

def mix(video: Path, voice_wav: Path, music_wav: Path, out: Path,
        voice_lufs: float = -16, music_lufs: float = -27) -> None:
    graph = (
        f"[1:a]aresample={SR},pan=stereo|c0=c0|c1=c0,loudnorm=I={voice_lufs}:TP=-2:LRA=7,asplit=2[v][key];"
        f"[2:a]aresample={SR},loudnorm=I={music_lufs}:TP=-6:LRA=9[m];"
        f"[m][key]sidechaincompress=threshold=0.015:ratio=4:attack=40:release=600[duck];"
        f"[v][duck]amix=inputs=2:normalize=0:duration=longest,alimiter=limit=0.9:level=false[a]")
    subprocess.run([_ffmpeg(), "-y", "-loglevel", "error", "-i", str(video), "-i", str(voice_wav),
                    "-i", str(music_wav), "-filter_complex", graph, "-map", "0:v", "-map", "[a]",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", str(SR),
                    "-t", f"{DURATION:g}", "-movflags", "+faststart", str(out)], check=True)


if __name__ == "__main__":
    import sys
    if "voice" in sys.argv:
        voice()
    if "music" in sys.argv:
        music()
