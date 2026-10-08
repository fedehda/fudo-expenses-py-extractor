"""Motores de extracción con IA: Gemini (principal) y OpenAI (opcional)."""
import base64
import copy
import json
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from .catalogo import CatalogoFudo
from .config import Config, clave_valida
from .esquema import ExtraccionComprobante

try:
    from google import genai
    from google.genai import errors as genai_errors
    from google.genai import types as genai_types
except ImportError:  # pragma: no cover
    genai = None
    genai_errors = None
    genai_types = None

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None


class IANoDisponible(Exception):
    """Ningún motor pudo responder (sin internet, saturación, cuota). El ticket va a pendientes."""


class ErrorConfiguracion(Exception):
    """Clave inválida o modelo inexistente: no tiene sentido seguir procesando."""


@dataclass
class ResultadoIA:
    extraccion: ExtraccionComprobante
    motor: str  # "GEMINI:<modelo>" u "OPENAI:<modelo>"


def _schema_sin_refs(modelo) -> Dict[str, Any]:
    """JSON Schema de Pydantic con las $ref resueltas (más compatible con structured output)."""
    schema = modelo.model_json_schema()
    defs = schema.pop("$defs", {})

    def resolver(nodo):
        if isinstance(nodo, dict):
            if "$ref" in nodo:
                nombre = nodo["$ref"].split("/")[-1]
                base = copy.deepcopy(defs[nombre])
                extra = {k: v for k, v in nodo.items() if k != "$ref"}
                base.update(extra)
                return resolver(base)
            return {k: resolver(v) for k, v in nodo.items() if k != "default" and k != "title"}
        if isinstance(nodo, list):
            return [resolver(x) for x in nodo]
        return nodo

    return resolver(schema)


def _es_transitorio(e: Exception) -> bool:
    codigo = getattr(e, "code", None) or getattr(e, "status_code", None)
    if codigo in (408, 429, 500, 502, 503, 504):
        return True
    texto = f"{type(e).__name__} {e}".lower()
    claves = ("overloaded", "high demand", "resource_exhausted", "unavailable", "timeout", "timed out",
              "connecterror", "connection", "getaddrinfo", "network", "temporarily", "rate limit")
    return any(k in texto for k in claves)


def _es_config(e: Exception) -> bool:
    codigo = getattr(e, "code", None) or getattr(e, "status_code", None)
    texto = str(e).lower()
    return codigo in (401, 403) or "api key not valid" in texto or "api_key_invalid" in texto or "permission" in texto


def _limpiar_json(texto: str) -> str:
    t = (texto or "").strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t
        t = t.rsplit("```", 1)[0]
    return t.strip()


def construir_prompt(catalogo: CatalogoFudo, contexto_qr: Optional[str] = None, texto_ocr: Optional[str] = None) -> str:
    partes = [
        "Sos un asistente contable de un restaurante en Argentina. Analizá el comprobante de compra adjunto "
        "(foto o PDF) y devolvé los datos en el esquema JSON pedido.",
        "",
        "REGLAS:",
        "- El EMISOR es quien vende. No confundir con los datos del cliente (el restaurante).",
        "- tipo_documento: factura_electronica (Factura A/B/C con CAE o QR), factura_manual (talonario preimpreso a mano), "
        "tique_fiscal (controlador fiscal, dice TIQUE / P.V. / CF), remito, presupuesto (o 'documento no válido como factura'), "
        "recibo, ticket_no_fiscal (papel suelto, anotación a mano), otro. Explicá en evidencia_tipo qué lo indica.",
        "- tiene_nombre_emisor = false si no hay nombre ni razón social del vendedor impresa o sellada.",
        "- Fechas en YYYY-MM-DD. Los comprobantes argentinos usan DD/MM/AAAA.",
        "- Importes: el punto es separador de miles y la coma decimal (1.234,50 = 1234.50).",
        "- monto_total = importe FINAL a pagar (con IVA, percepciones y descuentos).",
        "- articulos: una entrada por línea con descripción legible, cantidad con unidad e importe de la línea.",
        "- tipo_comprobante: solo uno de " + ", ".join(catalogo.tipos_comprobante) + ". Remito/presupuesto/ticket a mano -> Remito.",
        "- medio_pago_impreso: SOLO si está escrito en el comprobante; si no, null.",
        "- huella: copiá TODO dato que identifique al emisor aunque no haya nombre: teléfonos/WhatsApp, alias/CBU/CVU, "
        "email, redes, dirección, texto preimpreso o sello del encabezado, tipo y numeración del talonario, y una descripción "
        "visual breve. Es clave para reconocer al proveedor la próxima vez.",
        "- Si un dato no se ve, usá null. No inventes.",
        "",
        "Categorías válidas de Fudo (categoria_fudo_sugerida debe ser una de estas, textual): " + "; ".join(catalogo.categorias),
    ]
    if catalogo.proveedores:
        partes.append("Proveedores ya cargados en Fudo (proveedor_fudo_match solo si es claramente el mismo): "
                      + "; ".join(catalogo.proveedores[:200]))
    if contexto_qr:
        partes += ["", "DATOS YA VERIFICADOS POR EL QR DE ARCA (son correctos, no los contradigas): " + contexto_qr,
                   "Concentrate en artículos, medio de pago, razón social, categoría y huella."]
    if texto_ocr:
        partes += ["", "Texto leído por OCR local (puede tener errores, usalo solo como ayuda para números y nombres):",
                   texto_ocr[:4000]]
    return "\n".join(partes)


