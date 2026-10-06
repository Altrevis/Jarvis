"""
generate_image — create a picture from a description, for free, and show it.

WHERE THE PICTURE COMES FROM — free rungs first
    1. Pollinations.ai, FLUX.1-schnell. A FREE account at
       https://enter.pollinations.ai/keys gives an `sk_` key and a free
       ("Quest Pollen") balance; one image costs 0.002 pollen, so that balance
       covers a great many. Put it in config/api_keys.json as
       "pollinations_api_key". gen.pollinations.ai refuses a request without
       one (401), so a keyless call goes to the legacy image.pollinations.ai
       instead. Measured Oct 2026: it served ONE image (model "sana", at most
       1024 px, with a pollinations.ai logo in the corner), then answered 402
       with an x402 crypto-payment demand on every call after. So it is worth a
       try — a refusal costs half a second — and the free key is the real fix.
    2. Hugging Face, FLUX.1-schnell, with a free account token
       ("hf_token" in config/api_keys.json) — free monthly credits.
    3. Gemini's image models: a free Gemini key has NO image quota (429 every
       time), so this only helps a key with billing enabled.

The file lands in <Pictures>/JARVIS/images and is shown where the HUD core is.
"""
from __future__ import annotations

import random
import time
from pathlib import Path
from urllib.parse import quote

from core.user_dirs import jarvis_output_dir

_SIZES = {
    "square":    (1024, 1024),
    "landscape": (1280, 720),
    "portrait":  (720, 1280),
    "wide":      (1536, 640),
}

_TIMEOUT = 120


def _ext_for(data: bytes) -> str | None:
    """The file type from its first bytes — a provider that fails sometimes
    answers 200 with a JSON error, and that must not be saved as a .jpg."""
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return None


def _keys() -> dict:
    try:
        from memory.config_manager import load_api_keys
        return load_api_keys() or {}
    except Exception:
        return {}


def _pollinations_key() -> str:
    # "pollination_api_key", without the s, is the spelling people type by hand.
    keys = _keys()
    return str(keys.get("pollinations_api_key") or keys.get("pollination_api_key") or "").strip()


def _pollinations_keyless(prompt: str, w: int, h: int, seed: int) -> bytes:
    import requests
    url = (f"https://image.pollinations.ai/prompt/{quote(prompt, safe='')}"
           f"?width={w}&height={h}&seed={seed}")
    r = requests.get(url, timeout=60, headers={"User-Agent": "JARVIS-desktop-assistant"})
    if r.status_code == 200 and _ext_for(r.content) and len(r.content) > 2048:
        return r.content
    if r.status_code == 402:
        raise RuntimeError("the keyless allowance is used up — a free sk_ key from "
                           "enter.pollinations.ai/keys (pollinations_api_key) lifts it")
    raise RuntimeError(f"keyless HTTP {r.status_code}: {r.text[:100]!r}")


def _pollinations(prompt: str, w: int, h: int, seed: int) -> bytes:
    import requests
    key = _pollinations_key()
    if not key:
        return _pollinations_keyless(prompt, w, h, seed)
    headers = {"User-Agent": "JARVIS-desktop-assistant", "Authorization": f"Bearer {key}"}
    url = (f"https://gen.pollinations.ai/image/{quote(prompt, safe='')}"
           f"?width={w}&height={h}&model=flux&seed={seed}")
    r = requests.get(url, timeout=_TIMEOUT, headers=headers)
    if r.status_code == 200 and _ext_for(r.content) and len(r.content) > 2048:
        return r.content
    if r.status_code == 401:
        raise RuntimeError("the pollinations_api_key was refused")
    if r.status_code == 402:
        # The key's free pollen balance is spent: the keyless allowance still
        # gives a picture now and then while it refills.
        try:
            return _pollinations_keyless(prompt, w, h, seed)
        except RuntimeError as e:
            raise RuntimeError(f"free pollen balance used up for now; {e}")
    raise RuntimeError(f"HTTP {r.status_code}: {r.text[:100]!r}")


def _huggingface(prompt: str, w: int, h: int, seed: int) -> bytes:
    import requests
    token = str(_keys().get("hf_token") or "").strip()
    if not token:
        raise RuntimeError("no hf_token configured")
    r = requests.post(
        "https://router.huggingface.co/hf-inference/models/black-forest-labs/FLUX.1-schnell",
        headers={"Authorization": f"Bearer {token}", "Accept": "image/png"},
        json={"inputs": prompt,
              "parameters": {"width": w, "height": h, "seed": seed,
                             "num_inference_steps": 4}},
        timeout=_TIMEOUT)
    if r.status_code == 200 and _ext_for(r.content):
        return r.content
    raise RuntimeError(f"HTTP {r.status_code}: {r.text[:100]!r}")


