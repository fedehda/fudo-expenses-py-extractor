"""Carga y optimización de imágenes."""
import hashlib
import io
import mimetypes
from pathlib import Path
from typing import Optional, Tuple

from PIL import Image, ImageOps


def hash_archivo(ruta: Path) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 16), b""):
            h.update(bloque)
    return h.hexdigest()


def abrir_imagen(ruta: Path) -> Optional[Image.Image]:
    """Abre la imagen a resolución completa, corrigiendo la rotación EXIF. None si es PDF o falla."""
    if ruta.suffix.lower() == ".pdf":
        return None
    try:
        with Image.open(ruta) as img:
            img = ImageOps.exif_transpose(img)
            return img.convert("RGB")
    except Exception:
        return None


def optimizar_para_ia(ruta: Path, img: Optional[Image.Image], max_lado: int = 1600) -> Tuple[bytes, str]:
    """Imagen reducida a máx. 1600 px en JPEG 85 %. Los PDF se envían tal cual."""
    if ruta.suffix.lower() == ".pdf" or img is None:
        mime = "application/pdf" if ruta.suffix.lower() == ".pdf" else (mimetypes.guess_type(str(ruta))[0] or "image/jpeg")
        return ruta.read_bytes(), mime
    work = img
    if max(work.size) > max_lado:
        factor = max_lado / max(work.size)
        work = work.resize((int(work.width * factor), int(work.height * factor)), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    work.save(buf, format="JPEG", quality=85, optimize=True)
    return buf.getvalue(), "image/jpeg"
