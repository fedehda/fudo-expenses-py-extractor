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

        # Pre-cargar un artículo sin identificar asociado a ticket_viejo.jpg
        mem.guardar_articulos(
            comprobante_hash="hash_viejo",
            fecha="05-10-2026",
            proveedor_id=None,
            proveedor_nombre="Sin identificar",
            articulos=[{"descripcion": "Levadura fresca", "cantidad": "5 kg", "cantidad_numerica": 5.0, "importe": 8000.0}],
            archivo="ticket_viejo.jpg"
        )

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Gastos"
        ws.append(["Fecha", "Monto", "Proveedor", "Categoría", "Comentario", "Tipo de comprobante",
                   "Número de comprobante", "Medio de pago", "Caja", "Fecha de pago", "Fecha de vencimiento", "CUIT"])
        ws.append(["10-10-2026", 15000.0, "Distribuidora Pan SRL", "Panadería",
                   "[Huella 90%] 50 kg Harina 000 ($15,000.00)", "Factura B",
                   "1-100", "Efectivo", "Caja 1", "10-10-2026", "10-10-2026", "30709497401"])

        ws_rev = wb.create_sheet(title="Revisar")
        ws_rev.append(["Archivo", "Motivo de Revisión", "Tipo Detectado", "CUIT", "Proveedor Asignado",
                       "Candidatos Sugeridos (Huella)", "Monto", "Estrategia Usada"])
        ws_rev.append(["ticket_viejo.jpg", "Sin nombre", "Factura B", "30709497401", "Panadería Central",
                       "Panadería Central (90%)", 8000.0, "IA"])

        wb.save(excel_path)
        wb.close()

        # Probar aprendizaje completo
        cat = CatalogoFudo()
        res = aprender_de_excel(excel_path, mem, cat)

        assert res["proveedores_confirmados"] >= 1
        assert res["revisiones_procesadas"] >= 1
        assert res["articulos_actualizados"] >= 2

        # 1. Verificar que el artículo nuevo se ingirió en el histórico
        arts = mem.consultar_todos_los_articulos(filtro_proveedor="Distribuidora Pan SRL")
        assert len(arts) == 1
        assert arts[0].producto_normalizado == "harina 000"
        assert arts[0].precio_unitario == 300.0

        # 2. Verificar que el artículo anterior de ticket_viejo.jpg se actualizó de 'Sin identificar' a 'Panadería Central'
        arts_rev = mem.consultar_todos_los_articulos(filtro_proveedor="Panadería Central")
        assert len(arts_rev) == 1
        assert arts_rev[0].archivo == "ticket_viejo.jpg"


def test_senales_entrenamiento_gestion():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_senales.db"
        mem = Memoria(db_path)

        pid = mem.guardar_proveedor(
            cuit="30112233445",
            razon_social="Molino Cañuelas S.A.",
            proveedor_fudo="Molino Cañuelas",
            categoria="Panadería",
            caja="Principal",
            medio_pago="Transferencia",
            confirmado=True
        )

        # 1. Agregar señales manuales
        assert mem.guardar_senal_manual(pid, "telefono", "1145678900") is True
        assert mem.guardar_senal_manual(pid, "alias_cbu", "molino.canuelas.mp") is True

        # 2. Consultar señales detalladas
        senales = mem.consultar_senales_proveedor(pid)
        assert len(senales) == 2
        tipos = [s["tipo"] for s in senales]
        assert "telefono" in tipos
        assert "alias_cbu" in tipos

        # 3. Eliminar una señal
        assert mem.eliminar_senal(pid, "telefono", "1145678900") is True
        senales_post = mem.consultar_senales_proveedor(pid)
        assert len(senales_post) == 1
        assert senales_post[0]["tipo"] == "alias_cbu"

        # 4. Listar proveedores con conteo de señales
        provs_mem = mem.listar_proveedores_memoria()
        assert len(provs_mem) == 1
        assert provs_mem[0]["cant_senales"] == 1