def _gemini(prompt: str) -> bytes:
    from core import gemini
    cl = gemini.client(timeout_ms=90_000)
    last = "no model answered"
    for model in ("gemini-3.1-flash-image", "gemini-2.5-flash-image"):
        try:
            r = cl.models.generate_content(
                model=model, contents=prompt,
                config={"response_modalities": ["IMAGE", "TEXT"],
                        "automatic_function_calling": {"disable": True}})
            for part in r.candidates[0].content.parts:
                blob = getattr(part, "inline_data", None)
                if blob is not None and blob.data:
                    return blob.data
            last = f"{model}: no image in the reply"
        except Exception as e:
            last = f"{model}: {str(e)[:120]}"
    raise RuntimeError(last)


def _slug(text: str) -> str:
    from core.fuzzy_find import normalize
    s = normalize(text).replace(" ", "-")[:48].strip("-")
    return s or "image"


def generate_image(parameters: dict, player=None) -> str:
    p = parameters or {}
    prompt = str(p.get("prompt") or "").strip()
    if not prompt:
        return "No description given for the image."
    style = str(p.get("style") or "").strip()
    if style:
        prompt = f"{prompt}, {style} style"
    aspect = str(p.get("aspect") or "square").lower().strip()
    w, h = _SIZES.get(aspect, _SIZES["square"])
    seed = int(p["seed"]) if str(p.get("seed", "")).strip().lstrip("-").isdigit() \
        else random.randint(1, 2_000_000_000)

    t0 = time.monotonic()
    errors = []
    data = None
    for name, fn in (("Pollinations", lambda: _pollinations(prompt, w, h, seed)),
                     ("Hugging Face", lambda: _huggingface(prompt, w, h, seed)),
                     ("Gemini", lambda: _gemini(prompt))):
        try:
            data = fn()
            source = name
            break
        except Exception as e:
            errors.append(f"{name}: {str(e)[:120]}")
            print(f"[Image] {name} failed — {str(e)[:160]}")
    if data is None:
        keys = _keys()
        if not _pollinations_key() and not keys.get("hf_token"):
            return ("Image generation is not set up yet: the free image services "
                    "now need a free key. Tell the user to create a free account at "
                    "enter.pollinations.ai/keys and paste the sk_ key into "
                    "config/api_keys.json as \"pollinations_api_key\" — then it "
                    "works with no cost. Details: " + " | ".join(errors))
        return ("Image generation failed — every provider refused or timed out: "
                + " | ".join(errors))

    ext = _ext_for(data) or ".png"
    title = str(p.get("title") or "").strip() or prompt[:60]
    out = jarvis_output_dir("images") / f"{time.strftime('%Y%m%d-%H%M%S')}-{_slug(title)}{ext}"
    Path(out).write_bytes(data)
    print(f"[Image] {source}: {len(data):,} bytes in {time.monotonic() - t0:.1f}s → {out}")

    if player is not None and hasattr(player, "show_image"):
        player.show_image(str(out), f"IMAGE — {title}")
    return (f"Image created ({source}, seed {seed}) and shown on the display; saved "
            f"to {out}. Tell the user in one short sentence that it is on screen. "
            f"For another version of the same idea, call again without a seed.")


TOOL = {
    "name": "generate_image",
    "description": (
        "Creates an image from a description (a picture, illustration, logo idea, "
        "wallpaper, concept art…) and shows it on the assistant's display. Free, "
        "no account needed. Write 'prompt' in ENGLISH and make it detailed: "
        "subject, setting, style, lighting, colours, composition — expand a short "
        "request into a full description. Takes roughly 5 to 30 seconds, so say "
        "one short sentence first. Saved in the user's Pictures/JARVIS/images "
        "folder. Not for charts or graphs of data: use generate_chart for those."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "prompt": {"type": "STRING",
                       "description": "Detailed English description of the image"},
            "title": {"type": "STRING",
                      "description": "Short title in the user's language, for the display and the file name"},
            "aspect": {"type": "STRING",
                       "description": "square (default) | landscape | portrait | wide"},
            "style": {"type": "STRING",
                      "description": "Optional style: photorealistic, digital art, watercolor, anime, 3d render, pixel art…"},
            "seed": {"type": "INTEGER",
                     "description": "Only to reproduce an earlier image exactly"},
        },
        "required": ["prompt"],
    },
    "handler": generate_image,
}
