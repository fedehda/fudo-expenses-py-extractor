"""Pruebas unitarias para huella de proveedor y reconocimiento por señales."""
from fudo.esquema import Articulo, ExtraccionComprobante, Huella, TipoDocumento
from fudo.huella import normalizar_alias, normalizar_telefono, puntuar, rankear, senales_de


def test_normalizadores_huella():
    assert normalizar_telefono("11-4567-8901") == "45678901"
    assert normalizar_telefono("+54 9 11 4567-8901") == "45678901"
    assert normalizar_telefono("123") is None

    assert normalizar_alias("Alias: verduleria.juan.mp") == "verduleria.juan.mp"
    assert normalizar_alias("CBU: 0170099220000012345678") == "0170099220000012345678"


def test_puntuar_huella_por_telefono():
    ticket = {"telefono": {"45678901"}, "items": {"tomate", "lechuga"}}
    guardadas = {"telefono": {"45678901"}, "items": {"papa", "cebolla"}}

    puntaje, razones = puntuar(ticket, guardadas)
    assert puntaje >= 0.90
    assert any("telefono" in r for r in razones)


def test_puntuar_huella_conflicto_cuit():
    # Si tienen CUITs distintos y válidos, el puntaje debe ser 0.0 aunque tengan teléfonos parecidos
    ticket = {"cuit": {"30709497401"}, "telefono": {"45678901"}}
    guardadas = {"cuit": {"30123456789"}, "telefono": {"45678901"}}

    puntaje, razones = puntuar(ticket, guardadas)
    assert puntaje == 0.0
    assert "CUIT distinto" in razones


def test_rankear_huella():
    ticket_ext = ExtraccionComprobante(
        tipo_documento=TipoDocumento.remito,
        tiene_nombre_emisor=False,
        articulos=[Articulo(descripcion="5 cajones Tomate perita"), Articulo(descripcion="2 bolsas Papa negra")],
        huella=Huella(
            telefonos=["11-5555-4321"],
            direccion="Mercado Central Nave 4 Puesto 12"
        )
    )
    senales_ticket = senales_de(ticket_ext)

    # Base de memoria simulada
    memoria_senales = {
        1: ("Verdulería Don Pepe", {
            "telefono": {"55554321"},
            "direccion": {"mercado central nave 4 puesto 12"},
            "items": {"tomate", "papa", "cebolla"}
        }),
        2: ("Carnicería El Trébol", {
            "telefono": {"11112222"},
            "items": {"lomo", "asado", "vacio"}
        })
    }

    candidatos = rankear(senales_ticket, memoria_senales, top=2)
    assert len(candidatos) > 0
    assert candidatos[0].nombre == "Verdulería Don Pepe"
    assert candidatos[0].puntaje >= 0.95


def test_generar_nombre_estandarizado():
    from fudo.imagen import generar_nombre_estandarizado, sanitizar_nombre_archivo

    # Sanitización básica
    assert sanitizar_nombre_archivo("Distribuidora Pan & Café S.A.!") == "distribuidora_pan_cafe_s_a"
    assert sanitizar_nombre_archivo("Molino Cañuelas") == "molino_canuelas"

    # Formatos de fecha DD-MM-AAAA
    nom1 = generar_nombre_estandarizado("12-10-2026", "Molino Cañuelas", ".jpg")
    assert nom1 == "20261012_molino_canuelas.jpg"

    # Con número de comprobante
    nom2 = generar_nombre_estandarizado("2026-10-12", "Distribuidora Pan", ".png", comprobante_nro="0001-00004567")
    assert nom2 == "20261012_distribuidora_pan_0001-00004567.png"

    # Proveedor vacío o None
    nom3 = generar_nombre_estandarizado("15/05/2026", None, ".jpeg")
    assert nom3 == "20260515_sin_identificar.jpeg"
