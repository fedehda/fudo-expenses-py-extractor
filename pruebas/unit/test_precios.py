"""Pruebas unitarias para el módulo analítico de precios y comparador."""
import tempfile
from pathlib import Path
from fudo.esquema import Articulo
from fudo.memoria import Memoria
from fudo.precios import (
    ItemHistorico,
    calcular_resumen_producto,
    inferir_precio_unitario,
    normalizar_producto,
)


def test_normalizar_producto():
    assert normalizar_producto("Tomate perita x 10 kg") == "tomate perita"
    assert normalizar_producto("QUESO MUZZARELLA X CAJON") == "queso muzzarella"
    assert normalizar_producto("Harina 0000 Chacabuco (bolsa)") == "harina 0000 chacabuco"
    assert normalizar_producto("") == ""
    assert normalizar_producto(None) == ""


def test_inferir_precio_unitario():
    # Con precio unitario explícito
    assert inferir_precio_unitario(1000.0, 5.0, 200.0) == 200.0
    # Inferido por importe y cantidad
    assert inferir_precio_unitario(1500.0, 3.0, None) == 500.0
    # Sin cantidad numérica
    assert inferir_precio_unitario(300.0, None, None) == 300.0
    # Sin importe ni precio
    assert inferir_precio_unitario(None, None, None) is None


def test_calcular_resumen_producto():
    items = [
        ItemHistorico(
            id=1, comprobante_hash="h1", fecha="01-10-2026", proveedor_id=1,
            proveedor_nombre="Distribuidora Norte", producto_original="Harina 000",
            producto_normalizado="harina 000", cantidad_texto="10 kg", cantidad_numerica=10.0,
            unidad_medida="kg", precio_unitario=100.0, importe_total=1000.0,
            tipo_comprobante="Factura A", numero_comprobante="0001-00001234", archivo="fact1.jpg"
        ),
        ItemHistorico(
            id=2, comprobante_hash="h2", fecha="05-10-2026", proveedor_id=2,
            proveedor_nombre="Molinos del Sur", producto_original="Harina 000 x bolsa",
            producto_normalizado="harina 000", cantidad_texto="10 kg", cantidad_numerica=10.0,
            unidad_medida="kg", precio_unitario=80.0, importe_total=800.0,
            tipo_comprobante="Factura B", numero_comprobante="0002-00005678", archivo="fact2.jpg"
        ),
        ItemHistorico(
            id=3, comprobante_hash="h3", fecha="10-10-2026", proveedor_id=1,
            proveedor_nombre="Distribuidora Norte", producto_original="Harina 000",
            producto_normalizado="harina 000", cantidad_texto="10 kg", cantidad_numerica=10.0,
            unidad_medida="kg", precio_unitario=120.0, importe_total=1200.0,
            tipo_comprobante="Factura A", numero_comprobante="0001-00009999", archivo="fact3.jpg"
        ),
    ]

    res = calcular_resumen_producto(items)
    assert res is not None
    assert res.producto_normalizado == "harina 000"
    # Último precio (fecha 10-10-2026) es 120.0
    assert res.ultimo_precio == 120.0
    assert res.ultimo_proveedor == "Distribuidora Norte"
    # Precio anterior (fecha 05-10-2026) es 80.0
    assert res.precio_anterior == 80.0
    # Variación porcentual de 80 a 120 es +50.0%
    assert res.variacion_pct == 50.0
    # Mejor precio histórico registrado es 80.0 de Molinos del Sur
    assert res.mejor_precio == 80.0
    assert res.mejor_proveedor == "Molinos del Sur"
    assert res.total_compras == 3
    assert len(res.proveedores) == 2


def test_memoria_articulos_sqlite():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_file = Path(tmpdir) / "test_precios.db"
        mem = Memoria(db_file)

        art1 = Articulo(descripcion="Tomate perita", cantidad="5 kg", cantidad_numerica=5.0,
                        unidad_medida="kg", precio_unitario=200.0, importe=1000.0)
        art2 = Articulo(descripcion="Lechuga criolla", cantidad="2 kg", cantidad_numerica=2.0,
                        unidad_medida="kg", precio_unitario=150.0, importe=300.0)

        guardados = mem.guardar_articulos(
            comprobante_hash="hash_a",
            fecha="01-10-2026",
            proveedor_id=10,
            proveedor_nombre="Verdulería Central",
            articulos=[art1, art2],
            tipo_comprobante="Factura B",
            numero_comprobante="0001-00001111",
            archivo="ticket1.jpeg"
        )
        assert guardados == 2

        # Segunda compra con aumento del Tomate a 250.0 (+25%)
        art1_nuevo = Articulo(descripcion="Tomate perita x cajon", cantidad="10 kg", cantidad_numerica=10.0,
                              unidad_medida="kg", precio_unitario=250.0, importe=2500.0)

        mem.guardar_articulos(
            comprobante_hash="hash_b",
            fecha="05-10-2026",
            proveedor_id=11,
            proveedor_nombre="Distribuidora San Juan",
            articulos=[art1_nuevo],
            tipo_comprobante="Factura A",
            numero_comprobante="0002-00002222",
            archivo="ticket2.jpeg"
        )

        resumenes = mem.consultar_resumen_productos()
        assert len(resumenes) == 2  # Tomate perita y Lechuga criolla

        # Buscar el resumen del tomate
        res_tomate = next(r for r in resumenes if "tomate" in r.producto_normalizado)
        assert res_tomate.ultimo_precio == 250.0
        assert res_tomate.precio_anterior == 200.0
        assert res_tomate.variacion_pct == 25.0
        assert res_tomate.mejor_precio == 200.0
        assert res_tomate.mejor_proveedor == "Verdulería Central"
        assert res_tomate.total_compras == 2

        # Alerta de aumento con umbral de 10%
        alertas = mem.consultar_alertas_aumento(umbral_pct=10.0)
        assert len(alertas) == 1
        assert "tomate" in alertas[0].producto_normalizado

        # Historial cronológico del tomate
        hist = mem.consultar_historico_producto(res_tomate.producto_normalizado)
        assert len(hist) == 2

        # Proveedores con artículos
        provs = mem.listar_proveedores_con_articulos()
        assert "Distribuidora San Juan" in provs
        assert "Verdulería Central" in provs
