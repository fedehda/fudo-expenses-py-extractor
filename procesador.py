#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""FudoExtractor v2 - Extractor Inteligente y Portable de Comprobantes para Fudo
================================================================================
- Router por tipo de documento (Facturas con QR ARCA, tiques fiscales, remitos).
- Extracción determinística de QR de ARCA (CUIT, fecha, tipo, número, total, CAE).
- Extracción con IA (Gemini 3.8 Flash con fallback a Gemini 3.5 Flash-Lite / OpenAI).
- Memoria persistente SQLite por CUIT y reconocimiento por huella para comprobantes sin nombre.
- Validaciones determinísticas de CUIT, fechas, totales e integridad fiscal.
- Generación de 'Plantilla-Gastos.xlsx' oficial de 11 columnas + hoja 'Revisar'.
- Flujo de aprendizaje continuo con '--aprender'.
- Banco de pruebas y métricas con '--evaluar'.
"""

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

# Consola de Windows segura
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from fudo.catalogo import CatalogoFudo
from fudo.config import BASE_DIR, Config, EXTENSIONES_VALIDAS, clave_valida
from fudo.evaluador import ejecutar_evaluacion
from fudo.excel import GestorExcel, aprender_de_excel
from fudo.extractores import MotorIA
from fudo.memoria import Memoria
from fudo.ocr_offline import easyocr_disponible
from fudo.router import RouterTickets


def main():
    parser = argparse.ArgumentParser(
        description="FudoExtractor - Extracción inteligente de comprobantes para Fudo.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "--input", "-i",
        default="input_tickets",
        help="Carpeta con comprobantes a procesar (por defecto: input_tickets/)"
    )
    parser.add_argument(
        "--output", "-o",
        default="output_fudo",
        help="Carpeta donde se guardará el Excel generado (por defecto: output_fudo/)"
    )
    parser.add_argument(
        "--no-archive",
        action="store_true",
        help="No mover los comprobantes procesados a procesados/"
    )
    parser.add_argument(
        "--template", "-t",
        default=None,
        help="Ruta alternativa a Plantilla-Gastos.xlsx"
    )
    parser.add_argument(
        "--model", "-m",
        default=None,
        help="Modelo de IA principal (por defecto: GEMINI_MODEL de .env o gemini-3.8-flash)"
    )
    parser.add_argument(
        "--aprender", "-a",
        metavar="ARCHIVO_EXCEL",
        default=None,
        help="Aprender de un archivo Excel corregido por el usuario (actualiza la memoria de proveedores)"
    )
    parser.add_argument(
        "--evaluar",
        action="store_true",
        help="Ejecutar benchmarking con el banco de pruebas (pruebas/tickets_reales/)"
    )
    parser.add_argument(
        "--limite", "-l",
        type=int,
        default=None,
        help="Límite máximo de comprobantes a procesar o evaluar"
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=None,
        help="Límite de tiempo global en segundos para el proceso"
    )
    parser.add_argument(
        "--gui", "-g",
        action="store_true",
        help="Iniciar la interfaz gráfica de usuario (GUI) de control y precios"
    )
    parser.add_argument(
        "--precios",
        nargs="?",
        const="output_fudo/Historico_Precios.xlsx",
        default=None,
        metavar="ARCHIVO_SALIDA",
        help="Exportar histórico analítico de precios y comparador de proveedores a Excel"
    )
    args = parser.parse_args()

    # Modo 0: Interfaz Gráfica (GUI)
    if args.gui:
        from fudo.gui import iniciar_app
        iniciar_app()
        return

    # Modo 0.1: Exportación analítica de precios
    if args.precios:
        from fudo.memoria import Memoria
        from fudo.precios import exportar_historico_precios_excel
        mem = Memoria(BASE_DIR / "memoria.db")
        ruta_p = Path(args.precios).resolve()
        if not ruta_p.is_absolute():
            ruta_p = BASE_DIR / args.precios
        items = mem.consultar_todos_los_articulos(limite=50000)
        resumenes = mem.consultar_resumen_productos()
        if not items:
            print("[i] No hay compras registradas en el histórico de precios todavía.")
            return
        exportar_historico_precios_excel(items, resumenes, ruta_p)
        print(f"[OK] Reporte analítico de precios generado en:\n     {ruta_p}")
        return

    # Modo 1: Evaluación / Benchmarking
    if args.evaluar:
        ejecutar_evaluacion(modelo=args.model, limite=args.limite, timeout_max_segundos=args.timeout)
        return

    # Modo 2: Aprendizaje desde Excel corregido
    if args.aprender:
        print("\n" + "=" * 65)
        print("          FUDO EXTRACTOR - MÓDULO DE APRENDIZAJE")
        print("=" * 65)
        ruta_xlsx = Path(args.aprender).resolve()
        if not ruta_xlsx.exists():
            ruta_xlsx = (BASE_DIR / args.aprender).resolve()
        if not ruta_xlsx.exists():
            print(f"[!] Error: no se encontró el archivo Excel: {args.aprender}")
            sys.exit(1)

        memoria = Memoria(BASE_DIR / "memoria.db")
        catalogo = CatalogoFudo(template_path=Path(args.template).resolve() if args.template else None)
        print(f"[*] Leyendo correcciones desde: {ruta_xlsx.name}")
        res = aprender_de_excel(ruta_xlsx, memoria, catalogo)
        print(f"[OK] Proveedores confirmados/actualizados: {res['proveedores_confirmados']}")
        print(f"[OK] Comprobantes de revisión procesados:   {res['revisiones_procesadas']}")
        print("La memoria ahora recordará estas asociaciones en futuras extracciones.")
        print("=" * 65)
        return

    # Modo 3: Extracción normal de comprobantes
    print("=" * 65)
    print("       FUDO EXTRACTOR v2 - PROCESADOR INTELIGENTE")
    print("       (QR ARCA + IA Multimodal + Memoria por Huella)")
    print("=" * 65)
    print(f"[*] Directorio base: {BASE_DIR}")

    dir_input = (BASE_DIR / args.input).resolve()
    dir_output = (BASE_DIR / args.output).resolve()
    dir_procesados = (BASE_DIR / "procesados").resolve()

    dir_input.mkdir(parents=True, exist_ok=True)
    dir_output.mkdir(parents=True, exist_ok=True)
    dir_procesados.mkdir(parents=True, exist_ok=True)

    archivos = sorted([p for p in dir_input.rglob("*") if p.is_file() and p.suffix.lower() in EXTENSIONES_VALIDAS])
    if args.limite and args.limite > 0:
        archivos = archivos[:args.limite]

    if not archivos:
        print(f"\n[i] No se encontraron comprobantes en la carpeta:\n    {dir_input}")
        print("    Copia tus fotos o PDFs en esa carpeta y vuelve a ejecutar el programa.")
        print("=" * 65)
        sys.exit(0)

    print(f"[*] Comprobantes encontrados para procesar: {len(archivos)}")

    # Inicializar componentes
    catalogo = CatalogoFudo(template_path=Path(args.template).resolve() if args.template else None)
    if catalogo.template_file:
        print(f"[*] Plantilla de Fudo: {catalogo.template_file.name} (Cat: {len(catalogo.categorias)} | Prov: {len(catalogo.proveedores)})")

    memoria = Memoria(BASE_DIR / "memoria.db")
    print(f"[*] Memoria SQLite activa: {memoria.db_path.name}")

    motor_ia = MotorIA(modelo=args.model)
    print(f"[*] Motores: {motor_ia.descripcion()}")
    if easyocr_disponible():
        print("    - OCR local: EasyOCR disponible para contingencia offline")
    print("-" * 65)

    router = RouterTickets(catalogo=catalogo, memoria=memoria, motor_ia=motor_ia)

    filas_gastos = []
    filas_revisar = []
    archivos_ok = []
    archivos_pendientes = []
    total_monto = 0.0
    lote_id = f"lote_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    for idx, arch in enumerate(archivos, start=1):
        print(f"[{idx}/{len(archivos)}] Analizando: {arch.name}...")
        try:
            res = router.procesar(arch, lote_id=lote_id)

            if res.estado == "DUPLICADO":
                print(f"    [!] Omitido: {res.motivos[0]}")
                continue

            if res.estado == "PENDIENTE":
                print(f"    [⏳] Encolado como pendiente: {res.motivos[0]}")
                archivos_pendientes.append(arch)
                continue

            if res.estado == "ERROR":
                print(f"    [!] Error en comprobante: {'; '.join(res.motivos)}")
                continue

            # Comprobante resuelto (OK o REVISAR)
            if res.fila_gastos:
                filas_gastos.append(res.fila_gastos)
                archivos_ok.append(arch)
                monto = float(res.fila_gastos.get("monto", 0.0))
                total_monto += monto

                # Registrar en base de comprobantes procesados para evitar futuros duplicados
                ext = res.extraccion
                cuit_reg = ext.cuit_emisor if ext else None
                tipo_reg = res.fila_gastos.get("tipo_comprobante", "")
                num_reg = res.fila_gastos.get("numero_comprobante", "")
                from fudo.validaciones import normalizar_numero_comprobante
                num_norm = normalizar_numero_comprobante(num_reg)

                memoria.registrar_comprobante(
                    h=res.hash_sha256,
                    cuit=cuit_reg,
                    tipo=tipo_reg,
                    numero_norm=num_norm,
                    fecha=res.fila_gastos.get("fecha"),
                    monto=monto,
                    archivo=arch.name,
                    lote=lote_id,
                    proveedor_id=res.proveedor_id_asociado
                )

                tag_estado = "[OK]" if res.estado == "OK" else "[REVISAR]"
                prov_str = res.fila_gastos.get("proveedor", "")
                cat_str = res.fila_gastos.get("categoria", "")
                print(f"    {tag_estado} ({res.estrategia}) | {prov_str} | {cat_str} | ${monto:,.2f}")
                if res.motivos:
                    print(f"      Alertas: {'; '.join(res.motivos)}")

            if res.fila_revisar:
                filas_revisar.append(res.fila_revisar)

            time.sleep(Config.pausa_entre_tickets)

        except Exception as e:
            print(f"    [!] Error inesperado al procesar {arch.name}: {e}")

    if not filas_gastos:
        if archivos_pendientes:
            print(f"\n[i] Todos los comprobantes ({len(archivos_pendientes)}) quedaron en cola de pendientes.")
            print("    Se intentarán nuevamente cuando haya conexión a internet.")
        else:
            print("\n[!] No se pudieron extraer datos de los comprobantes ingresados.")
        sys.exit(0)

    # Generar el archivo Excel
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    nombre_excel = f"Gastos_Fudo_{timestamp}.xlsx"
    salida_excel = dir_output / nombre_excel

    gestor = GestorExcel(template_path=catalogo.template_file, catalogo=catalogo)
    wb = gestor.crear_workbook(salida_excel)
    gestor.escribir_lote(wb, filas_gastos, filas_revisar)
    wb.save(salida_excel)
    wb.close()

    print("\n" + "=" * 65)
    print("                    RESUMEN DEL PROCESO")
    print("=" * 65)
    print(f"[*] Comprobantes procesados:          {len(archivos_ok)} de {len(archivos)}")
    if filas_revisar:
        print(f"[*] Comprobantes en hoja 'Revisar':    {len(filas_revisar)} (requieren tu confirmación)")
    if archivos_pendientes:
        print(f"[*] Comprobantes pendientes:           {len(archivos_pendientes)} (permanecen en input_tickets/)")
    print(f"[*] Monto total acumulado:            ${total_monto:,.2f}")
    print(f"[*] Archivo Fudo generado:           {salida_excel.name}")
    print(f"    Ruta:                            {salida_excel}")

    # Archivar los comprobantes procesados con éxito
    if not args.no_archive:
        import shutil
        for arch in archivos_ok:
            destino = dir_procesados / arch.name
            if destino.exists():
                destino = dir_procesados / f"{arch.stem}_{timestamp}{arch.suffix}"
            try:
                shutil.move(str(arch), str(destino))
            except Exception as e:
                print(f"[!] No se pudo mover {arch.name} a procesados/: {e}")
        print(f"[*] Comprobantes archivados en:       {dir_procesados.name}/")

    if filas_revisar:
        print("\n[TIP] Abre el Excel generado y consulta la hoja 'Revisar'.")
        print("      Una vez corregidos los proveedores o categorías en la hoja 'Gastos',")
        print(f"      ejecuta: FudoExtractor.exe --aprender {salida_excel.name}")
        print("      para que el sistema aprenda tus preferencias.")

    print("\n[OK] Proceso finalizado. El archivo generado está listo para importar en Fudo.")
    print("=" * 65)


if __name__ == "__main__":
    main()
