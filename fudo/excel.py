"""Generación y lectura de archivos Excel para Fudo.
Maneja las 11 columnas oficiales de la hoja 'Gastos', la hoja 'Revisar' y el comando '--aprender'.
"""
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .catalogo import CatalogoFudo
from .memoria import Memoria
from .validaciones import cuit_valido, formatear_fecha_fudo, normalizar_numero_comprobante, solo_digitos


COLUMNAS_FUDO_OFICIALES = [
    "Fecha",
    "Monto",
    "Proveedor",
    "Categoría",
    "Comentario",
    "Tipo de comprobante",
    "Número de comprobante",
    "Medio de pago",
    "Caja",
    "Fecha de pago",
    "Fecha de vencimiento",
]

COLUMNAS_REVISAR = [
    "Archivo",
    "Motivo de Revisión",
    "Tipo Detectado",
    "CUIT",
    "Proveedor Asignado",
    "Candidatos Sugeridos (Huella)",
    "Monto",
    "Estrategia Usada",
]


class GestorExcel:
    def __init__(self, template_path: Optional[Path], catalogo: CatalogoFudo):
        self.template_path = template_path
        self.catalogo = catalogo

    def crear_workbook(self, destino: Path) -> openpyxl.Workbook:
        if self.template_path and self.template_path.exists():
            shutil.copy2(self.template_path, destino)
            wb = openpyxl.load_workbook(destino)
        else:
            wb = openpyxl.Workbook()
            ws_gastos = wb.active
            ws_gastos.title = "Gastos"
            for col_idx, col_name in enumerate(COLUMNAS_FUDO_OFICIALES, start=1):
                ws_gastos.cell(row=1, column=col_idx, value=col_name)

            ws_listas = wb.create_sheet(title="Listas")
            ws_listas.cell(row=1, column=1, value="Categoría")
            for r, c in enumerate(self.catalogo.categorias, start=2):
                ws_listas.cell(row=r, column=1, value=c)

            ws_listas.cell(row=1, column=2, value="Proveedor")
            for r, p in enumerate(self.catalogo.proveedores, start=2):
                ws_listas.cell(row=r, column=2, value=p)

            ws_listas.cell(row=1, column=3, value="Tipo de comprobante")
            for r, t in enumerate(self.catalogo.tipos_comprobante, start=2):
                ws_listas.cell(row=r, column=3, value=t)

            ws_listas.cell(row=1, column=4, value="Medio de pago")
            for r, m in enumerate(self.catalogo.medios_pago, start=2):
                ws_listas.cell(row=r, column=4, value=m)

            ws_listas.cell(row=1, column=5, value="Caja")
            for r, cj in enumerate(self.catalogo.cajas, start=2):
                ws_listas.cell(row=r, column=5, value=cj)

        return wb

    def escribir_lote(self, wb: openpyxl.Workbook, filas_gastos: List[Dict[str, Any]], filas_revisar: List[Dict[str, Any]]):
        # 1. Hoja Gastos (11 columnas oficiales)
        if "Gastos" not in wb.sheetnames:
            ws_gastos = wb.create_sheet(title="Gastos")
            for col_idx, col_name in enumerate(COLUMNAS_FUDO_OFICIALES, start=1):
                ws_gastos.cell(row=1, column=col_idx, value=col_name)
        else:
            ws_gastos = wb["Gastos"]

        fila_inicio = 2
        while (ws_gastos.cell(row=fila_inicio, column=1).value is not None or
               ws_gastos.cell(row=fila_inicio, column=2).value is not None or
               ws_gastos.cell(row=fila_inicio, column=3).value is not None):
            fila_inicio += 1

        for idx, f in enumerate(filas_gastos):
            r = fila_inicio + idx
            ws_gastos.cell(row=r, column=1, value=formatear_fecha_fudo(f.get("fecha", "")))
            ws_gastos.cell(row=r, column=2, value=f.get("monto", 0.0))
            ws_gastos.cell(row=r, column=3, value=f.get("proveedor", ""))
            ws_gastos.cell(row=r, column=4, value=f.get("categoria", ""))
            ws_gastos.cell(row=r, column=5, value=f.get("comentario", ""))
            ws_gastos.cell(row=r, column=6, value=f.get("tipo_comprobante", ""))
            ws_gastos.cell(row=r, column=7, value=f.get("numero_comprobante", ""))
            ws_gastos.cell(row=r, column=8, value=f.get("medio_pago", ""))
            ws_gastos.cell(row=r, column=9, value=f.get("caja", ""))
            ws_gastos.cell(row=r, column=10, value=formatear_fecha_fudo(f.get("fecha_pago", f.get("fecha", ""))))
            venc = f.get("fecha_vencimiento")
            ws_gastos.cell(row=r, column=11, value=formatear_fecha_fudo(venc) if venc else None)

        # 2. Hoja Revisar (solo si hay comprobantes que requieran atención)
        if filas_revisar:
            if "Revisar" in wb.sheetnames:
                ws_rev = wb["Revisar"]
            else:
                ws_rev = wb.create_sheet(title="Revisar")

            header_fill = PatternFill(start_color="FFF3CD", end_color="FFF3CD", fill_type="solid")
            header_font = Font(bold=True, color="856404")

            for col_idx, col_name in enumerate(COLUMNAS_REVISAR, start=1):
                cell = ws_rev.cell(row=1, column=col_idx, value=col_name)
                cell.fill = header_fill
                cell.font = header_font

            for idx, r_data in enumerate(filas_revisar, start=2):
                ws_rev.cell(row=idx, column=1, value=r_data.get("archivo", ""))
                ws_rev.cell(row=idx, column=2, value=r_data.get("motivos", ""))
                ws_rev.cell(row=idx, column=3, value=r_data.get("tipo_detectado", ""))
                ws_rev.cell(row=idx, column=4, value=r_data.get("cuit", ""))
                ws_rev.cell(row=idx, column=5, value=r_data.get("proveedor_asignado", ""))
                ws_rev.cell(row=idx, column=6, value=r_data.get("candidatos_sugeridos", ""))
                ws_rev.cell(row=idx, column=7, value=r_data.get("monto", 0.0))
                ws_rev.cell(row=idx, column=8, value=r_data.get("estrategia", ""))

            # Ajustar anchos de columnas
            for col in ws_rev.columns:
                max_len = max(len(str(cell.value or "")) for cell in col)
                col_letter = get_column_letter(col[0].column)
                ws_rev.column_dimensions[col_letter].width = min(max(max_len + 2, 12), 40)


