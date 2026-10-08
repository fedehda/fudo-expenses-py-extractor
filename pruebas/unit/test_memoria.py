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
