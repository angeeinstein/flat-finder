"""Image download, thumbnail generation, perceptual hashing."""
from __future__ import annotations

import hashlib
import io
import logging
from pathlib import Path
from typing import Iterable

from flask import current_app

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:  # pragma: no cover
    HAS_PIL = False

try:
    import imagehash
    HAS_IMAGEHASH = True
except ImportError:  # pragma: no cover
    HAS_IMAGEHASH = False


logger = logging.getLogger(__name__)


def _image_dir(apt_id: int) -> Path:
    base = Path(current_app.config["IMAGE_DIR"]) / str(apt_id)
    base.mkdir(parents=True, exist_ok=True)
    return base


def url_filename(url: str, ext: str = "jpg") -> str:
    h = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    return f"{h}.{ext}"


def save_image(apt_id: int, url: str, content: bytes) -> dict:
    """Save raw image bytes for an apartment. Returns dict with paths and metadata."""
    out_dir = _image_dir(apt_id)
    ext = "jpg"
    width = height = None
    phash = None

    is_grayscale = False
    if HAS_PIL:
        try:
            img = Image.open(io.BytesIO(content))
            img.load()
            width, height = img.size
            ext = (img.format or "JPEG").lower().replace("jpeg", "jpg")
            # Detect floor-plan-like images (grayscale / 1-bit / monochrome palette)
            is_grayscale = img.mode in ("L", "1", "LA", "P")
            if img.mode == "P" and img.palette:
                # Paletted image — check if it's effectively grayscale
                try:
                    converted = img.convert("RGB")
                    r, g, b = converted.split()
                    is_grayscale = (
                        list(r.getdata()) == list(g.getdata()) == list(b.getdata())
                    )
                except Exception:
                    pass
            if HAS_IMAGEHASH:
                try:
                    phash = str(imagehash.phash(img.convert("RGB")))
                except Exception:
                    phash = None
        except Exception as e:
            logger.warning("Image decode failed: %s", e)

    filename = url_filename(url, ext=ext)
    path = out_dir / filename
    path.write_bytes(content)

    thumb_filename = None
    if HAS_PIL:
        try:
            thumb_filename = f"thumb_{filename}"
            with Image.open(path) as im:
                im = im.convert("RGB") if im.mode in ("P", "RGBA", "LA") else im
                im.thumbnail((400, 400))
                im.save(out_dir / thumb_filename, "JPEG", quality=82)
        except Exception as e:
            logger.warning("Thumbnail generation failed: %s", e)
            thumb_filename = None

    return {
        "local_path": str(path.relative_to(Path(current_app.config["IMAGE_DIR"]))),
        "thumbnail_path": (
            str((out_dir / thumb_filename).relative_to(Path(current_app.config["IMAGE_DIR"])))
            if thumb_filename
            else None
        ),
        "width": width,
        "height": height,
        "file_size": len(content),
        "perceptual_hash": phash,
        "is_grayscale": is_grayscale,
    }


def perceptual_hashes_similar(a: str | None, b: str | None, max_distance: int = 6) -> bool:
    if not a or not b or not HAS_IMAGEHASH:
        return False
    try:
        return abs(imagehash.hex_to_hash(a) - imagehash.hex_to_hash(b)) <= max_distance
    except Exception:
        return False
