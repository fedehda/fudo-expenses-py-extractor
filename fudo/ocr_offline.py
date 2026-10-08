"""Módulo de OCR local opcional (EasyOCR / Tesseract) para contingencia offline.

Permite procesar tickets cuando no hay conexión a internet ni claves de API,
o cuando las APIs de IA fallan por saturación prolongada.
"""
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple

from PIL import Image, ImageOps

from .config import BASE_DIR, Config
from .esquema import Articulo, ExtraccionComprobante, Huella, TipoDocumento
from .validaciones import cuit_valido, solo_digitos

# Detección dinámica de motores OCR locales
_EASYOCR_READER = None
_EASYOCR_DISPONIBLE = None


def easyocr_disponible() -> bool:
    global _EASYOCR_DISPONIBLE
    if _EASYOCR_DISPONIBLE is not None:
        return _EASYOCR_DISPONIBLE
    try:
        import easyocr  # noqa: F401
        _EASYOCR_DISPONIBLE = True
    except ImportError:
        _EASYOCR_DISPONIBLE = False
    return _EASYOCR_DISPONIBLE


def obtener_reader_easyocr():
    global _EASYOCR_READER
    if _EASYOCR_READER is not None:
        return _EASYOCR_READER
    if not easyocr_disponible():
        return None
    try:
        import easyocr
        # Directorio de modelos portable si existe
        dir_modelos = BASE_DIR / "ocr_offline" / "modelos"
        if dir_modelos.exists():
            _EASYOCR_READER = easyocr.Reader(["es"], model_storage_directory=str(dir_modelos), gpu=False)
        else:
            _EASYOCR_READER = easyocr.Reader(["es"], gpu=False)
        return _EASYOCR_READER
    except Exception as e:
        print(f"    [!] Error al inicializar EasyOCR: {e}")
        return None


def ejecutar_ocr_imagen(img: Image.Image) -> str:
    """Ejecuta OCR sobre la imagen usando EasyOCR (o pytesseract si está disponible)."""
    # 1. Probar EasyOCR
    reader = obtener_reader_easyocr()
    if reader:
        try:
            import numpy as np
            arr = np.array(img.convert("RGB"))
            resultados = reader.readtext(arr, detail=0)
            return "\n".join(resultados)
        except Exception as e:
            print(f"    [!] Falló EasyOCR: {e}")

    # 2. Fallback a Tesseract si existe el binario
    try:
        import pytesseract
        tess_bin = BASE_DIR / "tesseract" / "tesseract.exe"
        if tess_bin.exists():
            pytesseract.pytesseract.tesseract_cmd = str(tess_bin)
        try:
            return pytesseract.image_to_string(img, lang="spa")
        except Exception:
            return pytesseract.image_to_string(img)
    except Exception:
        pass

    return ""


def extraer_con_ocr_offline(ruta: Path, img: Image.Image) -> ExtraccionComprobante:
    """Extrae CUIT, total, fecha y señales mediante OCR local y expresiones regulares."""
    texto = ejecutar_ocr_imagen(img)
    if not texto.strip():
        raise RuntimeError("OCR local no devolvió texto legible.")

    # 1. CUIT
    cuit = None
    m_cuit = re.search(r'\b(20|23|24|27|30|33|34)[\s\-]?(\d{8})[\s\-]?(\d)\b', texto)
    if m_cuit:
        cuit_cand = f"{m_cuit.group(1)}{m_cuit.group(2)}{m_cuit.group(3)}"
        if cuit_valido(cuit_cand):
            cuit = cuit_cand

    # 2. Monto total
    monto = 0.0
    m_monto = re.search(
        r'(?i)(?:total|total a pagar|importe total|total pesos|total general)[\s\:\$]*([\d\.\,]+)',
        texto
    )
    if m_monto:
        monto_raw = m_monto.group(1).strip()
        if ',' in monto_raw and '.' in monto_raw:
            monto_raw = monto_raw.replace('.', '').replace(',', '.')
        elif ',' in monto_raw:
            monto_raw = monto_raw.replace(',', '.')
        try:
            monto = float(monto_raw)
        except ValueError:
            monto = 0.0

    # 3. Fecha
    fecha = None
    m_fecha = re.search(r'\b(\d{1,2})[\/\-\.](\d{1,2})[\/\-\.](\d{2,4})\b', texto)
    if m_fecha:
        d, m, y = m_fecha.group(1), m_fecha.group(2), m_fecha.group(3)
        if len(y) == 2:
            y = f"20{y}"
        try:
            fecha = datetime(int(y), int(m), int(d)).strftime("%Y-%m-%d")
        except Exception:
            fecha = None

    # 4. Tipo de comprobante
    tipo_comp = "Factura B"
    tipo_doc = TipoDocumento.factura_manual
    if re.search(r'(?i)\bfactura\s*a\b', texto) or re.search(r'\bCOD[\.\s]*0?1\b', texto):
        tipo_comp = "Factura A"
        tipo_doc = TipoDocumento.factura_electronica
    elif re.search(r'(?i)\bfactura\s*c\b', texto) or re.search(r'\bCOD[\.\s]*11\b', texto):
        tipo_comp = "Factura C"
        tipo_doc = TipoDocumento.factura_electronica
    elif re.search(r'(?i)\brecibo\b', texto):
        tipo_comp = "Recibo"
        tipo_doc = TipoDocumento.recibo
    elif re.search(r'(?i)\bremito\b', texto):
        tipo_comp = "Remito"
        tipo_doc = TipoDocumento.remito
    elif re.search(r'(?i)\b(tique|ticket|controlador fiscal)\b', texto):
        tipo_doc = TipoDocumento.tique_fiscal

    # 5. Número de comprobante
    num_comp = ""
    m_num = re.search(r'\b(\d{4,5})[\s\-]+(\d{6,8})\b', texto)
    if m_num:
        num_comp = f"{m_num.group(1)}-{m_num.group(2)}"

    # 6. Huella (teléfonos, alias, etc.)
    telefonos = re.findall(r'\b(?:11|\d{3,4})[\s\-]?\d{3,4}[\s\-]?\d{4}\b', texto)
    alias_cbu = re.findall(r'(?i)\b(?:alias|cbu|cvu)[\s\:]+([a-zA-Z0-9\.\_]{6,22})\b', texto)

    lineas = [l.strip() for l in texto.splitlines() if len(l.strip()) > 3]
    resumen_items = lineas[:8] if lineas else ["Texto extraído por OCR offline"]

    articulos_obj = [Articulo(descripcion=it, cantidad=None, importe=None) for it in resumen_items]

    return ExtraccionComprobante(
        tipo_documento=tipo_doc,
        evidencia_tipo="Extracción offline por OCR local",
        tiene_nombre_emisor=False,
        cuit_emisor=cuit,
        razon_social=None,
        proveedor_fudo_match=None,
        fecha_emision=fecha,
        tipo_comprobante=tipo_comp,
        numero_comprobante=num_comp,
        monto_total=monto,
        articulos=articulos_obj,
        categoria_fudo_sugerida=None,
        medio_pago_impreso=None,
        huella=Huella(
            telefonos=telefonos[:3],
            alias_cbu=alias_cbu[:2],
            texto_encabezado=lineas[0] if lineas else None,
            descripcion_visual="Procesado offline con OCR"
        ),
        legibilidad="regular"
    )
