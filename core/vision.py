"""
vision — a picture the user hands over, at the size a model needs to see it.

WHY SHRINK FIRST
    A phone photo is 12 megapixels; a vision model reads it at about one.
    Claude bills an image at roughly width x height / 750 tokens, and recent
    models accept large images, so a 4000x3000 photo sent as-is can cost three
    times what the same photo costs at 1.15 megapixels — for nothing, since
    describing it or reading its text does not need the extra pixels.
    So every image FILE that goes to a model goes through load() first.

WHO USES IT
    screen_process, angle 'file'   Gemini Live looks at the file itself:
                                   no Claude call at all, the cheapest way.
    file_processor describe / ocr  one short call on the fast tier.
    ask_claude with files          the picture goes as a picture, not as
                                   20 000 characters of binary noise.
    generate_image, editing        the source photo, before it is uploaded.
"""
from __future__ import annotations

import io
from pathlib import Path

# What PIL opens without plugins. SVG is text (read it as text) and HEIC needs
# pillow-heif, so neither is listed.
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff"}

# ~1.15 megapixels: about 1 600 Claude tokens, and a phone screenshot's text
# stays readable at that size.
MAX_PIXELS = 1_150_000
_JPEG_QUALITY = 88


def is_image(path) -> bool:
    """True when the path names an image file this module can load."""
    return bool(path) and Path(str(path)).suffix.lower() in IMAGE_EXTS


def load(path, max_pixels: int = MAX_PIXELS) -> tuple[bytes, str]:
    """The image file as JPEG bytes of at most `max_pixels`, and its MIME type.

    Raises ValueError when the file is missing or is not an image PIL opens."""
    from PIL import Image, ImageOps

    p = Path(str(path)).expanduser()
    try:
        with Image.open(p) as im:
            # Phones store "this side up" in EXIF; without this a portrait
            # photo reaches the model lying on its side.
            im = _flatten(ImageOps.exif_transpose(im))
            w, h = im.size
            if w * h > max_pixels:
                scale = (max_pixels / (w * h)) ** 0.5
                im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))),
                               Image.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=_JPEG_QUALITY)
    except (OSError, SyntaxError, ValueError) as e:
        # UnidentifiedImageError and FileNotFoundError are both OSErrors.
        raise ValueError(f"{p.name} is not an image I can open ({e})") from e
    return buf.getvalue(), "image/jpeg"


def _flatten(im):
    """RGB, with any transparency laid on white: JPEG has no alpha channel,
    and a transparent logo flattened on black reads as a black square."""
    from PIL import Image

    if im.mode in ("RGBA", "LA", "P", "PA"):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, "white")
        bg.paste(im, mask=im.getchannel("A"))
        return bg
    return im.convert("RGB")