def aprender_de_excel(ruta_excel: Path, memoria: Memoria, catalogo: CatalogoFudo) -> Dict[str, Any]:
    """Lee un archivo Excel corregido por el usuario e incorpora las correcciones a la memoria SQLite."""
    if not ruta_excel.exists():
        raise FileNotFoundError(f"No existe el archivo {ruta_excel}")

    wb = openpyxl.load_workbook(ruta_excel, data_only=True)
    confirmados = 0
    actualizados = 0
    try:
        # 1. Hoja de datos (Gastos o Gabarito)
        hoja_datos = next((h for h in ("Gastos", "Gabarito") if h in wb.sheetnames), None)
        if hoja_datos:
            ws = wb[hoja_datos]
            headers = {}
            for col in range(1, ws.max_column + 1):
                val = ws.cell(row=1, column=col).value
                if val:
                    headers[str(val).strip().lower()] = col

            col_prov = headers.get("proveedor")
            col_cat = headers.get("categoría") or headers.get("categoria")
            col_pago = headers.get("medio de pago") or headers.get("medio_pago")
            col_caja = headers.get("caja")
            col_coment = headers.get("comentario")
            col_monto = headers.get("monto")
            col_fecha = headers.get("fecha")
            col_cuit = headers.get("cuit")

            for r in range(2, ws.max_row + 1):
                prov = ws.cell(row=r, column=col_prov).value if col_prov else None
                if not prov or str(prov).strip() in ("", "Sin identificar", "Proveedor No Identificado", "None"):
                    continue

                prov_str = str(prov).strip()
                cat_str = str(ws.cell(row=r, column=col_cat).value).strip() if col_cat and ws.cell(row=r, column=col_cat).value else None
                pago_str = str(ws.cell(row=r, column=col_pago).value).strip() if col_pago and ws.cell(row=r, column=col_pago).value else None
                caja_str = str(ws.cell(row=r, column=col_caja).value).strip() if col_caja and ws.cell(row=r, column=col_caja).value else None
                cuit_raw = str(ws.cell(row=r, column=col_cuit).value).strip() if col_cuit and ws.cell(row=r, column=col_cuit).value else None
                c_clean = solo_digitos(cuit_raw) if cuit_raw and cuit_valido(solo_digitos(cuit_raw)) else None

                # Guardar confirmación en memoria
                pid = memoria.guardar_proveedor(
                    cuit=c_clean,
                    razon_social=prov_str,
                    proveedor_fudo=prov_str,
                    categoria=cat_str,
                    caja=caja_str,
                    medio_pago=pago_str,
                    confirmado=True
                )
                if pid:
                    confirmados += 1

        # Si hay hoja Revisar, vincular las correcciones con los archivos y sus señales
        if "Revisar" in wb.sheetnames:
            ws_rev = wb["Revisar"]
            headers_rev = {}
            for col in range(1, ws_rev.max_column + 1):
                val = ws_rev.cell(row=1, column=col).value
                if val:
                    headers_rev[str(val).strip().lower()] = col

            col_arch = headers_rev.get("archivo")
            col_prov_asig = headers_rev.get("proveedor asignado")
            col_cuit = headers_rev.get("cuit")

            for r in range(2, ws_rev.max_row + 1):
                arch = ws_rev.cell(row=r, column=col_arch).value if col_arch else None
                prov_rev = ws_rev.cell(row=r, column=col_prov_asig).value if col_prov_asig else None
                cuit_rev = ws_rev.cell(row=r, column=col_cuit).value if col_cuit else None

                if prov_rev and str(prov_rev).strip() not in ("", "Sin identificar"):
                    p_str = str(prov_rev).strip()
                    c_clean = solo_digitos(cuit_rev) if cuit_rev and cuit_valido(solo_digitos(cuit_rev)) else None
                    memoria.guardar_proveedor(
                        cuit=c_clean,
                        razon_social=p_str,
                        proveedor_fudo=p_str,
                        categoria=None,
                        caja=None,
                        medio_pago=None,
                        confirmado=True
                    )
                    actualizados += 1

    finally:
        wb.close()

    return {
        "proveedores_confirmados": confirmados,
        "revisiones_procesadas": actualizados,
    }
