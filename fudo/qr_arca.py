"""Lectura del QR de facturas electrónicas de ARCA (ex AFIP).

El QR contiene una URL del tipo https://www.afip.gob.ar/fe/qr/?p=<base64 JSON> con:
ver, fecha, cuit, ptoVta, tipoCmp, nroCmp, importe, moneda, ctz, tipoDocRec, nroDocRec, tipoCodAut, codAut.
"""
import base64
import json
from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import parse_qs, urlparse

from PIL import Image, ImageOps

try:
    import zxingcpp
except ImportError:  # pragma: no cover
    zxingcpp = None

# Código ARCA -> (tipo Fudo, descripción, es_nota_credito)
TIPOS_ARCA = {
    1: ("Factura A", "Factura A", False), 2: ("Factura A", "Nota de Débito A", False),
    3: ("Factura A", "Nota de Crédito A", True), 4: ("Recibo", "Recibo A", False),
    6: ("Factura B", "Factura B", False), 7: ("Factura B", "Nota de Débito B", False),
    8: ("Factura B", "Nota de Crédito B", True), 9: ("Recibo", "Recibo B", False),
    11: ("Factura C", "Factura C", False), 12: ("Factura C", "Nota de Débito C", False),
    13: ("Factura C", "Nota de Crédito C", True), 15: ("Recibo", "Recibo C", False),
    51: ("Factura A", "Factura M", False), 53: ("Factura A", "Nota de Crédito M", True),
    81: ("Factura A", "Tique Factura A", False), 82: ("Factura B", "Tique Factura B", False),
    83: ("Factura B", "Tique", False), 111: ("Factura C", "Tique Factura C", False),
    201: ("Factura A", "Factura de Crédito Electrónica A", False),
    203: ("Factura A", "NC Factura de Crédito Electrónica A", True),
    206: ("Factura B", "Factura de Crédito Electrónica B", False),
    208: ("Factura B", "NC Factura de Crédito Electrónica B", True),
    211: ("Factura C", "Factura de Crédito Electrónica C", False),
    213: ("Factura C", "NC Factura de Crédito Electrónica C", True),
}


@dataclass
class DatosQR:
    cuit: str
    fecha: str
    tipo_fudo: str
    tipo_descripcion: str
    es_nota_credito: bool
    numero: str
    importe: float
    moneda: str
    cotizacion: float
    cae: Optional[str]
    advertencias: List[str] = field(default_factory=list)

    @property
    def importe_pesos(self) -> float:
        if self.moneda and self.moneda.upper() != "PES" and self.cotizacion:
            return round(self.importe * self.cotizacion, 2)
        return self.importe


def _b64_decode(texto: str) -> bytes:
    t = texto.strip().replace(" ", "+")
    t += "=" * (-len(t) % 4)
    try:
        return base64.b64decode(t, validate=False)
    except Exception:
        return base64.urlsafe_b64decode(t)


def parsear_url_qr(texto: str) -> Optional[DatosQR]:
    """Convierte el texto del QR en DatosQR. None si no es un QR de ARCA válido."""
    if not texto:
        return None
    try:
        url = urlparse(texto.strip())
        if not any(d in (url.netloc or "").lower() for d in ("afip.gob.ar", "arca.gob.ar")):
            return None
        p = parse_qs(url.query).get("p", [None])[0]
        if not p:
            return None
        datos = json.loads(_b64_decode(p).decode("utf-8", errors="replace"))
    except Exception:
        return None

    try:
        tipo_cod = int(datos.get("tipoCmp"))
        cuit = "".join(ch for ch in str(datos.get("cuit", "")) if ch.isdigit())
        pto = int(datos.get("ptoVta"))
        nro = int(datos.get("nroCmp"))
        importe = float(datos.get("importe"))
        fecha = str(datos.get("fecha", ""))[:10]
    except (TypeError, ValueError):
        return None
    if len(cuit) != 11:
        return None

    advert = []
    tipo_fudo, desc, es_nc = TIPOS_ARCA.get(tipo_cod, (None, f"Código ARCA {tipo_cod}", False))
    if tipo_fudo is None:
        tipo_fudo = "Factura B"
        advert.append(f"Tipo de comprobante ARCA desconocido ({tipo_cod})")
    if es_nc:
        advert.append(f"Es {desc}: verificar si corresponde cargarla como gasto")
    moneda = str(datos.get("moneda", "PES") or "PES")
    try:
        ctz = float(datos.get("ctz", 1) or 1)
    except (TypeError, ValueError):
        ctz = 1.0
    if moneda.upper() != "PES":
        advert.append(f"Moneda {moneda} (cotización {ctz}); monto convertido a pesos")

    cae = datos.get("codAut")
    return DatosQR(
        cuit=cuit, fecha=fecha, tipo_fudo=tipo_fudo, tipo_descripcion=desc, es_nota_credito=es_nc,
        numero=f"{pto:05d}-{nro:08d}", importe=importe, moneda=moneda, cotizacion=ctz,
        cae=str(cae) if cae else None, advertencias=advert,
    )


def _variantes(img: Image.Image):
    yield img
    gris = ImageOps.grayscale(img)
    yield ImageOps.autocontrast(gris)
    if max(img.size) < 1800:
        yield gris.resize((img.width * 2, img.height * 2), Image.Resampling.LANCZOS)
    else:
        # Fotos grandes: el QR suele estar abajo; probar la mitad inferior ampliada
        mitad = gris.crop((0, gris.height // 2, gris.width, gris.height))
        yield mitad
    yield gris.point(lambda v: 255 if v > 140 else 0)


def leer_qr_arca(img: Optional[Image.Image]) -> Optional[DatosQR]:
    if img is None or zxingcpp is None:
        return None
    for variante in _variantes(img):
        try:
            resultados = zxingcpp.read_barcodes(variante)
        except Exception:
            continue
        for r in resultados:
            datos = parsear_url_qr(getattr(r, "text", ""))
            if datos:
                return datos
    return None
