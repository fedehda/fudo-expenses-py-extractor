"""Configuración global: rutas portables, .env y parámetros ajustables."""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Consola de Windows segura para acentos
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(dotenv_path=BASE_DIR / ".env")

EXTENSIONES_VALIDAS = {".jpg", ".jpeg", ".png", ".webp", ".pdf", ".bmp"}

# Versión del prompt/esquema: invalida la caché de evaluación cuando cambia.
VERSION_EXTRACCION = "2"


def clave_valida(valor: str | None) -> bool:
    """Una clave es válida si no está vacía ni es un texto de ejemplo del .env."""
    if not valor:
        return False
    v = valor.strip().lower()
    return bool(v) and not v.startswith("tu_clave") and v not in {"xxx", "changeme", "none"}


def _int_env(nombre: str, defecto: int) -> int:
    try:
        return int(os.getenv(nombre, str(defecto)).strip())
    except ValueError:
        return defecto


def _bool_env(nombre: str, defecto: bool = False) -> bool:
    v = os.getenv(nombre)
    if v is None:
        return defecto
    return v.strip().lower() in {"1", "si", "sí", "true", "yes", "s"}


class Config:
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    gemini_model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite").strip() or "gemini-3.5-flash-lite"
    gemini_model_respaldo = os.getenv("GEMINI_MODEL_RESPALDO", "gemini-3.1-flash-lite").strip() or "gemini-3.1-flash-lite"
    openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"

    max_dias_antiguedad = _int_env("MAX_DIAS_ANTIGUEDAD", 60)
    pausa_entre_tickets = float(os.getenv("PAUSA_ENTRE_TICKETS", "1.5") or 1.5)

    # EasyOCR opcional (carpeta ocr_offline/ instalada con instalar_ocr_offline.bat)
    ocr_como_ayuda = _bool_env("OCR_COMO_AYUDA", False)
    ocr_si_falla_ia = _bool_env("OCR_SI_FALLA_IA", False)

    # Umbrales de la huella de proveedor (0..1)
    umbral_huella_alto = float(os.getenv("UMBRAL_HUELLA_ALTO", "0.85") or 0.85)
    umbral_huella_gris = float(os.getenv("UMBRAL_HUELLA_GRIS", "0.45") or 0.45)

    proveedor_desconocido = "Sin identificar"
