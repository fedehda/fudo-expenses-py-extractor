"""Huella de proveedor: normalización de señales y puntaje de coincidencia.

Sirve para reconocer remitos, presupuestos o tickets a mano que no traen nombre,
comparando teléfonos, alias, dirección, encabezado y artículos contra la memoria.
"""
import difflib
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from .esquema import ExtraccionComprobante
from .validaciones import cuit_valido, normalizar_texto, solo_digitos

# Pesos (probabilidad de que la señal identifique al proveedor por sí sola)
PESOS = {
    "cuit": 1.0,
    "telefono": 0.9,
    "alias_cbu": 0.9,
    "email": 0.85,
    "red": 0.75,
    "direccion": 0.6,
    "encabezado": 0.5,
    "items": 0.35,
}
TIPOS_EXACTOS = ("cuit", "telefono", "alias_cbu", "email", "red")

PALABRAS_IGNORADAS = {
    "kilo", "kilos", "kgs", "unid", "unidad", "unidades", "caja", "cajas", "cajon", "cajones",
    "bolsa", "bolsas", "pack", "paquete", "paquetes", "docena", "docenas", "litro", "litros",
    "gramos", "grs", "total", "subtotal", "precio", "varios", "articulo", "articulos", "x",
}

Senales = Dict[str, Set[str]]


def normalizar_telefono(t: str) -> Optional[str]:
    d = solo_digitos(t)
    if len(d) < 7:
        return None
    return d[-8:]


def normalizar_alias(t: str) -> Optional[str]:
    d = solo_digitos(t)
    if len(d) == 22:
        return d
    a = re.sub(r"(?i)^\s*(alias|cbu|cvu)\s*[:\-]?\s*", "", t or "").strip().lower().replace(" ", "")
    return a if len(a) >= 6 else None


def normalizar_red(t: str) -> Optional[str]:
    r = (t or "").strip().lower()
    r = re.sub(r"^(https?://)?(www\.)?(instagram|facebook|fb)\.com/", "", r).strip("@/ ")
    return r if len(r) >= 3 else None


def tokens_articulos(ext: ExtraccionComprobante) -> Set[str]:
    tokens: Set[str] = set()
    for a in ext.articulos:
        for w in normalizar_texto(a.descripcion).split():
            if len(w) >= 4 and not w.isdigit() and w not in PALABRAS_IGNORADAS:
                tokens.add(w)
    return tokens


def senales_de(ext: ExtraccionComprobante, cuit: Optional[str] = None) -> Senales:
    """Extrae y normaliza las señales identificatorias de una extracción."""
    h = ext.huella
    s: Senales = {k: set() for k in PESOS}
    c = solo_digitos(cuit or ext.cuit_emisor)
    if cuit_valido(c):
        s["cuit"].add(c)
    s["telefono"] |= {v for v in (normalizar_telefono(t) for t in h.telefonos) if v}
    s["alias_cbu"] |= {v for v in (normalizar_alias(t) for t in h.alias_cbu) if v}
    s["email"] |= {e.strip().lower() for e in h.emails if "@" in (e or "")}
    s["red"] |= {v for v in (normalizar_red(t) for t in h.redes) if v}
    if h.direccion and len(normalizar_texto(h.direccion)) >= 6:
        s["direccion"].add(normalizar_texto(h.direccion))
    if h.texto_encabezado and len(normalizar_texto(h.texto_encabezado)) >= 6:
        s["encabezado"].add(normalizar_texto(h.texto_encabezado))
    s["items"] = tokens_articulos(ext)
    return {k: v for k, v in s.items() if v}


@dataclass
class Candidato:
    proveedor_id: int
    nombre: str
    puntaje: float
    razones: List[str] = field(default_factory=list)


def _similitud_max(valores: Set[str], guardados: Set[str]) -> Tuple[float, str]:
    mejor, cual = 0.0, ""
    for v in valores:
        for g in guardados:
            r = difflib.SequenceMatcher(None, v, g).ratio()
            if r > mejor:
                mejor, cual = r, g
    return mejor, cual


def puntuar(ticket: Senales, guardadas: Senales) -> Tuple[float, List[str]]:
    """Combina las coincidencias con un 'O' probabilístico: 1 - Π(1 - p_i)."""
    # CUIT distinto y ambos válidos: no puede ser el mismo proveedor
    if ticket.get("cuit") and guardadas.get("cuit") and not (ticket["cuit"] & guardadas["cuit"]):
        return 0.0, ["CUIT distinto"]

    probs: List[float] = []
    razones: List[str] = []
    for tipo in TIPOS_EXACTOS:
        comunes = ticket.get(tipo, set()) & guardadas.get(tipo, set())
        if comunes:
            probs.append(PESOS[tipo])
            razones.append(f"{tipo} {sorted(comunes)[0]}")

    for tipo, umbral in (("direccion", 0.85), ("encabezado", 0.8)):
        if ticket.get(tipo) and guardadas.get(tipo):
            sim, _ = _similitud_max(ticket[tipo], guardadas[tipo])
            if sim >= umbral:
                probs.append(PESOS[tipo] * sim)
                razones.append(f"{tipo} similar ({sim:.0%})")

    if ticket.get("items") and guardadas.get("items"):
        inter = ticket["items"] & guardadas["items"]
        if inter:
            jacc = len(inter) / len(ticket["items"])
            p = PESOS["items"] * min(1.0, jacc / 0.5)
            if p >= 0.05:
                probs.append(p)
                razones.append(f"artículos en común: {', '.join(sorted(inter)[:4])}")

    restante = 1.0
    for p in probs:
        restante *= (1 - p)
    return round(1 - restante, 3), razones


def rankear(ticket: Senales, memoria: Dict[int, Tuple[str, Senales]], top: int = 3) -> List[Candidato]:
    candidatos = []
    for pid, (nombre, guardadas) in memoria.items():
        p, razones = puntuar(ticket, guardadas)
        if p > 0:
            candidatos.append(Candidato(pid, nombre, p, razones))
    candidatos.sort(key=lambda c: c.puntaje, reverse=True)
    return candidatos[:top]
