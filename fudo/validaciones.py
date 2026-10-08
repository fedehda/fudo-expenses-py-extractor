"""Validaciones determinísticas y normalizaciones."""
import re
import unicodedata
from datetime import date, datetime
from typing import Iterable, List, Optional


def solo_digitos(texto: Optional[str]) -> str:
    return "".join(ch for ch in str(texto or "") if ch.isdigit())


def cuit_valido(cuit: Optional[str]) -> bool:
    """Dígito verificador módulo 11 de CUIT/CUIL."""
    d = solo_digitos(cuit)
    if len(d) != 11 or d[:2] not in {"20", "23", "24", "25", "26", "27", "30", "33", "34"}:
        return False
    pesos = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]
    suma = sum(int(a) * b for a, b in zip(d[:10], pesos))
    resto = 11 - (suma % 11)
    verificador = 0 if resto == 11 else (9 if resto == 10 else resto)
    return verificador == int(d[10])


def formatear_cuit(cuit: Optional[str]) -> Optional[str]:
    d = solo_digitos(cuit)
    return f"{d[:2]}-{d[2:10]}-{d[10]}" if len(d) == 11 else (cuit or None)


def parsear_fecha(texto: Optional[str]) -> Optional[date]:
    if not texto:
        return None
    t = str(texto).strip()[:10]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d.%m.%Y"):
        try:
            return datetime.strptime(t, fmt).date()
        except ValueError:
            continue
    return None


def formatear_fecha_fudo(valor: object) -> str:
    """Devuelve la fecha en formato 'DD-MM-AAAA' exigido por Fudo."""
    if not valor:
        return ""
    if isinstance(valor, (datetime, date)):
        return valor.strftime("%d-%m-%Y")
    d = parsear_fecha(str(valor))
    if d:
        return d.strftime("%d-%m-%Y")
    return str(valor).strip()


def validar_fecha(f: Optional[date], max_dias: int, hoy: Optional[date] = None) -> Optional[str]:
    """Devuelve el motivo de revisión o None si la fecha es razonable."""
    hoy = hoy or date.today()
    if f is None:
        return "Fecha no legible (se usó la de hoy)"
    if f > hoy:
        return f"Fecha futura ({f.strftime('%d-%m-%Y')})"
    if (hoy - f).days > max_dias:
        return f"Comprobante de hace {(hoy - f).days} días (máx. {max_dias})"
    return None


def validar_total(importes: Iterable[Optional[float]], total: Optional[float]) -> Optional[str]:
    """Compara la suma de líneas con el total. Solo opina si hay al menos 2 líneas con importe."""
    valores = [v for v in importes if v is not None]
    if total is None or total <= 0 or len(valores) < 2:
        return None
    suma = round(sum(valores), 2)
    dif = abs(suma - total)
    # Tolerancia: 2 % o $10 (redondeos, IVA discriminado, percepciones)
    if dif > max(10.0, total * 0.02):
        # Factura A: la suma de líneas suele ser neto sin IVA. 21 % y 10,5 % son las alícuotas comunes.
        for alicuota in (1.21, 1.105):
            if abs(suma * alicuota - total) <= max(10.0, total * 0.02):
                return None
        return f"Suma de artículos ${suma:,.2f} no coincide con el total ${total:,.2f}"
    return None


def normalizar_texto(texto: Optional[str]) -> str:
    t = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode("ascii").lower()
    t = re.sub(r"\b(s\.?a\.?|s\.?r\.?l\.?|s\.?a\.?s\.?|s\.?h\.?|y cia|hnos?)\b", " ", t)
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def normalizar_numero_comprobante(numero: Optional[str]) -> str:
    """'B 0003-00012345' -> '3-12345' para comparar duplicados sin depender del formato."""
    partes = [p.lstrip("0") or "0" for p in re.findall(r"\d+", str(numero or ""))]
    return "-".join(partes[-2:]) if partes else ""


def normalizar_medio_pago(texto: Optional[str], opciones: List[str]) -> Optional[str]:
    if not texto:
        return None
    t = normalizar_texto(texto)
    reglas = [
        (("efectivo", "cash", "contado"), "Efectivo"),
        (("cuenta corriente", "cta cte", "cte cte", "a pagar", "a cuenta"), "Cta. Cte."),
        (("mercadopago", "mercado pago", " mp ", "qr mp"), "MercadoPago"),
        (("payway", "posnet", "lapos", "tarjeta", "debito", "credito", "visa", "master"), "Payway"),
        (("transferencia", "transf", "cbu", "cvu", "alias"), "Transferencia"),
    ]
    tt = f" {t} "
    for claves, valor in reglas:
        if any(c in tt for c in claves) and valor in opciones:
            return valor
    for op in opciones:
        if normalizar_texto(op) == t:
            return op
    return None
