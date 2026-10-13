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


def sanitizar_nombre_archivo(texto: str) -> str:
    """Limpia un texto para usarlo como componente seguro de nombre de archivo."""
    import re
    import unicodedata

    if not texto:
        return "sin_identificar"
    # Normalizar tildes y caracteres especiales
    t = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode("ascii").lower()
    # Reemplazar caracteres no alfanuméricos por guiones bajos
    t = re.sub(r"[^a-z0-9]+", "_", t).strip("_")
    return t or "sin_identificar"


def generar_nombre_estandarizado(
    fecha: Optional[str],
    proveedor: Optional[str],
    extension: str,
    comprobante_nro: Optional[str] = None
) -> str:
    """Genera un nombre de archivo estandarizado con formato 'YYYYMMDD_proveedor[_nro].ext'.
    
    Acepta fechas en formato 'YYYY-MM-DD', 'DD-MM-YYYY' o 'DD/MM/AAAA'.
    """
    import re
    from datetime import datetime

    ext = extension if extension.startswith(".") else f".{extension}"
    
    # 1. Normalizar fecha a YYYYMMDD
    f_str = ""
    if fecha:
        limpia = str(fecha).strip()
        # Caso YYYY-MM-DD o YYYY/MM/DD
        m_iso = re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})", limpia)
        if m_iso:
            y, m, d = m_iso.groups()
            f_str = f"{int(y):04d}{int(m):02d}{int(d):02d}"
        else:
            # Caso DD-MM-YYYY o DD/MM/AAAA
            m_lat = re.match(r"^(\d{1,2})[-/](\d{1,2})[-/](\d{4})", limpia)
            if m_lat:
                d, m, y = m_lat.groups()
                f_str = f"{int(y):04d}{int(m):02d}{int(d):02d}"

    if not f_str:
        f_str = datetime.now().strftime("%Y%m%d")

    # 2. Sanitizar nombre del proveedor
    prov_clean = sanitizar_nombre_archivo(proveedor or "sin_identificar")

    # 3. Componente opcional de número de comprobante
    extra = ""
    if comprobante_nro:
        nro_clean = re.sub(r"[^0-9a-zA-Z]+", "-", str(comprobante_nro)).strip("-")
        if nro_clean:
            extra = f"_{nro_clean}"

    return f"{f_str}_{prov_clean}{extra}{ext.lower()}"
