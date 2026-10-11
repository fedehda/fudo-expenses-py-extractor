"""Pruebas unitarias para persistencia y migraciones de Memoria SQLite."""
import tempfile
from pathlib import Path

from fudo.memoria import Memoria


def test_memoria_crud_y_senales():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_memoria.db"
        mem = Memoria(db_path)

        # 1. Guardar proveedor nuevo
        pid = mem.guardar_proveedor(
            cuit="30709497401",
            razon_social="Verduleria Central SRL",
            proveedor_fudo="Verdulería Central",
            categoria="Verdulería",
            caja="Principal",
            medio_pago="Efectivo",
            confirmado=False
        )
        assert pid is not None

        # 2. Búsqueda por CUIT
        p = mem.buscar_por_cuit("30-70949740-1")
        assert p is not None
        assert p["proveedor_fudo"] == "Verdulería Central"

        # 3. Guardar señales de huella
        mem.agregar_senales(pid, {
            "telefono": {"55554321"},
            "alias_cbu": {"verduleria.central.mp"}
        })

        todas = mem.todas_las_senales()
        assert pid in todas
        nombre, senales = todas[pid]
        assert nombre == "Verdulería Central"
        assert "55554321" in senales["telefono"]

        # 4. Registro de comprobante y duplicados
        mem.registrar_comprobante(
            h="hash123",
            cuit="30709497401",
            tipo="Factura A",
            numero_norm="4-1284",
            fecha="2026-09-15",
            monto=45000.0,
            archivo="ticket1.jpg",
            lote="lote1",
            proveedor_id=pid
        )
        assert mem.hash_procesado("hash123") == "ticket1.jpg"
        assert mem.duplicado_fiscal("30709497401", "Factura A", "4-1284") == "ticket1.jpg"
        assert mem.duplicado_fiscal("30709497401", "Factura A", "9-9999") is None

        # 5. Cola de pendientes
        intentos = mem.marcar_pendiente("hash999", "ticket_error.jpg", "Error 503 IA")
        assert intentos == 1
        assert mem.es_pendiente("hash999") is True


def test_aprender_de_excel_firmas():
    import openpyxl
    from fudo.excel import aprender_de_excel
    from fudo.catalogo import CatalogoFudo

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_aprender.db"
        mem = Memoria(db_path)
        excel_path = Path(tmpdir) / "test_gastos.xlsx"

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Gastos"
        ws.append(["Fecha", "Monto", "Proveedor", "Categoría", "Comentario", "Tipo de comprobante",
                   "Número de comprobante", "Medio de pago", "Caja", "Fecha de pago", "Fecha de vencimiento", "CUIT"])
        ws.append(["10-10-2026", 15000.0, "Distribuidora Pan SRL", "Panadería", "Compra pan", "Factura B",
                   "1-100", "Efectivo", "Caja 1", "10-10-2026", "10-10-2026", "30709497401"])
        wb.save(excel_path)
        wb.close()

        # Probar llamada SIN catalogo
        res1 = aprender_de_excel(excel_path, mem)
        assert res1["proveedores_confirmados"] >= 1
        assert mem.buscar_por_cuit("30-70949740-1") is not None

        # Probar llamada CON catalogo
        cat = CatalogoFudo()
        res2 = aprender_de_excel(excel_path, mem, cat)
        assert res2["proveedores_confirmados"] >= 1
