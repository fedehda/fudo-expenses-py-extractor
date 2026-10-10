"""Esquemas Pydantic que se piden a los modelos de IA."""
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class TipoDocumento(str, Enum):
    factura_electronica = "factura_electronica"   # Factura A/B/C impresa por sistema, con CAE y/o QR
    factura_manual = "factura_manual"             # Factura de talonario preimpreso completada a mano
    tique_fiscal = "tique_fiscal"                 # Ticket de controlador fiscal (supermercado, mayorista)
    remito = "remito"
    presupuesto = "presupuesto"                   # Presupuesto / nota de pedido / "documento no válido como factura"
    recibo = "recibo"
    ticket_no_fiscal = "ticket_no_fiscal"         # Papel suelto, anotación a mano, comanda
    otro = "otro"


class Articulo(BaseModel):
    descripcion: str = Field(description="Producto o servicio, legible. Ej: 'Tomate perita'.")
    cantidad: Optional[str] = Field(None, description="Cantidad con unidad si figura. Ej: '10 kg', '2 cajones'.")
    cantidad_numerica: Optional[float] = Field(None, description="Valor numérico de la cantidad si es deducible. Ej: 10.0.")
    unidad_medida: Optional[str] = Field(None, description="Unidad de medida: kg, g, lts, ml, un, cajon, bolsa, pack, etc.")
    precio_unitario: Optional[float] = Field(None, description="Precio unitario de la línea si figura o si se puede deducir.")
    importe: Optional[float] = Field(None, description="Importe total de la línea (cantidad x precio), si figura.")


class Huella(BaseModel):
    """Señales que identifican al emisor aunque el comprobante no tenga nombre."""
    telefonos: List[str] = Field(default_factory=list, description="Teléfonos o WhatsApp impresos, sellados o escritos.")
    alias_cbu: List[str] = Field(default_factory=list, description="Alias, CBU o CVU para transferencias.")
    emails: List[str] = Field(default_factory=list)
    redes: List[str] = Field(default_factory=list, description="Usuarios de Instagram/Facebook/web.")
    direccion: Optional[str] = Field(None, description="Dirección del emisor (no la del cliente).")
    texto_encabezado: Optional[str] = Field(
        None, description="Texto preimpreso o sello del encabezado que identifique al emisor, aunque no sea un nombre (ej. 'Frutas y verduras - Puesto 45 Mercado Central')."
    )
    talonario: Optional[str] = Field(
        None, description="Tipo de talonario y numeración (ej. 'Remito X N° 0001-00000452', 'talonario duplicado azul')."
    )
    descripcion_visual: Optional[str] = Field(
        None, description="Descripción breve del formato: manuscrito/impreso, color del papel, logo."
    )


class ExtraccionComprobante(BaseModel):
    tipo_documento: TipoDocumento = Field(description="Clasificación del documento.")
    evidencia_tipo: Optional[str] = Field(None, description="Qué texto o rasgo justificó la clasificación.")
    tiene_nombre_emisor: bool = Field(description="True si el emisor está identificado con nombre o razón social impresa.")
    cuit_emisor: Optional[str] = Field(None, description="CUIT del EMISOR (no del cliente). Solo dígitos o con guiones. Null si no figura.")
    razon_social: Optional[str] = Field(None, description="Razón social o nombre de fantasía del emisor.")
    proveedor_fudo_match: Optional[str] = Field(None, description="Nombre EXACTO de la lista de proveedores de Fudo si es claramente el mismo; si no, null.")
    fecha_emision: Optional[str] = Field(None, description="Fecha de emisión YYYY-MM-DD.")
    tipo_comprobante: Optional[str] = Field(None, description="Uno de: Factura A, Factura B, Factura C, Recibo, Remito.")
    numero_comprobante: Optional[str] = Field(None, description="Número tal como figura, ej. 00003-00012345.")
    monto_total: Optional[float] = Field(None, description="Importe TOTAL final del comprobante.")
    articulos: List[Articulo] = Field(default_factory=list, description="Cada línea de producto/servicio.")
    categoria_fudo_sugerida: Optional[str] = Field(None, description="Categoría exacta de la lista de Fudo.")
    medio_pago_impreso: Optional[str] = Field(None, description="Medio de pago SOLO si está impreso o escrito.")
    huella: Huella = Field(default_factory=Huella)
    legibilidad: Optional[str] = Field(None, description="'buena', 'regular' o 'mala'.")