class MotorIA:
    def __init__(self, cfg: type[Config] = Config, modelo: Optional[str] = None):
        self.cfg = cfg
        self.modelos_gemini = [m for m in dict.fromkeys([modelo or cfg.gemini_model, cfg.gemini_model_respaldo]) if m]
        self.gemini = None
        self.openai = None
        if genai and clave_valida(cfg.gemini_key):
            self.gemini = genai.Client(api_key=cfg.gemini_key)
        if OpenAI and clave_valida(cfg.openai_key):
            self.openai = OpenAI(api_key=cfg.openai_key)
        self._schema = _schema_sin_refs(ExtraccionComprobante)

    @property
    def disponible(self) -> bool:
        return bool(self.gemini or self.openai)

    def descripcion(self) -> str:
        partes = []
        partes.append(f"Gemini ({' -> '.join(self.modelos_gemini)}) " + ("ACTIVO" if self.gemini else "SIN CLAVE"))
        partes.append(f"OpenAI ({self.cfg.openai_model}) " + ("ACTIVO" if self.openai else "apagado"))
        return " | ".join(partes)

    def extraer(self, datos: bytes, mime: str, prompt: str) -> ResultadoIA:
        errores = []
        if self.gemini:
            for modelo in self.modelos_gemini:
                for intento, espera in enumerate((3, 6, 9, None), start=1):
                    try:
                        return ResultadoIA(self._gemini(modelo, datos, mime, prompt), f"GEMINI:{modelo}")
                    except Exception as e:  # noqa: BLE001
                        if _es_config(e):
                            raise ErrorConfiguracion(f"Gemini rechazó la clave o el modelo '{modelo}': {e}") from e
                        if not _es_transitorio(e) or espera is None:
                            errores.append(f"{modelo}: {str(e)[:160]}")
                            break
                        print(f"    [!] {modelo} saturado/sin respuesta. Reintento {intento}/3 en {espera}s...")
                        time.sleep(espera)
        if self.openai:
            try:
                return ResultadoIA(self._openai(datos, mime, prompt), f"OPENAI:{self.cfg.openai_model}")
            except Exception as e:  # noqa: BLE001
                if _es_config(e):
                    print(f"    [!] OpenAI rechazó la clave: {str(e)[:120]}")
                errores.append(f"openai: {str(e)[:160]}")
        raise IANoDisponible("; ".join(errores) or "sin motores de IA configurados")

    def _gemini(self, modelo: str, datos: bytes, mime: str, prompt: str) -> ExtraccionComprobante:
        part = genai_types.Part.from_bytes(data=datos, mime_type=mime)
        response = self.gemini.models.generate_content(
            model=modelo,
            contents=[part, prompt],
            config=genai_types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ExtraccionComprobante,
                temperature=0.1,
            ),
        )
        return ExtraccionComprobante.model_validate_json(_limpiar_json(response.text))

    def _openai(self, datos: bytes, mime: str, prompt: str) -> ExtraccionComprobante:
        if mime == "application/pdf":
            contenido = {"type": "file", "file": {"filename": "comprobante.pdf",
                                                  "file_data": f"data:application/pdf;base64,{base64.b64encode(datos).decode()}"}}
        else:
            contenido = {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{base64.b64encode(datos).decode()}",
                                                            "detail": "high"}}
        completion = self.openai.chat.completions.parse(
            model=self.cfg.openai_model,
            messages=[{"role": "user", "content": [{"type": "text", "text": prompt}, contenido]}],
            response_format=ExtraccionComprobante,
            timeout=30.0,
        )
        parsed = completion.choices[0].message.parsed
        if parsed is None:
            raise ValueError("OpenAI no devolvió datos estructurados")
        return parsed


def extraccion_a_dict(ext: ExtraccionComprobante) -> Dict[str, Any]:
    return json.loads(ext.model_dump_json())
